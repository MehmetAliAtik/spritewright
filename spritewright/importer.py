"""Import external PNGs / sprite sheets back into grid JSON, and clean up "fake" pixel art.

* import_image(png, ...)  -> (Sprite, report): slice a PNG / sheet / Unity atlas (atlas.json is read
  automatically when next to the PNG) into frames, map colours onto a palette with the same
  nearest-colour logic as quantize (no dither by default), threshold semi-alpha, report every remap.
* detect_grid(img, ...)   -> dict: block size / offset / confidence of upscaled pixel art (AI images,
  blurred / JPEG'd upscales). Scores candidate block sizes 2..32 (step 0.02 px, so 7.5 px blocks are
  found too) by how much of the colour-difference energy falls on the candidate block boundaries.
* depixelize(img, ...)    -> (Image, report): detect_grid + sample the interior median of every
  block (1 block = 1 pixel), threshold alpha, optional background removal, palette / K-colour
  quantize or merge of near-duplicate colours.
"""
from __future__ import annotations

import json
import math
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

from .canvas import Canvas
from .errors import PixelError
from .palette import TRANSPARENT, Palette, parse_hex, rgb_to_lab, to_hex
from .paths import projects_root
from .sprite import Sprite, load_sprite

MAX_AUTO_COLORS = 64


# --------------------------------------------------------------------------- helpers
def load_rgba(src) -> np.ndarray:
    """Path / PIL Image / (H,W,3|4) array -> (H,W,4) uint8."""
    if isinstance(src, np.ndarray):
        a = src
        if a.ndim != 3 or a.shape[2] not in (3, 4):
            raise PixelError(f"image array must be (H,W,3|4), got {a.shape}")
        if a.shape[2] == 3:
            a = np.concatenate([a, np.full(a.shape[:2] + (1,), 255, a.dtype)], 2)
        return np.ascontiguousarray(a.astype(np.uint8))
    if isinstance(src, Image.Image):
        return np.array(src.convert("RGBA"))
    p = Path(src)
    if not p.is_file():
        raise PixelError(f"image {src!r} not found")
    with Image.open(p) as im:
        return np.array(im.convert("RGBA"))


def resolve_palette(spec, base_dir=None) -> Palette:
    """Palette name / .hex / .json palette / sprite source (its palette)."""
    if spec is None:
        return None
    try:
        return Palette.load(spec, base_dir=base_dir)
    except PixelError as first:
        try:
            return load_sprite(spec).palette
        except PixelError:
            raise first from None


def _pack(rgb):
    rgb = rgb.astype(np.int64)
    return (rgb[..., 0] << 16) | (rgb[..., 1] << 8) | rgb[..., 2]


def _unpack(v):
    v = int(v)
    return ((v >> 16) & 255, (v >> 8) & 255, v & 255)


def _delta_e(a, b):
    return float(np.sqrt(((rgb_to_lab(np.array(a, float)) - rgb_to_lab(np.array(b, float))) ** 2).sum()))


def map_to_palette(rgba, pal, alpha_threshold=128, dither="none"):
    """RGBA (H,W,4) -> (indices (H,W) int16, stats). No dither = exact colours kept, others snapped
    to the perceptually nearest palette colour (Palette.nearest_many, as in quantize)."""
    a = rgba[..., 3]
    semi = (a > 0) & (a < 255)
    opaque = a >= alpha_threshold
    stats = {"semi_alpha": int(semi.sum()), "semi_to_opaque": int((semi & opaque).sum()),
             "semi_to_transparent": int((semi & ~opaque).sum()), "remapped": 0, "mapping": {},
             "max_distance": 0.0, "opaque": int(opaque.sum())}
    idx = np.full(a.shape, TRANSPARENT, dtype=np.int16)
    if not opaque.any():
        return idx, stats
    packed = _pack(rgba[..., :3])
    if dither in (None, "none"):
        uniq, inv = np.unique(packed[opaque], return_inverse=True)
        cols = np.array([_unpack(u) for u in uniq], dtype=np.float64)
        exact = {c: i for i, c in enumerate(pal.colors)}
        lut = np.array([exact.get(tuple(int(v) for v in c), -2) for c in cols], dtype=np.int16)
        miss = lut == -2
        if miss.any():
            lut[miss] = pal.nearest_many(cols[miss])
        idx[opaque] = lut[inv]
        counts = np.bincount(inv, minlength=len(uniq))
        for k in np.nonzero(miss)[0]:
            src, dst = tuple(int(v) for v in cols[k]), pal.colors[int(lut[k])]
            d = round(_delta_e(src, dst), 2)
            stats["mapping"][to_hex(src)] = {"to": to_hex(dst), "index": int(lut[k]), "count": int(counts[k]),
                                             "distance": d}
            stats["remapped"] += int(counts[k])
            stats["max_distance"] = max(stats["max_distance"], d)
        return idx, stats
    # dithered: reuse export.quantize on a temporary PNG (keeps its exact behaviour)
    from .export import quantize
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "frame.png"
        Image.fromarray(rgba, "RGBA").save(p)
        cv = quantize(p, pal, dither=dither, alpha_threshold=alpha_threshold)
    idx[:] = cv.data
    pc = np.array(pal.colors, dtype=np.int64)
    got = np.zeros(packed.shape, np.int64)
    got[opaque] = _pack(pc[idx[opaque]])
    diff = opaque & (got != packed)
    stats["remapped"] = int(diff.sum())
    pairs = Counter(zip(packed[diff].tolist(), idx[diff].tolist()))
    for (src, i), n in pairs.most_common():
        key = to_hex(_unpack(src)) + "->" + to_hex(pal.colors[i])
        d = round(_delta_e(_unpack(src), pal.colors[i]), 2)
        stats["mapping"][key] = {"to": to_hex(pal.colors[i]), "index": int(i), "count": int(n), "distance": d}
        stats["max_distance"] = max(stats["max_distance"], d)
    return idx, stats


