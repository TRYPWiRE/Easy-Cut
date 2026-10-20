"""Builds preview frames: decodes the clips under the playhead and composites them with every effect.

Works on small frames (the preview canvas size), so it stays light on the CPU. The export does not use
this - it hands the whole timeline to FFmpeg as one filter graph (see render.py).
"""
import os

import numpy as np

from . import animations, effects, filters, media, textrender
from .effects import hex_to_rgb


def blend_onto(canvas, img, cx, cy, alpha):
    """Alpha-composite BGRA/BGR `img` centred at (cx, cy) onto BGR `canvas` (in place)."""
    H, W = canvas.shape[:2]
    h, w = img.shape[:2]
    x0 = int(round(cx - w / 2))
    y0 = int(round(cy - h / 2))
    x1, y1 = max(0, x0), max(0, y0)
    x2, y2 = min(W, x0 + w), min(H, y0 + h)
    if x2 <= x1 or y2 <= y1 or alpha <= 0.001:
        return
    src = img[y1 - y0:y2 - y0, x1 - x0:x2 - x0]
    dst = canvas[y1:y2, x1:x2]
    if src.shape[2] == 4:
        a = src[:, :, 3:4].astype(np.float32) * (alpha / 255.0)
    else:
        a = np.full(src.shape[:2] + (1,), alpha, np.float32)
    if a.min() >= 0.999:
        dst[:] = src[:, :, :3]
        return
    dst[:] = (src[:, :, :3].astype(np.float32) * a + dst.astype(np.float32) * (1 - a) + 0.5).astype(np.uint8)


class Compositor:
    def __init__(self):
        self.readers = {}
        self.images = {}
        self.missing = set()

    def close(self):
        for r in self.readers.values():
            try:
                r.close()
            except Exception:
                pass
        self.readers.clear()
        self.images.clear()

    def prune(self, project):
        ids = {c["id"] for c in project.clips}
        for k in list(self.readers):
            if k[0] not in ids:
                try:
                    self.readers.pop(k).close()
                except Exception:
                    pass

    def _reader(self, clip, box):
        key = (clip["id"], clip["path"], box)
        r = self.readers.get(key)
        if r is None:
            for k in [k for k in self.readers if k[0] == clip["id"]]:
                self.readers.pop(k).close()
            r = media.FrameReader(clip["path"], max_size=box)
            self.readers[key] = r
        return r

    def _image(self, path, box):
        key = (path, box)
        img = self.images.get(key)
        if img is None:
            import cv2
            img = media.read_image(path)
            if img is None:
                return None
            h, w = img.shape[:2]
            s = min(1.0, box[0] / w, box[1] / h)
            if s < 1:
                img = cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
            if len(self.images) > 40:
                self.images.clear()
            self.images[key] = img
        return img

    def clip_frame(self, clip, t, W, H):
        """Processed BGRA/BGR picture of a clip at timeline time t (before placement), or None."""
        kind = clip["kind"]
        side = int(min(1920, max(W, H) * max(1.0, min(2.0, float(clip.get("scale", 1.0))))))
        box = (side, side)
        if kind == "text":
            img = textrender.render(clip, min(W, H) / 1080.0)
        elif kind == "image":
            if not os.path.exists(clip["path"]):
                self.missing.add(clip["path"])
                return None
            img = self._image(clip["path"], box)
        elif kind == "video":
            if not os.path.exists(clip["path"]):
                self.missing.add(clip["path"])
                return None
            img = self._reader(clip, box).frame_at(max(0.0, clip.source_time(t)))
        else:
            return None
        if img is None:
            return None
        img = effects.process_preview(img, clip)
        img = filters.apply_preview(img, clip)
        return img

    def compose(self, project, t, W, H, skip=None):
        """BGR uint8 frame of the timeline at time t, W x H pixels."""
        import cv2
        r, g, b = hex_to_rgb(project.background)
        canvas = np.empty((H, W, 3), np.uint8)
        canvas[:] = (b, g, r)
        for clip in project.active_visual(t):
            if skip and clip["id"] in skip:
                continue
            st = animations.state(clip, t)
            if t < animations.visible_from(clip):
                img = None
            else:
                try:
                    img = self.clip_frame(clip, t, W, H)
                except Exception:
                    img = None
            if img is not None:
                ch, cw = img.shape[:2]
                fw, fh = effects.fitted_size(clip, cw, ch, W, H, text_scale=1.0)
                fw, fh = fw * st["scale"], fh * st["scale"]
                if fw >= 1 and fh >= 1:
                    iw, ih = max(1, int(round(fw))), max(1, int(round(fh)))
                    if (iw, ih) != (cw, ch):
                        interp = cv2.INTER_AREA if iw < cw else cv2.INTER_LINEAR
                        img = cv2.resize(img, (iw, ih), interpolation=interp)
                    mask = animations.reveal_mask(ih, iw, st["reveals"])
                    if mask is not None:
                        img = effects.to_bgra(np.ascontiguousarray(img)).copy()
                        img[:, :, 3] = (img[:, :, 3] * mask).astype(np.uint8)
                    rot = float(clip.get("rotation", 0.0)) + st["rot"]
                    if abs(rot) > 0.01:
                        img = effects.rotate_bgra(img, rot)
                    cx = W / 2 + (float(clip.get("x", 0)) + st["dx"]) * W
                    cy = H / 2 + (float(clip.get("y", 0)) + st["dy"]) * H
                    blend_onto(canvas, img, cx, cy, st["alpha"] * float(clip.get("opacity", 1.0)))
            if st["veil"] is not None and st["veil"][1] > 0.001:
                vr, vg, vb = hex_to_rgb(st["veil"][0])
                a = st["veil"][1]
                canvas[:] = (canvas.astype(np.float32) * (1 - a) + np.array((vb, vg, vr), np.float32) * a + 0.5
                             ).astype(np.uint8)
        return canvas

    def clip_rect(self, project, clip, t, W, H):
        """On-canvas rectangle (cx, cy, w, h) of a clip for drawing selection handles in the preview."""
        if clip["kind"] == "text":
            img = textrender.render(clip, min(W, H) / 1080.0)
            cw, ch = img.shape[1], img.shape[0]
        else:
            sw, sh = clip.get("src_w") or 16, clip.get("src_h") or 9
            cw, ch = effects.content_size(clip, sw, sh)
        fw, fh = effects.fitted_size(clip, cw, ch, W, H, text_scale=1.0)
        st = animations.state(clip, t)
        cx = W / 2 + (float(clip.get("x", 0)) + st["dx"]) * W
        cy = H / 2 + (float(clip.get("y", 0)) + st["dy"]) * H
        return cx, cy, fw * st["scale"], fh * st["scale"]
