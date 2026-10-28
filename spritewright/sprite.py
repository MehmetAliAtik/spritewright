"""Sprite (named frames + durations + animations) and the JSON text-grid format.

Grid JSON format::

    {
      "name": "hero", "width": 16, "height": 16,
      "palette": "pico-8",                # palette name | "palette.json" (relative) | {name: hex} | [hex]
      "chars": {"A": 0, "s": "skin", "r": "#ff004d"},   # char -> index / name / hex ('.' = transparent)
      "frames": {
        "idle1": {"duration": 200, "rows": ["....", ...]},
        "idle2": ["....", ...]           # shorthand: rows only (default duration)
      },
      "animations": {"idle": ["idle1", "idle2"]},       # optional; else derived from names
      "parts": {...}, "rig_animations": {...}           # optional part rig (see parts.py)
    }

If "palette" is omitted, the palette is built from the hex values in "chars".
"""
from __future__ import annotations

import json
import re
import runpy
import sys
from pathlib import Path

import numpy as np

from .canvas import GRID_CHARS, Canvas
from .errors import ColorError, GridError, PixelError, SourceError
from .palette import TRANSPARENT, Palette, is_hex
from .paths import ROOT, examples_root, projects_root, scratch_root
ALLOWED_CHARS = set(GRID_CHARS)


def _anim_name(frame_name):
    m = re.match(r"^(.*?)[_-]?(\d+)$", frame_name)
    return m.group(1) if m and m.group(1) else frame_name


