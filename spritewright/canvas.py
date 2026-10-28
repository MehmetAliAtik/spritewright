"""Indexed-color Canvas with a pixel-art drawing API.

Pixels are palette indices (int16); -1 means transparent. Every drawing call accepts a
palette index, a palette color name ("skin"), or a hex string (strict mode: must be in the
palette). Coordinates are integers, (0,0) is top-left.
"""
from __future__ import annotations

from collections import Counter, deque
from contextlib import contextmanager

import numpy as np

from .errors import ColorError, GridError, PixelError
from .palette import TRANSPARENT, Palette

MAX_SIZE = 256

BAYER2 = np.array([[0, 2], [3, 1]], dtype=np.float64)
BAYER4 = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], dtype=np.float64)
BAYER8 = np.zeros((8, 8))
for _y in range(8):
    for _x in range(8):
        BAYER8[_y, _x] = 4 * BAYER4[_y % 4, _x % 4] + BAYER2[_y // 4, _x // 4]

GRID_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789#@$%&*+=?!"


def threshold_map(pattern, w, h, ox=0, oy=0):
    """(h,w) array of thresholds in (0,1) for an ordered-dither pattern."""
    ys, xs = np.mgrid[0:h, 0:w]
    xs = xs + ox
    ys = ys + oy
    if pattern in ("bayer2", "b2"):
        m = BAYER2
    elif pattern in ("bayer4", "b4", "bayer"):
        m = BAYER4
    elif pattern in ("bayer8", "b8"):
        m = BAYER8
    elif pattern == "checker":
        return np.where((xs + ys) % 2 == 0, 0.25, 0.75)
    elif pattern == "hlines":
        return np.where(ys % 2 == 0, 0.25, 0.75)
    elif pattern == "vlines":
        return np.where(xs % 2 == 0, 0.25, 0.75)
    elif pattern == "diagonal":
        return ((xs + ys) % 4 + 0.5) / 4.0
    else:
        raise PixelError(f"unknown dither pattern {pattern!r}; use bayer2, bayer4, bayer8, "
                         f"checker, hlines, vlines, diagonal")
    n = m.shape[0]
    return (m[ys % n, xs % n] + 0.5) / (n * n)


def _bresenham(x0, y0, x1, y1):
    pts = []
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        pts.append((x0, y0))
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy
    return pts


def _ellipse_points(x0, y0, x1, y1):
    """Zingl's midpoint ellipse inside the bounding box (inclusive corners)."""
    pts = []
    a, b = abs(x1 - x0), abs(y1 - y0)
    b1 = b & 1
    dx = 4 * (1 - a) * b * b
    dy = 4 * (b1 + 1) * a * a
    err = dx + dy + b1 * a * a
    if x0 > x1:
        x0 = x1
        x1 += a
    if y0 > y1:
        y0 = y1
    y0 += (b + 1) // 2
    y1 = y0 - b1
    a8 = 8 * a * a
    b8 = 8 * b * b
    while True:
        pts += [(x1, y0), (x0, y0), (x0, y1), (x1, y1)]
        e2 = 2 * err
        if e2 <= dy:
            y0 += 1
            y1 -= 1
            dy += a8
            err += dy
        if e2 >= dx or 2 * err > dy:
            x0 += 1
            x1 -= 1
            dx += b8
            err += dx
        if x0 > x1:
            break
    while y0 - y1 < b:
        pts += [(x0 - 1, y0), (x1 + 1, y0), (x0 - 1, y1), (x1 + 1, y1)]
        y0 += 1
        y1 -= 1
    return pts


class Canvas:
    """Indexed pixel canvas. Create with Canvas(w, h, palette)."""

    def __init__(self, w, h, palette, fill=None, strict=True, name=None):
        for nm, v in (("width", w), ("height", h)):
            if not isinstance(v, (int, np.integer)) or isinstance(v, bool):
                raise PixelError(f"canvas {nm} must be an int, got {v!r}")
            if not 1 <= v <= MAX_SIZE:
                raise PixelError(f"canvas {nm} {v} out of range 1..{MAX_SIZE} (sprites: 16..256)")
        self.w, self.h = int(w), int(h)
        self.palette = Palette.load(palette)
        self.strict = strict
        self.name = name
        self.data = np.full((self.h, self.w), TRANSPARENT, dtype=np.int16)
        self._sym = None  # (mx, my, axis2_x, axis2_y)
        if fill is not None:
            self.data[:] = self.c(fill)

    # ------------------------------------------------------------------ basics
    @classmethod
    def from_array(cls, arr, palette, strict=True, name=None):
        arr = np.asarray(arr)
        cv = cls(arr.shape[1], arr.shape[0], palette, strict=strict, name=name)
        if arr.size and (arr.max() >= len(cv.palette) or arr.min() < -1):
            raise PixelError("array contains indices outside the palette")
        cv.data[:] = arr
        return cv

    @property
    def size(self):
        return (self.w, self.h)

    def __repr__(self):
        return f"Canvas({self.w}x{self.h}, palette={self.palette.name!r}, name={self.name!r})"

    def copy(self, name=None):
        cv = Canvas(self.w, self.h, self.palette, strict=self.strict, name=name or self.name)
        cv.data = self.data.copy()
        return cv

    def c(self, color) -> int:
        """Resolve a color argument to a palette index (honours strict mode)."""
        return self.palette.index(color, strict=self.strict)

    def get(self, x, y) -> int:
        if not (0 <= x < self.w and 0 <= y < self.h):
            raise PixelError(f"get({x},{y}) outside canvas {self.w}x{self.h}")
        return int(self.data[y, x])

    def in_bounds(self, x, y):
        return 0 <= x < self.w and 0 <= y < self.h

    def clear(self, color=None):
        self.data[:] = self.c(color)
        return self

    fill = clear

    def opaque_mask(self):
        return self.data >= 0

    def mask(self, color):
        """Boolean mask of pixels equal to color (or list of colors)."""
        if isinstance(color, (list, set)):
            m = np.zeros_like(self.data, dtype=bool)
            for col in color:
                m |= self.data == self.c(col)
            return m
        return self.data == self.c(color)

    def bbox(self):
        """(x, y, w, h) of opaque pixels, or None if empty."""
        ys, xs = np.nonzero(self.data >= 0)
        if len(xs) == 0:
            return None
        return (int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))

    def colors_used(self):
        """{index: count} of opaque pixels."""
        vals, counts = np.unique(self.data[self.data >= 0], return_counts=True)
        return {int(v): int(c) for v, c in zip(vals, counts)}

    def diff_count(self, other):
        return int((self.data != other.data).sum())

    def ascii(self, chars=None):
        """Text view of the canvas: one char per pixel ('.' transparent) + legend."""
        used = sorted(self.colors_used())
        if chars is None:
            chars = {}
            for i, idx in enumerate(used):
                chars[idx] = GRID_CHARS[i % len(GRID_CHARS)]
        lines = ["".join("." if v < 0 else chars[int(v)] for v in row) for row in self.data]
        legend = [f"{chars[i]} = {i} #{self.palette.hex(i)}"
                  + (f" ({self.palette.name_of(i)})" if self.palette.name_of(i) else "") for i in used]
        return "\n".join(lines) + "\n\n" + "\n".join(legend)

    # ------------------------------------------------------------------ symmetry
    def symmetry(self, mode=None, axis_x=None, axis_y=None):
        """Enable mirror drawing. mode: None/'off', 'x' (mirror left<->right), 'y' (top<->bottom),
        'xy'/'both'. axis_x/axis_y: mirror axis coordinate (default center, e.g. 15.5 for w=32;
        integer axis = that column is the mirror line). Affects all drawing ops until disabled."""
        if mode in (None, "off", False, "none"):
            self._sym = None
            return self
        if mode not in ("x", "y", "xy", "both"):
            raise PixelError(f"symmetry mode must be 'x', 'y', 'xy' or None, got {mode!r}")
        ax = (self.w - 1) / 2 if axis_x is None else axis_x
        ay = (self.h - 1) / 2 if axis_y is None else axis_y
        self._sym = ("x" in mode or mode == "both", "y" in mode or mode == "both",
                     int(round(2 * ax)), int(round(2 * ay)))
        return self

    @contextmanager
    def mirrored(self, mode="x", axis_x=None, axis_y=None):
        """with cv.mirrored('x'): ...   temporarily enables symmetry."""
        old = self._sym
        self.symmetry(mode, axis_x, axis_y)
        try:
            yield self
        finally:
            self._sym = old

    def _apply(self, xs, ys, vals):
        """Write pixels (with symmetry copies), clipping to bounds."""
        xs = np.asarray(xs, dtype=np.int64).ravel()
        ys = np.asarray(ys, dtype=np.int64).ravel()
        vals = np.broadcast_to(np.asarray(vals, dtype=np.int16), xs.shape)
        variants = [(xs, ys)]
        if self._sym:
            mx, my, a2x, a2y = self._sym
            if mx:
                variants.append((a2x - xs, ys))
            if my:
                variants.append((xs, a2y - ys))
            if mx and my:
                variants.append((a2x - xs, a2y - ys))
        for vx, vy in variants:
            ok = (vx >= 0) & (vx < self.w) & (vy >= 0) & (vy < self.h)
            self.data[vy[ok], vx[ok]] = vals[ok]

    def _region_mask(self, region):
        """None -> whole canvas; (x,y,w,h) rect; bool array; Canvas (its opaque pixels);
        color/name/index -> pixels of that color."""
        if region is None:
            return np.ones((self.h, self.w), dtype=bool)
        if isinstance(region, np.ndarray):
            if region.shape != (self.h, self.w):
                raise PixelError(f"mask shape {region.shape} != canvas (h,w) {(self.h, self.w)}")
            return region.astype(bool)
        if isinstance(region, Canvas):
            if region.size != self.size:
                raise PixelError("mask canvas must have the same size as the target canvas")
            return region.data >= 0
        if isinstance(region, (tuple, list)) and len(region) == 4:
            x, y, w, h = (int(v) for v in region)
            m = np.zeros((self.h, self.w), dtype=bool)
            m[max(0, y):max(0, y + h), max(0, x):max(0, x + w)] = True
            return m
        return self.mask(region)

    def shape_mask(self, kind, *args):
        """Bool mask of a shape: shape_mask('ellipse', x,y,w,h) / ('rect', x,y,w,h) /
        ('polygon', points) / ('circle', cx,cy,r)."""
        tmp = Canvas(self.w, self.h, self.palette)
        getattr(tmp, kind)(*args, 0)
        return tmp.data >= 0

    # ------------------------------------------------------------------ primitives
    def pixel(self, x, y, color):
        self._apply([x], [y], [self.c(color)])
        return self

    def pixels(self, points, color):
        pts = list(points)
        if pts:
            xs, ys = zip(*pts)
            self._apply(xs, ys, self.c(color))
        return self

    def line(self, x0, y0, x1, y1, color):
        """Bresenham line (inclusive endpoints)."""
        pts = _bresenham(int(x0), int(y0), int(x1), int(y1))
        xs, ys = zip(*pts)
        self._apply(xs, ys, self.c(color))
        return self

    def polyline(self, points, color):
        for (a, b), (c, d) in zip(points, points[1:]):
            self.line(a, b, c, d, color)
        return self

    def rect(self, x, y, w, h, color, fill=True):
        """Rectangle with top-left (x,y), size w x h. fill=False -> 1px outline."""
        if w <= 0 or h <= 0:
            raise PixelError(f"rect size must be positive, got {w}x{h}")
        idx = self.c(color)
        if fill:
            ys, xs = np.mgrid[y:y + h, x:x + w]
            self._apply(xs, ys, idx)
        else:
            self.line(x, y, x + w - 1, y, idx)
            self.line(x, y + h - 1, x + w - 1, y + h - 1, idx)
            self.line(x, y, x, y + h - 1, idx)
            self.line(x + w - 1, y, x + w - 1, y + h - 1, idx)
        return self

    def ellipse(self, x, y, w, h, color, fill=True):
        """Pixel-clean midpoint ellipse fitting the box (x, y, w, h)."""
        if w <= 0 or h <= 0:
            raise PixelError(f"ellipse size must be positive, got {w}x{h}")
        idx = self.c(color)
        if w == 1 or h == 1:
            return self.rect(x, y, w, h, idx, True)
        pts = _ellipse_points(x, y, x + w - 1, y + h - 1)
        if fill:
            rows = {}
            for px, py in pts:
                lo, hi = rows.get(py, (px, px))
                rows[py] = (min(lo, px), max(hi, px))
            xs, ys = [], []
            for py, (lo, hi) in rows.items():
                xs += range(lo, hi + 1)
                ys += [py] * (hi - lo + 1)
            self._apply(xs, ys, idx)
        else:
            xs, ys = zip(*pts)
            self._apply(xs, ys, idx)
        return self

    def circle(self, cx, cy, r, color, fill=True):
        return self.ellipse(cx - r, cy - r, 2 * r + 1, 2 * r + 1, color, fill)

    def polygon(self, points, color, fill=True):
        """Polygon from [(x,y), ...] (closed automatically). Filled via even-odd scanline at
        pixel centers; the outline is always drawn so edges stay crisp."""
        if len(points) < 3:
            raise PixelError("polygon needs at least 3 points")
        idx = self.c(color)
        pts = [(int(a), int(b)) for a, b in points]
        if fill:
            ys_all = [p[1] for p in pts]
            xs_out, ys_out = [], []
            for yy in range(max(0, min(ys_all)), min(self.h - 1, max(ys_all)) + 1):
                yc = yy + 0.5
                xints = []
                for (xa, ya), (xb, yb) in zip(pts, pts[1:] + pts[:1]):
                    if (ya <= yc < yb) or (yb <= yc < ya):
                        xints.append(xa + (yc - ya) * (xb - xa) / (yb - ya))
                xints.sort()
                for xa, xb in zip(xints[0::2], xints[1::2]):
                    lo, hi = int(np.ceil(xa - 0.5)), int(np.floor(xb - 0.5))
                    if hi >= lo:
                        xs_out += range(lo, hi + 1)
                        ys_out += [yy] * (hi - lo + 1)
            if xs_out:
                self._apply(xs_out, ys_out, idx)
        for (xa, ya), (xb, yb) in zip(pts, pts[1:] + pts[:1]):
            self.line(xa, ya, xb, yb, idx)
        return self

    def flood_fill(self, x, y, color, connectivity=4):
        """Fill the contiguous same-color area containing (x,y) (transparent areas too)."""
        if not self.in_bounds(x, y):
            raise PixelError(f"flood_fill start ({x},{y}) outside canvas {self.w}x{self.h}")
        idx = self.c(color)
        target = self.data[y, x]
        if target == idx and not self._sym:
            return self
        nbrs = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        if connectivity == 8:
            nbrs += [(1, 1), (1, -1), (-1, 1), (-1, -1)]
        seen = np.zeros_like(self.data, dtype=bool)
        q = deque([(x, y)])
        seen[y, x] = True
        xs, ys = [], []
        while q:
            cx, cy = q.popleft()
            xs.append(cx)
            ys.append(cy)
            for dx, dy in nbrs:
                nx, ny = cx + dx, cy + dy
                if 0 <= nx < self.w and 0 <= ny < self.h and not seen[ny, nx] and self.data[ny, nx] == target:
                    seen[ny, nx] = True
                    q.append((nx, ny))
        self._apply(xs, ys, idx)
        return self

    def draw_grid(self, x, y, rows, chars, skip_transparent=True):
        """Draw a small text grid at (x,y). chars maps char -> color; '.' = transparent.
        Example: cv.draw_grid(10, 4, [".AA.", "ABBA"], {"A": "outline", "B": "skin"})"""
        lut = {}
        for ch, col in chars.items():
            if len(ch) != 1:
                raise GridError(f"draw_grid: key {ch!r} must be a single character")
            lut[ch] = self.c(col)
        lut.setdefault(".", TRANSPARENT)
        xs, ys, vs = [], [], []
        for ry, row in enumerate(rows):
            for rx, ch in enumerate(row):
                if ch not in lut:
                    raise GridError(f"draw_grid: row {ry + 1} col {rx + 1}: unknown char {ch!r} "
                                    f"(known: {''.join(sorted(lut))})")
                v = lut[ch]
                if v == TRANSPARENT and skip_transparent:
                    continue
                xs.append(x + rx)
                ys.append(y + ry)
                vs.append(v)
        if xs:
            self._apply(xs, ys, vs)
        return self

    # ------------------------------------------------------------------ fills
    def dither(self, region, color1, color2=None, pattern="bayer4", level=0.5, offset=(0, 0)):
        """Ordered-dither fill of a region. level = fraction (0..1 or 0..100%) of pixels that get
        color1; the rest get color2 (or stay untouched if color2 is None).
        region: None | (x,y,w,h) | bool mask | color (pixels of that color)."""
        m = self._region_mask(region)
        lvl = level / 100.0 if level > 1 else level
        t = threshold_map(pattern, self.w, self.h, *offset)
        c1 = self.c(color1)
        a = m & (t < lvl)
        ys, xs = np.nonzero(a)
        self._apply(xs, ys, c1)
        if color2 is not None:
            b = m & ~(t < lvl)
            ys, xs = np.nonzero(b)
            self._apply(xs, ys, self.c(color2))
        return self

    def gradient(self, region, color_from, color_to=None, direction="v", ramp=None,
                 dither="bayer4"):
        """Dithered gradient over a region using a palette ramp.

        direction: 'h' (left->right), 'v' (top->bottom), 'd' (top-left->bottom-right),
        'd2' (top-right->bottom-left), 'radial' (center->edge).
        ramp: explicit list of colors; else intermediate palette colors between from/to are
        found automatically (palette.ramp_between). dither: bayer2/bayer4/bayer8/checker/'none'."""
        m = self._region_mask(region)
        if not m.any():
            return self
        if ramp is None:
            if color_to is None:
                raise PixelError("gradient needs color_to or ramp")
            cols = self.palette.ramp_between(self.c(color_from), self.c(color_to))
        else:
            cols = [self.c(c) for c in ramp]
        ys, xs = np.nonzero(m)
        x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
        W, H = max(1, x1 - x0), max(1, y1 - y0)
        if direction == "h":
            t = (xs - x0) / W
        elif direction == "v":
            t = (ys - y0) / H
        elif direction == "d":
            t = ((xs - x0) + (ys - y0)) / (W + H)
        elif direction == "d2":
            t = ((x1 - xs) + (ys - y0)) / (W + H)
        elif direction == "radial":
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            r = np.hypot((xs - cx) / max(1, W / 2), (ys - cy) / max(1, H / 2))
            t = np.clip(r / np.sqrt(2) * 1.25, 0, 1)
        else:
            raise PixelError(f"gradient direction must be h, v, d, d2 or radial, got {direction!r}")
        n = len(cols)
        v = t * (n - 1)
        i = np.floor(v).astype(int)
        f = v - i
        if dither in (None, "none"):
            sel = np.round(v).astype(int)
        else:
            th = threshold_map(dither, self.w, self.h)[ys, xs]
            sel = np.where(f > th, np.minimum(i + 1, n - 1), i)
        vals = np.array(cols, dtype=np.int16)[np.clip(sel, 0, n - 1)]
        self._apply(xs, ys, vals)
        return self

    # ------------------------------------------------------------------ stamping
    def _src_array(self, src):
        if isinstance(src, Canvas):
            arr = src.data
            if src.palette != self.palette:
                lut = {}
                for idx in np.unique(arr[arr >= 0]):
                    lut[int(idx)] = self.palette.index(src.palette.colors[int(idx)], strict=self.strict)
                out = arr.copy()
                for a, b in lut.items():
                    out[arr == a] = b
                arr = out
            return arr
        arr = np.asarray(src, dtype=np.int16)
        if arr.ndim != 2:
            raise PixelError("stamp source must be a Canvas or 2-D index array")
        return arr

    def stamp(self, src, x, y, flip_h=False, flip_v=False, rotate=0, skip_transparent=True):
        """Draw another Canvas (or index array) with top-left at (x,y).
        Flip is applied first, then clockwise rotation (0/90/180/270)."""
        arr = self._src_array(src)
        if flip_h:
            arr = arr[:, ::-1]
        if flip_v:
            arr = arr[::-1, :]
        if rotate % 360 not in (0, 90, 180, 270):
            raise PixelError(f"rotate must be 0, 90, 180 or 270, got {rotate}")
        arr = np.rot90(arr, k=-(rotate % 360) // 90)
        ys, xs = np.mgrid[0:arr.shape[0], 0:arr.shape[1]]
        vals = arr
        if skip_transparent:
            keep = arr >= 0
            xs, ys, vals = xs[keep], ys[keep], arr[keep]
        self._apply(xs + x, ys + y, vals)
        return self

    def copy_region(self, x, y, w, h):
        """New Canvas with the given region (out-of-bounds parts become transparent)."""
        out = Canvas(w, h, self.palette, strict=self.strict)
        for yy in range(h):
            sy = y + yy
            if 0 <= sy < self.h:
                for xx in range(w):
                    sx = x + xx
                    if 0 <= sx < self.w:
                        out.data[yy, xx] = self.data[sy, sx]
        return out

    def paste_region(self, sx, sy, w, h, dx, dy, src=None, flip_h=False, flip_v=False,
                     rotate=0, skip_transparent=True):
        """Copy region (sx,sy,w,h) of src (default: self) to (dx,dy)."""
        region = (src or self).copy_region(sx, sy, w, h)
        return self.stamp(region, dx, dy, flip_h, flip_v, rotate, skip_transparent)

    # ------------------------------------------------------------------ transforms (in place)
    def shift(self, dx, dy, wrap=False):
        if wrap:
            self.data = np.roll(self.data, (dy, dx), axis=(0, 1))
        else:
            out = np.full_like(self.data, TRANSPARENT)
            h, w = self.h, self.w
            ys0, ys1 = max(0, dy), min(h, h + dy)
            xs0, xs1 = max(0, dx), min(w, w + dx)
            if ys1 > ys0 and xs1 > xs0:
                out[ys0:ys1, xs0:xs1] = self.data[ys0 - dy:ys1 - dy, xs0 - dx:xs1 - dx]
            self.data = out
        return self

    def flip_h(self):
        self.data = self.data[:, ::-1].copy()
        return self

    def flip_v(self):
        self.data = self.data[::-1, :].copy()
        return self

    def rotate(self, degrees):
        if degrees % 360 not in (0, 90, 180, 270):
            raise PixelError(f"rotate must be 0/90/180/270, got {degrees}")
        if degrees % 180 == 90 and self.w != self.h:
            raise PixelError("90/270 rotation of a non-square canvas changes its size; use stamp()")
        self.data = np.rot90(self.data, k=-(degrees % 360) // 90).copy()
        return self

    def mirror(self, direction="lr", axis=None):
        """Copy one half onto the other, mirrored. 'lr': left half -> right, 'rl', 'tb', 'bt'."""
        d = self.data
        if direction in ("lr", "rl"):
            a2 = int(round(2 * ((self.w - 1) / 2 if axis is None else axis)))
            for x in range(self.w):
                mx = a2 - x
                if 0 <= mx < self.w and ((direction == "lr" and x < mx) or (direction == "rl" and x > mx)):
                    d[:, mx] = d[:, x]
        elif direction in ("tb", "bt"):
            a2 = int(round(2 * ((self.h - 1) / 2 if axis is None else axis)))
            for y in range(self.h):
                my = a2 - y
                if 0 <= my < self.h and ((direction == "tb" and y < my) or (direction == "bt" and y > my)):
                    d[my, :] = d[y, :]
        else:
            raise PixelError(f"mirror direction must be lr, rl, tb or bt, got {direction!r}")
        return self

    def recolor(self, mapping, region=None):
        """Simultaneous color replacement {from: to, ...} (optionally inside a region)."""
        m = self._region_mask(region)
        src = self.data.copy()
        for a, b in mapping.items():
            sel = (src == self.c(a)) & m
            self.data[sel] = self.c(b)
        return self

    replace = recolor

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _neighbors(conn):
        n4 = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        return n4 if conn == 4 else n4 + [(1, 1), (1, -1), (-1, 1), (-1, -1)]

    def _shifted(self, arr, dx, dy, fill):
        """out[y,x] = arr[y+dy, x+dx] (fill outside)."""
        h, w = arr.shape
        out = np.full_like(arr, fill)
        ys0, ys1 = max(0, -dy), min(h, h - dy)
        xs0, xs1 = max(0, -dx), min(w, w - dx)
        if ys1 > ys0 and xs1 > xs0:
            out[ys0:ys1, xs0:xs1] = arr[ys0 + dy:ys1 + dy, xs0 + dx:xs1 + dx]
        return out

    def _darken(self, idx, steps, ramps):
        for r in ramps or []:
            if idx in r:
                return r[max(0, r.index(idx) - steps)]
        return self.palette.darker(idx, steps)

    def _lighten(self, idx, steps, ramps):
        for r in ramps or []:
            if idx in r:
                return r[min(len(r) - 1, r.index(idx) + steps)]
        return self.palette.lighter(idx, steps)

    def outline(self, color=None, selective=False, connectivity=8, steps=1, ramps=None,
                inside=False, region=None):
        """Auto-outline the outer contour.

        color: outline color (plain mode). selective=True: each outline pixel = one ramp step
        darker (`steps`) than the adjacent inner color (ramps: list of dark->light color lists;
        fallback palette.darker by luminance+hue). connectivity: 4 or 8.
        inside=True: recolor the shape's own edge pixels instead of growing outward.
        region: restrict to the opaque pixels inside this mask."""
        if connectivity not in (4, 8):
            raise PixelError("connectivity must be 4 or 8")
        if not selective and color is None:
            raise PixelError("outline needs a color (or selective=True)")
        rs = [[self.c(c) for c in r] for r in (ramps or [])]
        op = self.data >= 0
        if region is not None:
            op &= self._region_mask(region)
        nbrs = self._neighbors(connectivity)
        if inside:
            outside_nb = np.zeros_like(op)
            for dx, dy in nbrs:
                outside_nb |= ~self._shifted(op, dx, dy, False)
            cand = op & outside_nb
        else:
            any_nb = np.zeros_like(op)
            for dx, dy in nbrs:
                any_nb |= self._shifted(op, dx, dy, False)
            cand = ~(self.data >= 0) & any_nb
        if not selective:
            self.data[cand] = self.c(color)
            return self
        src = self.data.copy()
        out = self.data.copy()
        for y, x in zip(*np.nonzero(cand)):
            if inside:
                base = int(src[y, x])
            else:
                cnt = Counter()
                for dx, dy in self._neighbors(4):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < self.w and 0 <= ny < self.h and op[ny, nx]:
                        cnt[int(src[ny, nx])] += 1
                if not cnt:
                    for dx, dy in self._neighbors(8)[4:]:
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < self.w and 0 <= ny < self.h and op[ny, nx]:
                            cnt[int(src[ny, nx])] += 1
                top = max(cnt.values())
                ties = [k for k, v in cnt.items() if v == top]
                base = min(ties, key=lambda k: self.palette.luminance(k))
            out[y, x] = self._darken(base, steps, rs)
        self.data = out
        return self

    def shade(self, region=None, ramp=None, light="top-left", depth=1, shadow_depth=None,
              light_steps=1, shadow_steps=1, threshold=0.35):
        """Shade-assist: pixels of the region near the edge facing the light get one ramp step
        lighter, pixels near the opposite edge one step darker.
        region: mask/rect/color (default: all opaque). ramp: dark->light colors (default: palette
        neighbours via lighter()/darker()). light: top-left, top, top-right, left, right, ...
        depth: band width (px) of the lit edge; shadow_depth: band width of the shadow edge.
        threshold: how directly an edge must face the light (cosine, 0..1) to be lit/shaded."""
        dirs = {"top-left": (-1, -1), "top": (0, -1), "top-right": (1, -1), "left": (-1, 0),
                "right": (1, 0), "bottom-left": (-1, 1), "bottom": (0, 1), "bottom-right": (1, 1)}
        if light not in dirs:
            raise PixelError(f"light must be one of {', '.join(dirs)}")
        lx, ly = dirs[light]
        m = self._region_mask(region) & (self.data >= 0)
        sd = depth if shadow_depth is None else shadow_depth
        rs = [[self.c(c) for c in ramp]] if ramp else None

        # distance (in px, 4-connected) from the region edge
        dist = np.zeros(m.shape, dtype=np.int32)
        cur = m.copy()
        k = 0
        while cur.any() and k < 64:
            k += 1
            dist[cur] = k
            nxt = cur.copy()
            for dx, dy in self._neighbors(4):
                nxt &= self._shifted(cur, dx, dy, False)
            cur = nxt
        # outward contour normal from the gradient of a blurred mask
        r = 2
        blur = np.zeros(m.shape)
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                blur += self._shifted(m.astype(np.float64), dx, dy, 0.0)
        gx = self._shifted(blur, 1, 0, 0.0) - self._shifted(blur, -1, 0, 0.0)
        gy = self._shifted(blur, 0, 1, 0.0) - self._shifted(blur, 0, -1, 0.0)
        nx, ny = -gx, -gy  # points outward
        nl = np.hypot(nx, ny) + 1e-9
        L = np.array([lx, ly], dtype=np.float64)
        L /= np.hypot(*L)
        facing = (nx * L[0] + ny * L[1]) / nl
        lit = m & (dist <= depth) & (facing > threshold) if depth > 0 else np.zeros_like(m)
        shd = m & (dist <= sd) & (facing < -threshold) if sd > 0 else np.zeros_like(m)
        both = lit & shd
        lit &= ~both
        shd &= ~both
        src = self.data.copy()
        cache = {}
        for sel, fn, st in ((lit, self._lighten, light_steps), (shd, self._darken, shadow_steps)):
            for y, x in zip(*np.nonzero(sel)):
                b = int(src[y, x])
                key = (b, fn.__name__)
                if key not in cache:
                    cache[key] = fn(b, st, rs)
                self.data[y, x] = cache[key]
        return self

    def orphans(self, connectivity=4):
        """Orphan pixels: opaque pixels with no same-color neighbour (4- or 8-conn).
        Returns list of dicts {x, y, color, isolated} (isolated = no opaque neighbour at all)."""
        op = self.data >= 0
        same = np.zeros_like(op)
        anyn = np.zeros_like(op)
        for dx, dy in self._neighbors(connectivity):
            sh = self._shifted(self.data, dx, dy, TRANSPARENT)
            same |= sh == self.data
        for dx, dy in self._neighbors(8):
            anyn |= self._shifted(op, dx, dy, False)
        res = []
        for y, x in zip(*np.nonzero(op & ~same)):
            res.append({"x": int(x), "y": int(y), "color": int(self.data[y, x]),
                        "isolated": bool(not anyn[y, x])})
        return res

    def clean(self, remove=True, connectivity=4, isolated_only=False):
        """Find orphans; if remove, isolated ones become transparent and others take the most
        common 4-neighbour color. Returns the orphan list."""
        orph = self.orphans(connectivity)
        if isolated_only:
            orph = [o for o in orph if o["isolated"]]
        if remove:
            src = self.data.copy()
            for o in orph:
                x, y = o["x"], o["y"]
                if o["isolated"]:
                    self.data[y, x] = TRANSPARENT
                    continue
                cnt = Counter()
                for dx, dy in self._neighbors(4):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < self.w and 0 <= ny < self.h:
                        cnt[int(src[ny, nx])] += 1
                self.data[y, x] = cnt.most_common(1)[0][0]
        return orph

    # ------------------------------------------------------------------ output
    def to_rgba(self, bg=None) -> np.ndarray:
        """(h, w, 4) uint8 array. bg: None (transparent) or a color for transparent pixels."""
        lut = np.zeros((len(self.palette) + 1, 4), dtype=np.uint8)
        for i, c in enumerate(self.palette.colors):
            lut[i] = (*c, 255)
        if bg is not None:
            from .palette import parse_hex
            try:
                lut[-1] = (*parse_hex(bg), 255)
            except ColorError:
                lut[-1] = (*self.palette.colors[self.palette.index(bg)], 255)
        idx = np.where(self.data < 0, len(self.palette), self.data)
        return lut[idx]

    def to_image(self, scale=1, bg=None):
        from PIL import Image
        img = Image.fromarray(self.to_rgba(bg), "RGBA")
        if scale != 1:
            img = img.resize((self.w * scale, self.h * scale), Image.NEAREST)
        return img

    def save(self, path, scale=1, bg=None):
        """Save PNG (nearest-neighbour scaled)."""
        from pathlib import Path
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.to_image(scale, bg).save(p)
        return p