def auto_palette(rgba_list, alpha_threshold=128, max_colors=MAX_AUTO_COLORS, name="auto"):
    """Exact colour palette of the opaque pixels (sorted dark -> light). > max_colors -> error."""
    cnt = Counter()
    for rgba in rgba_list:
        op = rgba[..., 3] >= alpha_threshold
        u, c = np.unique(_pack(rgba[..., :3])[op], return_counts=True)
        cnt.update(dict(zip(u.tolist(), c.tolist())))
    if not cnt:
        raise PixelError("image has no opaque pixels; nothing to build a palette from")
    if len(cnt) > max_colors:
        raise PixelError(f"image has {len(cnt)} distinct colours (> {max_colors}); give a palette with "
                         f"--palette (name/.hex/.json/sprite), or reduce colours first "
                         f"(depixelize --colors K / --palette, or quantize)")
    cols = [_unpack(v) for v in cnt]
    lum = rgb_to_lab(np.array(cols, float))[:, 0]
    cols = [cols[i] for i in np.argsort(lum, kind="stable")]
    return Palette([to_hex(c) for c in cols], name=name)


# --------------------------------------------------------------------------- slicing
def _xy2(v, what):
    if v is None:
        return None
    if isinstance(v, str):
        try:
            a, b = (int(t) for t in v.lower().replace(",", "x").split("x"))
            return a, b
        except Exception:
            raise PixelError(f"{what} must look like WxH, got {v!r}") from None
    a, b = v
    return int(a), int(b)


def grid_cells(W, H, frame=None, cols=None, rows=None, margin=0, spacing=0):
    """-> (fw, fh, [(row, col, x, y), ...]) for a regular sheet. margin = border on every side,
    spacing = gap between cells."""
    margin, spacing = int(margin or 0), int(spacing or 0)
    if margin < 0 or spacing < 0:
        raise PixelError("margin/spacing must be >= 0")
    iw, ih = W - 2 * margin, H - 2 * margin
    if iw <= 0 or ih <= 0:
        raise PixelError(f"margin {margin} leaves no image ({W}x{H})")
    frame = _xy2(frame, "frame size")
    if frame:
        fw, fh = frame
        if fw < 1 or fh < 1:
            raise PixelError("frame size must be positive")
        nc = (iw + spacing) // (fw + spacing) if not cols else int(cols)
        nr = (ih + spacing) // (fh + spacing) if not rows else int(rows)
    elif cols or rows:
        nc, nr = int(cols or 1), int(rows or 1)
        fw = (iw - (nc - 1) * spacing) // nc
        fh = (ih - (nr - 1) * spacing) // nr
        if fw * nc + (nc - 1) * spacing != iw or fh * nr + (nr - 1) * spacing != ih:
            raise PixelError(f"{W}x{H} image does not divide into {nc}x{nr} cells with margin {margin} and "
                             f"spacing {spacing}; give --frame WxH instead")
    else:
        fw, fh, nc, nr = iw, ih, 1, 1
    if nc < 1 or nr < 1 or margin + nc * fw + (nc - 1) * spacing > W or margin + nr * fh + (nr - 1) * spacing > H:
        raise PixelError(f"frame {fw}x{fh} (cols {nc}, rows {nr}, margin {margin}, spacing {spacing}) does not fit "
                         f"the {W}x{H} image")
    cells = [(r, c, margin + c * (fw + spacing), margin + r * (fh + spacing)) for r in range(nr) for c in range(nc)]
    return fw, fh, cells


