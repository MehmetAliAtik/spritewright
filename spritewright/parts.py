"""Part rig: a character split into parts (head, body, arm_l, ...) animated by integer offsets.

    rig = Rig(32, 32, "pico-8")
    body = rig.part("body", z=1)            # full-size canvas by default
    head = rig.part("head", z=2)
    eyes_closed = rig.alt("head", "blink")  # alternate drawing (copy of base by default)
    rig.animation("idle", [
        {},                                         # frame 1: rest pose
        {"head": (0, 1), "body": {"dy": 1, "swap": None}, "arm_l": {"visible": False}},
    ], duration=300)
    sprite = rig.build(outline="outline")   # frames idle1, idle2

Per-part frame spec: (dx, dy) tuple or dict with dx, dy, flip_h, flip_v, visible, swap (alt name), z.
Flips happen inside the part's own box. Offsets are integers only.

JSON form (inside a grid sprite file): "parts": {name: {"z":1, "x":0, "y":0, "rows":[...],
"alts": {"blink": [...rows]}}}, "rig_animations": {"idle": {"duration": 300, "frames": [{...}]}},
"rig_outline": {"color": "A"} or {"selective": true}.
"""
from __future__ import annotations

from .canvas import Canvas
from .errors import GridError, PixelError
from .palette import Palette


class Part:
    def __init__(self, name, canvas, z=0, x=0, y=0):
        self.name, self.canvas, self.z, self.x, self.y = name, canvas, z, x, y
        self.alts: dict[str, Canvas] = {}

    def __repr__(self):
        return f"Part({self.name!r}, z={self.z}, at=({self.x},{self.y}), alts={list(self.alts)})"


_KEYS = {"dx", "dy", "flip_h", "flip_v", "visible", "swap", "z"}


