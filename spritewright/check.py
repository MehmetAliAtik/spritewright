"""Quality check: one PASS / WARN / FAIL report for a sprite source and/or a Unity atlas.

    rep = ps.check("examples/sprites/hero.py")  # source + output/sprites/atlas.json if it belongs to hero
    rep = ps.check("output/test/atlas.json")  # an atlas directly (atlas.png + sheets/*.png)
    rep["exit_code"]                          # 1 if any FAIL, else 0

Inputs
  * sprite source (grid JSON / rig JSON / .py / Sprite): frames are checked directly. If
    output/<project>/atlas.json was produced from the same source (meta.source / meta.sprite), the
    atlas PNGs are checked too and the per-animation checks run on the atlas cells (what Unity sees).
  * atlas: atlas.json, atlas.png (sibling json) or a directory containing atlas.json. The palette
    comes from meta.source (or palette=...).

Checks (id -> status rule; thresholds in DEFAULTS, all overridable)
  files.alpha          any alpha not 0/255 in a PNG                          -> FAIL
  files.off_palette    opaque RGB not in the sprite palette                    -> FAIL
  colors.count         distinct opaque colours > max_colors                    -> WARN
  atlas.geometry       cell/sheet/strip sizes vs atlas.json                    -> FAIL (stale strip / junk in unused cell -> WARN)
  atlas.sync           atlas cells != current source frames (stale export)     -> WARN
  anim.size_drift      opaque bbox w/h range > size_drift (> size_drift_fail -> FAIL); empty frame -> FAIL
  anim.foot_drift      foot y (lowest opaque row) vs pivot y, foot x (bbox centre) spread
                       > foot_drift -> WARN (> foot_drift_fail -> FAIL). Body bob does not move the
                       lowest row, so rig bob never triggers it.
  anim.motion          consecutive frames identical, or diff < max(motion_min_px, motion_min_ratio * opaque) -> WARN
  anim.loop_seam       Sprite.loop_check(last -> first) > seam_factor * median step, or 0 (duplicate
                       frame -> hitch) -> WARN; SKIP for loop=false / single-frame animations
  anim.orphans         Canvas.orphans() count per frame > orphans_per_frame -> WARN (never FAIL)

Game style (group "game-style"; only with game=... / --game, or when the checked path lies inside
outputs/<Game>/ - detected by walking up to the folder holding game-style.json)
  game.off_palette     opaque colour not in the game palette                    -> FAIL
  game.color_limit     distinct opaque colours > game max_colors                 -> FAIL
  game.cell            atlas/sheet cell != character card cell (else game cell)  -> FAIL
                       (source only: canvas larger than the cell -> FAIL)
  game.char_colors     colour outside the character card's colour list          -> WARN
  game.light           HEURISTIC, WARN only: per frame, the interior opaque pixels (outline ring
                       removed unless outline=none) are split into thirds along the light vector;
                       the third facing the light should not be darker (mean luminance) than the
                       opposite third. WARN when more than half of the frames break it.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from .canvas import Canvas
from .errors import PixelError
from .palette import ROOT, Palette, to_hex
from .paths import rel_to, resolve_from
from .sprite import Sprite, load_sprite, output_dir, resolve_source
from .unity import _anim_settings, _point_of_bbox, _union_bbox, parse_pivot

DEFAULTS = {
    "max_colors": 16,          # distinct opaque colours per PNG / sprite
    "size_drift": 2,           # px, bbox w/h range within an animation -> WARN above
    "size_drift_fail": 6,      # px -> FAIL above
    "foot_drift": 1,           # px, foot vs pivot (y) / foot x spread -> WARN above
    "foot_drift_fail": 4,      # px -> FAIL above
    "motion_min_px": 2,        # consecutive frames differing in fewer px -> WARN
    "motion_min_ratio": 0.01,  # ... or in fewer than this share of the opaque pixels
    "seam_factor": 2.0,        # loop seam > factor * median step -> WARN
    "orphans_per_frame": 3,    # orphan pixels per frame -> WARN above
    "orphan_connectivity": 4,  # same as `clean`
}
STATUSES = ("PASS", "WARN", "FAIL")
_RANK = {"SKIP": -1, "PASS": 0, "WARN": 1, "FAIL": 2}


def _item(cid, status, message, details=None, threshold=None):
    return {"id": cid, "status": status, "message": message, "details": details or {},
            "threshold": threshold}


def _worst(*sts):
    return max(sts, key=lambda s: _RANK[s])


def _level(value, warn, fail):
    return "FAIL" if value > fail else "WARN" if value > warn else "PASS"


# --------------------------------------------------------------------------- input resolution
def _find(path):
    p = Path(path)
    for c in ([p] if p.is_absolute() else [Path.cwd() / p, ROOT / p]):
        if c.exists():
            return c.resolve()
    return None


def _is_atlas_json(p):
    try:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return False
    return isinstance(d, dict) and "cell" in d and "animations" in d and "frames" in d and "meta" in d


def _atlas_path(src):
    """atlas.json path if src names an atlas (json / png / directory), else None."""
    if isinstance(src, Sprite):
        return None
    p = _find(src)
    if p is None:
        return None
    if p.is_dir():
        j = p / "atlas.json"
        if not j.is_file():
            raise PixelError(f"{p}: directory has no atlas.json (run unity-sheet first)")
        return j
    if p.suffix.lower() == ".png":
        j = p.with_suffix(".json")
        if not j.is_file():
            j = p.parent / "atlas.json"
        if j.is_file() and _is_atlas_json(j):
            return j
        raise PixelError(f"{p}: no atlas.json next to this PNG")
    if p.suffix.lower() == ".json" and _is_atlas_json(p):
        return p
    return None


def _same_file(a, b):
    try:
        return Path(a).resolve() == Path(b).resolve()
    except Exception:
        return False


def _atlas_for_source(sp):
    origin = sp.source or sp.extra.get("_script")
    if not origin:
        return None
    j = output_dir(origin, create=False) / "atlas.json"
    if not j.is_file() or not _is_atlas_json(j):
        return None
    meta = json.loads(j.read_text(encoding="utf-8")).get("meta", {})
    if meta.get("source"):
        return j if _same_file(resolve_from(meta["source"], j.parent), origin) else None
    return j if meta.get("sprite") == sp.name else None


# --------------------------------------------------------------------------- image helpers
def _rgba(path):
    return np.asarray(Image.open(path).convert("RGBA"))


def _opaque_rgbs(arr):
    m = arr[..., 3] > 0
    px = arr[m][:, :3].astype(np.uint32)
    return m, (px[:, 0] << 16) | (px[:, 1] << 8) | px[:, 2]


def _cells_sprite(atlas_arr, data, name):
    """Atlas cells -> Sprite (ad-hoc palette of the colours present) so the Canvas/Sprite tools
    (bbox, orphans, loop_check, diff_count) work on the exported pixels."""
    cw, ch = data["cell"]["w"], data["cell"]["h"]
    m, packed = _opaque_rgbs(atlas_arr)
    uniq, inv = np.unique(packed, return_inverse=True)
    if len(uniq) == 0:
        uniq = np.array([0], dtype=np.uint32)
    if len(uniq) > 255:
        raise PixelError(f"atlas has {len(uniq)} distinct colours; cannot analyse as indexed art")
    pal = Palette(["%06x" % int(v) for v in uniq], name="atlas-colours")
    idx = np.full(atlas_arr.shape[:2], -1, dtype=np.int16)
    if m.any():
        idx[m] = inv.astype(np.int16)
    sp = Sprite(cw, ch, pal, name=name)
    H, W = idx.shape
    for a in data["animations"]:
        names = []
        for i in range(int(a["frame_count"])):
            x, y = i * cw, int(a["row"]) * ch
            if y + ch > H or x + cw > W:
                break  # geometry check reports it
            nm = f"{a['name']}__{i}"
            sp.add_frame(nm, Canvas.from_array(idx[y:y + ch, x:x + cw], pal, name=nm))
            names.append(nm)
        sp.animations[a["name"]] = names
    return sp


def atlas_sprite(src):
    """Sprite of the cells of an atlas / per-animation sheet (json, png with sibling json, or folder
    with atlas.json), frame durations from the json; None if src is not an atlas/sheet."""
    try:
        j = _atlas_path(src)
    except PixelError:
        return None
    if j is None:
        return None
    data = json.loads(j.read_text(encoding="utf-8"))
    img = j.parent / data.get("meta", {}).get("image", j.with_suffix(".png").name)
    if not img.is_file():
        img = j.with_suffix(".png")
    if not img.is_file():
        raise PixelError(f"{img} not found (named by {j.name})")
    sp = _cells_sprite(_rgba(img), data, data.get("meta", {}).get("sprite") or j.stem)
    for a in data["animations"]:
        for i, d in enumerate(a.get("durations") or []):
            nm = f"{a['name']}__{i}"
            if nm in sp.frames:
                sp.durations[nm] = int(d)
    sp.source = str(j)
    return sp


# --------------------------------------------------------------------------- file checks
def _file_checks(files, palette, th):
    """files: {label: rgba array}. -> [alpha, off_palette, colors]."""
    semi, offp, counts = {}, {}, {}
    palset = None
    if palette is not None:
        palset = {(r << 16) | (g << 8) | b for r, g, b in palette.colors}
    for label, arr in files.items():
        a = arr[..., 3]
        bad = (a != 0) & (a != 255)
        if bad.any():
            ys, xs = np.nonzero(bad)
            semi[label] = {"count": int(bad.sum()), "pixels": [[int(x), int(y)] for x, y in zip(xs[:20], ys[:20])],
                           "alphas": sorted({int(v) for v in a[bad]})[:16]}
        m, packed = _opaque_rgbs(arr)
        uniq = np.unique(packed)
        counts[label] = int(len(uniq))
        if palset is not None:
            off = np.array([int(v) not in palset for v in packed], dtype=bool)
            if off.any():
                ys, xs = np.nonzero(m)
                offp[label] = {"count": int(off.sum()),
                               "colors": sorted({"#%06x" % int(v) for v in packed[off]})[:16],
                               "pixels": [[int(x), int(y)] for x, y in zip(xs[off][:20], ys[off][:20])]}
    n = len(files)
    out = []
    if semi:
        tot = sum(v["count"] for v in semi.values())
        out.append(_item("files.alpha", "FAIL", f"{tot} semi-transparent pixel(s) (alpha not 0/255): {', '.join(semi)}",
                         semi, "alpha in {0, 255}"))
    else:
        out.append(_item("files.alpha", "PASS", f"alpha only 0/255 ({n} image(s))", {}, "alpha in {0, 255}"))
    if palset is None:
        out.append(_item("files.off_palette", "SKIP", "palette unknown (no source; pass --palette), check skipped"))
    elif offp:
        tot = sum(v["count"] for v in offp.values())
        out.append(_item("files.off_palette", "FAIL", f"{tot} off-palette pixel(s) ({palette.name}): {', '.join(offp)}",
                         offp, f"palette {palette.name}"))
    else:
        out.append(_item("files.off_palette", "PASS", f"all colours in palette {palette.name} ({n} image(s))", {},
                         f"palette {palette.name}"))
    mx = max(counts.values()) if counts else 0
    st = "WARN" if mx > th["max_colors"] else "PASS"
    out.append(_item("colors.count", st, f"at most {mx} colours per image (limit {th['max_colors']})",
                     {"per_file": counts}, th["max_colors"]))
    return out


def _geometry(data, atlas_arr, strips):
    fails, warns = [], []
    cw, ch = int(data["cell"]["w"]), int(data["cell"]["h"])
    rows, cols = int(data.get("rows", 0)), int(data.get("columns", 0))
    H, W = atlas_arr.shape[:2]
    fs = data.get("frame_size") or data["cell"]
    if (fs.get("w"), fs.get("h")) != (cw, ch):
        fails.append(f"frame_size {fs} != cell {cw}x{ch}")
    if data.get("spacing", 0) or data.get("margin", 0):
        warns.append(f"spacing/margin {data.get('spacing')}/{data.get('margin')} (expected 0)")
    if W % cw or H % ch:
        fails.append(f"atlas {W}x{H} is not a multiple of cell {cw}x{ch}")
    if (W, H) != (cols * cw, rows * ch):
        fails.append(f"atlas {W}x{H} != columns*cell x rows*cell = {cols * cw}x{rows * ch}")
    ms = data.get("meta", {}).get("size")
    if ms and (ms.get("w"), ms.get("h")) != (W, H):
        fails.append(f"meta.size {ms['w']}x{ms['h']} != actual atlas {W}x{H}")
    for k, f in data.get("frames", {}).items():
        r = f.get("frame", {})
        if (r.get("w"), r.get("h")) != (cw, ch):
            fails.append(f"'{k}': frame {r.get('w')}x{r.get('h')} != cell {cw}x{ch}")
        elif r.get("x", 0) % cw or r.get("y", 0) % ch or r.get("x", 0) + cw > W or r.get("y", 0) + ch > H:
            fails.append(f"'{k}': frame ({r.get('x')},{r.get('y')}) not on the cell grid / inside the atlas")
    used = set()
    for a in data["animations"]:
        fc, row = int(a["frame_count"]), int(a["row"])
        if fc > cols or row >= rows:
            fails.append(f"animation {a['name']}: {fc} frames / row {row} do not fit the atlas ({rows}x{cols})")
        used |= {(row, i) for i in range(fc)}
        sp = strips.get(a["name"])
        if sp is None:
            fails.append(f"strip missing: {a.get('strip', a['name'])}")
            continue
        sh, sw = sp.shape[:2]
        if (sw, sh) != (fc * cw, ch):
            fails.append(f"strip {a['name']}: {sw}x{sh} != frame_count*cell = {fc * cw}x{ch}")
        elif row < rows and fc <= cols and not np.array_equal(sp, atlas_arr[row * ch:(row + 1) * ch, :fc * cw]):
            warns.append(f"strip {a['name']} differs from its atlas row (stale output?)")
    if not fails:
        junk = [f"({r},{c})" for r in range(rows) for c in range(cols)
                if (r, c) not in used and atlas_arr[r * ch:(r + 1) * ch, c * cw:(c + 1) * cw, 3].any()]
        if junk:
            warns.append("pixels in unused cells: " + ", ".join(junk))
    st = "FAIL" if fails else "WARN" if warns else "PASS"
    msg = (fails + warns)[0] if (fails or warns) else \
        f"cell {cw}x{ch}, atlas {W}x{H} = {cols}x{rows} cells, {len(strips)} strip(s) consistent"
    if len(fails) + len(warns) > 1:
        msg += f" (+{len(fails) + len(warns) - 1} more)"
    return _item("atlas.geometry", st, msg, {"fail": fails, "warn": warns, "cell": [cw, ch],
                                             "atlas": [W, H], "rows": rows, "columns": cols},
                 "atlas = columns*cell x rows*cell, strip = frame_count*cell")


def _anim_key(name):
    return str(name).replace("_", "").replace("-", "").replace(" ", "").lower()


def _sync(sp, data, cells):
    """Compare each atlas cell with the current source frame stamped at its recorded offset."""
    cw, ch = data["cell"]["w"], data["cell"]["h"]
    stale, missing = [], []
    for k, f in data.get("frames", {}).items():
        src = f.get("source_frame")
        if src not in sp.frames:
            missing.append(src)
            continue
        c = Canvas(cw, ch, sp.palette)
        c.stamp(sp.frames[src], f["offset"]["x"], f["offset"]["y"])
        nm = f"{f['animation']}__{f['index']}"
        if nm not in cells.frames or not np.array_equal(c.to_rgba(), cells.frames[nm].to_rgba()):
            stale.append(k)
    # char-export / build name animations Title_Case (idle -> Idle): compare case/separator-insensitively
    anims_atl = {_anim_key(a["name"]) for a in data["animations"]}
    extra = sorted(a for a, v in sp.get_animations().items() if v and _anim_key(a) not in anims_atl)
    if stale or missing:
        return _item("atlas.sync", "WARN", f"atlas out of date with the source ({len(stale) + len(missing)} frame(s) differ/missing); "
                     "re-run the export", {"stale": stale, "missing_source_frames": missing,
                                                          "not_exported": extra})
    if extra:
        return _item("atlas.sync", "PASS", f"atlas up to date; animation(s) not exported: {', '.join(extra)}",
                     {"not_exported": extra})
    return _item("atlas.sync", "PASS", "atlas cells identical to the current source frames")


# --------------------------------------------------------------------------- animation checks
def _anim_checks(sp, anim, names, pivot, loop, th):
    out = []
    cvs = [sp.frame(n) for n in names]
    bbs = [cv.bbox() for cv in cvs]
    empty = [n for n, b in zip(names, bbs) if b is None]
    # -- size drift
    sizes = {n: [b[2], b[3]] for n, b in zip(names, bbs) if b}
    if empty:
        out.append(_item("anim.size_drift", "FAIL", f"empty frame(s): {', '.join(empty)}", {"empty": empty, "sizes": sizes},
                         [th["size_drift"], th["size_drift_fail"]]))
    else:
        ws, hs = [v[0] for v in sizes.values()], [v[1] for v in sizes.values()]
        dw, dh = max(ws) - min(ws), max(hs) - min(hs)
        st = _level(max(dw, dh), th["size_drift"], th["size_drift_fail"])
        out.append(_item("anim.size_drift", st, f"size drift: width {dw} px, height {dh} px "
                         f"(limit {th['size_drift']})", {"sizes": sizes, "dw": dw, "dh": dh},
                         [th["size_drift"], th["size_drift_fail"]]))
    full = [(n, b) for n, b in zip(names, bbs) if b]
    if not full:
        return out
    # -- foot drift: lowest opaque row vs pivot y; bbox-centre x spread
    feet = {n: _point_of_bbox(b, "bottom-center") for n, b in full}
    px, py = pivot
    dys = {n: py - f[1] for n, f in feet.items()}  # > 0: foot above the pivot (floating)
    xs = [f[0] for f in feet.values()]
    dy = max(abs(v) for v in dys.values())
    dx = max(xs) - min(xs)
    st = _level(max(dy, dx), th["foot_drift"], th["foot_drift_fail"])
    out.append(_item("anim.foot_drift", st, f"foot point: at most {dy} px from pivot y, x spread {dx} px "
                     f"(limit {th['foot_drift']})",
                     {"pivot": [px, py], "feet": {n: list(f) for n, f in feet.items()},
                      "dy_from_pivot": dys, "dx_vs_pivot": {n: f[0] - px for n, f in feet.items()}},
                     [th["foot_drift"], th["foot_drift_fail"]]))
    # -- motion
    if len(cvs) < 2:
        out.append(_item("anim.motion", "PASS", "single frame (static)", {}, None))
    else:
        steps = [cvs[i].diff_count(cvs[i + 1]) for i in range(len(cvs) - 1)]
        opaque = float(np.mean([int(cv.opaque_mask().sum()) for cv in cvs]))
        lim = max(th["motion_min_px"], th["motion_min_ratio"] * opaque)
        ident = [f"{names[i]}->{names[i + 1]}" for i, s in enumerate(steps) if s == 0]
        low = [f"{names[i]}->{names[i + 1]}" for i, s in enumerate(steps) if 0 < s < lim]
        det = {"steps": {f"{names[i]}->{names[i + 1]}": s for i, s in enumerate(steps)},
               "min_visible": round(lim, 2), "identical": ident, "low": low}
        if ident or low:
            parts = ([f"identical frames: {', '.join(ident)}"] if ident else []) + \
                    ([f"too little change (<{lim:.0f} px): {', '.join(low)}"] if low else [])
            out.append(_item("anim.motion", "WARN", "; ".join(parts), det,
                             [th["motion_min_px"], th["motion_min_ratio"]]))
        else:
            out.append(_item("anim.motion", "PASS", f"frame-to-frame change {min(steps)}-{max(steps)} px "
                             f"(min {lim:.0f})", det, [th["motion_min_px"], th["motion_min_ratio"]]))
    # -- loop seam (Sprite.loop_check)
    if not loop:
        out.append(_item("anim.loop_seam", "SKIP", "loop off, loop seam not checked"))
    elif len(cvs) < 2:
        out.append(_item("anim.loop_seam", "SKIP", "single frame"))
    else:
        seam = sp.loop_check(anim)
        steps = [cvs[i].diff_count(cvs[i + 1]) for i in range(len(cvs) - 1)]
        med = float(np.median(steps))
        det = {"seam": seam, "median_step": med, "factor": th["seam_factor"]}
        if seam == 0:
            out.append(_item("anim.loop_seam", "WARN", "last frame equals the first: duplicate frame in the loop (hitch)",
                             det, th["seam_factor"]))
        elif len(cvs) > 2 and seam > th["seam_factor"] * med and seam >= th["motion_min_px"]:
            out.append(_item("anim.loop_seam", "WARN", f"loop seam {seam} px > {th['seam_factor']:g} x median step "
                             f"({med:g} px): jump on last->first", det, th["seam_factor"]))
        else:
            out.append(_item("anim.loop_seam", "PASS", f"loop seam {seam} px (median step {med:g} px)",
                             det, th["seam_factor"]))
    # -- orphans (Canvas.orphans, same as `clean`)
    per = {}
    for n, cv in zip(names, cvs):
        o = cv.orphans(th["orphan_connectivity"])
        if o:
            per[n] = {"count": len(o), "pixels": [{"x": p["x"], "y": p["y"], "isolated": p["isolated"]} for p in o]}
    mx = max((v["count"] for v in per.values()), default=0)
    tot = sum(v["count"] for v in per.values())
    st = "WARN" if mx > th["orphans_per_frame"] else "PASS"
    out.append(_item("anim.orphans", st, f"orphan pixels: {tot} total, at most {mx} per frame "
                     f"(limit {th['orphans_per_frame']}; may be deliberate highlights/dither)", per,
                     th["orphans_per_frame"]))
    return out


def _source_pivot(sp, frames):
    piv = parse_pivot(sp.extra.get("pivot")) or parse_pivot((sp.extra.get("unity") or {}).get("pivot"))
    if piv and piv[0] == "point":
        return piv[1]
    ub = _union_bbox(frames)
    return _point_of_bbox(ub, "bottom-center") if ub else (0, 0)


# --------------------------------------------------------------------------- game style
def _light_violation(cv, vec, skip_ring):
    """True if the lit third of the shape is darker than the shadow third (None = not measurable)."""
    from .palette import luminance
    m = cv.data >= 0
    if skip_ring:
        inner = m.copy()
        inner[1:, :] &= m[:-1, :]
        inner[:-1, :] &= m[1:, :]
        inner[:, 1:] &= m[:, :-1]
        inner[:, :-1] &= m[:, 1:]
        inner[0, :] = inner[-1, :] = False
        inner[:, 0] = inner[:, -1] = False
        if inner.sum() >= 8:
            m = inner
    ys, xs = np.nonzero(m)
    if len(xs) < 6:
        return None
    lut = np.array([luminance(c) for c in cv.palette.colors])
    lum = lut[cv.data[ys, xs]]
    vx, vy = vec
    proj = (xs - xs.mean()) * vx + (ys - ys.mean()) * vy
    lo, hi = proj.min(), proj.max()
    if hi - lo < 2:
        return None
    t1, t2 = lo + (hi - lo) / 3, lo + 2 * (hi - lo) / 3
    lit, shadow = lum[proj >= t2], lum[proj <= t1]
    if not len(lit) or not len(shadow):
        return None
    return float(lit.mean()) + 0.01 < float(shadow.mean())


def _game_checks(st, card, files, sp, data, frames_sprite):
    """files: {label: rgba array} (atlas PNGs); sp: source sprite or None; frames_sprite: Sprite whose
    frames are analysed for the light heuristic."""
    from .style import LIGHTS
    out = []
    gpal = {int(e["hex"], 16) for e in st["palette"]}
    used = set()
    for arr in files.values():
        used |= {int(v) for v in np.unique(_opaque_rgbs(arr)[1])}
    if sp is not None and not files:
        for f in sp.frames.values():
            for i in f.colors_used():
                r, g, b = sp.palette.colors[i]
                used.add((r << 16) | (g << 8) | b)
    off = sorted("#%06x" % v for v in used - gpal)
    gname = st["name"]
    if off:
        out.append(_item("game.off_palette", "FAIL", f"{len(off)} colour(s) not in the {gname} game palette: {', '.join(off[:8])}"
                         + (" ..." if len(off) > 8 else "") + " (ask the user; if approved: game-palette-add)",
                         {"colors": off}, "game palette"))
    else:
        out.append(_item("game.off_palette", "PASS", f"all colours in the {gname} game palette ({len(used)} colours)",
                         {}, "game palette"))
    mc = int(st["max_colors"])
    out.append(_item("game.color_limit", "FAIL" if len(used) > mc else "PASS",
                     f"{len(used)} distinct colours (game limit {mc})", {"count": len(used)}, mc))
    exp = tuple(card["cell"]) if card else tuple(st["cell"])
    who = f"card {card['name']}" if card else f"game {gname}"
    if data is not None:
        got = (int(data["cell"]["w"]), int(data["cell"]["h"]))
        st_ = "PASS" if got == exp else "FAIL"
        out.append(_item("game.cell", st_, f"cell {got[0]}x{got[1]}, expected {exp[0]}x{exp[1]} ({who})",
                         {"cell": list(got), "expected": list(exp)}, list(exp)))
    elif sp is not None:
        got = (sp.w, sp.h)
        if got[0] > exp[0] or got[1] > exp[1]:
            out.append(_item("game.cell", "FAIL", f"canvas {got[0]}x{got[1]} larger than the cell ({exp[0]}x{exp[1]}, {who})",
                             {"canvas": list(got), "expected": list(exp)}, list(exp)))
        else:
            out.append(_item("game.cell", "PASS", f"canvas {got[0]}x{got[1]} fits the {exp[0]}x{exp[1]} cell ({who}; "
                             "placed in the cell on export)", {"canvas": list(got), "expected": list(exp)}, list(exp)))
    if card and card.get("colors"):
        allowed = {int(c["hex"], 16) for c in card["colors"]}
        extra = sorted("#%06x" % v for v in (used & gpal) - allowed)
        if extra:
            out.append(_item("game.char_colors", "WARN", f"colours not on the {card['name']} card: {', '.join(extra[:8])}",
                             {"colors": extra}, "card colours"))
        else:
            out.append(_item("game.char_colors", "PASS", f"only colours from the {card['name']} card", {}, "card colours"))
    else:
        out.append(_item("game.char_colors", "SKIP", "no character card (path not under characters/<Name>/)"))
    vec = LIGHTS.get(st.get("light"))
    if vec is None or frames_sprite is None:
        out.append(_item("game.light", "SKIP", f"no heuristic for light direction '{st.get('light')}'"))
    else:
        res = {n: _light_violation(cv, vec, st.get("outline") != "none") for n, cv in frames_sprite.frames.items()}
        meas = {n: v for n, v in res.items() if v is not None}
        bad = [n for n, v in meas.items() if v]
        if meas and len(bad) * 2 > len(meas):
            out.append(_item("game.light", "WARN", f"heuristic: in {len(bad)}/{len(meas)} frames the {st['light']} side is "
                             "darker than the opposite side (light direction rule?)", {"frames": bad}, st["light"]))
        else:
            out.append(_item("game.light", "PASS", f"heuristic: shading matches light {st['light']} "
                             f"({len(meas) - len(bad)}/{len(meas)} frames)", {"frames_against": bad}, st["light"]))
    return out


def _resolve_game(game, game_root, path):
    """-> (style dict, card | None) or None."""
    from . import layout
    from .style import load_style
    if game:
        st = load_style(game, game_root)
        gdir = layout.game_dir(st["name"], game_root)
    else:
        if not path:
            return None
        found = layout.find_game(path)
        if not found:
            return None
        gdir = found[0]
        st = json.loads((gdir / "game-style.json").read_text(encoding="utf-8"))
    card = None
    if path:
        found = layout.find_game(path)
        if found and found[1] is not None and Path(found[0]).resolve() == Path(gdir).resolve():
            card = layout.load_card(found[1], found[2])
    return st, card


# --------------------------------------------------------------------------- main
def check(src, atlas=None, out=None, palette=None, thresholds=None, write=True, game=None, game_root=None, **kw):
    """Run all checks. src: sprite source / Sprite / atlas.json / atlas.png / atlas directory.
    atlas: explicit atlas (path) for a source, False = never look for one. out: report path
    (.json -> + .txt sibling) or directory (default: next to the atlas, else output/<project>/).
    palette: override palette for atlas-only checks. thresholds / **kw: keys of DEFAULTS.
    Returns {checks, groups, summary, summary_line, exit_code, text, paths}."""
    th = dict(DEFAULTS)
    th.update(thresholds or {})
    for k, v in kw.items():
        if k not in DEFAULTS:
            raise PixelError(f"unknown check threshold {k!r}; known: {', '.join(DEFAULTS)}")
        if v is not None:
            th[k] = v
    groups = []
    sp = None
    atlas_j = _atlas_path(src)
    if atlas_j is None:
        sp = load_sprite(src)
        if atlas is None:
            atlas_j = _atlas_for_source(sp)
        elif atlas is not False:
            atlas_j = _atlas_path(atlas)
            if atlas_j is None:
                raise PixelError(f"{atlas}: not an atlas.json / atlas.png / atlas folder")
    data = json.loads(atlas_j.read_text(encoding="utf-8")) if atlas_j else None
    if sp is None and data is not None:
        msrc = resolve_from(data.get("meta", {}).get("source"), atlas_j.parent)
        if msrc:
            try:
                sp = load_sprite(msrc)
            except Exception:
                sp = None
    pal = Palette.load(palette) if palette is not None else (sp.palette if sp is not None else None)
    name = sp.name if sp is not None else (data or {}).get("meta", {}).get("sprite", "atlas")

    # ---- source
    if sp is not None:
        g = []
        used = set()
        for f in sp.frames.values():
            used |= set(f.colors_used())
        st = "WARN" if len(used) > th["max_colors"] else "PASS"
        g.append(_item("colors.count", st, f"source uses {len(used)} colours (limit {th['max_colors']}); "
                       f"palette {sp.palette.name} ({len(sp.palette)} colours, Canvas strict: no off-palette colours)",
                       {"used": sorted(sp.palette.hex(i) for i in used)}, th["max_colors"]))
        groups.append({"name": "source", "checks": g})

    # ---- atlas files
    cells = None
    if data is not None:
        base = atlas_j.parent
        img = base / data.get("meta", {}).get("image", "atlas.png")
        if not img.is_file():
            raise PixelError(f"{img} not found (atlas.json points to it)")
        atlas_arr = _rgba(img)
        strips, files = {}, {img.name: atlas_arr}
        for a in data["animations"]:
            p = base / a.get("strip", f"sheets/{a['name']}.png")
            if p.is_file():
                strips[a["name"]] = _rgba(p)
                files[p.relative_to(base).as_posix()] = strips[a["name"]]
        g = _file_checks(files, pal, th)
        g.append(_geometry(data, atlas_arr, strips))
        cells = _cells_sprite(atlas_arr, data, name)
        if sp is not None and atlas is not False:
            g.append(_sync(sp, data, cells))
        groups.append({"name": "atlas", "checks": g})
        pv = data["pivot"]["pixel"]
        for a in data["animations"]:
            names = cells.animations.get(a["name"], [])
            if names:
                groups.append({"name": f"atlas/{a['name']}",
                               "checks": _anim_checks(cells, a["name"], names, (pv["x"], pv["y"]),
                                                      bool(a.get("loop", True)), th)})
    else:
        anims = {a: v for a, v in sp.get_animations().items() if v}
        pivot = _source_pivot(sp, [sp.frame(n) for v in anims.values() for n in v])
        for a, names in anims.items():
            loop = bool(_anim_settings(sp, a).get("loop", True))
            groups.append({"name": f"source/{a}", "checks": _anim_checks(sp, a, names, pivot, loop, th)})

    # ---- game style (explicit game, or path inside outputs/<Game>/)
    gpath = atlas_j if atlas_j is not None else (
        (sp.source or sp.extra.get("_script")) if sp is not None else None)
    gres = _resolve_game(game, game_root, gpath)
    game_name = None
    if gres:
        st, card = gres
        game_name = st["name"]
        gfiles = files if data is not None else {}
        fs = cells if cells is not None else sp
        groups.append({"name": "game-style", "checks": _game_checks(st, card, gfiles, sp, data, fs)})

    # ---- summary
    allc = [c for g in groups for c in g["checks"]]
    summary = {s: sum(c["status"] == s for c in allc) for s in STATUSES}
    summary["SKIP"] = sum(c["status"] == "SKIP" for c in allc)
    line = f"check: {summary['PASS']} PASS, {summary['WARN']} WARN, {summary['FAIL']} FAIL"
    rep = {"tool": "spritewright check", "sprite": name,
           "inputs": {"source": str(sp.source or sp.extra.get("_script") or "") if sp is not None else None,
                      "atlas": str(atlas_j) if atlas_j else None},
           "thresholds": th, "groups": groups, "summary": summary, "summary_line": line,
           "exit_code": 1 if summary["FAIL"] else 0}
    if game_name:
        rep["inputs"]["game"] = game_name
    rep["text"] = report_text(rep)
    rep["checks"] = allc
    rep["paths"] = {}
    if write:
        if out:
            o = Path(out)
            jp = o if o.suffix.lower() == ".json" else o / f"{name}_check.json"
        else:
            if atlas_j is not None:
                d = atlas_j.parent
            else:
                origin = sp.source or sp.extra.get("_script")
                d = output_dir(origin) if origin else output_dir("misc")
            jp = d / f"{name}_check.json"
        jp.parent.mkdir(parents=True, exist_ok=True)
        tp = jp.with_suffix(".txt")
        body, text = portable_report(rep, jp.parent)
        jp.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tp.write_text(text + "\n", encoding="utf-8")
        rep["paths"] = {"json": jp, "txt": tp}
    return rep


def issue_lines(rep, limit=None, width=150):
    """One short line per WARN/FAIL check (FAIL first): 'FAIL game.cell [atlas/Walk] message'."""
    out = []
    for status in ("FAIL", "WARN"):
        for g in rep["groups"]:
            for c in g["checks"]:
                if c["status"] == status:
                    ln = f"{status} {c['id']} [{g['name']}] {c['message']}"
                    out.append(ln if len(ln) <= width else ln[:width - 3] + "...")
    if limit is not None and len(out) > limit:
        out = out[:limit] + [f"... +{len(out) - limit} more (--verbose)"]
    return out


def short_text(rep, limit=8):
    """Quiet check output: summary line + one line per WARN/FAIL (truncated)."""
    return "\n".join([rep["summary_line"]] + issue_lines(rep, limit))


def portable_report(rep, base_dir):
    """(json body, text) of a report for writing into `base_dir`: input paths relative to that folder,
    so saved reports carry no absolute paths. The in-memory report keeps absolute paths."""
    body = {k: v for k, v in rep.items() if k not in ("text", "checks", "paths")}
    inputs = dict(body.get("inputs") or {})
    if inputs.get("source"):
        inputs["source"] = rel_to(inputs["source"], base_dir)
    if inputs.get("atlas"):
        inputs["atlas"] = ", ".join(rel_to(a, base_dir) if a else a for a in str(inputs["atlas"]).split(", "))
    body["inputs"] = inputs
    return body, report_text(body)


def report_text(rep):
    lines = [f"=== spritewright check: {rep['sprite']} ==="]
    if rep["inputs"]["source"]:
        lines.append(f"source: {rep['inputs']['source']}")
    lines.append(f"atlas : {rep['inputs']['atlas'] or '(none - only the source frames were checked)'}")
    if rep["inputs"].get("game"):
        lines.append(f"game  : {rep['inputs']['game']} (game-style.json)")
    for g in rep["groups"]:
        lines.append(f"\n[{g['name']}]")
        for c in g["checks"]:
            lines.append(f"  {c['status']:<4}  {c['id']:<18} {c['message']}")
            if c["status"] in ("WARN", "FAIL") and c["id"] == "anim.orphans":
                for fr, v in list(c["details"].items())[:4]:
                    pts = " ".join(f"({p['x']},{p['y']})" for p in v["pixels"][:12])
                    lines.append(f"{'':26}{fr}: {v['count']} -> {pts}{' ...' if v['count'] > 12 else ''}")
    lines.append("")
    lines.append(rep["summary_line"] + (f"  ({rep['summary']['SKIP']} skipped)" if rep["summary"]["SKIP"] else ""))
    return "\n".join(lines)
