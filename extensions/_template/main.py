"""Template extension - copy this folder to extensions/<your-id>/, rename the id in manifest.json and edit.

register(api) is called once when Easy-Cut starts (or right after the extension is installed).
Everything registered here shows up in the Filters, Animations and Effects panels automatically.
"""
import numpy as np


def register(api):
    # 1) A colour filter: a 3x3 RGB matrix plus tone settings (same maths in preview and export)
    api.register_filter("example-teal-orange", "Teal & Orange",
                        matrix=[[1.10, 0.00, -0.05], [0.00, 1.00, 0.05], [-0.08, 0.05, 1.12]],
                        contrast=1.08, swatch="#2ec4b6")

    # 2) An animation: expressions in E (eased progress, 0 = hidden, 1 = normal).
    #    Python evaluates them for the preview and FFmpeg evaluates the same text for the export.
    api.register_animation("example-swing", "Swing", scale="(0.8+0.2*E)", dx="(0.15*(1-E)*sin(PI*E*3))", fade=True)

    # 3) A video effect: an FFmpeg filter chain (may use {amount}, 0..1) + a numpy preview function
    def vignette_preview(bgr, amount):
        h, w = bgr.shape[:2]
        y, x = np.ogrid[:h, :w]
        d = ((x - w / 2) ** 2 / (w / 2) ** 2 + (y - h / 2) ** 2 / (h / 2) ** 2)
        mask = np.clip(1 - d * 0.45 * amount, 0, 1)[..., None]
        return (bgr * mask).astype(np.uint8)

    api.register_effect("example-vignette", "Vignette", ffmpeg="vignette=angle=PI/4*{amount}",
                        preview=vignette_preview)