class Rig:
    def __init__(self, w, h, palette, name="rig"):
        self.w, self.h = w, h
        self.palette = Palette.load(palette)
        self.name = name
        self.parts: dict[str, Part] = {}
        self.animations: dict[str, dict] = {}
        self.post = []  # callables(canvas) applied to each composed frame

    def part(self, name, z=None, x=0, y=0, w=None, h=None) -> Canvas:
        """Create (or fetch) a part; returns its drawing Canvas. Box defaults to full size."""
        if name in self.parts:
            p = self.parts[name]
            if z is not None:
                p.z = z
            return p.canvas
        cv = Canvas(w or self.w, h or self.h, self.palette, name=name)
        self.parts[name] = Part(name, cv, len(self.parts) if z is None else z, x, y)
        return cv

    def get(self, name) -> Part:
        if name not in self.parts:
            raise PixelError(f"no part {name!r}; parts: {', '.join(self.parts)}")
        return self.parts[name]

    def alt(self, part, alt_name, copy=True) -> Canvas:
        """Alternate drawing for a part (e.g. 'blink'); starts as a copy of the base drawing."""
        p = self.get(part)
        if alt_name not in p.alts:
            p.alts[alt_name] = p.canvas.copy(alt_name) if copy else Canvas(p.canvas.w, p.canvas.h, self.palette)
        return p.alts[alt_name]

    def _norm(self, spec, frame_no, anim):
        out = {}
        for pname, s in (spec or {}).items():
            self.get(pname)
            if isinstance(s, (tuple, list)):
                if len(s) != 2 or not all(isinstance(v, int) for v in s):
                    raise PixelError(f"animation {anim!r} frame {frame_no}: part {pname!r} offset must be (dx, dy) ints")
                s = {"dx": s[0], "dy": s[1]}
            elif not isinstance(s, dict):
                raise PixelError(f"animation {anim!r} frame {frame_no}: part {pname!r} spec must be (dx,dy) or dict")
            bad = set(s) - _KEYS
            if bad:
                raise PixelError(f"animation {anim!r} frame {frame_no}: part {pname!r}: unknown keys {sorted(bad)}; "
                                 f"allowed {sorted(_KEYS)}")
            for k in ("dx", "dy"):
                if k in s and not isinstance(s[k], int):
                    raise PixelError(f"animation {anim!r} frame {frame_no}: part {pname!r}: {k} must be an integer "
                                     f"(no subpixel offsets), got {s[k]!r}")
            if s.get("swap") and s["swap"] not in self.parts[pname].alts:
                raise PixelError(f"animation {anim!r} frame {frame_no}: part {pname!r} has no alt {s['swap']!r}; "
                                 f"alts: {list(self.parts[pname].alts)}")
            out[pname] = s
        return out

    def pose(self, spec=None) -> Canvas:
        """Compose one frame from a per-part spec."""
        spec = self._norm(spec, "?", "pose")
        cv = Canvas(self.w, self.h, self.palette)
        order = sorted(self.parts.values(),
                       key=lambda p: (spec.get(p.name, {}).get("z", p.z), list(self.parts).index(p.name)))
        for p in order:
            s = spec.get(p.name, {})
            if not s.get("visible", True):
                continue
            src = p.alts[s["swap"]] if s.get("swap") else p.canvas
            cv.stamp(src, p.x + s.get("dx", 0), p.y + s.get("dy", 0),
                     flip_h=s.get("flip_h", False), flip_v=s.get("flip_v", False))
        for fn in self.post:
            fn(cv)
        return cv

    def animation(self, name, frames, duration=150):
        """frames: list of per-part specs. duration: ms (int) or list per frame."""
        if not frames:
            raise PixelError(f"animation {name!r} has no frames")
        durs = duration if isinstance(duration, list) else [duration] * len(frames)
        if len(durs) != len(frames):
            raise PixelError(f"animation {name!r}: {len(frames)} frames but {len(durs)} durations")
        norm = [self._norm(f, i + 1, name) for i, f in enumerate(frames)]
        self.animations[name] = {"frames": norm, "durations": [int(d) for d in durs]}
        return self

    def build(self, sprite=None, outline=None, selective=False, connectivity=8, steps=1, ramps=None):
        """Render all animations into a Sprite (frames '<anim><n>'). outline: color for plain
        auto-outline; selective=True for selective outline."""
        from .sprite import Sprite
        sp = sprite or Sprite(self.w, self.h, self.palette, name=self.name)
        for an, a in self.animations.items():
            names = []
            for i, (spec, dur) in enumerate(zip(a["frames"], a["durations"])):
                cv = self.pose(spec)
                if outline is not None or selective:
                    cv.outline(color=outline, selective=selective, connectivity=connectivity,
                               steps=steps, ramps=ramps)
                fname = f"{an}{i + 1}"
                sp.add_frame(fname, cv, dur)
                names.append(fname)
            sp.animations[an] = names
        return sp

    # -- JSON
    @classmethod
    def from_dict(cls, d, palette, lut, origin="<dict>"):
        from .sprite import parse_rows
        rig = cls(d["width"], d["height"], palette, name=d.get("name", "rig"))
        parts = d["parts"]
        if not isinstance(parts, dict):
            raise GridError(f"{origin}: 'parts' must be an object name -> part")
        for pname, pd in parts.items():
            rows = pd.get("rows")
            if not rows:
                raise GridError(f"{origin}: part {pname!r} has no 'rows'")
            w, h = len(rows[0]), len(rows)
            cv = rig.part(pname, z=pd.get("z"), x=pd.get("x", 0), y=pd.get("y", 0), w=w, h=h)
            cv.data[:] = parse_rows(rows, w, h, lut, f"{origin}: part {pname!r}")
            for an, arows in pd.get("alts", {}).items():
                acv = rig.alt(pname, an, copy=False)
                acv.data[:] = parse_rows(arows, w, h, lut, f"{origin}: part {pname!r} alt {an!r}")
        inv = {v: k for k, v in lut.items()}
        for an, ad in d.get("rig_animations", {}).items():
            frames = [{k: (tuple(v) if isinstance(v, list) else v) for k, v in f.items()} for f in ad["frames"]]
            rig.animation(an, frames, ad.get("durations", ad.get("duration", 150)))
        ol = d.get("rig_outline")
        if ol:
            col = ol.get("color")
            if isinstance(col, str) and len(col) == 1 and col in lut:
                col = lut[col]
            rig._json_outline = dict(outline=col, selective=ol.get("selective", False),
                                     connectivity=ol.get("connectivity", 8))
            o = rig._json_outline
            rig.post.append(lambda cv: cv.outline(color=o["outline"], selective=o["selective"],
                                                  connectivity=o["connectivity"]))
        del inv
        return rig
