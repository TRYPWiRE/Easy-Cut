"""Project model: tracks and clips, plus save/load (.ecut JSON files)."""
import copy
import json
import os
import uuid

from . import __version__

DEFAULT_CLIP = {
    "id": "",
    "kind": "video",            # video | image | audio | text
    "path": "",
    "name": "",
    "track": 0,
    "start": 0.0,               # timeline seconds
    "duration": 5.0,            # timeline seconds
    "in_point": 0.0,            # source seconds
    "source_duration": 0.0,     # length of the source file (0 = unlimited, e.g. images)
    "has_audio": False,
    "has_video": True,
    "src_w": 0,
    "src_h": 0,
    "sample_rate": 48000,
    # speed & audio
    "speed": 1.0,
    "keep_pitch": True,
    "pitch": 0.0,               # semitones
    "volume": 1.0,
    "muted": False,
    # music / audio tools
    "pan": 0.0,                     # -1 left .. 1 right
    "afade_in": 0.0,                # audio fade in/out (seconds) - the handles on the timeline clip
    "afade_out": 0.0,
    "eq_low": 0.0,                  # dB
    "eq_mid": 0.0,
    "eq_high": 0.0,
    "compress": False,              # even out loud and quiet parts
    "denoise": 0.0,                 # 0..1 background noise reduction
    "reverb": 0.0,                  # 0..1
    # transform
    "fit": "fit",               # fit | fill
    "scale": 1.0,
    "x": 0.0,                   # offset as a fraction of canvas width
    "y": 0.0,                   # offset as a fraction of canvas height
    "rotation": 0.0,
    "opacity": 1.0,
    # look
    "brightness": 0.0,          # -1..1
    "contrast": 1.0,            # 0..2
    "saturation": 1.0,          # 0..2
    "filter": "none",
    "filter_amount": 1.0,
    "anim_in": "none",
    "anim_in_dur": 0.5,
    "anim_out": "none",
    "anim_out_dur": 0.5,
    "trans_in": "none",             # transition from the previous clip (drawn before `start`)
    "trans_dur": 0.5,
    # effects & compositing
    "crop": [0.0, 0.0, 0.0, 0.0],   # left, top, right, bottom (fractions)
    "flip_h": False,
    "flip_v": False,
    "mirror": "none",               # none | left | right | top | bottom
    "chroma": False,
    "chroma_color": "#00ff00",
    "chroma_similarity": 0.15,
    "chroma_blend": 0.08,
    "stabilize": False,
    "stabilize_strength": 0.5,      # 0..1
    # text
    "text": "",
    "font": "Segoe UI",
    "font_size": 80,                # px at 1080p
    "text_color": "#ffffff",
    "bold": True,
    "text_bg": False,
    "text_bg_color": "#000000",
    "text_outline": True,
    "text_style": "none",
    # extension data
    "fx": [],                       # extension video effects: [{"id", "amount"}]
    "ext": {},
}

VIDEO_KINDS = ("video", "image", "text")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class Clip(dict):
    """A dict with attribute access - keeps save/load and undo trivially simple."""

    def __init__(self, *a, **kw):
        super().__init__(copy.deepcopy(DEFAULT_CLIP))
        self.update(*a, **kw)
        if not self["id"]:
            self["id"] = new_id()

    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k)

    def __setattr__(self, k, v):
        self[k] = v

    @property
    def end(self) -> float:
        return self["start"] + self["duration"]

    @property
    def is_visual(self) -> bool:
        return self["kind"] in VIDEO_KINDS

    @property
    def has_sound(self) -> bool:
        return self["kind"] in ("video", "audio") and self["has_audio"]

    @property
    def vis_start(self) -> float:
        """When the clip first appears - earlier than `start` while its transition plays."""
        from .animations import pre_roll
        return self["start"] - pre_roll(self)

    def source_span(self) -> float:
        """How many source seconds the clip consumes."""
        return self["duration"] * self["speed"]

    def max_duration(self) -> float:
        if self["kind"] in ("image", "text") or not self["source_duration"]:
            return 3600.0 * 3
        return max(0.05, (self["source_duration"] - self["in_point"]) / max(0.01, self["speed"]))

    def source_time(self, t: float) -> float:
        """Source-file time shown at timeline time t."""
        return self["in_point"] + (t - self["start"]) * self["speed"]


