"""Unity export: fixed-cell sprite sheets with foot-pivot alignment.

    ps.unity_sheet("examples/sprites/hero.py")  # -> output/sprites/{sheets/, atlas.png, atlas.json, preview/, UNITY_IMPORT.txt}

Layout
  * every cell has the same size (auto: union of all frames' content relative to the pivot + padding,
    width forced even; or an explicit cell=(w, h)), spacing 0, margin 0 -> image size = n * cell.
  * sheets/<anim>.png: one horizontal strip per animation.
  * atlas.png: one animation per row, columns = longest animation; unused cells fully transparent.
  * alpha is strictly 0 or 255 (asserted). 1x by default; scaled copies only in preview/.

Pivot ("foot point") - a pixel in sprite coordinates that lands on the same cell pixel (the anchor)
in every frame; offsets are integers only.
  * align="fixed" (default): ONE sprite-space pivot for every frame, so intentional motion inside the
    canvas (a rig's body bob, a jump arc) is preserved. Default pivot = bottom-center of the UNION
    content bbox of all exported frames: x = ux + uw // 2, y = lowest opaque row of the union.
    Override per sprite in the source: "pivot": {"x": 16, "y": 31} | "bottom-center" | "center",
    or via the API/CLI pivot argument.
  * align="auto": per-frame foot detection - lowest opaque row of that frame, horizontal center of
    that frame's whole bbox (x + w // 2). The full-bbox center is used instead of the bottom row's
    center because feet alternate in walk/run cycles and would make the sprite jitter sideways.
    Cancels in-canvas bob/jump motion - use it for sprites drawn without a stable ground line.
  * Anchor (cell pixel receiving the pivot): default bottom-center = (cell_w // 2, cell_h - 1) when
    nothing hangs below the pivot. Unity normalized pivot = (ax / W, (H - 1 - ay) / H), i.e. the
    left edge of the anchor column and the bottom edge of the anchor row, y measured from the bottom.

Optional source settings (grid JSON top level, or sprite.extra for .py sources)::

    "pivot": {"x": 16, "y": 31},
    "unity": {"align": "fixed", "padding": 1, "cell": [32, 32], "fps": 8, "loop": true,
              "animations": {"death": {"fps": 10, "loop": false}}}

"rig_animations": {"idle": {"fps": 4, "loop": true, ...}} is honoured as well.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from .canvas import Canvas
from .errors import PixelError
from .sprite import Sprite, load_sprite, output_dir, resolve_source

STD_PPU = (16, 32, 64, 128, 256)
PIVOT_MODES = ("bottom-center", "center")


# --------------------------------------------------------------------------- helpers
def _parse_xy(v, what):
    if isinstance(v, str):
        try:
            a, b = (int(t) for t in v.replace("x", ",").split(","))
            return a, b
        except Exception:
            raise PixelError(f"{what} must look like 'x,y', got {v!r}") from None
    if isinstance(v, dict) and "x" in v and "y" in v:
        return int(v["x"]), int(v["y"])
    if isinstance(v, (list, tuple)) and len(v) == 2:
        return int(v[0]), int(v[1])
    raise PixelError(f"{what} must be x,y / {{'x':..,'y':..}} / [x, y], got {v!r}")


def parse_pivot(v):
    """-> None | ('mode', name) | ('point', (x, y)). Accepts 'bottom-center', 'center', 'auto',
    'x,y', {'x','y'}, {'mode': ...}, [x, y]."""
    if v is None:
        return None
    if isinstance(v, dict) and "mode" in v:
        v = v["mode"]
    if isinstance(v, str) and v.strip().lower() in PIVOT_MODES + ("auto",):
        return ("mode", v.strip().lower())
    return ("point", _parse_xy(v, "pivot"))


def _parse_cell(v):
    if v is None:
        return None
    if isinstance(v, str):
        try:
            w, h = (int(t) for t in v.lower().split("x"))
        except Exception:
            raise PixelError(f"cell must look like 32x32, got {v!r}") from None
    else:
        w, h = _parse_xy(v, "cell")
    if w < 1 or h < 1:
        raise PixelError(f"cell must be positive, got {w}x{h}")
    return w, h


def _point_of_bbox(bb, mode):
    x, y, w, h = bb
    if mode == "center":
        return x + w // 2, y + h // 2
    return x + w // 2, y + h - 1  # bottom-center: lowest opaque row, bbox horizontal center


def _union_bbox(cvs):
    m = np.zeros_like(cvs[0].data, dtype=bool)
    for cv in cvs:
        m |= cv.data >= 0
    ys, xs = np.nonzero(m)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)


def binary_alpha(img: Image.Image) -> Image.Image:
    """Threshold any semi-transparent alpha to 0/255 and assert the result."""
    arr = np.array(img.convert("RGBA"))
    a = arr[..., 3]
    arr[..., 3] = np.where(a >= 128, 255, 0).astype(np.uint8)
    arr[arr[..., 3] == 0] = 0
    assert np.isin(arr[..., 3], (0, 255)).all(), "alpha must be 0 or 255"
    return Image.fromarray(arr, "RGBA")


def recommend_ppu(cell_h):
    """Smallest standard PPU (16/32/64/128/256) >= cell height: the character is <= 1 unit tall
    and every sprite of that size class shares one PPU (needed for a consistent pixel grid /
    Pixel Perfect Camera)."""
    for v in STD_PPU:
        if v >= cell_h:
            return v
    return STD_PPU[-1]


def _anim_settings(sp, name):
    u = sp.extra.get("unity") or {}
    per = (u.get("animations") or {}).get(name) or {}
    rig = (sp.extra.get("rig_animations") or {}).get(name) or {}
    out = {}
    for k in ("fps", "loop"):
        for srcd in (per, rig, u):
            if isinstance(srcd, dict) and k in srcd:
                out[k] = srcd[k]
                break
    return out


# --------------------------------------------------------------------------- main
def prepare_unity(src, cell=None, padding=None, pivot=None, align=None, anchor=None, fps=None, no_loop=(),
                  anims=None, ppu=None):
    """Shared core of every Unity export (unity_sheet and the game layout's char-export): loads the
    sprite, resolves the pivot / alignment, sizes ONE cell for all selected animations and composes the
    pivot-aligned cell frames + timing. Writes nothing. Returns a dict used by render_rows/sheet_json."""
    sp = load_sprite(src)
    u = sp.extra.get("unity") or {}

    # ---- animations
    all_anims = sp.get_animations()
    names = list(anims) if anims else list(all_anims)
    for a in names:
        if a not in all_anims:
            raise PixelError(f"no animation {a!r}; animations: {', '.join(all_anims)}")
    names = [a for a in names if all_anims[a]]
    if not names:
        raise PixelError("sprite has no animations to export")
    frames = {a: [sp.frame(f) for f in all_anims[a]] for a in names}
    every = [cv for a in names for cv in frames[a]]

    # ---- pivot / alignment
    piv = parse_pivot(pivot) or parse_pivot(sp.extra.get("pivot")) or parse_pivot(u.get("pivot"))
    align = (align or ("auto" if piv == ("mode", "auto") else None) or u.get("align") or "fixed").lower()
    if align not in ("fixed", "auto"):
        raise PixelError(f"align must be 'fixed' or 'auto', got {align!r}")
    mode = piv[1] if piv and piv[0] == "mode" and piv[1] != "auto" else "bottom-center"
    ub = _union_bbox(every)
    if ub is None:
        raise PixelError("all frames are empty; nothing to export")
    if piv and piv[0] == "point":
        if align == "auto":
            raise PixelError("an explicit pivot point needs align='fixed' (auto detects the foot per frame)")
        fixed = piv[1]
        pivot_desc = {"mode": "point", "x": fixed[0], "y": fixed[1]}
    else:
        fixed = _point_of_bbox(ub, mode)
        pivot_desc = {"mode": f"union-{mode}" if align == "fixed" else f"per-frame-{mode}",
                      "x": fixed[0], "y": fixed[1]}
    fpiv = {}
    for cv in every:
        bb = cv.bbox()
        fpiv[id(cv)] = _point_of_bbox(bb, mode) if (align == "auto" and bb) else fixed

    # ---- extents relative to the pivot (in pixels)
    left = right = up = down = 0
    for cv in every:
        bb = cv.bbox()
        if not bb:
            continue
        px, py = fpiv[id(cv)]
        left = max(left, px - bb[0])
        right = max(right, bb[0] + bb[2] - 1 - px)
        up = max(up, py - bb[1])
        down = max(down, bb[1] + bb[3] - 1 - py)
    pad = int(u.get("padding", 1) if padding is None else padding)
    if pad < 0:
        raise PixelError("padding must be >= 0")
    cell = _parse_cell(cell if cell is not None else u.get("cell"))
    if cell is None:
        hw = max(left + pad, right + 1 + pad, 1)
        cw = 2 * hw
        ch = pad + up + 1 + down + (pad if down else 0)
        ax, ay = hw, pad + up
        if anchor is not None:
            raise PixelError("anchor needs an explicit cell size")
    else:
        cw, ch = cell
        ax, ay = _parse_xy(anchor, "anchor") if anchor is not None else (cw // 2, ch - 1 - down)
    if not (0 <= ax < cw and 0 <= ay < ch):
        raise PixelError(f"anchor ({ax},{ay}) lies outside the {cw}x{ch} cell")
    # fit check (also catches cells smaller than the content bbox)
    need = []
    if ax - left < 0:
        need.append(f"{left - ax} px more on the left")
    if ax + right > cw - 1:
        need.append(f"{ax + right - cw + 1} px more on the right")
    if ay - up < 0:
        need.append(f"{up - ay} px more on top")
    if ay + down > ch - 1:
        need.append(f"{ay + down - ch + 1} px more at the bottom")
    maxw = max(cv.bbox()[2] for cv in every if cv.bbox())
    maxh = max(cv.bbox()[3] for cv in every if cv.bbox())
    if cw < maxw or ch < maxh or need:
        raise PixelError(f"cell {cw}x{ch} is smaller than the content (largest frame bbox {maxw}x{maxh}, "
                         f"pivot-aligned extent {left + right + 1}x{up + down + 1}): needs "
                         + (", ".join(need) or "a larger cell") + f"; anchor ({ax},{ay})")
    if cw > 256 or ch > 256:
        raise PixelError(f"cell {cw}x{ch} exceeds 256 px")

    # ---- compose aligned cell-sized sprite (integer offsets only)
    cell_sp = Sprite(cw, ch, sp.palette, name=sp.name, default_duration=sp.default_duration)
    offsets = {}
    for a in names:
        cell_names = []
        for i, cv in enumerate(frames[a]):
            px, py = fpiv[id(cv)]
            ox, oy = ax - px, ay - py
            c = Canvas(cw, ch, sp.palette)
            c.stamp(cv, ox, oy)
            if int((c.data >= 0).sum()) != int((cv.data >= 0).sum()):
                raise PixelError(f"frame {cv.name!r} was clipped while aligning (internal error)")
            nm = f"{a}__{i}"
            cell_sp.add_frame(nm, c, sp.durations.get(cv.name, sp.default_duration))
            cell_names.append(nm)
            offsets[nm] = (ox, oy, cv.name)
        cell_sp.animations[a] = cell_names

    # ---- timing
    no_loop = set(no_loop or ())
    timing = {}
    for a in names:
        st = _anim_settings(sp, a)
        src_durs = [sp.durations.get(cv.name, sp.default_duration) for cv in frames[a]]
        afps = st.get("fps", fps)
        if afps and "fps" in st and len(set(src_durs)) > 1:
            # the source defines fps AND explicit per-frame timing: report the declared fps,
            # keep the hand-set durations (no fps derived from the duration average)
            afps = float(afps)
            durs = src_durs
        elif afps:
            afps = float(afps)
            durs = [int(round(1000 / afps))] * len(src_durs)
        else:
            durs = src_durs
            afps = round(1000 * len(durs) / sum(durs), 3)
        loop = False if a in no_loop else bool(st.get("loop", True))
        t, times = 0, []
        for d in durs:
            times.append(round(t / 1000, 4))
            t += d
        timing[a] = {"frame_count": len(durs), "fps": afps, "loop": loop, "durations": durs,
                     "uniform": len(set(durs)) == 1, "times": times, "length": round(t / 1000, 4),
                     "source_frames": [cv.name for cv in frames[a]]}

    # ---- pivot json / ppu
    nx, ny = ax / cw, (ch - 1 - ay) / ch
    if ax * 2 == cw and ay == ch - 1:
        preset = "Bottom"
    elif ax * 2 == cw and (ch - 1 - ay) * 2 == ch:
        preset = "Center"
    else:
        preset = "Custom"
    rec_ppu = int(ppu) if ppu else recommend_ppu(ch)
    piv_json = {"pixel": {"x": ax, "y": ay}, "pixel_from_bottom": {"x": ax, "y": ch - 1 - ay},
                "normalized": {"x": round(nx, 6), "y": round(ny, 6)}, "unity_preset": preset,
                "align": align, "source": pivot_desc,
                "note": "pixel = cell pixel (y down) holding the foot point; normalized = Unity "
                        "custom pivot (x from left edge, y from bottom edge)"}
    return {"sprite": sp, "names": names, "cell_sprite": cell_sp, "offsets": offsets, "timing": timing,
            "cell": (cw, ch), "anchor": (ax, ay), "padding": pad, "pivot": piv_json, "ppu": rec_ppu,
            "preset": preset}


def render_rows(prep, names, strip_of, label=None):
    """Compose animations `names` (one row each, in this order) from prepare_unity() output.
    strip_of: {anim: strip path stored in the json}. label: {anim: display name used in the json
    (default: the animation name)}. Returns (image with binary alpha, frames hash, animation entries,
    columns)."""
    cell_sp, (cw, ch), sp = prep["cell_sprite"], prep["cell"], prep["sprite"]
    label = label or {}
    cols = max(prep["timing"][a]["frame_count"] for a in names)
    img = Image.new("RGBA", (cols * cw, len(names) * ch), (0, 0, 0, 0))
    fhash, entries = {}, []
    for row, a in enumerate(names):
        tm, disp = prep["timing"][a], label.get(a, a)
        entries.append({"name": disp, "row": row, "frame_count": tm["frame_count"], "fps": tm["fps"],
                        "loop": tm["loop"], "durations": tm["durations"], "uniform": tm["uniform"],
                        "times": tm["times"], "length": tm["length"], "strip": strip_of[a],
                        "source_frames": tm["source_frames"]})
        if disp != a:
            entries[-1]["source_animation"] = a
        for i, nm in enumerate(cell_sp.animations[a]):
            img.paste(cell_sp.frame(nm).to_image(1), (i * cw, row * ch))
            ox, oy, srcname = prep["offsets"][nm]
            fhash[f"{sp.name} {disp} {i}"] = {
                "frame": {"x": i * cw, "y": row * ch, "w": cw, "h": ch}, "rotated": False, "trimmed": False,
                "spriteSourceSize": {"x": 0, "y": 0, "w": cw, "h": ch}, "sourceSize": {"w": cw, "h": ch},
                "duration": tm["durations"][i], "animation": disp, "index": i, "source_frame": srcname,
                "offset": {"x": ox, "y": oy}}
    return binary_alpha(img), fhash, entries, cols


def sheet_json(prep, image_name, size, entries, fhash, cols, extra=None, json_dir=None):
    """atlas.json-format dict (readable by check / import) for one rendered image. meta.source is stored
    relative to `json_dir` (the folder the json is written to) so no absolute path ends up on disk."""
    from .paths import rel_to
    sp, (cw, ch) = prep["sprite"], prep["cell"]
    data = {
        "frames": fhash,
        "meta": {"app": "spritewright", "version": "1.0", "target": "unity", "image": image_name,
                 "format": "RGBA8888", "size": {"w": size[0], "h": size[1]}, "scale": "1",
                 "frameTags": [{"name": e["name"], "from": e["row"] * cols,
                                "to": e["row"] * cols + e["frame_count"] - 1,
                                "direction": "forward"} for e in entries],
                 "layers": [], "slices": [], "sprite": sp.name,
                 "source": (rel_to(sp.source or sp.extra.get("_script"), json_dir) if json_dir is not None
                            else str(sp.source or sp.extra.get("_script") or ""))},
        "cell": {"w": cw, "h": ch}, "frame_size": {"w": cw, "h": ch}, "rows": len(entries), "columns": cols,
        "spacing": 0, "margin": 0, "padding": prep["padding"], "pivot": prep["pivot"],
        "animations": entries,
        "unity": {"pixels_per_unit": prep["ppu"], "sprite_mode": "Multiple", "filter_mode": "Point",
                  "compression": "None", "slice": "Grid By Cell Size",
                  "pivot": prep["preset"]},
    }
    if extra:
        data.update(extra)
    return data


def unity_sheet(src, out_dir=None, cell=None, padding=None, pivot=None, align=None, anchor=None,
                fps=None, no_loop=(), anims=None, preview_scale=4, ppu=None, print_note=False):
    """Unity-ready export. Returns a report dict (paths, cell, rows, columns, pivot, animations, note).
    cell: (w, h) / 'WxH' (None = auto). pivot: see parse_pivot. align: 'fixed' | 'auto'.
    anchor: (x, y) cell pixel for the pivot (None = bottom-center). fps: used when the source has
    none. no_loop: animation names exported with loop=false. anims: subset/order of animations."""
    prep = prepare_unity(src, cell=cell, padding=padding, pivot=pivot, align=align, anchor=anchor, fps=fps,
                         no_loop=no_loop, anims=anims, ppu=ppu)
    sp, names, cell_sp = prep["sprite"], prep["names"], prep["cell_sprite"]
    cw, ch = prep["cell"]
    if out_dir is None:
        origin = sp.source or sp.extra.get("_script")
        if origin is None and not isinstance(src, Sprite):
            origin = resolve_source(src)
        out_dir = output_dir(origin) if origin else output_dir("misc")
    out_dir = Path(out_dir)

    # ---- images
    sheets_dir = out_dir / "sheets"
    prev_dir = out_dir / "preview"
    sheets_dir.mkdir(parents=True, exist_ok=True)
    atlas, fhash, anim_info, cols = render_rows(prep, names, {a: f"sheets/{a}.png" for a in names})
    rows = len(names)
    strips = {}
    for a in names:
        p = sheets_dir / f"{a}.png"
        render_rows(prep, [a], {a: ""})[0].save(p)
        strips[a] = p
    atlas_p = out_dir / "atlas.png"
    atlas.save(atlas_p)

    # ---- previews (scaled copies + GIFs; never meant for import)
    previews = {}
    s = int(preview_scale or 0)
    if s >= 1:
        from . import export as ex
        prev_dir.mkdir(parents=True, exist_ok=True)
        pa = prev_dir / f"atlas_x{s}.png"
        atlas.resize((atlas.width * s, atlas.height * s), Image.NEAREST).save(pa)
        previews["atlas"] = str(pa)
        for info in anim_info:
            a = info["name"]
            im = Image.open(strips[a])
            ps_ = prev_dir / f"{a}_x{s}.png"
            im.resize((im.width * s, im.height * s), Image.NEAREST).save(ps_)
            gp = prev_dir / f"{a}.gif"
            ex.gif(cell_sp, gp, anim=a, scale=s,
                   fps=info["fps"] if info["uniform"] else None)
            previews[a] = [str(ps_), str(gp)]

    # ---- json + note
    piv_json, rec_ppu = prep["pivot"], prep["ppu"]
    jp = out_dir / "atlas.json"
    data = sheet_json(prep, "atlas.png", atlas.size, anim_info, fhash, cols, json_dir=out_dir)
    jp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    note = unity_note(sp.name, cw, ch, rows, cols, atlas.size, piv_json, rec_ppu, anim_info)
    np_ = out_dir / "UNITY_IMPORT.txt"
    np_.write_text(note + "\n", encoding="utf-8")
    if print_note:
        print(note)
    return {"atlas": atlas_p, "json": jp, "note_path": np_, "strips": strips, "previews": previews,
            "cell": (cw, ch), "rows": rows, "columns": cols, "pivot": piv_json, "animations": anim_info,
            "ppu": rec_ppu, "note": note, "out_dir": out_dir}


def unity_note(name, cw, ch, rows, cols, size, piv, ppu, anims):
    n = piv["normalized"]
    if piv["unity_preset"] == "Custom":
        pv = f"Custom  (X {n['x']:.4f}, Y {n['y']:.4f})"
    else:
        pv = f"{piv['unity_preset']}  (= Custom X {n['x']:.4f}, Y {n['y']:.4f})"
    lines = [
        f"=== Unity import note: {name} ===",
        f"File           : atlas.png ({size[0]}x{size[1]})  |  single animation: sheets/<anim>.png",
        f"Cell           : {cw}x{ch} px, spacing 0, margin 0",
        f"Rows x columns : {rows} x {cols}  (one animation per row; empty cells are transparent)",
        f"Pivot          : {pv}",
        f"                 cell pixel ({piv['pixel']['x']},{piv['pixel']['y']}) = foot point, align: {piv['align']}",
        f"Pixels Per Unit: {ppu}  (smallest standard value 16/32/64/128 covering the {ch} px cell height;",
        "                 the character is ~1 unit tall and every sprite of the same size class shares the",
        "                 PPU -> consistent pixel grid with the Pixel Perfect Camera. Use one PPU per project.)",
        "",
        "Texture Import Settings:",
        "  Texture Type   : Sprite (2D and UI)",
        "  Sprite Mode    : Multiple",
        f"  Pixels Per Unit: {ppu}",
        "  Mesh Type      : Full Rect",
        "  Filter Mode    : Point (no filter)",
        "  Compression    : None",
        f"  Max Size       : >= {max(size)}",
        "  Wrap Mode      : Clamp",
        "",
        "Sprite Editor -> Slice:",
        "  Type           : Grid By Cell Size",
        f"  Pixel Size     : X {cw}  Y {ch}",
        "  Offset / Padding: 0 / 0",
        f"  Pivot          : {piv['unity_preset']}" + (f"  (Custom Pivot X {n['x']:.4f}, Y {n['y']:.4f})"
                                                       if piv["unity_preset"] == "Custom" else ""),
        "  Keep Empty Rects: off (empty cells of short rows are skipped)",
        "",
        "Animations (row: name, frames, fps, loop):",
    ]
    for a in anims:
        t = "" if a["uniform"] else f"  (frame durations differ: {a['durations']} ms -> keyframe times {a['times']} s)"
        lines.append(f"  {a['row']}: {a['name']:<10s} {a['frame_count']} frames  {a['fps']:g} fps  "
                     f"loop={'on' if a['loop'] else 'off'}{t}")
    lines.append("  Clip: Sample Rate = fps, Loop Time = loop value. Details: atlas.json")
    return "\n".join(lines)
