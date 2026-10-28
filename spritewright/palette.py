"""Palettes, color parsing, perceptual nearest-color, ramps."""
from __future__ import annotations

import colorsys
import json
import re
from pathlib import Path

import numpy as np

from .errors import ColorError, PixelError
from .paths import BUNDLED_PALETTES, ROOT, palette_dirs

PALETTE_DIR = BUNDLED_PALETTES  # palettes shipped with the package (pico-8); see paths.palette_dirs()
TRANSPARENT = -1
TRANSPARENT_TOKENS = {None, ".", "transparent", "none", "clear"}
_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")

ALIASES = {"pico8": "pico-8"}


def _find_named(key):
    """Path of palette `key`.hex in the palette folders (search order: paths.palette_dirs), or None."""
    for d in palette_dirs():
        p = d / f"{key}.hex"
        if p.is_file():
            return p
    return None


# --------------------------------------------------------------------------- helpers
def parse_hex(s) -> tuple:
    """'#f2c39b' / 'F2C39B' / (r,g,b) -> (r,g,b)."""
    if isinstance(s, (tuple, list)) and len(s) in (3, 4):
        vals = tuple(int(v) for v in s[:3])
        if any(v < 0 or v > 255 for v in vals):
            raise ColorError(f"RGB values must be 0..255, got {s!r}")
        return vals
    if not isinstance(s, str):
        raise ColorError(f"expected hex color string like 'f2c39b', got {s!r}")
    m = _HEX_RE.match(s.strip())
    if not m:
        raise ColorError(f"invalid hex color {s!r}; expected RRGGBB or #RRGGBB")
    v = m.group(1)
    return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))


def is_hex(s) -> bool:
    return isinstance(s, str) and bool(_HEX_RE.match(s.strip()))


def to_hex(rgb) -> str:
    return "%02x%02x%02x" % tuple(int(v) for v in rgb[:3])


def rgb_to_lab(rgb) -> np.ndarray:
    """sRGB (..., 3) 0..255 -> CIELAB (..., 3)."""
    a = np.asarray(rgb, dtype=np.float64) / 255.0
    a = np.where(a > 0.04045, ((a + 0.055) / 1.055) ** 2.4, a / 12.92)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = a @ m.T
    xyz = xyz / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    L = 116 * f[..., 1] - 16
    A = 500 * (f[..., 0] - f[..., 1])
    B = 200 * (f[..., 1] - f[..., 2])
    return np.stack([L, A, B], axis=-1)


def luminance(rgb) -> float:
    """Relative luminance 0..1 (Rec.709 on linearised sRGB)."""
    a = np.asarray(rgb[:3], dtype=np.float64) / 255.0
    a = np.where(a > 0.04045, ((a + 0.055) / 1.055) ** 2.4, a / 12.92)
    return float(0.2126 * a[0] + 0.7152 * a[1] + 0.0722 * a[2])


def hsv(rgb):
    r, g, b = (v / 255.0 for v in rgb[:3])
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return h * 360.0, s, v