class Sprite:
    """A set of equally sized frames sharing one palette."""

    def __init__(self, w, h, palette, name="sprite", default_duration=100):
        self.w, self.h = int(w), int(h)
        Canvas(self.w, self.h, palette)  # validates size
        self.palette = Palette.load(palette)
        self.name = name
        self.frames: dict[str, Canvas] = {}
        self.durations: dict[str, int] = {}
        self.animations: dict[str, list] = {}
        self.default_duration = default_duration
        self.source = None
        self.extra = {}  # unknown JSON keys preserved on save

    def __repr__(self):
        return f"Sprite({self.name!r}, {self.w}x{self.h}, frames={list(self.frames)})"

    # -- frames
    def new_frame(self, name, duration=None, copy_from=None) -> Canvas:
        if name in self.frames:
            raise PixelError(f"frame {name!r} already exists in sprite {self.name!r}")
        cv = self.frame(copy_from).copy(name) if copy_from is not None else Canvas(self.w, self.h, self.palette, name=name)
        cv.name = name
        self.frames[name] = cv
        self.durations[name] = int(duration or self.default_duration)
        return cv

    def add_frame(self, name, canvas, duration=None):
        if canvas.size != (self.w, self.h):
            raise PixelError(f"frame {name!r} is {canvas.w}x{canvas.h}, sprite is {self.w}x{self.h}")
        if canvas.palette != self.palette:
            cv = Canvas(self.w, self.h, self.palette)
            cv.stamp(canvas, 0, 0)
            canvas = cv
        canvas.name = name
        self.frames[name] = canvas
        self.durations[name] = int(duration or self.durations.get(name) or self.default_duration)
        return canvas

    def frame(self, key) -> Canvas:
        if isinstance(key, int):
            names = list(self.frames)
            if not -len(names) <= key < len(names):
                raise PixelError(f"frame index {key} out of range (sprite has {len(names)} frames)")
            return self.frames[names[key]]
        if key not in self.frames:
            raise PixelError(f"no frame {key!r} in sprite {self.name!r}; frames: {', '.join(self.frames)}")
        return self.frames[key]

    def __getitem__(self, key):
        return self.frame(key)

    def remove_frame(self, name):
        self.frame(name)
        del self.frames[name]
        self.durations.pop(name, None)
        for a in self.animations.values():
            while name in a:
                a.remove(name)

    def get_animations(self) -> dict:
        """Explicit animations, else derived by stripping trailing digits (walk1, walk2 -> walk)."""
        if self.animations:
            return {k: list(v) for k, v in self.animations.items()}
        out = {}
        for n in self.frames:
            out.setdefault(_anim_name(n), []).append(n)
        return out

    def frame_names(self, anim=None) -> list:
        if anim is None:
            return list(self.frames)
        anims = self.get_animations()
        if anim not in anims:
            if anim in self.frames:
                return [anim]
            raise PixelError(f"no animation {anim!r}; animations: {', '.join(anims)}")
        return anims[anim]

    # -- frame tools
    def copy_frame(self, src, dst, duration=None):
        cv = self.frame(src).copy(dst)
        self.frames[dst] = cv
        self.durations[dst] = int(duration or self.durations.get(src, self.default_duration))
        return cv

    def _targets(self, frame):
        if frame in (None, "all", "*"):
            return list(self.frames.values())
        if isinstance(frame, (list, tuple)):
            return [self.frame(f) for f in frame]
        return [self.frame(frame)]

    def shift(self, frame, dx, dy, wrap=False):
        for f in self._targets(frame):
            f.shift(dx, dy, wrap)
        return self

    def flip_h(self, frame=None):
        for f in self._targets(frame):
            f.flip_h()
        return self

    def flip_v(self, frame=None):
        for f in self._targets(frame):
            f.flip_v()
        return self

    def mirror(self, frame=None, direction="lr"):
        for f in self._targets(frame):
            f.mirror(direction)
        return self

    def recolor(self, mapping, frame=None):
        for f in self._targets(frame):
            f.recolor(mapping)
        return self

    def outline(self, frame=None, **kw):
        for f in self._targets(frame):
            f.outline(**kw)
        return self

    def loop_check(self, anim=None) -> int:
        """Pixel diff count between the last and first frame of an animation (0 = identical)."""
        names = self.frame_names(anim)
        return self.frame(names[-1]).diff_count(self.frame(names[0]))

    # -- persistence
    def to_dict(self, base_dir=None) -> dict:
        used = set()
        for f in self.frames.values():
            used |= set(f.colors_used())
        used = sorted(used)
        if len(used) > len(GRID_CHARS):
            raise GridError(f"sprite uses {len(used)} colors; text-grid format supports {len(GRID_CHARS)}")
        # stable, readable chars: reuse previous mapping if present
        prev = self.extra.get("_chars_by_index", {})
        chars, taken = {}, set()
        for idx in used:
            ch = prev.get(idx)
            if ch and ch not in taken:
                chars[idx] = ch
                taken.add(ch)
        pool = [c for c in GRID_CHARS if c not in taken]
        for idx in used:
            if idx not in chars:
                chars[idx] = pool.pop(0)
        d = {"name": self.name, "width": self.w, "height": self.h,
             "palette": self.palette.spec(base_dir),
             "chars": {chars[i]: (self.palette.name_of(i) or i) for i in used},
             "frames": {}}
        for n, f in self.frames.items():
            rows = ["".join("." if v < 0 else chars[int(v)] for v in row) for row in f.data]
            d["frames"][n] = {"duration": self.durations.get(n, self.default_duration), "rows": rows}
        if self.animations:
            d["animations"] = self.animations
        for k, v in self.extra.items():
            if not k.startswith("_") and k not in d:
                d[k] = v
        return d

    def save(self, path=None):
        """Save as grid JSON (default: the file it was loaded from)."""
        path = Path(path or self.source or "")
        if not path.name:
            raise PixelError("Sprite.save needs a path")
        if path.suffix.lower() != ".json":
            raise PixelError(f"sprites are saved as .json grids, got {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        d = self.to_dict(base_dir=path.parent)
        txt = json.dumps(d, indent=2)
        path.write_text(txt + "\n", encoding="utf-8")
        self.source = str(path)
        return path

    @classmethod
    def from_dict(cls, d, base_dir=None, origin="<dict>") -> "Sprite":
        return load_grid_dict(d, base_dir, origin)

    @classmethod
    def load(cls, path) -> "Sprite":
        return load_sprite(path)


# --------------------------------------------------------------------------- grid loading
def _parse_chars(chars, palette, origin):
    if not isinstance(chars, dict):
        raise GridError(f"{origin}: 'chars' must be an object mapping char -> color")
    lut = {".": TRANSPARENT}
    for ch, col in chars.items():
        if len(ch) != 1:
            raise GridError(f"{origin}: chars key {ch!r} must be exactly one character")
        if ch == ".":
            raise GridError(f"{origin}: '.' is reserved for transparent")
        if ch not in ALLOWED_CHARS:
            raise GridError(f"{origin}: char {ch!r} not allowed; use A-Z a-z 0-9 or one of #@$%&*+=?!")
        try:
            lut[ch] = palette.index(col, strict=True)
        except ColorError as e:
            raise GridError(f"{origin}: chars[{ch!r}] = {col!r}: {e}") from None
    return lut


def parse_rows(rows, w, h, lut, where):
    """Rows (list of str) -> (h,w) int16 array, with precise errors."""
    if not isinstance(rows, list):
        raise GridError(f"{where}: rows must be a list of strings")
    if len(rows) != h:
        raise GridError(f"{where}: has {len(rows)} rows, expected {h} (height)")
    arr = np.full((h, w), TRANSPARENT, dtype=np.int16)
    for y, row in enumerate(rows):
        if not isinstance(row, str):
            raise GridError(f"{where} row {y + 1} (y={y}): expected a string, got {type(row).__name__}")
        if len(row) != w:
            raise GridError(f"{where} row {y + 1} (y={y}): length {len(row)}, expected {w} (width)")
        for x, ch in enumerate(row):
            if ch not in lut:
                known = "".join(k for k in lut if k != ".")
                raise GridError(f"{where} row {y + 1} (y={y}) col {x + 1} (x={x}): unknown char {ch!r}; "
                                f"defined chars: {known} and '.'")
            arr[y, x] = lut[ch]
    return arr


def load_grid_dict(d, base_dir=None, origin="<dict>") -> Sprite:
    if not isinstance(d, dict):
        raise GridError(f"{origin}: top level must be a JSON object")
    for k in ("width", "height"):
        if not isinstance(d.get(k), int):
            raise GridError(f"{origin}: missing or non-integer {k!r}")
    w, h = d["width"], d["height"]
    if "palette" in d:
        palette = Palette.load(d["palette"], base_dir=base_dir)
    else:
        cols = [v for v in d.get("chars", {}).values()]
        if not cols or not all(is_hex(c) for c in cols):
            raise GridError(f"{origin}: no 'palette' given, so every chars value must be a hex color")
        palette = Palette(list(dict.fromkeys(c.lower().lstrip("#") for c in cols)), name=d.get("name", "grid"))
    lut = _parse_chars(d.get("chars", {}), palette, origin)
    sp = Sprite(w, h, palette, name=d.get("name", Path(origin).stem),
                default_duration=int(d.get("default_duration", 100)))
    sp.extra["_chars_by_index"] = {v: k for k, v in lut.items() if v >= 0}
    frames = d.get("frames", {})
    if isinstance(frames, list):
        frames = {f.get("name", f"frame{i + 1}"): f for i, f in enumerate(frames)}
    if not isinstance(frames, dict):
        raise GridError(f"{origin}: 'frames' must be an object or list")
    for name, fd in frames.items():
        if isinstance(fd, list):
            rows, dur = fd, None
        elif isinstance(fd, dict):
            if "rows" not in fd:
                raise GridError(f"{origin}: frame {name!r} has no 'rows'")
            rows, dur = fd["rows"], fd.get("duration")
        else:
            raise GridError(f"{origin}: frame {name!r} must be a list of rows or an object with 'rows'")
        arr = parse_rows(rows, w, h, lut, f"{origin}: frame {name!r}")
        cv = Canvas.from_array(arr, palette, name=name)
        sp.add_frame(name, cv, dur)
    if "parts" in d:
        from .parts import Rig
        rig = Rig.from_dict(d, palette, lut, origin)
        rig.build(sp)
    if "animations" in d:
        anims = d["animations"]
        if not isinstance(anims, dict):
            raise GridError(f"{origin}: 'animations' must be an object name -> [frame names]")
        for a, names in anims.items():
            for n in names:
                if n not in sp.frames:
                    raise GridError(f"{origin}: animation {a!r} references unknown frame {n!r}")
        sp.animations.update({a: list(v) for a, v in anims.items()})
    for k, v in d.items():
        if k not in ("name", "width", "height", "palette", "chars", "frames", "animations",
                     "default_duration"):
            sp.extra[k] = v
    if not sp.frames:
        raise GridError(f"{origin}: sprite has no frames")
    return sp


# --------------------------------------------------------------------------- source resolution
def resolve_source(src) -> Path:
    """Find a sprite source: absolute/relative path, projects/<src> or (checkout) examples/<src>
    [.json|.py]."""
    p = Path(src)
    cands = [p] if p.is_absolute() else [Path.cwd() / p, projects_root() / p, ROOT / p, examples_root() / p]
    more = []
    for c in cands:
        more.append(c)
        if not c.suffix:
            more += [c.with_suffix(".json"), c.with_suffix(".py")]
    for c in more:
        if c.is_file():
            return c.resolve()
    raise SourceError(f"sprite source {src!r} not found (looked for: "
                      + ", ".join(str(c) for c in more[:6]) + ")")


def project_of(path) -> str:
    p = Path(path).resolve()
    for base in (projects_root(), examples_root()):
        try:
            rel = p.relative_to(base.resolve())
        except ValueError:
            continue
        return rel.parts[0] if len(rel.parts) > 1 else "misc"
    return "misc"


def output_root() -> Path:
    """Scratch output root: env SPRITEWRIGHT_OUTPUT if set, else ./output (current directory)."""
    return scratch_root()


def output_dir(path_or_project, create=True) -> Path:
    """output/<project>/ for a source path or project name (created unless create=False)."""
    s = str(path_or_project)
    proj = project_of(s) if (s.endswith((".json", ".py")) or "/" in s or "\\" in s) else s
    d = output_root() / proj
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def load_sprite(src) -> Sprite:
    """Load a grid .json or a drawing .py script (must define build() -> Sprite, or `sprite`)."""
    if isinstance(src, Sprite):
        return src
    path = resolve_source(src)
    if path.suffix.lower() == ".json":
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except json.JSONDecodeError as e:
            raise GridError(f"{path}: invalid JSON at line {e.lineno} col {e.colno}: {e.msg}") from None
        sp = load_grid_dict(d, base_dir=path.parent, origin=str(path.name))
        sp.source = str(path)
        return sp
    if path.suffix.lower() == ".py":
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        ns = runpy.run_path(str(path), run_name="spritewright_source")
        sp = ns["build"]() if callable(ns.get("build")) else ns.get("sprite")
        if not isinstance(sp, Sprite):
            raise SourceError(f"{path}: script must define build() returning a Sprite (or a `sprite` variable)")
        sp.extra["_script"] = str(path)
        return sp
    raise SourceError(f"{path}: unsupported source type (use .json grid or .py script)")