class Project:
    def __init__(self):
        self.name = "Untitled"
        self.path = ""
        self.aspect = "movie"
        self.fps = 30
        self.background = "#000000"
        self.tracks = [
            {"type": "video", "name": "Video 2", "hidden": False, "muted": False, "solo": False},
            {"type": "video", "name": "Video 1", "hidden": False, "muted": False, "solo": False},
            {"type": "audio", "name": "Audio 1", "hidden": False, "muted": False, "solo": False},
        ]
        self.clips = []
        self.media = []   # paths in the media bin

    # ----------------------------------------------------------- queries
    def duration(self) -> float:
        return max([c.end for c in self.clips], default=0.0)

    def clip(self, cid):
        for c in self.clips:
            if c["id"] == cid:
                return c
        return None

    def clips_on(self, track: int):
        return sorted((c for c in self.clips if c["track"] == track), key=lambda c: c["start"])

    def video_track_indices_bottom_up(self):
        """Video tracks in compositing order (lowest first)."""
        return [i for i in range(len(self.tracks) - 1, -1, -1) if self.tracks[i]["type"] == "video"]

    def active_visual(self, t: float):
        """Visual clips visible at time t, bottom layer first."""
        out = []
        for ti in self.video_track_indices_bottom_up():
            if self.tracks[ti]["hidden"]:
                continue
            for c in self.clips_on(ti):
                if c.vis_start <= t < c.end and c.is_visual:
                    out.append(c)
        return out

    def track_free(self, track, start, end, ignore=None) -> bool:
        for c in self.clips_on(track):
            if ignore is not None and c["id"] == ignore["id"]:
                continue
            if c["start"] < end - 1e-6 and c.end > start + 1e-6:
                return False
        return True

    def tracks_of(self, kind):
        return [i for i, t in enumerate(self.tracks) if t["type"] == kind]

    def track_end(self, track) -> float:
        return max([c.end for c in self.clips_on(track)], default=0.0)

    # ----------------------------------------------------------- editing
    def add_track(self, kind: str) -> int:
        n = len(self.tracks_of(kind)) + 1
        t = {"type": kind, "name": f"{'Video' if kind == 'video' else 'Audio'} {n}", "hidden": False, "muted": False,
             "solo": False}
        if kind == "video":
            # new video tracks go on top
            self.tracks.insert(0, t)
            for c in self.clips:
                c["track"] += 1
            return 0
        self.tracks.append(t)
        return len(self.tracks) - 1

    def remove_track(self, idx: int):
        if not (0 <= idx < len(self.tracks)):
            return
        kind = self.tracks[idx]["type"]
        if len(self.tracks_of(kind)) <= 1:
            return
        self.clips = [c for c in self.clips if c["track"] != idx]
        del self.tracks[idx]
        for c in self.clips:
            if c["track"] > idx:
                c["track"] -= 1

    def place(self, clip: Clip, preferred_track=None, at=None) -> Clip:
        """Put a clip on a suitable track, creating one if every track is busy at that time."""
        kind = "audio" if clip["kind"] == "audio" else "video"
        tracks = self.tracks_of(kind)
        if preferred_track is not None and preferred_track in tracks:
            order = [preferred_track] + [t for t in reversed(tracks) if t != preferred_track]
        else:
            order = list(reversed(tracks))   # bottom-most first (main track)
        if at is None:
            main = order[0]
            at = self.track_end(main)
        clip["start"] = max(0.0, at)
        for t in order:
            if self.track_free(t, clip["start"], clip["start"] + clip["duration"]):
                clip["track"] = t
                break
        else:
            t = self.add_track(kind)
            clip["track"] = t
        self.clips.append(clip)
        return clip

    def clip_from_media(self, info, duration=None) -> Clip:
        name = os.path.basename(info.path)
        c = Clip(kind=info.kind, path=info.path, name=name, has_audio=info.has_audio,
                 has_video=info.has_video, src_w=info.width, src_h=info.height,
                 sample_rate=info.sample_rate)
        if info.kind == "image":
            c["duration"] = duration or 5.0
            c["source_duration"] = 0.0
        else:
            c["source_duration"] = info.duration
            c["duration"] = duration or max(0.1, info.duration)
        return c

    def split(self, clip: Clip, t: float):
        """Split a clip at timeline time t. Returns the new right-hand clip, or None."""
        if not (clip["start"] + 0.04 < t < clip.end - 0.04):
            return None
        right = Clip(copy.deepcopy(dict(clip)))
        right["id"] = new_id()
        left_dur = t - clip["start"]
        right["start"] = t
        right["duration"] = clip["duration"] - left_dur
        right["in_point"] = clip["in_point"] + left_dur * clip["speed"]
        clip["duration"] = left_dur
        # the animation-in belongs to the left piece, the animation-out to the right piece
        clip["anim_out"] = "none"
        right["anim_in"] = "none"
        right["trans_in"] = "none"
        self.clips.append(right)
        return right

    def set_speed(self, clip: Clip, speed: float):
        """Change speed keeping the same source footage (so the clip gets shorter/longer)."""
        speed = min(10.0, max(0.1, float(speed)))
        span = clip.source_span()
        clip["speed"] = speed
        clip["duration"] = max(0.05, min(span / speed, clip.max_duration()))

    def detach_audio(self, clip):
        """Move a video clip's sound onto its own audio clip (the video clip is muted). Returns the new clip."""
        if clip["kind"] != "video" or not clip.has_sound:
            return None
        a = Clip(copy.deepcopy(dict(clip)))
        a["id"] = new_id()
        a["kind"] = "audio"
        a["has_video"] = False
        a["name"] = os.path.splitext(clip["name"])[0] + " (audio)"
        a["anim_in"] = a["anim_out"] = a["trans_in"] = "none"
        a["muted"] = False
        clip["muted"] = True
        tracks = self.tracks_of("audio")
        for t in tracks:
            if self.track_free(t, a["start"], a.end):
                a["track"] = t
                break
        else:
            a["track"] = self.add_track("audio")
        self.clips.append(a)
        return a

    def soloed(self):
        """Indexes of soloed tracks (empty = no solo)."""
        return {i for i, t in enumerate(self.tracks) if t.get("solo")}

    def remove(self, clip):
        self.clips = [c for c in self.clips if c["id"] != clip["id"]]

    def ripple_close(self, track):
        """Close gaps on a track (used by 'Remove gaps')."""
        t = 0.0
        for c in self.clips_on(track):
            c["start"] = t
            t = c.end

    # ----------------------------------------------------------- io
    def to_dict(self) -> dict:
        return {
            "app": "Easy-Cut", "version": __version__,
            "name": self.name, "aspect": self.aspect, "fps": self.fps, "background": self.background,
            "tracks": copy.deepcopy(self.tracks), "clips": [dict(copy.deepcopy(dict(c))) for c in self.clips],
            "media": list(self.media),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        p = cls()
        p.name = d.get("name", "Untitled")
        p.aspect = d.get("aspect", "movie")
        p.fps = int(d.get("fps", 30))
        p.background = d.get("background", "#000000")
        if d.get("tracks"):
            p.tracks = copy.deepcopy(d["tracks"])
        p.clips = [Clip(c) for c in d.get("clips", [])]
        p.media = list(d.get("media", []))
        return p

    def save(self, path: str):
        self.path = path
        self.name = os.path.splitext(os.path.basename(path))[0]
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=1)
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: str) -> "Project":
        with open(path, "r", encoding="utf-8") as f:
            p = cls.from_dict(json.load(f))
        p.path = path
        return p


class History:
    """Snapshot-based undo/redo."""

    def __init__(self, project: Project, limit=100):
        self.undo_stack = []
        self.redo_stack = []
        self.limit = limit
        self.current = json.dumps(project.to_dict())

    def commit(self, project: Project):
        snap = json.dumps(project.to_dict())
        if snap == self.current:
            return False
        self.undo_stack.append(self.current)
        del self.undo_stack[:-self.limit]
        self.redo_stack.clear()
        self.current = snap
        return True

    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    def undo(self):
        if not self.undo_stack:
            return None
        self.redo_stack.append(self.current)
        self.current = self.undo_stack.pop()
        return Project.from_dict(json.loads(self.current))

    def redo(self):
        if not self.redo_stack:
            return None
        self.undo_stack.append(self.current)
        self.current = self.redo_stack.pop()
        return Project.from_dict(json.loads(self.current))