def _hue_diff(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


def _move_hue(h, target, amount):
    """Move hue h toward target by `amount` degrees along shortest arc (no overshoot)."""
    d = ((target - h + 540) % 360) - 180
    step = min(abs(d), amount)
    return (h + (step if d >= 0 else -step)) % 360


# --------------------------------------------------------------------------- Palette
class Palette:
    """Ordered list of RGB colors plus optional names ("skin" -> index)."""

    def __init__(self, colors, names=None, name="custom", source=None):
        cols = [parse_hex(c) for c in colors]
        if not cols:
            raise PixelError("palette must contain at least one color")
        if len(cols) > 255:
            raise PixelError(f"palette has {len(cols)} colors; max 255 (one GIF index is reserved)")
        self.colors = cols
        self.name = name
        self.source = source  # builtin slug or file path, used when saving sprites
        self.names: dict[str, int] = {}
        for n, i in (names or {}).items():
            self.set_name(n, i)
        self._lab = rgb_to_lab(np.array(cols, dtype=np.float64))

    # -- container protocol
    def __len__(self):
        return len(self.colors)

    def __iter__(self):
        return iter(self.colors)

    def __getitem__(self, i):
        return self.colors[self.index(i)]

    def __repr__(self):
        return f"Palette({self.name!r}, {len(self)} colors, names={list(self.names)})"

    def __eq__(self, other):
        return isinstance(other, Palette) and self.colors == other.colors

    def __hash__(self):
        return hash(tuple(self.colors))

    # -- loading / saving
    @staticmethod
    def builtin_names():
        """Names of every palette found in the palette folders (bundled + user folders)."""
        return sorted({p.stem for d in palette_dirs() for p in d.glob("*.hex")})

    @classmethod
    def load(cls, spec, base_dir=None) -> "Palette":
        """spec: Palette | palette name ('pico-8', or any <name>.hex in a palette folder) | path
        (.hex/.json) | dict | list of hex."""
        if isinstance(spec, Palette):
            return spec
        if isinstance(spec, list):
            return cls(spec, name="inline")
        if isinstance(spec, dict):
            return cls._from_dict(spec, source=None)
        if not isinstance(spec, (str, Path)):
            raise PixelError(f"cannot interpret palette spec {spec!r}")
        s = str(spec)
        key = ALIASES.get(s.lower().replace("_", "-").replace(" ", "-").replace("-", ""), None) \
            or s.lower().replace("_", "-").replace(" ", "-")
        builtin = None if s.endswith((".hex", ".json")) else _find_named(key)
        if builtin is not None:
            p = cls._from_hex_file(builtin)
            p.name = key
            p.source = key
            return p
        cands = []
        pth = Path(s)
        if pth.is_absolute():
            cands.append(pth)
        else:
            if base_dir:
                cands.append(Path(base_dir) / pth)
            cands += [Path.cwd() / pth, ROOT / pth] + [d / pth for d in palette_dirs()]
        for c in cands:
            if c.is_file():
                if c.suffix.lower() == ".json":
                    with open(c, encoding="utf-8") as f:
                        p = cls._from_dict(json.load(f), source=str(c))
                else:
                    p = cls._from_hex_file(c)
                return p
        raise PixelError(
            f"palette {s!r} not found. Available palettes: {', '.join(cls.builtin_names())}; "
            f"give a path to a .hex/.json file, or drop <name>.hex into ./palettes, "
            f"~/.spritewright/palettes or a folder listed in SPRITEWRIGHT_PALETTES")

    @classmethod
    def _from_hex_file(cls, path):
        path = Path(path)
        cols = []
        for ln, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.split(";")[0].strip()
            if not line:
                continue
            if not is_hex(line):
                raise PixelError(f"{path}: line {ln}: {line!r} is not RRGGBB")
            cols.append(line)
        return cls(cols, name=path.stem, source=str(path))

    @classmethod
    def _from_dict(cls, d, source=None):
        name = d.get("name", "custom") if isinstance(d, dict) else "custom"
        if "colors" in d:
            colors = d["colors"]
            names = dict(d.get("names", {}))
        else:  # plain {"skin": "f2c39b", ...}
            colors = {k: v for k, v in d.items() if k != "name"}
            names = {}
        if isinstance(colors, dict):
            cols = []
            for i, (n, h) in enumerate(colors.items()):
                cols.append(h)
                names[n] = i
            colors = cols
        p = cls(colors, names=names, name=name, source=source)
        return p

    def to_dict(self):
        inv = {i: n for n, i in self.names.items()}
        if len(inv) == len(self.colors) and len(self.names) == len(self.colors):
            return {"name": self.name, "colors": {inv[i]: to_hex(c) for i, c in enumerate(self.colors)}}
        return {"name": self.name, "colors": [to_hex(c) for c in self.colors], "names": dict(self.names)}

    def save(self, path):
        """Save as .hex (colors only) or .json (with names)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() == ".hex":
            path.write_text("\n".join(to_hex(c) for c in self.colors) + "\n", encoding="utf-8")
        else:
            path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        self.source = str(path)
        return path

    def spec(self, relative_to=None):
        """Serializable reference used inside sprite JSON."""
        if self.source and not self.names and _find_named(self.source) is not None:
            return self.source
        if self.source and Path(self.source).exists():
            p = Path(self.source)
            if relative_to:
                try:
                    return str(p.resolve().relative_to(Path(relative_to).resolve())).replace("\\", "/")
                except ValueError:
                    pass
            return str(p)
        return self.to_dict()

    def copy(self, name=None):
        return Palette(self.colors, dict(self.names), name or self.name, self.source)

    def extended(self, colors, name=None):
        """New palette with extra colors appended. colors: list of hex or {name: hex}."""
        p = self.copy(name)
        items = colors.items() if isinstance(colors, dict) else [(None, c) for c in colors]
        for n, c in items:
            rgb = parse_hex(c)
            if rgb in p.colors:
                idx = p.colors.index(rgb)
            else:
                p.colors.append(rgb)
                idx = len(p.colors) - 1
            if n:
                p.names[n] = idx
        p._lab = rgb_to_lab(np.array(p.colors, dtype=np.float64))
        p.source = None
        return p

    # -- names / lookup
    def set_name(self, name, color):
        if not isinstance(name, str) or not name or name.lower() in TRANSPARENT_TOKENS:
            raise ColorError(f"invalid color name {name!r}")
        idx = self.index(color)
        self.names[name] = idx
        return idx

    def name_of(self, i):
        for n, j in self.names.items():
            if j == i:
                return n
        return None

    def hex(self, color):
        return to_hex(self.colors[self.index(color)])

    def index(self, color, strict=True) -> int:
        """Resolve palette index / name / hex / rgb tuple -> index (TRANSPARENT for '.'/None).

        strict=True: off-palette colors raise ColorError. strict=False: snapped to nearest.
        """
        if isinstance(color, str) and color.strip().lower() in TRANSPARENT_TOKENS:
            return TRANSPARENT
        if color is None:
            return TRANSPARENT
        if isinstance(color, (bool,)):
            raise ColorError(f"invalid color {color!r}")
        if isinstance(color, (int, np.integer)):
            c = int(color)
            if c == TRANSPARENT:
                return TRANSPARENT
            if 0 <= c < len(self.colors):
                return c
            raise ColorError(f"palette index {c} out of range for palette {self.name!r} "
                             f"(valid 0..{len(self.colors) - 1}, or -1 for transparent)")
        if isinstance(color, str):
            key = color.strip()
            if key in self.names:
                return self.names[key]
            if key.lower() in self.names:
                return self.names[key.lower()]
            if is_hex(key):
                rgb = parse_hex(key)
            else:
                known = ", ".join(self.names) if self.names else "(palette has no named colors)"
                raise ColorError(f"unknown color name {color!r} for palette {self.name!r}; "
                                 f"known names: {known}; or use an index 0..{len(self) - 1} / hex")
        elif isinstance(color, (tuple, list)):
            rgb = parse_hex(color)
        else:
            raise ColorError(f"cannot interpret color {color!r}")
        if rgb in self.colors:
            return self.colors.index(rgb)
        n = self.nearest(rgb)
        if strict:
            raise ColorError(
                f"color #{to_hex(rgb)} is not in palette {self.name!r} (strict mode). "
                f"Nearest is index {n} #{to_hex(self.colors[n])}. "
                f"Use that, add it to the palette, or pass strict=False to snap.")
        return n

    def nearest(self, rgb) -> int:
        lab = rgb_to_lab(np.array(parse_hex(rgb), dtype=np.float64))
        return int(np.argmin(((self._lab - lab) ** 2).sum(-1)))

    def nearest_many(self, rgb_array) -> np.ndarray:
        """(..., 3) array -> (...) indices."""
        arr = np.asarray(rgb_array, dtype=np.float64)
        lab = rgb_to_lab(arr)
        flat = lab.reshape(-1, 3)
        out = np.empty(flat.shape[0], dtype=np.int16)
        for s in range(0, flat.shape[0], 8192):
            chunk = flat[s:s + 8192]
            d = ((chunk[:, None, :] - self._lab[None, :, :]) ** 2).sum(-1)
            out[s:s + 8192] = d.argmin(1)
        return out.reshape(arr.shape[:-1])

    # -- color relations
    def luminance(self, color):
        return luminance(self.colors[self.index(color)])

    def hsv(self, color):
        return hsv(self.colors[self.index(color)])

    def _step(self, idx, darker=True):
        base = self.colors[idx]
        lb = luminance(base)
        hb, sb, vb = hsv(base)
        best, best_score = None, 1e9
        for j, c in enumerate(self.colors):
            if j == idx:
                continue
            lj = luminance(c)
            gap = (lb - lj) if darker else (lj - lb)
            if gap <= 0.015:
                continue
            hj, sj, vj = hsv(c)
            grayish = sb < 0.15 or sj < 0.15
            hd = _hue_diff(hb, hj) / 180.0
            if not grayish and hd > 0.33:  # > 60 degrees: different color family
                continue
            # darker steps may drift toward blue/purple, lighter toward yellow (bonus)
            target = 250 if darker else 60
            drift = (_hue_diff(hb, target) - _hue_diff(hj, target)) / 180.0
            score = gap * 2.0 + hd * (0.4 if grayish else 1.2) + abs(sb - sj) * 0.3 - max(0, drift) * 0.3
            if score < best_score:
                best, best_score = j, score
        return best

    def darker(self, color, steps=1) -> int:
        """Next darker palette color with similar hue (one 'ramp step'); repeat `steps` times."""
        idx = self.index(color)
        for _ in range(steps):
            n = self._step(idx, True)
            if n is None:
                break
            idx = n
        return idx

    def lighter(self, color, steps=1) -> int:
        idx = self.index(color)
        for _ in range(steps):
            n = self._step(idx, False)
            if n is None:
                break
            idx = n
        return idx

    def auto_ramp(self, color, down=2, up=2) -> list:
        """Ramp (dark -> light) of palette indices around `color` using darker()/lighter()."""
        idx = self.index(color)
        ramp = [idx]
        cur = idx
        for _ in range(down):
            n = self.darker(cur)
            if n == cur or n in ramp:
                break
            ramp.insert(0, n)
            cur = n
        cur = idx
        for _ in range(up):
            n = self.lighter(cur)
            if n == cur or n in ramp:
                break
            ramp.append(n)
            cur = n
        return ramp

    def ramp_between(self, a, b, tolerance=0.45) -> list:
        """Palette indices forming a path from color a to color b (inclusive), sorted.

        Intermediate colors are those whose Lab position projects between a and b and lies
        within `tolerance` * |a-b| of the line.
        """
        ia, ib = self.index(a), self.index(b)
        la, lb = self._lab[ia], self._lab[ib]
        d = lb - la
        L2 = float((d ** 2).sum())
        if L2 == 0:
            return [ia]
        mids = []
        for j in range(len(self.colors)):
            if j in (ia, ib):
                continue
            v = self._lab[j] - la
            t = float((v * d).sum() / L2)
            if 0.05 < t < 0.95:
                perp = np.sqrt(max(0.0, float((v ** 2).sum()) - t * t * L2))
                if perp < tolerance * np.sqrt(L2):
                    mids.append((t, j))
        mids.sort()
        # drop near-duplicates in t
        out, last_t = [ia], 0.0
        for t, j in mids:
            if t - last_t > 0.08:
                out.append(j)
                last_t = t
        out.append(ib)
        return out


# --------------------------------------------------------------------------- ramp generator
def generate_ramp(base, steps=5, hue_shift=14.0, palette=None, dedupe=True):
    """Hue-shifted ramp from a base color.

    Darker steps rotate hue toward blue/purple (~250 deg) and gain saturation; lighter steps
    rotate toward yellow (~60 deg) and lose saturation. Returns list of hex strings
    (dark -> light). If `palette` is given, each step is snapped to the nearest palette color
    and a list of palette indices is returned instead.
    """
    if not 2 <= steps <= 9:
        raise PixelError(f"ramp steps must be 2..9, got {steps}")
    r, g, b = parse_hex(base)
    h, s, v = hsv((r, g, b))
    mid = (steps - 1) // 2
    n_dark, n_light = mid, steps - 1 - mid
    out = []
    for i in range(steps):
        k = i - mid
        if k == 0:
            hh, ss, vv = h, s, v
        elif k < 0:
            t = -k / max(1, n_dark)  # 0..1
            hh = _move_hue(h, 250, hue_shift * -k) if s > 0.05 else h
            vv = v - (v - 0.12) * (t * 0.72)
            ss = min(1.0, s + (1 - s) * 0.25 * t) if s > 0.05 else s
        else:
            t = k / max(1, n_light)
            hh = _move_hue(h, 60, hue_shift * k) if s > 0.05 else h
            vv = v + (1.0 - v) * (0.25 + 0.6 * t) if v < 1 else 1.0
            vv = min(1.0, vv)
            ss = max(0.0, s * (1 - 0.45 * t))
        rr, gg, bb = colorsys.hsv_to_rgb(hh / 360, ss, vv)
        out.append(to_hex((round(rr * 255), round(gg * 255), round(bb * 255))))
    if palette is None:
        return out
    pal = Palette.load(palette)
    idxs = [pal.nearest(c) for c in out]
    if dedupe:
        res = []
        for i in idxs:
            if not res or res[-1] != i:
                res.append(i)
        idxs = res
    return idxs