def find_atlas(png, atlas=None):
    """atlas: path | False/'none' (ignore) | None (auto: <png>.json or atlas.json next to the PNG whose
    meta.image names this PNG)."""
    if atlas in (False, "none", "no"):
        return None, None
    if atlas:
        p = Path(atlas)
        if not p.is_file():
            raise PixelError(f"atlas json {atlas!r} not found")
        return json.loads(p.read_text(encoding="utf-8")), p
    if not isinstance(png, (str, Path)):
        return None, None
    png = Path(png)
    for c in (png.with_suffix(".json"), png.parent / "atlas.json"):
        if c.is_file():
            try:
                d = json.loads(c.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            img = (d.get("meta") or {}).get("image")
            if isinstance(d.get("frames"), (dict, list)) and (img is None or Path(img).name == png.name):
                return d, c
    return None, None


def _atlas_frames(d):
    fr = d.get("frames")
    if isinstance(fr, dict):
        items = list(fr.items())
    elif isinstance(fr, list):
        items = [(f.get("filename", f"frame{i}"), f) for i, f in enumerate(fr)]
    else:
        raise PixelError("atlas json has no 'frames'")
    return items


def _parse_anim_rows(spec):
    """'idle:4,walk:6' / 'idle,walk' -> [(name, count|None)]."""
    out = []
    for item in [t.strip() for t in str(spec).split(",") if t.strip()]:
        if ":" in item:
            n, c = item.split(":", 1)
            try:
                out.append((n.strip(), int(c)))
            except ValueError:
                raise PixelError(f"--anim-rows item {item!r}: count must be an integer") from None
        else:
            out.append((item, None))
    return out


def _split(v):
    if v is None:
        return None
    if isinstance(v, str):
        return [t.strip() for t in v.split(",") if t.strip()]
    return list(v)


# --------------------------------------------------------------------------- import
def import_image(png, project=None, name=None, out=None, frame=None, cols=None, rows=None, margin=0, spacing=0,
                 names=None, anim=None, anim_rows=None, atlas=None, palette=None, alpha_threshold=128,
                 dither="none", skip_empty=False, fps=None, restore_offsets=False, canvas=None,
                 max_auto_colors=MAX_AUTO_COLORS, save=True):
    """Import a PNG / sheet / Unity atlas as a grid-JSON sprite.

    Frames: atlas.json (auto-detected next to the PNG, or `atlas=`) > grid (frame=WxH or cols/rows,
    margin, spacing) > the whole image as one frame. Names: names=[..] > anim_rows='idle:4,walk:6'
    (one animation per sheet row) > anim='idle' (idle1..N) > atlas source_frame names > frame1..N.
    Palette: palette= (name/.hex/.json/sprite source) > the atlas' source sprite palette > exact
    colours of the image (<= 64, saved as <name>_palette.json next to the sprite).
    restore_offsets: atlas cells are shifted back by their 'offset' into the original canvas size
    (canvas=WxH or the atlas' source sprite size) -> pixel-identical to the exported source frames.
    Returns (Sprite, report)."""
    rgba = load_rgba(png)
    H, W = rgba.shape[:2]
    stem = Path(png).stem if isinstance(png, (str, Path)) else "imported"
    name = name or (Path(out).stem if out else stem)
    if out is None and save:
        if not project:
            raise PixelError("import needs a project (projects/<project>/<name>.json) or an explicit out path")
        out = projects_root() / project / f"{name}.json"
    out = Path(out) if out else None
    notes = []
    adict, apath = (None, None)
    if not (frame or cols or rows):
        adict, apath = find_atlas(png, atlas)
    elif atlas not in (None, False, "none", "no"):
        adict, apath = find_atlas(png, atlas)

    # ---- frame list: (name, anim, x, y, w, h, duration, offset)
    entries = []
    anim_meta = {}
    pivot = None
    src_sprite = None
    if adict is not None:
        items = _atlas_frames(adict)
        meta = adict.get("meta") or {}
        if meta.get("source"):
            from .paths import resolve_from
            try:
                src_sprite = load_sprite(resolve_from(meta["source"], Path(apath).parent) if apath
                                         else meta["source"])
            except PixelError:
                notes.append(f"atlas source {meta['source']} not loadable; its palette/size are not used")
        per_anim = Counter()
        for key, f in items:
            r = f.get("frame") or {}
            a = f.get("animation")
            i = f.get("index", per_anim[a])
            per_anim[a] += 1
            fn = f.get("source_frame") or (f"{a}{int(i) + 1}" if a else str(key))
            entries.append({"name": fn, "anim": a, "x": int(r["x"]), "y": int(r["y"]), "w": int(r["w"]),
                            "h": int(r["h"]), "duration": f.get("duration"), "offset": f.get("offset")})
        if len({e["name"] for e in entries}) != len(entries):
            for k, e in enumerate(entries):
                e["name"] = f"{e['anim'] or 'frame'}{k + 1}"
        for a in adict.get("animations") or []:
            if isinstance(a, dict) and a.get("name"):
                anim_meta[a["name"]] = {k: a[k] for k in ("fps", "loop") if k in a}
        if not anim_meta:
            for t in meta.get("frameTags") or []:
                anim_meta.setdefault(t.get("name"), {})
        pv = adict.get("pivot") or {}
        if isinstance(pv.get("pixel"), dict):
            pivot = {"x": int(pv["pixel"]["x"]), "y": int(pv["pixel"]["y"]), "align": pv.get("align", "fixed"),
                     "source": pv.get("source")}
        sizes = {(e["w"], e["h"]) for e in entries}
        if len(sizes) != 1:
            raise PixelError(f"atlas frames have different sizes {sorted(sizes)}; import needs equal frames")
        fw, fh = sizes.pop()
    else:
        fw, fh, cells = grid_cells(W, H, frame, cols, rows, margin, spacing)
        for r, c, x, y in cells:
            entries.append({"name": None, "anim": None, "row": r, "col": c, "x": x, "y": y, "w": fw, "h": fh,
                            "duration": None, "offset": None})
    for e in entries:
        if e["x"] < 0 or e["y"] < 0 or e["x"] + e["w"] > W or e["y"] + e["h"] > H:
            raise PixelError(f"frame {e['name'] or (e['x'], e['y'])} rect {e['x']},{e['y']},{e['w']}x{e['h']} "
                             f"is outside the {W}x{H} image")
        e["rgba"] = rgba[e["y"]:e["y"] + e["h"], e["x"]:e["x"] + e["w"]].copy()
        e["empty"] = not (e["rgba"][..., 3] >= alpha_threshold).any()

    # ---- naming
    anim_rows_l = _parse_anim_rows(anim_rows) if anim_rows else None
    names_l = _split(names)
    animations = {}
    if anim_rows_l:
        if adict is not None:
            raise PixelError("--anim-rows is for plain grids; the atlas already defines animations "
                             "(pass atlas='none' / --atlas none to ignore it)")
        nrows = max(e["row"] for e in entries) + 1
        if len(anim_rows_l) > nrows:
            raise PixelError(f"--anim-rows names {len(anim_rows_l)} rows but the sheet has {nrows}")
        keep = []
        for r, (an, cnt) in enumerate(anim_rows_l):
            row = [e for e in entries if e["row"] == r]
            if cnt is None:
                filled = [k for k, e in enumerate(row) if not e["empty"]]
                cnt = (filled[-1] + 1) if filled else 0
            if cnt > len(row):
                raise PixelError(f"--anim-rows {an}:{cnt} but row {r} has only {len(row)} cells")
            sel = [e for e in row[:cnt] if not (skip_empty and e["empty"])]
            for k, e in enumerate(sel):
                e["name"], e["anim"] = f"{an}{k + 1}", an
            animations[an] = [e["name"] for e in sel]
            keep += sel
        for e in entries:
            if e["row"] >= len(anim_rows_l) and not e["empty"]:
                notes.append(f"row {e['row']} has content but no --anim-rows entry; ignored")
                break
        entries = keep
    else:
        if skip_empty:
            dropped = [e for e in entries if e["empty"]]
            entries = [e for e in entries if not e["empty"]]
            if dropped:
                notes.append(f"skipped {len(dropped)} empty frame(s)")
        if names_l:
            if len(names_l) != len(entries):
                raise PixelError(f"--names gives {len(names_l)} names for {len(entries)} frames"
                                 + ("" if skip_empty else " (use --skip-empty to drop empty cells)"))
            for e, n in zip(entries, names_l):
                e["name"] = n
        elif anim:
            for k, e in enumerate(entries):
                e["name"], e["anim"] = f"{anim}{k + 1}", anim
            animations[anim] = [e["name"] for e in entries]
        elif adict is None:
            for k, e in enumerate(entries):
                e["name"] = f"frame{k + 1}"
        if adict is not None and not names_l:
            for e in entries:
                if e["anim"]:
                    animations.setdefault(e["anim"], []).append(e["name"])
    if not entries:
        raise PixelError("no frames to import (all empty?)")
    if len({e["name"] for e in entries}) != len(entries):
        raise PixelError("frame names are not unique: " + ", ".join(e["name"] for e in entries))

    # ---- palette
    pal_src = "given"
    if palette is not None:
        pal = resolve_palette(palette)
    elif src_sprite is not None:
        pal, pal_src = src_sprite.palette, "atlas source sprite"
    else:
        pal = auto_palette([e["rgba"] for e in entries], alpha_threshold, max_auto_colors, name=f"{name}_palette")
        pal_src = "auto (exact image colours)"
        if out is not None:
            pal.save(out.parent / f"{name}_palette.json")

    # ---- restore original canvas from atlas offsets
    tw, th = fw, fh
    if restore_offsets:
        if adict is None:
            raise PixelError("restore_offsets needs an atlas.json with per-frame offsets")
        cs = _xy2(canvas, "canvas")
        if cs is None and src_sprite is not None:
            cs = (src_sprite.w, src_sprite.h)
        if cs is None:
            raise PixelError("restore_offsets: give canvas=WxH (the atlas source sprite is not available)")
        tw, th = cs

    # ---- build sprite
    sp = Sprite(tw, th, pal, name=name)
    frames_rep = []
    totals = {"remapped": 0, "semi_alpha": 0, "semi_to_opaque": 0, "semi_to_transparent": 0}
    mapping = {}
    max_d = 0.0
    for e in entries:
        idx, st = map_to_palette(e["rgba"], pal, alpha_threshold, dither)
        if restore_offsets:
            off = e["offset"] or {"x": 0, "y": 0}
            big = Canvas(tw, th, pal)
            big.stamp(Canvas.from_array(idx, pal), -int(off["x"]), -int(off["y"]))
            if int((big.data >= 0).sum()) != int((idx >= 0).sum()):
                raise PixelError(f"frame {e['name']}: restoring offset {off} into {tw}x{th} clips pixels")
            cv = big
        else:
            cv = Canvas.from_array(idx, pal)
        dur = int(round(1000 / float(fps))) if fps else e["duration"]
        sp.add_frame(e["name"], cv, dur)
        for k in totals:
            totals[k] += st[k]
        for src, m in st["mapping"].items():
            if src in mapping:
                mapping[src]["count"] += m["count"]
            else:
                mapping[src] = dict(m)
        max_d = max(max_d, st["max_distance"])
        frames_rep.append({"name": e["name"], "animation": e["anim"], "rect": [e["x"], e["y"], e["w"], e["h"]],
                           "empty": e["empty"], "opaque": st["opaque"], "remapped": st["remapped"],
                           "semi_alpha": st["semi_alpha"], "semi_to_opaque": st["semi_to_opaque"],
                           "semi_to_transparent": st["semi_to_transparent"], "mapping": st["mapping"]})
    if animations:
        sp.animations = {a: list(v) for a, v in animations.items() if v}
    unity = {}
    if anim_meta:
        unity["animations"] = {a: m for a, m in anim_meta.items() if m and a in sp.animations}
        if not unity["animations"]:
            del unity["animations"]
    if fps:
        unity["fps"] = float(fps)
    if pivot:
        unity["align"] = pivot["align"]
        if restore_offsets:
            srcp = pivot.get("source") or {}
            if pivot["align"] == "fixed" and "x" in srcp:
                sp.extra["pivot"] = {"x": int(srcp["x"]), "y": int(srcp["y"])}
        else:
            sp.extra["pivot"] = {"x": pivot["x"], "y": pivot["y"]}
    if unity:
        sp.extra["unity"] = unity
    sp.extra["imported_from"] = {"image": str(png) if isinstance(png, (str, Path)) else "<image>",
                                 "atlas": str(apath) if apath else None}
    report = {
        "image": str(png) if isinstance(png, (str, Path)) else "<image>", "image_size": [W, H],
        "atlas": str(apath) if apath else None, "frame_size": [fw, fh], "sprite_size": [tw, th],
        "frames": frames_rep, "frame_count": len(frames_rep), "animations": sp.get_animations(),
        "palette": pal.name, "palette_source": pal_src, "palette_colors": len(pal),
        "alpha_threshold": alpha_threshold, "dither": dither or "none",
        "remapped_total": totals["remapped"], "semi_alpha_total": totals["semi_alpha"],
        "semi_to_opaque": totals["semi_to_opaque"], "semi_to_transparent": totals["semi_to_transparent"],
        "color_mapping": dict(sorted(mapping.items(), key=lambda kv: -kv[1]["count"])),
        "max_distance": round(max_d, 2), "exact": totals["remapped"] == 0 and totals["semi_alpha"] == 0,
        "restored_offsets": bool(restore_offsets), "notes": notes, "path": None}
    if save and out is not None:
        report["path"] = str(sp.save(out))
    return sp, report


def import_text(rep) -> str:
    L = [f"import: {rep['image']} ({rep['image_size'][0]}x{rep['image_size'][1]})"
         + (f"  atlas {rep['atlas']}" if rep["atlas"] else ""),
         f"frames: {rep['frame_count']} x {rep['frame_size'][0]}x{rep['frame_size'][1]}"
         + (f" -> canvas {rep['sprite_size'][0]}x{rep['sprite_size'][1]} (offsets restored)"
            if rep["restored_offsets"] else ""),
         f"palette: {rep['palette']} ({rep['palette_colors']} colours, {rep['palette_source']})"]
    for a, fs in rep["animations"].items():
        L.append(f"  anim {a}: {', '.join(fs)}")
    for f in rep["frames"]:
        L.append(f"  {f['name']:14s} rect {','.join(map(str, f['rect']))}  opaque {f['opaque']:4d}  "
                 f"remapped {f['remapped']:4d}  semi-alpha {f['semi_alpha']} "
                 f"(->255: {f['semi_to_opaque']}, ->0: {f['semi_to_transparent']})" + ("  [empty]" if f["empty"] else ""))
    L.append(f"remapped pixels: {rep['remapped_total']}   semi-alpha thresholded: {rep['semi_alpha_total']}   "
             f"max colour distance (dE76): {rep['max_distance']}")
    for src, m in list(rep["color_mapping"].items())[:24]:
        L.append(f"  #{src.split('->')[0]} -> #{m['to']} (index {m['index']}): {m['count']} px, dE {m['distance']}")
    if len(rep["color_mapping"]) > 24:
        L.append(f"  ... {len(rep['color_mapping']) - 24} more mappings (see --report json)")
    L.append("result: EXACT (no colour or alpha changes)" if rep["exact"] else "result: colours/alpha were changed")
    for n in rep["notes"]:
        L.append(f"note: {n}")
    if rep["path"]:
        L.append(f"saved {rep['path']}")
    return "\n".join(L)


# --------------------------------------------------------------------------- grid detection
def _profiles(arr):
    """Edge-energy profiles: px[i] = colour difference between columns i and i+1 (summed over rows),
    baseline (noise floor = median) subtracted and thinned to local maxima, so blur that spreads an
    edge over 2-3 px still yields one peak on the block boundary."""
    a = arr[..., 3:4] / 255.0
    f = np.concatenate([arr[..., :3] * a, arr[..., 3:4]], 2)
    out = []
    for d, ax in ((np.abs(np.diff(f, axis=1)).sum(2), 0), (np.abs(np.diff(f, axis=0)).sum(2), 1)):
        # ignore weak per-pixel differences (noise, JPEG 8x8 block seams in flat areas)
        thr = max(24.0, 4.0 * float(np.median(d)))
        p = np.where(d > thr, d, 0.0).sum(ax)
        q = np.clip(p - np.median(p), 0, None)
        left = np.concatenate([[-1.0], q[:-1]])
        right = np.concatenate([q[1:], [-1.0]])
        out.append(np.where((q >= left) & (q > right) | (q > left) & (q >= right), q, 0.0))
    return out[0], out[1]


def _axis_scores(p, sizes, ostep=0.1):
    """For each block size s: best offset and its gain = share of edge energy on the boundaries minus
    share of positions that are boundaries (true size ~ 1 - 1/s; multiples ~ half; divisors lose 1/s)."""
    L = len(p)
    tot = p.sum()
    if L < 4 or tot <= 0:
        return np.zeros(len(sizes)), np.zeros(len(sizes))
    best_sc = np.zeros(len(sizes))
    best_o = np.zeros(len(sizes))
    for i, s in enumerate(sizes):
        offs = np.round(np.arange(0.0, s, ostep), 6)
        k = np.arange(1, int(L / s) + 2)
        pos = np.floor(offs[:, None] + k[None, :] * s + 0.5 + 1e-6).astype(np.int64) - 1
        valid = (pos >= 0) & (pos < L)
        n = valid.sum(1)
        e = np.where(valid, p[np.clip(pos, 0, L - 1)], 0).sum(1) / tot
        sc = e - n / L
        sc[n < 2] = -1
        j = int(np.argmax(sc))
        best_sc[i], best_o[i] = sc[j], offs[j]
    return best_sc, best_o


def _confidence(p, s, o):
    """(energy share on boundaries - boundary position share) / (1 - position share), 0..1."""
    L = len(p)
    if L < 2 or p.sum() <= 0:
        return 0.0
    k = np.arange(1, int(L / s) + 2)
    pos = np.floor(o + k * s + 0.5 + 1e-6).astype(int) - 1
    pos = np.unique(pos[(pos >= 0) & (pos < L)])
    f = len(pos) / L
    if f >= 1:
        return 0.0
    e = p[pos].sum() / p.sum()
    return float(max(0.0, min(1.0, (e - f) / (1 - f))))


def detect_grid(img, min_size=2, max_size=32, step=0.02):
    """Detect the block size / offset of upscaled ("fake") pixel art.

    Returns {size, size_float, integer, offset: (ox, oy), confidence, confidence_x/y, candidates}.
    size is the detected block size (an int when within 0.03 px of one); offset is where the first
    block starts (px, may be fractional for non-integer sizes)."""
    arr = load_rgba(img).astype(np.float64)
    H, W = arr.shape[:2]
    max_size = min(float(max_size), max(W, H) / 2.0)
    if max_size < min_size:
        raise PixelError(f"image {W}x{H} too small for block sizes >= {min_size}")
    px, py = _profiles(arr)
    sizes = np.round(np.arange(float(min_size), max_size + 1e-9, step), 4)
    sx, ox = _axis_scores(px, sizes)
    sy, oy = _axis_scores(py, sizes)
    wx, wy = (1.0 if px.sum() > 0 else 0.0), (1.0 if py.sum() > 0 else 0.0)
    if wx + wy == 0:
        raise PixelError("no block grid found (image has no edges)")
    score = (sx * wx + sy * wy) / (wx + wy)
    best = float(score.max())
    if best <= 0:
        raise PixelError("no block grid found (image has no regular edges)")
    tied = np.nonzero(score >= best - 1e-9)[0]
    # contiguous run around the first maximum; take its middle (sizes giving identical boundaries)
    run = [tied[0]]
    for t in tied[1:]:
        if t == run[-1] + 1:
            run.append(t)
        else:
            break
    i = int(run[len(run) // 2])
    s = float(sizes[i])
    r = round(s)
    integer = abs(s - r) <= 0.03 + 1e-9
    if integer:
        j = int(np.argmin(np.abs(sizes - r)))
        if score[j] >= 0.97 * score[i]:
            i, s = j, float(r)
        else:
            integer = False
    if not integer:  # prefer simple fractions (7.5, 6.25) when they score as well
        for q in (2, 4, 3):
            f = round(s * q) / q
            j = int(np.argmin(np.abs(sizes - f)))
            if abs(s - f) <= 0.08 and abs(sizes[j] - f) < 0.011 and score[j] >= 0.97 * score[i]:
                i, s = j, float(f)
                integer = float(f).is_integer()
                break
    offx, offy = float(ox[i]), float(oy[i])
    if integer:  # re-search whole-pixel offsets only
        offx = float(_axis_scores(px, [s], ostep=1.0)[1][0]) if wx else 0.0
        offy = float(_axis_scores(py, [s], ostep=1.0)[1][0]) if wy else 0.0
    cx, cy = _confidence(px, s, offx), _confidence(py, s, offy)
    peaks = [j for j in range(len(sizes)) if score[j] >= score[max(0, j - 12):j + 13].max() - 1e-12]
    cands = sorted(((float(sizes[j]), round(float(score[j]), 3)) for j in peaks), key=lambda t: -t[1])[:5]
    return {"size": int(s) if integer else round(s, 2), "size_float": round(s, 3), "integer": integer,
            "offset": (int(offx), int(offy)) if integer else (round(offx, 2), round(offy, 2)),
            "confidence": round((cx + cy) / 2, 3), "confidence_x": round(cx, 3), "confidence_y": round(cy, 3),
            "score": round(float(score[i]), 3), "image_size": (W, H), "candidates": cands}


def _block_ranges(n_px, s, o):
    """Blocks covering >= half a block inside [0, n_px): list of (start, end) floats."""
    i0 = math.ceil((-s / 2 - o) / s - 1e-9)
    i1 = math.floor((n_px + s / 2 - o) / s + 1e-9) - 1
    return [(o + i * s, o + (i + 1) * s) for i in range(i0, i1 + 1)]


def _interior(a, b, n_px, frac):
    """Pixel index range of the interior (frac trimmed off each side) of block [a, b)."""
    m = (b - a) * frac
    lo = max(0, math.ceil(a + m - 0.5))
    hi = min(n_px, math.floor(b - m - 0.5) + 1)
    if hi <= lo:
        c = min(n_px - 1, max(0, int(math.floor((a + b) / 2))))
        lo, hi = c, c + 1
    return lo, hi


def sample_blocks(arr, size, offset, mode="median", trim=0.25):
    """Downsample: one output pixel per block (interior median / centre pixel)."""
    H, W = arr.shape[:2]
    s = float(size)
    xs, ys = _block_ranges(W, s, float(offset[0])), _block_ranges(H, s, float(offset[1]))
    if not xs or not ys:
        raise PixelError("no full blocks inside the image")
    if len(xs) > 256 or len(ys) > 256:
        raise PixelError(f"result would be {len(xs)}x{len(ys)} px (> 256); block size too small?")
    out = np.zeros((len(ys), len(xs), 4), np.uint8)
    xr = [_interior(a, b, W, trim if mode == "median" else 0.5) for a, b in xs]
    yr = [_interior(a, b, H, trim if mode == "median" else 0.5) for a, b in ys]
    for j, (y0, y1) in enumerate(yr):
        for i, (x0, x1) in enumerate(xr):
            blk = arr[y0:y1, x0:x1].reshape(-1, 4)
            out[j, i] = np.round(np.median(blk, 0)).astype(np.uint8)
    return out


def _merge_colors(rgb_list, counts, tol):
    """Greedy clustering in Lab: most frequent colour first; members within tol join. -> centres, labels"""
    lab = rgb_to_lab(np.array(rgb_list, float))
    order = np.argsort(-np.array(counts), kind="stable")
    centres, members = [], []
    labels = np.zeros(len(rgb_list), int)
    for k in order:
        if centres:
            d = np.sqrt(((np.array([lab[c[0]] for c in members]) - lab[k]) ** 2).sum(1))
            j = int(np.argmin(d))
            if d[j] <= tol:
                members[j].append(k)
                labels[k] = j
                continue
        members.append([k])
        labels[k] = len(members) - 1
    for mem in members:
        w = np.array([counts[m] for m in mem], float)
        c = (np.array([rgb_list[m] for m in mem], float) * w[:, None]).sum(0) / w.sum()
        centres.append(tuple(int(round(v)) for v in c))
    return centres, labels


def _kmeans(rgb, k, iters=12):
    """Deterministic k-means in Lab on (N,3) rgb; init = merged clusters by frequency."""
    uniq, inv, cnt = np.unique(rgb.astype(np.int64), axis=0, return_inverse=True, return_counts=True)
    inv = inv.reshape(-1)
    if len(uniq) <= k:
        return [tuple(int(v) for v in u) for u in uniq]
    cents, _ = _merge_colors([tuple(u) for u in uniq], cnt.tolist(), 4.0)
    cents = cents[:max(k, 1)]  # merged clusters come out most-frequent first
    if len(cents) < k:
        extra = [tuple(int(v) for v in uniq[i]) for i in np.argsort(-cnt) if tuple(uniq[i]) not in cents]
        cents += extra[:k - len(cents)]
    lab = rgb_to_lab(uniq.astype(float))
    C = rgb_to_lab(np.array(cents, float))
    for _ in range(iters):
        d = ((lab[:, None] - C[None]) ** 2).sum(-1)
        lbl = d.argmin(1)
        for j in range(len(C)):
            m = lbl == j
            if m.any():
                C[j] = (lab[m] * cnt[m, None]).sum(0) / cnt[m].sum()
    d = ((lab[:, None] - C[None]) ** 2).sum(-1)
    lbl = d.argmin(1)
    out = []
    for j in range(len(C)):
        m = lbl == j
        if m.any():
            c = (uniq[m] * cnt[m, None]).sum(0) / cnt[m].sum()
            out.append(tuple(int(round(v)) for v in c))
    return out


def depixelize(img, size=None, offset=None, min_size=2, max_size=32, sample="median", palette=None, colors=None,
               merge=8.0, transparent="none", tolerance=12.0, alpha_threshold=128):
    """Fake pixel art -> clean 1:1 pixel art. Returns (PIL RGBA Image, report).

    size/offset: force the grid (else detect_grid). sample: median (interior median, robust to blur
    and JPEG noise) | center. palette: snap to a palette; colors=K: K-colour k-means; otherwise
    near-duplicate colours within `merge` dE are merged (0 = keep raw medians). transparent:
    'none' | 'auto' (background = most common border colour) | hex; pixels within `tolerance` dE of
    it become transparent."""
    arr = load_rgba(img)
    det = detect_grid(arr, min_size, max_size) if size is None else None
    if size is None:
        s, off = det["size"], det["offset"]
    else:
        s = float(size)
        off = tuple(offset) if offset is not None else detect_offset(arr, s)
        det = {"size": size, "size_float": float(size), "integer": float(size).is_integer(), "offset": off,
               "confidence": None, "forced": True, "image_size": (arr.shape[1], arr.shape[0])}
    if offset is not None:
        off = tuple(offset)
        det["offset"] = off
    small = sample_blocks(arr.astype(np.float64), s, off, mode=sample)
    h, w = small.shape[:2]
    a = small[..., 3]
    semi = int(((a > 0) & (a < 255)).sum())
    opaque = a >= alpha_threshold
    rep = {"detect": det, "output_size": [w, h], "semi_alpha": semi, "sample": sample}
    # background removal
    bg = None
    if transparent and transparent != "none":
        if transparent == "auto":
            border = np.concatenate([small[0], small[-1], small[:, 0], small[:, -1]])
            border = border[border[:, 3] >= alpha_threshold][:, :3]
            if len(border):
                cents, lbl = _merge_colors([tuple(map(int, c)) for c in border], [1] * len(border), tolerance)
                bg = cents[int(np.bincount(lbl).argmax())]
        else:
            bg = parse_hex(transparent)
        if bg is not None:
            labs = rgb_to_lab(small[..., :3].astype(float))
            d = np.sqrt(((labs - rgb_to_lab(np.array(bg, float))) ** 2).sum(-1))
            near = opaque & (d <= tolerance)
            # only background-coloured pixels connected (4-way) to the image border are removed,
            # so similar colours inside the sprite (eyes, outlines) survive
            rm = np.zeros_like(near)
            rm[0], rm[-1], rm[:, 0], rm[:, -1] = near[0], near[-1], near[:, 0], near[:, -1]
            while True:
                g = rm.copy()
                g[1:] |= rm[:-1]
                g[:-1] |= rm[1:]
                g[:, 1:] |= rm[:, :-1]
                g[:, :-1] |= rm[:, 1:]
                g &= near
                if (g == rm).all():
                    break
                rm = g
            opaque &= ~rm
            rep["background"] = {"color": to_hex(bg), "removed": int(rm.sum())}
    rgb = small[..., :3].astype(np.int64)
    out = np.zeros((h, w, 4), np.uint8)
    pts = rgb[opaque]
    if palette is not None:
        pal = resolve_palette(palette)
        idx = pal.nearest_many(pts.astype(float)) if len(pts) else np.zeros(0, int)
        cols = np.array(pal.colors, np.uint8)
        out[opaque, :3] = cols[idx] if len(pts) else 0
        rep["quantize"] = {"mode": "palette", "palette": pal.name}
    elif colors:
        cents = _kmeans(pts, int(colors)) if len(pts) else []
        if cents:
            P = Palette([to_hex(c) for c in cents], name="kmeans")
            out[opaque, :3] = np.array(P.colors, np.uint8)[P.nearest_many(pts.astype(float))]
        rep["quantize"] = {"mode": "kmeans", "colors": len(cents)}
    elif merge and len(pts):
        uniq, inv, cnt = np.unique(pts, axis=0, return_inverse=True, return_counts=True)
        cents, lbl = _merge_colors([tuple(int(v) for v in u) for u in uniq], cnt.tolist(), float(merge))
        out[opaque, :3] = np.array(cents, np.uint8)[lbl[inv.reshape(-1)]]
        rep["quantize"] = {"mode": "merge", "tolerance": merge, "colors_before": int(len(uniq)),
                           "colors": len(cents)}
    else:
        out[opaque, :3] = pts.astype(np.uint8)
        rep["quantize"] = {"mode": "raw"}
    out[opaque, 3] = 255
    rep["colors"] = int(len(np.unique(_pack(out[..., :3])[opaque]))) if opaque.any() else 0
    rep["opaque"] = int(opaque.sum())
    return Image.fromarray(out, "RGBA"), rep


def detect_offset(arr, s):
    """Best offset for a forced block size."""
    px, py = _profiles(np.asarray(arr, np.float64))
    _, ox = _axis_scores(px, [float(s)])
    _, oy = _axis_scores(py, [float(s)])
    if float(s).is_integer():
        return int(round(ox[0])) % int(s), int(round(oy[0])) % int(s)
    return float(ox[0]), float(oy[0])


def detect_text(det) -> str:
    s = det["size"]
    off = det["offset"]
    L = [f"block size: {s} px" + ("" if det.get("integer", True) else
                                  f"  (non-integer; blocks alternate {math.floor(det['size_float'])}/"
                                  f"{math.ceil(det['size_float'])} px, sampled on the fractional grid)"),
         f"offset: x={off[0]} y={off[1]}  (first full block starts here)"]
    if det.get("confidence") is not None:
        c = det["confidence"]
        lvl = "high" if c >= 0.5 else "medium" if c >= 0.25 else "low"
        L.append(f"confidence: {c} ({lvl}; x {det['confidence_x']}, y {det['confidence_y']})")
        W, H = det["image_size"]
        L.append(f"image: {W}x{H} -> about {round(W / det['size_float'])}x{round(H / det['size_float'])} px")
        L.append("candidates (size, score): " + ", ".join(f"{a:g}:{b}" for a, b in det["candidates"]))
    return "\n".join(L)
