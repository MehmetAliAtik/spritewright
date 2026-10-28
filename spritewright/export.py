"""Output & inspection: render, sheet, gif/apng, contact sheet, inspect, onion preview, diff,
quantize. Every function returns the written path(s) and/or useful data."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .canvas import Canvas, threshold_map
from .errors import PixelError
from .palette import TRANSPARENT, Palette, parse_hex, to_hex
from .sprite import Sprite, load_sprite


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except Exception:  # pragma: no cover
        return ImageFont.load_default()


def _out(path):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _canvas_of(src, frame=None) -> Canvas:
    if isinstance(src, Canvas):
        return src
    sp = load_sprite(src)
    return sp.frame(frame if frame is not None else 0)


def _checker(w, h, cell=8, c1=(205, 205, 205), c2=(235, 235, 235)):
    ys, xs = np.mgrid[0:h, 0:w]
    m = ((xs // cell + ys // cell) % 2).astype(bool)
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    arr[...] = (*c1, 255)
    arr[m] = (*c2, 255)
    return Image.fromarray(arr, "RGBA")


def _on_bg(img, bg):
    """Composite an RGBA image on bg: None (keep alpha), 'checker', or a hex color."""
    if bg is None:
        return img
    if bg == "checker":
        base = _checker(img.width, img.height, cell=max(4, img.width // 32))
    else:
        base = Image.new("RGBA", img.size, (*parse_hex(bg), 255))
    base.alpha_composite(img)
    return base


# --------------------------------------------------------------------------- render
def render(src, path, frame=None, scale=1, bg=None):
    """Single frame PNG, nearest-neighbour scaled. bg: None (transparent) | hex | 'checker'."""
    cv = _canvas_of(src, frame)
    img = _on_bg(cv.to_image(scale), bg)
    p = _out(path)
    img.save(p)
    return p


# --------------------------------------------------------------------------- sheet
def sheet(src, path, json_path=None, scale=1, columns=None, padding=0, frames=None, bg=None):
    """Sprite sheet PNG + JSON. JSON has:
       frames      (Aseprite hash: name -> {frame:{x,y,w,h}, duration, sourceSize, ...})
       meta        (app, image, size, scale, frameTags [{name, from, to, direction}])
       frame_list  [{name, index, x, y, w, h, duration}]   (Godot/Unity friendly)
       animations  {name: {from, to, frames:[names], durations:[ms]}}"""
    sp = load_sprite(src)
    names = frames or list(sp.frames)
    n = len(names)
    cols = columns or min(n, 8)
    rows = math.ceil(n / cols)
    fw, fh = sp.w * scale, sp.h * scale
    W, H = cols * fw + (cols + 1) * padding, rows * fh + (rows + 1) * padding
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fl, fhash = [], {}
    for i, nm in enumerate(names):
        cx, cy = i % cols, i // cols
        x, y = padding + cx * (fw + padding), padding + cy * (fh + padding)
        img.paste(sp.frame(nm).to_image(scale), (x, y))
        d = sp.durations.get(nm, sp.default_duration)
        fl.append({"name": nm, "index": i, "x": x, "y": y, "w": fw, "h": fh, "duration": d})
        fhash[f"{sp.name} {nm}"] = {"frame": {"x": x, "y": y, "w": fw, "h": fh}, "rotated": False,
                                    "trimmed": False, "spriteSourceSize": {"x": 0, "y": 0, "w": fw, "h": fh},
                                    "sourceSize": {"w": fw, "h": fh}, "duration": d}
    tags, anims = [], {}
    for an, fnames in sp.get_animations().items():
        idxs = [names.index(f) for f in fnames if f in names]
        if not idxs:
            continue
        tags.append({"name": an, "from": min(idxs), "to": max(idxs), "direction": "forward"})
        anims[an] = {"from": min(idxs), "to": max(idxs), "frames": [names[i] for i in idxs],
                     "durations": [sp.durations.get(names[i], sp.default_duration) for i in idxs]}
    p = _out(path)
    _on_bg(img, bg).save(p)
    jp = _out(json_path or p.with_suffix(".json"))
    data = {"frames": fhash,
            "meta": {"app": "spritewright", "version": "1.0", "image": p.name, "format": "RGBA8888",
                     "size": {"w": W, "h": H}, "scale": str(scale), "frameTags": tags, "layers": [],
                     "slices": []},
            "frame_list": fl, "animations": anims,
            "frame_size": {"w": fw, "h": fh}, "columns": cols, "rows": rows, "padding": padding}
    jp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return p, jp


# --------------------------------------------------------------------------- gif / apng
def _anim_frames(sp, anim):
    names = sp.frame_names(anim)
    return names, [sp.frame(n) for n in names], [sp.durations.get(n, sp.default_duration) for n in names]


def _transparent_color(palette):
    for cand in [(255, 0, 255), (0, 255, 0), (1, 2, 3), (254, 1, 253)]:
        if cand not in palette.colors:
            return cand
    for r in range(256):
        if (r, 7, 11) not in palette.colors:
            return (r, 7, 11)
    raise PixelError("could not find a free transparent color")  # pragma: no cover


def gif(src, path, anim=None, fps=None, scale=4, bg=None, verify=True):
    """Animated GIF: infinite loop, disposal=2, dedicated transparent index 0 (unless bg).
    fps overrides per-frame durations. Returns (path, report). Verifies by reloading."""
    sp = load_sprite(src)
    names, cvs, durs = _anim_frames(sp, anim)
    if fps:
        durs = [int(round(1000 / fps))] * len(cvs)
    durs = [max(20, int(round(d / 10.0)) * 10) for d in durs]  # GIF has 10ms resolution
    pal = sp.palette
    tcol = _transparent_color(pal)
    flat = list(tcol)
    for c in pal.colors:
        flat += list(c)
    flat += [0, 0, 0] * (256 - 1 - len(pal.colors))
    bg_idx = None
    if bg is not None:
        if bg == "checker":
            raise PixelError("GIF bg must be a color (or omitted for transparency), not 'checker'")
        try:
            bg_rgb = parse_hex(bg)
        except Exception:
            bg_rgb = pal.colors[pal.index(bg)]
        flat[0:3] = list(bg_rgb)
        bg_idx = 0
        bg = to_hex(bg_rgb)
    frames = []
    for cv in cvs:
        arr = np.where(cv.data < 0, 0, cv.data + 1).astype(np.uint8)
        im = Image.fromarray(arr, "P")
        if scale != 1:
            im = im.resize((cv.w * scale, cv.h * scale), Image.NEAREST)
        im.putpalette(flat)
        if bg_idx is None:
            im.info["transparency"] = 0
        frames.append(im)
    p = _out(path)
    kw = dict(save_all=True, append_images=frames[1:], duration=durs, loop=0, disposal=2, optimize=False)
    if bg_idx is None:
        kw["transparency"] = 0
        kw["background"] = 0
    frames[0].save(p, format="GIF", **kw)
    report = {"frames": len(frames), "durations_ms": durs, "transparent": bg_idx is None}
    if verify:
        report["verified"] = verify_animation(p, cvs, scale, bg)
    return p, report


def apng(src, path, anim=None, fps=None, scale=4, bg=None, verify=True):
    """Animated PNG (full RGBA, infinite loop)."""
    sp = load_sprite(src)
    names, cvs, durs = _anim_frames(sp, anim)
    if fps:
        durs = [int(round(1000 / fps))] * len(cvs)
    imgs = [_on_bg(cv.to_image(scale), bg) for cv in cvs]
    p = _out(path)
    imgs[0].save(p, format="PNG", save_all=True, append_images=imgs[1:], duration=durs, loop=0,
                 disposal=1, blend=0)
    report = {"frames": len(imgs), "durations_ms": durs}
    if verify:
        report["verified"] = verify_animation(p, cvs, scale, bg)
    return p, report


def verify_animation(path, canvases, scale, bg=None):
    """Reload an animation and compare every frame (alpha + RGB of opaque pixels) with the
    source canvases. Consecutive identical frames may be merged by the encoder; that's
    accounted for. Returns True or raises PixelError describing the first mismatch."""
    exp = []
    for cv in canvases:
        a = np.asarray(_on_bg(cv.to_image(scale), bg))
        if not exp or not np.array_equal(exp[-1], a):
            exp.append(a)
    im = Image.open(path)
    got = []
    for i in range(getattr(im, "n_frames", 1)):
        im.seek(i)
        got.append(np.asarray(im.convert("RGBA")))
    if len(got) not in (len(exp), len(canvases)):
        raise PixelError(f"{path}: reloaded {len(got)} frames, expected {len(exp)}")
    ref = exp if len(got) == len(exp) else [np.asarray(_on_bg(cv.to_image(scale), bg)) for cv in canvases]
    for i, (g, e) in enumerate(zip(got, ref)):
        ga, ea = g[..., 3] > 127, e[..., 3] > 127
        if not np.array_equal(ga, ea):
            raise PixelError(f"{path}: frame {i} transparency mismatch at {int((ga != ea).sum())} pixels")
        if not np.array_equal(g[ea][:, :3], e[ea][:, :3]):
            raise PixelError(f"{path}: frame {i} color mismatch")
    return True


# --------------------------------------------------------------------------- contact sheet
def load_frames_source(src):
    """Sprite from a sprite source OR an exported atlas / per-animation sheet (json, png + json,
    folder with atlas.json) - so contact/render tools work on what Unity imports."""
    if isinstance(src, Sprite):
        return src
    from .check import atlas_sprite
    sp = atlas_sprite(src) if not isinstance(src, Canvas) else None
    return sp if sp is not None else load_sprite(src)


def contact_sheet(src, path, scale=4, columns=None, frames=None, bg="checker", max_width=1024, rows=None):
    """All frames, numbered and named, gridded into ONE image. src: sprite source or atlas/sheet
    json/png. rows: list of frame-name lists, each starting a new row (e.g. one row per animation).
    The scale is reduced automatically (down to 1) so the image is at most max_width px wide
    (max_width=None: no limit). Returns the path."""
    sp = load_frames_source(src)
    if rows:
        rows = [[n for n in r if n in sp.frames] for r in rows]
        rows = [r for r in rows if r]
    else:
        names = frames or list(sp.frames)
        n = len(names)
        cols = columns or math.ceil(math.sqrt(n))
        rows = [names[i:i + cols] for i in range(0, n, cols)]
    cols = max(len(r) for r in rows)
    pad, lab = 8, 16
    scale = max(1, int(scale))
    while max_width and scale > 1 and cols * (sp.w * scale + pad) + pad > max_width:
        scale -= 1
    fw, fh = sp.w * scale, sp.h * scale
    font = _font(12)
    W, H = cols * (fw + pad) + pad, len(rows) * (fh + pad + lab) + pad
    img = Image.new("RGBA", (W, H), (48, 48, 56, 255))
    dr = ImageDraw.Draw(img)
    i = 0
    for cy, r in enumerate(rows):
        for cx, nm in enumerate(r):
            x, y = pad + cx * (fw + pad), pad + cy * (fh + pad + lab)
            tile = _on_bg(sp.frame(nm).to_image(scale), bg)
            img.paste(tile, (x, y))
            label = f"{i}: {nm} ({sp.durations.get(nm, sp.default_duration)}ms)"
            if fw < 110:  # narrow tiles: short label
                label = f"{i} {sp.durations.get(nm, sp.default_duration)}ms"
            dr.text((x, y + fh + 2), label, fill=(230, 230, 230, 255), font=font)
            i += 1
    p = _out(path)
    img.save(p)
    return p


# --------------------------------------------------------------------------- inspect
def inspect(src, path, region=None, frame=None, zoom=24, grid=True, indices=False, major=8):
    """Magnify region (x,y,w,h) zoom x with grid lines, coordinate labels on both axes,
    checkerboard for transparency, optional palette index in each cell."""
    cv = _canvas_of(src, frame)
    x0, y0, w, h = region or (0, 0, cv.w, cv.h)
    if w <= 0 or h <= 0:
        raise PixelError(f"inspect region must have positive size, got {region}")
    sub = cv.copy_region(x0, y0, w, h)
    Z = int(zoom)
    fs = max(9, min(14, int(Z * 0.5)))
    font = _font(fs)
    small = _font(max(8, int(Z * 0.35)))
    L, T = fs * 3, fs + 8
    W, H = L + w * Z + 1, T + h * Z + 1
    img = Image.new("RGBA", (W, H), (32, 32, 40, 255))
    dr = ImageDraw.Draw(img)
    pal = cv.palette.colors
    for yy in range(h):
        for xx in range(w):
            v = int(sub.data[yy, xx])
            px, py = L + xx * Z, T + yy * Z
            if v < 0:
                hz = Z // 2
                for qy in range(2):
                    for qx in range(2):
                        c = (200, 200, 200) if (qx + qy) % 2 == 0 else (235, 235, 235)
                        dr.rectangle([px + qx * hz, py + qy * hz, px + (qx + 1) * hz - 1 if qx == 0 else px + Z - 1,
                                      py + (qy + 1) * hz - 1 if qy == 0 else py + Z - 1], fill=c)
            else:
                dr.rectangle([px, py, px + Z - 1, py + Z - 1], fill=pal[v])
                if indices:
                    lum = 0.299 * pal[v][0] + 0.587 * pal[v][1] + 0.114 * pal[v][2]
                    dr.text((px + 2, py + 1), str(v), fill=(0, 0, 0) if lum > 140 else (255, 255, 255),
                            font=small)
    if grid:
        for xx in range(w + 1):
            ax = x0 + xx
            col = (255, 80, 80) if ax % major == 0 else (70, 70, 80)
            dr.line([L + xx * Z, T, L + xx * Z, T + h * Z], fill=col)
        for yy in range(h + 1):
            ay = y0 + yy
            col = (255, 80, 80) if ay % major == 0 else (70, 70, 80)
            dr.line([L, T + yy * Z, L + w * Z, T + yy * Z], fill=col)
    step = 1 if Z >= fs * 1.6 else 2
    for xx in range(0, w, step):
        dr.text((L + xx * Z + Z // 2, T - 3), str(x0 + xx), fill=(230, 230, 230), font=font, anchor="ms")
    for yy in range(0, h, step):
        dr.text((L - 4, T + yy * Z + Z // 2), str(y0 + yy), fill=(230, 230, 230), font=font, anchor="rm")
    p = _out(path)
    img.save(p)
    return p


# --------------------------------------------------------------------------- onion / diff
def onion(src, a, b, path=None, scale=8, alpha=0.4, tint=(255, 60, 60)):
    """Onion-skin merge: frame a tinted & translucent under frame b. Returns PIL image
    (and saves a 3-panel image [a | b | onion] when path is given)."""
    sp = load_sprite(src)
    A, B = sp.frame(a), sp.frame(b)
    ra = A.to_rgba().astype(np.float64)
    ra[..., :3] = ra[..., :3] * 0.5 + np.array(tint) * 0.5
    ra[..., 3] *= alpha
    base = Image.fromarray(ra.astype(np.uint8), "RGBA")
    base.alpha_composite(Image.fromarray(B.to_rgba(), "RGBA"))
    on = base.resize((sp.w * scale, sp.h * scale), Image.NEAREST)
    if path:
        pa = _on_bg(A.to_image(scale), "checker")
        pb = _on_bg(B.to_image(scale), "checker")
        po = _on_bg(on, "checker")
        gap = 8
        out = Image.new("RGBA", (pa.width * 3 + gap * 4, pa.height + gap * 2 + 16), (48, 48, 56, 255))
        dr = ImageDraw.Draw(out)
        f = _font(12)
        for i, (im, lab) in enumerate(((pa, a), (pb, b), (po, f"onion {a}->{b}"))):
            x = gap + i * (pa.width + gap)
            out.paste(im, (x, gap))
            dr.text((x, gap + pa.height + 2), str(lab), fill=(230, 230, 230), font=f)
        out.save(_out(path))
    return on


def diff(src, a, b, path=None, scale=8, other=None):
    """Highlight pixels that differ between frame a and frame b (of `other` sprite if given) in
    red over a dimmed grayscale of b. Returns (count, [(x,y), ...])."""
    sp = load_sprite(src)
    A = sp.frame(a)
    B = (load_sprite(other) if other else sp).frame(b)
    if A.size != B.size:
        raise PixelError(f"cannot diff {A.w}x{A.h} with {B.w}x{B.h}")
    rgba_a, rgba_b = A.to_rgba(), B.to_rgba()
    changed = np.any(rgba_a != rgba_b, axis=-1) & ~((rgba_a[..., 3] == 0) & (rgba_b[..., 3] == 0))
    pts = [(int(x), int(y)) for y, x in zip(*np.nonzero(changed))]
    if path:
        g = rgba_b[..., :3].mean(-1)
        out = np.zeros_like(rgba_b)
        out[..., 0] = out[..., 1] = out[..., 2] = (g * 0.35 + 140 * 0.65).astype(np.uint8)
        out[..., 3] = np.where(rgba_b[..., 3] > 0, 255, 0)
        out[changed] = (255, 0, 0, 255)
        img = _on_bg(Image.fromarray(out, "RGBA").resize((A.w * scale, A.h * scale), Image.NEAREST), "#202028")
        dr = ImageDraw.Draw(img)
        dr.text((4, 4), f"{len(pts)} px changed", fill=(255, 255, 255), font=_font(12))
        img.save(_out(path))
    return len(pts), pts


# --------------------------------------------------------------------------- quantize
def quantize(png, palette, dither="none", size=None, resample="box", alpha_threshold=128,
             strength=0.5):
    """Convert an image to a palette-indexed Canvas.
    dither: none | bayer4 | floyd (Floyd-Steinberg). size: (w, h) to downscale to first.
    resample: box | nearest | lanczos."""
    pal = Palette.load(palette)
    img = Image.open(png).convert("RGBA")
    if size:
        rs = {"box": Image.BOX, "nearest": Image.NEAREST, "lanczos": Image.LANCZOS}.get(resample)
        if rs is None:
            raise PixelError("resample must be box, nearest or lanczos")
        img = img.resize(tuple(size), rs)
    if img.width > 256 or img.height > 256:
        raise PixelError(f"image is {img.width}x{img.height}; max 256 — pass size=(w,h) / --size WxH")
    arr = np.asarray(img).astype(np.float64)
    rgb, a = arr[..., :3], arr[..., 3]
    h, w = a.shape
    if dither in (None, "none"):
        idx = pal.nearest_many(rgb)
    elif dither in ("bayer4", "bayer", "bayer2", "bayer8"):
        cols = np.array(pal.colors, dtype=np.float64)
        spread = np.median(np.sort(np.sqrt(((cols[:, None] - cols[None]) ** 2).sum(-1)), 1)[:, 1]) \
            if len(cols) > 1 else 32
        t = threshold_map(dither if dither != "bayer" else "bayer4", w, h) - 0.5
        idx = pal.nearest_many(np.clip(rgb + t[..., None] * spread * strength * 2, 0, 255))
    elif dither in ("floyd", "floyd-steinberg", "fs"):
        work = rgb.copy()
        cols = np.array(pal.colors, dtype=np.float64)
        idx = np.zeros((h, w), dtype=np.int16)
        for y in range(h):
            for x in range(w):
                old = np.clip(work[y, x], 0, 255)
                i = pal.nearest_many(old[None])[0]
                idx[y, x] = i
                err = (old - cols[i]) * (a[y, x] >= alpha_threshold)
                if x + 1 < w:
                    work[y, x + 1] += err * 7 / 16
                if y + 1 < h:
                    if x > 0:
                        work[y + 1, x - 1] += err * 3 / 16
                    work[y + 1, x] += err * 5 / 16
                    if x + 1 < w:
                        work[y + 1, x + 1] += err * 1 / 16
    else:
        raise PixelError(f"dither must be none, bayer4 or floyd, got {dither!r}")
    cv = Canvas(w, h, pal, name=Path(png).stem)
    cv.data[:] = np.where(a >= alpha_threshold, idx, TRANSPARENT)
    return cv


def palette_swatch(palette, path, cell=24, columns=16, labels=True):
    """PNG swatch of a palette with index numbers (and names)."""
    pal = Palette.load(palette)
    n = len(pal)
    cols = min(columns, n)
    rows = math.ceil(n / cols)
    lab = 14 if labels else 0
    img = Image.new("RGBA", (cols * cell, rows * (cell + lab)), (32, 32, 40, 255))
    dr = ImageDraw.Draw(img)
    f = _font(10)
    for i, c in enumerate(pal.colors):
        x, y = (i % cols) * cell, (i // cols) * (cell + lab)
        dr.rectangle([x, y, x + cell - 1, y + cell - 1], fill=c)
        if labels:
            dr.text((x + 1, y + cell), pal.name_of(i) or str(i), fill=(220, 220, 220), font=f)
    p = _out(path)
    img.save(p)
    return p


def strip_image(colors_hex, path, cell=32):
    """Simple strip of hex colors (for ramps)."""
    img = Image.new("RGB", (cell * len(colors_hex), cell))
    dr = ImageDraw.Draw(img)
    for i, c in enumerate(colors_hex):
        dr.rectangle([i * cell, 0, (i + 1) * cell - 1, cell - 1], fill=parse_hex(c))
    p = _out(path)
    img.save(p)
    return p
