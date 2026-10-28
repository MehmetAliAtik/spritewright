"""Command line interface: spritewright <command> ...  (spritewright -h)

From a source checkout without installing: python spritewright.py <command> ...

Quiet by default (token-efficient for an AI driver): every command prints a one-line result;
lists, reports, notes and logs only with --verbose (or --json where offered). File outputs are the
same in both modes."""
from __future__ import annotations

import argparse
import json
import runpy
import sys
from pathlib import Path

from . import __version__
from . import export as ex
from .errors import PixelError
from .palette import ROOT, Palette, generate_ramp, parse_hex, to_hex
from .paths import projects_root
from .sprite import Sprite, load_sprite, output_dir, resolve_source


def _size(s):
    try:
        w, h = s.lower().split("x")
        return int(w), int(h)
    except Exception:
        raise argparse.ArgumentTypeError(f"size must look like 32x32, got {s!r}")


def _region(s):
    try:
        v = [int(t) for t in s.split(",")]
        assert len(v) == 4
        return tuple(v)
    except Exception:
        raise argparse.ArgumentTypeError(f"region must be x,y,w,h, got {s!r}")


def _color(s):
    """CLI color: int index, name, or hex."""
    try:
        return int(s)
    except ValueError:
        return s


def _frame_key(s):
    if s is None:
        return None
    try:
        return int(s)
    except ValueError:
        return s


def _outpath(args, default_name):
    if getattr(args, "out", None):
        return Path(args.out)
    return output_dir(resolve_source(args.src)) / default_name


def _sp(args):
    return load_sprite(args.src)


def _v(args):
    return bool(getattr(args, "verbose", False))


def _short(s, n=160):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n - 3] + "..."


def _save_back(sp, args):
    """Write a modified sprite: -o path, else back into its .json source."""
    target = getattr(args, "out", None) or (sp.source if sp.source and str(sp.source).endswith(".json") else None)
    if not target:
        raise PixelError("source is a .py script; pass -o new.json to save the modified sprite")
    p = sp.save(target)
    print(f"saved {p}")
    return p


def _fname(sp, f):
    return sp.frame(_frame_key(f)).name if f is not None else list(sp.frames)[0]


# --------------------------------------------------------------------------- commands
def cmd_palettes(args):
    names = Palette.builtin_names()
    if _v(args):
        for n in names:
            print(f"{n:14s} {len(Palette.load(n)):3d} colors")
        return
    print(f"{len(names)} palettes: " + ", ".join(f"{n}({len(Palette.load(n))})" for n in names))


def cmd_palette_show(args):
    pal = Palette.load(args.palette)
    sw = ex.palette_swatch(pal, args.out) if args.out else None
    if _v(args):
        for i, c in enumerate(pal.colors):
            nm = pal.name_of(i)
            print(f"{i:3d}  #{to_hex(c)}" + (f"  {nm}" if nm else ""))
        if sw:
            print("swatch:", sw)
        return
    print(f"{pal.name} ({len(pal)}): " + " ".join("#" + to_hex(c) for c in pal.colors)
          + (f" | swatch {sw}" if sw else ""))


def cmd_palette_create(args):
    colors = {}
    pal = Palette.load(args.base) if args.base else None
    for item in args.colors:
        if "=" in item:
            n, h = item.split("=", 1)
        else:
            n, h = None, item
        rgb = parse_hex(h)
        if pal is not None and args.snap:
            rgb = pal.colors[pal.nearest(rgb)]
        colors[n or f"c{len(colors)}"] = to_hex(rgb)
    if pal is not None and args.extend:
        newp = pal.extended(colors, name=args.name or Path(args.out).stem)
    else:
        newp = Palette(list(colors.values()), names={k: i for i, k in enumerate(colors)},
                       name=args.name or Path(args.out).stem)
    out = Path(args.out)
    if not out.is_absolute() and not out.parent.exists():
        out = projects_root() / out
    print("saved", newp.save(out), f"({len(newp)} colors)")


def cmd_attach_palette(args):
    sp = _sp(args)
    newp = Palette.load(args.palette, base_dir=Path(sp.source).parent if sp.source else None)
    if args.copy_to_project and sp.source:
        dst = Path(sp.source).parent / (Path(args.palette).stem + ".json")
        newp.save(dst)
    lut = {}
    for f in sp.frames.values():
        for idx in f.colors_used():
            if idx not in lut:
                lut[idx] = newp.index(sp.palette.colors[idx], strict=not args.snap)
    for f in sp.frames.values():
        src = f.data.copy()
        for a, b in lut.items():
            f.data[src == a] = b
        f.palette = newp
    sp.palette = newp
    sp.extra.pop("_chars_by_index", None)
    _save_back(sp, args)


def cmd_ramp(args):
    idxs = None
    if args.palette:
        idxs = generate_ramp(args.base, args.steps, args.hue_shift, palette=args.palette)
        pal = Palette.load(args.palette)
        hexes = [pal.hex(i) for i in idxs]
    else:
        hexes = generate_ramp(args.base, args.steps, args.hue_shift)
    sw = ex.strip_image(hexes, args.out) if args.out else None
    if _v(args):
        if idxs is not None:
            print("indices:", " ".join(map(str, idxs)))
        print("ramp:", " ".join("#" + h for h in hexes))
        if sw:
            print("swatch:", sw)
        return
    print("ramp: " + " ".join("#" + h for h in hexes)
          + (" | indices: " + " ".join(map(str, idxs)) if idxs is not None else "")
          + (f" | swatch {sw}" if sw else ""))


def cmd_new(args):
    from . import new_project
    sp = new_project(args.project, args.name, args.size, args.palette, args.frames.split(","))
    print(f"created {sp.source}")


def cmd_info(args):
    sp = _sp(args)
    if not _v(args):
        an = sp.get_animations()
        print(f"{sp.name} {sp.w}x{sp.h}, palette {sp.palette.name} ({len(sp.palette)}), {len(sp.frames)} frames; "
              f"anims: " + (", ".join(f"{a} {len(v)}f (loop diff {sp.loop_check(a)}px)" for a, v in an.items())
                            or "none"))
        return
    print(f"name: {sp.name}\nsize: {sp.w}x{sp.h}\npalette: {sp.palette.name} ({len(sp.palette)} colors)")
    print(f"source: {sp.source or sp.extra.get('_script')}")
    print("frames:")
    for n, f in sp.frames.items():
        print(f"  {n:16s} {sp.durations.get(n)}ms  colors={len(f.colors_used())}  bbox={f.bbox()}")
    print("animations:")
    for a, names in sp.get_animations().items():
        print(f"  {a}: {', '.join(names)}  (loop diff {sp.loop_check(a)} px)")


def cmd_validate(args):
    sp = _sp(args)
    print(f"OK: {sp.name} {sp.w}x{sp.h}, {len(sp.frames)} frames, palette {sp.palette.name}")


def cmd_ascii(args):
    sp = _sp(args)
    print(sp.frame(_frame_key(args.frame) if args.frame else 0).ascii())


def cmd_render(args):
    sp = _sp(args)
    fn = _fname(sp, args.frame)
    p = ex.render(sp.frame(fn), _outpath(args, f"{sp.name}_{fn}.png"), scale=args.scale, bg=args.bg)
    print(p)


def cmd_sheet(args):
    sp = _sp(args)
    p, j = ex.sheet(sp, _outpath(args, f"{sp.name}_sheet.png"), scale=args.scale,
                    columns=args.columns, padding=args.padding)
    if _v(args):
        print(p)
        print(j)
    else:
        print(f"{p} {j}")


def cmd_unity_sheet(args):
    from .unity import unity_sheet
    split = lambda s: [t.strip() for t in s.split(",") if t.strip()] if s else None  # noqa: E731
    rep = unity_sheet(args.src, out_dir=args.out, cell=args.cell, padding=args.padding,
                      pivot=args.pivot, align=args.align, anchor=args.anchor, fps=args.fps,
                      no_loop=split(args.no_loop) or (), anims=split(args.anims),
                      preview_scale=args.preview_scale, ppu=args.ppu)
    if not _v(args):
        print(f"unity-sheet: {len(rep['strips'])} anim(s) -> atlas {rep['atlas']} | note {rep['note_path']}")
        return
    for a, p in rep["strips"].items():
        print(f"strip  {p}")
    print(f"atlas  {rep['atlas']}")
    print(f"json   {rep['json']}")
    if rep["previews"]:
        print(f"preview {Path(rep['previews']['atlas']).parent}")
    print(f"note   {rep['note_path']}\n")
    print(rep["note"])


def cmd_check(args):
    from .check import check
    atlas = False if args.no_atlas else args.atlas
    rep = check(args.src, atlas=atlas, out=args.out, palette=args.palette, write=not args.no_write,
                max_colors=args.max_colors, size_drift=args.size_drift, size_drift_fail=args.size_drift_fail,
                foot_drift=args.foot_drift, foot_drift_fail=args.foot_drift_fail,
                motion_min_px=args.motion_min_px, motion_min_ratio=args.motion_min_ratio,
                seam_factor=args.seam_factor, orphans_per_frame=args.orphans,
                orphan_connectivity=args.connectivity, game=args.game, game_root=args.root)
    if args.json:
        body = {k: v for k, v in rep.items() if k not in ("text", "checks", "paths")}
        print(json.dumps(body, indent=2, ensure_ascii=False))
    elif _v(args):
        print(rep["text"])
    else:
        from .check import short_text
        print(short_text(rep))
    if args.json or _v(args):
        for k, p in rep["paths"].items():
            print(f"{k:5s} {p}", file=sys.stderr if args.json else sys.stdout)
    return rep["exit_code"]


def cmd_gif(args):
    sp = _sp(args)
    tag = args.anim or "all"
    if args.apng:
        p, rep = ex.apng(sp, _outpath(args, f"{sp.name}_{tag}.png"), anim=args.anim, fps=args.fps,
                         scale=args.scale, bg=args.bg)
    else:
        p, rep = ex.gif(sp, _outpath(args, f"{sp.name}_{tag}.gif"), anim=args.anim, fps=args.fps,
                        scale=args.scale, bg=args.bg)
    if _v(args):
        print(p)
        print(json.dumps(rep))
    else:
        print(f"{p} " + json.dumps({k: rep[k] for k in ("verified", "frames") if k in rep}))


def cmd_contact(args):
    sp = ex.load_frames_source(args.src)
    if args.out:
        out = Path(args.out)
    else:
        from .layout import find_game
        src = Path(sp.source) if sp.source else None
        found = find_game(src) if src is not None and src.exists() else None
        if found and found[1] is not None:  # inside outputs/<Game>/<kind>/<Asset>/ -> its review/
            out = Path(found[1]) / "review" / f"{Path(sp.source).stem}_contact.png"
        else:
            out = _outpath(args, f"{sp.name}_contact.png")
    p = ex.contact_sheet(sp, out, scale=args.scale, columns=args.columns, max_width=args.max_width or None)
    print(p)


def cmd_inspect(args):
    sp = _sp(args)
    fn = _fname(sp, args.frame)
    if args.region is None and not args.full:
        raise PixelError("inspect needs a region: -r x,y,w,h (e.g. -r 8,4,12,10); --full = whole frame")
    r = args.region or (0, 0, sp.w, sp.h)
    p = ex.inspect(sp.frame(fn), _outpath(args, f"{sp.name}_{fn}_inspect_{r[0]}_{r[1]}_{r[2]}x{r[3]}.png"),
                   region=r, zoom=args.zoom, indices=args.indices)
    print(p)


def cmd_preview(args):
    sp = _sp(args)
    a = _fname(sp, args.a)
    b = _fname(sp, args.b)
    p = _outpath(args, f"{sp.name}_onion_{a}_{b}.png")
    ex.onion(sp, a, b, p, scale=args.scale)
    print(p)


def cmd_diff(args):
    sp = _sp(args)
    a = _fname(sp, args.a)
    b = args.b
    p = _outpath(args, f"{sp.name}_diff_{a}_{b}.png")
    n, pts = ex.diff(sp, a, _frame_key(b), p, scale=args.scale, other=args.other)
    if _v(args):
        print(p)
        print(f"{n} pixels differ" + (f": {pts[:40]}{' ...' if n > 40 else ''}" if n else ""))
    else:
        print(f"{p}: {n} pixels differ")


def cmd_quantize(args):
    cv = ex.quantize(args.input, args.palette, dither=args.dither, size=args.size, resample=args.resample)
    out = Path(args.out) if args.out else output_dir("misc") / f"{Path(args.input).stem}_q.png"
    cv.save(out, scale=args.scale)
    jp = None
    if args.json:
        sp = Sprite(cv.w, cv.h, cv.palette, name=Path(args.json).stem)
        sp.add_frame("frame1", cv)
        jp = sp.save(args.json)
    print(f"{out}" + (f" {jp}" if jp else ""))


def _write_report(path, rep):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rep, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    return p


def cmd_import(args):
    from .importer import import_image, import_text
    if not args.project and not args.out:
        raise PixelError("import: give --project NAME (-> projects/<project>/<name>.json) or -o path.json")
    atlas = "none" if args.no_atlas else args.atlas
    sp, rep = import_image(args.input, project=args.project, name=args.name, out=args.out, frame=args.frame,
                           cols=args.cols, rows=args.rows, margin=args.margin, spacing=args.spacing,
                           names=args.names, anim=args.anim, anim_rows=args.anim_rows, atlas=atlas,
                           palette=args.palette, alpha_threshold=args.alpha_threshold, dither=args.dither,
                           skip_empty=args.skip_empty, fps=args.fps, restore_offsets=args.restore_offsets,
                           canvas=args.canvas)
    if args.report:
        rep["report_path"] = str(_write_report(args.report, rep))
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    elif _v(args):
        print(import_text(rep))
        if args.report:
            print(f"report {rep['report_path']}")
    else:
        print(_import_line(rep) + (f" | report {rep['report_path']}" if args.report else ""))


def _import_line(rep):
    return (f"import: {rep['frame_count']} frames {rep['frame_size'][0]}x{rep['frame_size'][1]}, "
            f"{len(rep['animations'])} anim(s), palette {rep['palette']} ({rep['palette_colors']}), "
            + ("EXACT" if rep["exact"] else f"colours/alpha changed ({rep['remapped_total']} px remapped)")
            + (f", {len(rep['notes'])} note(s)" if rep["notes"] else "")
            + (f" -> {rep['path']}" if rep["path"] else ""))


def _offset_arg(s):
    try:
        a, b = (float(t) for t in s.split(","))
        return (int(a) if a.is_integer() else a, int(b) if b.is_integer() else b)
    except Exception:
        raise argparse.ArgumentTypeError(f"offset must be x,y, got {s!r}")


def _detect_line(det):
    off = det["offset"]
    return (f"block size: {det['size']} px, offset: x={off[0]} y={off[1]}"
            + (f", confidence {det['confidence']}" if det.get("confidence") is not None else ""))


def cmd_depixelize(args):
    from .importer import depixelize, detect_grid, detect_text, import_image, import_text
    report_only = args.report_only or args.cmd == "grid-detect"
    if report_only:
        det = detect_grid(args.input, args.min_size, args.max_size)
        if args.json_report:
            print(json.dumps(det, indent=2))
        elif _v(args):
            print(detect_text(det))
        else:
            print(_detect_line(det))
        return
    img, rep = depixelize(args.input, size=args.size, offset=args.offset, min_size=args.min_size,
                          max_size=args.max_size, sample=args.sample, palette=args.palette, colors=args.colors,
                          merge=args.merge, transparent=args.transparent, tolerance=args.tolerance,
                          alpha_threshold=args.alpha_threshold)
    out = Path(args.out) if args.out else output_dir("misc") / f"{Path(args.input).stem}_clean.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    rep["png"] = str(out)
    if args.scale and args.scale > 1:
        prev = out.with_name(out.stem + f"_x{args.scale}.png")
        img.resize((img.width * args.scale, img.height * args.scale), 0).save(prev)
        rep["preview"] = str(prev)
    if args.json_report:
        print(json.dumps(rep, indent=2, default=str))
    elif not _v(args):
        line = (f"{_detect_line(rep['detect'])} -> {rep['output_size'][0]}x{rep['output_size'][1]} px, "
                f"{rep['colors']} colours; png {out}" + (f" | preview {rep['preview']}" if rep.get("preview") else ""))
        if args.sprite or args.project:
            _, irep = import_image(out, project=args.project, name=args.name or Path(args.input).stem,
                                   out=args.sprite or None, palette=args.palette, atlas="none")
            line += " | sprite " + ("EXACT" if irep["exact"] else "changed") + f" -> {irep['path']}"
        print(line)
        return
    else:
        print(detect_text(rep["detect"]))
        q = rep["quantize"]
        print(f"output: {rep['output_size'][0]}x{rep['output_size'][1]} px, {rep['colors']} colours "
              f"({q['mode']}), opaque {rep['opaque']}" +
              (f", background #{rep['background']['color']} removed ({rep['background']['removed']} px)"
               if rep.get("background") else ""))
        print(f"png    {out}" + (f"\npreview {rep['preview']}" if rep.get("preview") else ""))
    if args.sprite or args.project:
        sp_out = args.sprite or None
        _, irep = import_image(out, project=args.project, name=args.name or Path(args.input).stem, out=sp_out,
                               palette=args.palette, atlas="none")
        print(import_text(irep) if not args.json_report else json.dumps(irep, indent=2, default=str))


def cmd_blueprint(args):
    from .blueprint import blueprint_text, save_blueprint
    sizes = args.size or ["32"]
    quiet = []
    for sz in (["16", "32", "48"] if args.all else sizes):
        bp, paths = save_blueprint(sz, args.style, out_dir=args.out, scale=args.scale, overlay=args.overlay,
                                   frame=_frame_key(args.frame))
        if args.json:
            print(json.dumps(bp, indent=2))
        elif _v(args):
            print(blueprint_text(bp))
        else:
            w, h = bp["size"]
            quiet.append(f"blueprint {bp['style']} {w}x{h}" + (" APPROXIMATE" if bp["approximate"] else "")
                         + f": {paths['png']}")
            continue
        for k, p in paths.items():
            print(f"{k:4s} {p}")
        print()
    if quiet:
        print(" | ".join(quiet) + " (table: .txt next to the png, or --verbose)")


def _apply_frames(sp, args, fn):
    targets = list(sp.frames) if args.frame in (None, "all") else [sp.frame(_frame_key(args.frame)).name]
    res = {}
    for t in targets:
        res[t] = fn(sp.frame(t))
    return res


def cmd_outline(args):
    sp = _sp(args)
    if not args.selective and args.color is None:
        raise PixelError("outline: give --color C or --selective")
    _apply_frames(sp, args, lambda cv: cv.outline(color=_color(args.color) if args.color is not None else None,
                                                  selective=args.selective, connectivity=args.connectivity,
                                                  steps=args.steps, inside=args.inside))
    _save_back(sp, args)


def cmd_shade(args):
    sp = _sp(args)
    ramp = [_color(c) for c in args.ramp.split(",")] if args.ramp else None
    region = args.region or (_color(args.mask_color) if args.mask_color is not None else None)
    _apply_frames(sp, args, lambda cv: cv.shade(region, ramp=ramp, light=args.light, depth=args.depth,
                                                shadow_depth=args.shadow_depth))
    _save_back(sp, args)


def cmd_clean(args):
    sp = _sp(args)
    res = _apply_frames(sp, args, lambda cv: cv.clean(remove=args.remove, connectivity=args.connectivity,
                                                      isolated_only=args.isolated_only))
    total = sum(len(o) for o in res.values())
    if _v(args):
        for fn, orph in res.items():
            print(f"{fn}: {len(orph)} orphan(s)" + (": " + ", ".join(
                f"({o['x']},{o['y']}){'*' if o['isolated'] else ''}" for o in orph) if orph else ""))
        print("(* = isolated, no opaque neighbour)")
    else:
        hit = [fn for fn, o in res.items() if o]
        print(f"{total} orphan(s) in {len(hit)}/{len(res)} frames" + (f": {', '.join(hit[:8])}" if hit else "")
              + (" (removed)" if args.remove and total else ""))
    if args.remove and total:
        if _v(args):
            _save_back(sp, args)
        else:
            target = getattr(args, "out", None) or (sp.source if sp.source and str(sp.source).endswith(".json")
                                                    else None)
            if not target:
                raise PixelError("source is a .py script; pass -o new.json to save the modified sprite")
            sp.save(target)


def cmd_frame(args):
    sp = _sp(args)
    act = args.action
    if act == "copy":
        sp.copy_frame(_fname(sp, args.a), args.b)
    elif act == "shift":
        sp.shift(_fname(sp, args.a), args.dx, args.dy, wrap=args.wrap)
    elif act == "flip-h":
        sp.flip_h(None if args.a == "all" else _fname(sp, args.a))
    elif act == "flip-v":
        sp.flip_v(None if args.a == "all" else _fname(sp, args.a))
    elif act == "mirror":
        sp.mirror(None if args.a == "all" else _fname(sp, args.a), args.direction)
    elif act == "recolor":
        mp = {}
        for pair in args.map.split(","):
            a, b = pair.split("=")
            mp[_color(a)] = _color(b)
        sp.recolor(mp, None if args.a == "all" else _fname(sp, args.a))
    elif act == "onion":
        p = _outpath(args, f"{sp.name}_onion_{args.a}_{args.b}.png")
        ex.onion(sp, _fname(sp, args.a), _fname(sp, args.b), p, scale=args.scale)
        print(p)
        return
    elif act == "loopcheck":
        anims = [args.anim] if args.anim else list(sp.get_animations())
        if _v(args):
            for a in anims:
                print(f"{a}: last->first diff = {sp.loop_check(a)} px")
        else:
            print("loop diff (last->first): " + ", ".join(f"{a}={sp.loop_check(a)}px" for a in anims))
        return
    elif act == "delete":
        sp.remove_frame(_fname(sp, args.a))
    _save_back(sp, args)


def cmd_export_json(args):
    sp = _sp(args)
    out = args.out or str(Path(resolve_source(args.src)).with_suffix(".json"))
    print(sp.save(out))


def _xy(s):
    try:
        a, b = (int(t) for t in s.split(","))
        return a, b
    except Exception:
        raise argparse.ArgumentTypeError(f"offset must be dx,dy integers, got {s!r}")


def _keys(s):
    """'1:0,0;4:0,-3:ease_out;6:0,0' -> [(1,(0,0)), (4,(0,-3),'ease_out'), (6,(0,0))]"""
    out = []
    try:
        for item in s.split(";"):
            bits = item.strip().split(":")
            k = (int(bits[0]), _xy(bits[1]))
            out.append(k + ((bits[2],) if len(bits) > 2 and bits[2] else ()))
    except Exception:
        raise argparse.ArgumentTypeError(f"keys must look like '1:0,0;4:0,-3:ease_out;6:0,0', got {s!r}")
    return out


def _print_notes(notes):
    for n in notes:
        print(f"note: {n}")


def cmd_templates(args):
    from . import anim
    lib = anim.load_templates(args.templates)
    if args.show:
        print(json.dumps(anim.get_template(args.show, lib), indent=2))
        return
    if not _v(args):
        items = []
        for n, t in lib["templates"].items():
            fr = "/".join(t["tables"]) if "tables" in t else t.get("frames")
            items.append(f"{n}({fr}f@{t.get('fps', 8):g}{'' if t.get('loop', True) else ' once'})")
        print("templates: " + ", ".join(items) + f" | {len(anim.EASINGS)} easings | --show NAME / --verbose")
        return
    for n, t in lib["templates"].items():
        fr = t.get("frames")
        if "tables" in t:
            fr = "/".join(t["tables"])
        print(f"{n:8s} frames={fr!s:5s} fps={t.get('fps', 8):<4g} loop={'on ' if t.get('loop', True) else 'off'}  "
              f"{t.get('description', '')}")
        for vn, v in t.get("views", {}).items():
            print(f"  --view {vn}: {v.get('description', '')}")
    print(f"easings: {', '.join(anim.EASINGS)}")
    print(f"roles: " + ", ".join(f"{r}={'/'.join(a)}" for r, a in lib.get("_roles", {}).items()))


def _role_overrides(s):
    if not s:
        return None
    out = {}
    for pair in s.split(","):
        if "=" not in pair:
            raise PixelError(f"--map expects role=part pairs, got {pair!r}")
        r, p = pair.split("=", 1)
        out[r.strip()] = p.strip()
    return out


def cmd_anim_apply(args):
    from . import anim
    d, rig, path = anim.load_rig_json(args.src)
    lib = anim.load_templates(args.templates)
    rep = anim.apply_template(rig, args.template, name=args.name, frames=args.frames, scale=args.scale,
                              fps=args.fps, loop=False if args.no_loop else None,
                              roles=_role_overrides(args.map), lib=lib, view=args.view)
    out = anim.save_rig_json(d, rig, args.out or path, [rep["name"]])
    if not _v(args):
        print(f"{rep['name']}: {rep['template']}, {rep['frames']}f@{rep['fps']:g}, loop "
              f"{'on' if rep['loop'] else 'off'}" + (f"; notes: {_short('; '.join(rep['notes']), 200)}"
                                                     if rep["notes"] else "") + f"; saved {out}")
        return
    print(f"{rep['name']}: template {rep['template']}, {rep['frames']} frames, {rep['fps']:g} fps, "
          f"loop={'on' if rep['loop'] else 'off'}, scale {rep['scale']:g}")
    print("parts: " + ", ".join(f"{r}->{p}" for r, p in rep["roles"].items()))
    _print_notes(rep["notes"])
    print(f"saved {out}")


def _region_sprite(args):
    sp = _sp(args)
    if "parts" in sp.extra:
        raise PixelError("source is a part rig: use --part (region mode would bake the rig into frames)")
    names = sp.frame_names(args.anim) if args.anim else list(sp.frames)
    s, e = args.start, args.end or len(names)
    if not 1 <= s <= e <= len(names):
        raise PixelError(f"--start/--end {s}..{e} outside 1..{len(names)}")
    return sp, names[s - 1:e]


def cmd_tween(args):
    from . import anim
    if not args.keys and (args.from_ is None or args.to is None):
        raise PixelError("tween: give --from dx,dy --to dx,dy, or --keys")
    if bool(args.part) == bool(args.region):
        raise PixelError("tween: give exactly one of --part (rig json) or --region x,y,w,h (frame sprite)")
    if args.part:
        if not args.anim:
            raise PixelError("tween --part needs --anim NAME")
        d, rig, path = anim.load_rig_json(args.src)
        if args.keys:
            anim.rig_keyframes(rig, args.anim, {args.part: args.keys}, args.ease, frames=args.frames, add=args.add)
        else:
            anim.rig_tween(rig, args.anim, args.part, args.from_, args.to, start=args.start, end=args.end,
                           easing=args.ease, frames=args.frames, add=args.add)
        a = rig.animations[args.anim]
        offs = [(f.get(args.part, {}).get("dx", 0), f.get(args.part, {}).get("dy", 0)) for f in a["frames"]]
        line = f"{args.anim}/{args.part}: " + " ".join(f"{x},{y}" for x, y in offs)
        saved = anim.save_rig_json(d, rig, args.out or path, [args.anim])
        print(f"{line}\nsaved {saved}" if _v(args) else f"{line}; saved {saved}")
        return
    sp, names = _region_sprite(args)
    offs = anim.tween_region(sp, args.region, args.from_, args.to, names, args.ease, keys=args.keys)
    if _v(args):
        print("region offsets: " + " ".join(f"{n}={x},{y}" for n, (x, y) in zip(names, offs)))
    _save_back(sp, args)


def cmd_oscillate(args):
    from . import anim
    if bool(args.part) == bool(args.region):
        raise PixelError("oscillate: give exactly one of --part (rig json) or --region x,y,w,h (frame sprite)")
    loop = not args.no_loop
    if args.part:
        if not args.anim:
            raise PixelError("oscillate --part needs --anim NAME")
        d, rig, path = anim.load_rig_json(args.src)
        warns = anim.rig_oscillate(rig, args.anim, args.part, args.amp, args.period, args.phase, args.axis,
                                   args.mode, frames=args.frames, add=not args.set, loop=loop)
        a = rig.animations[args.anim]
        k = "dx" if args.axis == "x" else "dy"
        line = f"{args.anim}/{args.part} {k}: " + " ".join(str(f.get(args.part, {}).get(k, 0)) for f in a["frames"])
        saved = anim.save_rig_json(d, rig, args.out or path, [args.anim])
        if _v(args):
            print(line)
            for w in warns:
                print(f"warning: {w}")
            print(f"saved {saved}")
        else:
            print(line + "".join(f"; warning: {_short(w, 120)}" for w in warns) + f"; saved {saved}")
        return
    sp, names = _region_sprite(args)
    offs, warns = anim.oscillate_region(sp, args.region, args.amp, args.period, names, args.phase, args.axis,
                                        args.mode, loop=loop)
    if _v(args):
        print("region offsets: " + " ".join(f"{n}={x},{y}" for n, (x, y) in zip(names, offs)))
    for w in warns:
        print(f"warning: {_short(w, 160)}")
    _save_back(sp, args)


# --------------------------------------------------------------------------- game layout / style guide
def cmd_game_new(args):
    from .style import game_new
    st, paths = game_new(args.name, mood=args.mood, temperature=args.temperature, saturation=args.saturation,
                         contrast=args.contrast, cell=args.cell, ppu=args.ppu, outline=args.outline, light=args.light,
                         shading=args.shading, dither=args.dither, max_colors=args.max_colors,
                         proportions=args.proportions, palette=args.palette, colors=args.colors, roles=args.roles,
                         description=args.description, root=args.root, force=args.force)
    print(f"game {st['name']}: {len(st['palette'])} colours from {st['palette_source']}, cell "
          f"{st['cell'][0]}x{st['cell'][1]}, PPU {st['ppu']}, outline {st['outline']}, light {st['light']}"
          + ("" if _v(args) else f" -> {Path(paths['game-style.md']).parent}"))
    if not _v(args):
        return
    for e in st["palette"]:
        print(f"  {e['index']:2d}  #{e['hex']}  {e['role']}")
    for k, p in paths.items():
        print(f"wrote {p}")


def cmd_game_style(args):
    from . import layout
    from .style import load_style, style_text, validate_style
    st = load_style(args.game, args.root)
    errs, warns = validate_style(st, layout.game_dir(st["name"], args.root))
    if args.json:
        print(json.dumps(st, indent=2, ensure_ascii=False))
        for e in errs:
            print(f"ERROR {e}", file=sys.stderr)
    elif _v(args):
        print(style_text(st, errs, warns))
    else:
        W, H = st["cell"]
        print(f"{st['name']} style: {'INVALID' if errs else 'OK'} ({len(st['palette'])} colours, cell {W}x{H}, "
              f"PPU {st['ppu']}, outline {st['outline']}, light {st['light']})"
              + (f"; {len(warns)} warning(s)" if warns else "")
              + "".join(f"; ERROR {_short(e, 100)}" for e in errs[:3]))
    return 1 if errs else 0


def cmd_game_palette_add(args):
    from .style import game_palette_add
    st, paths = game_palette_add(args.game, args.hex, args.role, root=args.root)
    e = st["palette"][-1]
    print(f"added #{e['hex']} as '{e['role']}' (index {e['index']}); {st['name']} palette now "
          f"{len(st['palette'])} colours")
    if _v(args):
        for p in paths.values():
            print(f"updated {p}")


def cmd_char_new(args):
    from .layout import char_new
    card, paths = char_new(args.game, args.name, role=args.role, design=args.design, cell=args.cell,
                           pivot=args.pivot, colors=args.colors, kind=args.kind, root=args.root, force=args.force)
    print(f"{card['kind']} {card['name']} ({card['game']}): cell {card['cell'][0]}x{card['cell'][1]}, "
          f"{len(card['colors'])} colours: " + ", ".join(c["role"] for c in card["colors"])
          + ("" if _v(args) else f" -> {paths['dir']}"))
    if _v(args):
        for k, p in paths.items():
            print(f"{k:10s} {p}")


def cmd_char_export(args):
    from .layout import char_export
    split = lambda s: [t.strip() for t in s.split(",") if t.strip()] if s else None  # noqa: E731
    rep = char_export(args.game, args.name, args.src, anims=split(args.anims), fps=args.fps,
                      no_loop=split(args.no_loop) or (), preview_scale=args.preview_scale, kind=args.kind,
                      root=args.root)
    if not _v(args):
        print(f"exported {rep['character']} ({rep['game']}): "
              + ", ".join(f"{a} {v['frames']}f@{v['fps']:g}" for a, v in rep["animations"].items())
              + f" -> atlas {rep['atlas']}"
              + (f"; archived previous version ({len(rep['archived'])})" if rep["archived"] else "")
              + "".join(f"; warning: {_short(w, 100)}" for w in rep["warnings"]))
        return
    print(f"{rep['character']} ({rep['game']}) from {rep['source']}, cell {rep['cell'][0]}x{rep['cell'][1]}")
    for a, v in rep["animations"].items():
        print(f"  {a}: {v['frames']} frames, {v['fps']:g} fps, loop {'on' if v['loop'] else 'off'}")
        for k in ("sheet", "json", "gif", "note"):
            print(f"    {v[k]}")
    print(f"atlas  {rep['atlas']}  (rows: {', '.join(rep['atlas_rows'])})")
    print(f"json   {rep['atlas_json']}")
    for p in rep["archived"]:
        print(f"archived previous version -> {p}")
    for w in rep["warnings"]:
        print(f"warning: {w}")
    print(f"card   {rep['card']}")
    print(f"index  {rep['index']}")


def cmd_build(args):
    from .build import build, build_lines
    split = lambda s: [t.strip() for t in s.split(",") if t.strip()] if s else ()  # noqa: E731
    rep = build(args.game, args.character, args.animation, mode="draft" if args.draft else "final", src=args.src,
                fps=args.fps, no_loop=split(args.no_loop), preview_scale=args.preview_scale, kind=args.kind,
                root=args.root, verbose=_v(args))
    if args.json:
        body = {k: v for k, v in rep.items() if k not in ("check_text", "export")}
        print(json.dumps(body, indent=2, ensure_ascii=False, default=str))
    elif _v(args):
        print(rep["check_text"])
        print()
        for k, v in rep["paths"].items():
            for p in (v if isinstance(v, list) else [v]):
                print(f"{k:10s} {p}")
        for p in rep.get("export", {}).get("archived", []):
            print(f"archived   {p}")
        for w in rep.get("export", {}).get("warnings", []):
            print(f"warning: {w}")
        print("\n".join(build_lines(rep)[:1]))
    else:
        print("\n".join(build_lines(rep)))
    return rep["exit_code"]


def cmd_context(args):
    from .build import context
    try:
        lines = context(args.game, args.character, root=args.root, kind=args.kind)
    except PixelError as e:
        print(str(e).splitlines()[0])
        return 1
    print("\n".join(lines))
    return 0


def cmd_outputs_index(args):
    from .layout import write_index
    print(write_index(args.root))


def cmd_run(args):
    path = resolve_source(args.script)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    sys.argv = [str(path)] + args.rest
    runpy.run_path(str(path), run_name="__main__")


# --------------------------------------------------------------------------- parser
def build_parser():
    P = argparse.ArgumentParser(prog="spritewright", description="Scriptable pixel-art toolkit for AI agents: "
                                "every command writes files (PNG, sheets + JSON, GIF, Unity atlas). SRC = sprite "
                                ".json/.py path or project-relative name (e.g. examples/sprites/hero.py).")
    P.add_argument("--version", action="version", version=f"spritewright {__version__}")
    sub = P.add_subparsers(dest="cmd", required=True, metavar="<command>")

    def add(name, fn, help, src=True, out=True):
        p = sub.add_parser(name, help=help, description=help)
        if src:
            p.add_argument("src", help="sprite source (.json grid / .py script / projects-relative)")
        if out:
            p.add_argument("-o", "--out", help="output path (default: output/<project>/...)")
        p.add_argument("--verbose", action="store_true", help="full output (lists, reports, logs); default: one line")
        p.set_defaults(fn=fn)
        return p

    add("palettes", cmd_palettes, "list available palettes (bundled + palette folders)", src=False, out=False)
    p = add("palette-show", cmd_palette_show, "print a palette (and optional swatch PNG)", src=False)
    p.add_argument("palette", help="palette name or .hex/.json path")
    p = add("palette-create", cmd_palette_create, "create a custom palette (.json/.hex) from colors", src=False, out=False)
    p.add_argument("out", help="output file (.json keeps names); relative -> projects/")
    p.add_argument("colors", nargs="+", help="name=RRGGBB or RRGGBB")
    p.add_argument("--name", help="palette name stored in the file")
    p.add_argument("--base", help="base palette (for --extend / --snap)")
    p.add_argument("--extend", action="store_true", help="append colors to the base palette")
    p.add_argument("--snap", action="store_true", help="snap given colors to nearest base color")
    p = add("attach-palette", cmd_attach_palette, "switch a sprite to another palette (remap colors)")
    p.add_argument("palette", help="palette name or .hex/.json path")
    p.add_argument("--snap", action="store_true", help="snap colors not in the new palette to nearest")
    p.add_argument("--copy-to-project", action="store_true", help="store palette json next to the sprite")
    p = add("ramp", cmd_ramp, "generate a hue-shifted color ramp", src=False)
    p.add_argument("base", help="base color hex")
    p.add_argument("--steps", type=int, default=5, help="number of colours (default 5)")
    p.add_argument("--hue-shift", type=float, default=14.0, help="hue shift in degrees across the ramp")
    p.add_argument("--palette", help="snap ramp to this palette")
    p = add("new", cmd_new, "create a new project sprite (blank grid json + notes.md)", src=False, out=False)
    p.add_argument("project", help="project folder under projects/")
    p.add_argument("name", help="sprite name (file stem)")
    p.add_argument("--size", type=_size, default=(32, 32), help="WxH (default 32x32)")
    p.add_argument("--palette", default="pico-8", help="palette name or path (default pico-8)")
    p.add_argument("--frames", default="idle1", help="comma list of frame names (default idle1)")
    add("info", cmd_info, "show sprite info (frames, animations, loop diffs)", out=False)
    add("validate", cmd_validate, "parse a sprite and report errors precisely", out=False)
    p = add("ascii", cmd_ascii, "print a frame as a text grid with legend", out=False)
    p.add_argument("-f", "--frame", help="frame name or 1-based index (default: first frame)")
    p = add("render", cmd_render, "render one frame to PNG")
    p.add_argument("-f", "--frame", help="frame name or 1-based index (default: first frame)")
    p.add_argument("-s", "--scale", type=int, default=8, help="integer upscale factor (default 8)")
    p.add_argument("--bg", help="background hex or 'checker' (default transparent)")
    p = add("sheet", cmd_sheet, "sprite sheet PNG + JSON (Aseprite/Godot/Unity friendly)")
    p.add_argument("-s", "--scale", type=int, default=1, help="integer upscale factor (default 1)")
    p.add_argument("--columns", type=int, help="frames per row (default: up to 8)")
    p.add_argument("--padding", type=int, default=0, help="transparent px between frames (default 0)")
    p = add("unity-sheet", cmd_unity_sheet, "Unity sheet: fixed cells, foot-pivot aligned strips + atlas "
            "+ atlas.json + preview/ + UNITY_IMPORT.txt (-o = output folder, default output/<project>/)")
    p.add_argument("--cell", help="fixed cell WxH (default: auto from content + padding)")
    p.add_argument("--padding", type=int, help="auto-cell padding around content (default 1)")
    p.add_argument("--pivot", help="bottom-center | center | auto | x,y (sprite pixel of the foot)")
    p.add_argument("--align", choices=["fixed", "auto"],
                   help="fixed: one pivot for all frames (keeps bob/jump, default); auto: per-frame foot")
    p.add_argument("--anchor", help="x,y cell pixel receiving the pivot (needs --cell; default bottom-center)")
    p.add_argument("--fps", type=float, help="fps for animations without fps in the source")
    p.add_argument("--no-loop", help="comma list of animations exported with loop=false (e.g. death)")
    p.add_argument("--anims", help="comma list: export only these animations, in this row order")
    p.add_argument("--preview-scale", type=int, default=4, help="preview/ scale (0 = no previews)")
    p.add_argument("--ppu", type=int, help="Pixels Per Unit to recommend (default: rule from cell height)")
    p = add("check", cmd_check, "quality report PASS/WARN/FAIL for a sprite source and/or a Unity atlas "
            "(atlas.json / atlas.png / folder); exit code 1 on any FAIL. -o = report .json path or folder")
    p.add_argument("--atlas", help="atlas to check with the source (default: output/<project>/atlas.json if it "
                   "was made from this source)")
    p.add_argument("--no-atlas", action="store_true", help="check only the source frames")
    p.add_argument("--palette", help="palette for atlas-only checks (default: atlas meta.source)")
    p.add_argument("--max-colors", type=int, help="max distinct colours per PNG/sprite (default 16) -> WARN")
    p.add_argument("--size-drift", type=int, help="bbox w/h change px -> WARN above (default 2)")
    p.add_argument("--size-drift-fail", type=int, help="bbox w/h change px -> FAIL above (default 6)")
    p.add_argument("--foot-drift", type=int, help="foot vs pivot px -> WARN above (default 1)")
    p.add_argument("--foot-drift-fail", type=int, help="foot vs pivot px -> FAIL above (default 4)")
    p.add_argument("--motion-min-px", type=int, help="min px difference between frames (default 2)")
    p.add_argument("--motion-min-ratio", type=float, help="min difference as share of opaque px (default 0.01)")
    p.add_argument("--seam-factor", type=float, help="loop seam > factor x median step -> WARN (default 2)")
    p.add_argument("--orphans", type=int, help="orphan pixels per frame -> WARN above (default 3)")
    p.add_argument("--connectivity", type=int, choices=[4, 8], help="orphan connectivity (default 4, as clean)")
    p.add_argument("--json", action="store_true", help="print the JSON report instead of the text summary")
    p.add_argument("--no-write", action="store_true", help="do not save check .json/.txt files")
    p.add_argument("--game", help="also check game-style compliance against outputs/<Game>/game-style.json "
                   "(auto when the path is inside outputs/<Game>/)")
    p.add_argument("--root", help="outputs root for --game (default ./outputs or env SPRITEWRIGHT_OUTPUTS)")
    p = add("gif", cmd_gif, "animated GIF (or --apng)")
    p.add_argument("-a", "--anim", help="animation to export (default: all frames in order)")
    p.add_argument("--fps", type=float, help="frames per second (default: the frame durations)")
    p.add_argument("-s", "--scale", type=int, default=8, help="integer upscale factor (default 8)")
    p.add_argument("--bg", help="solid background color (default transparent)")
    p.add_argument("--apng", action="store_true", help="write an animated PNG instead of a GIF")
    p = add("contact", cmd_contact, "contact sheet of all frames in ONE image, numbered (sprite source, or "
            "exported atlas/sheet .json/.png); scale auto-reduced to keep width <= --max-width")
    p.add_argument("-s", "--scale", type=int, default=4, help="default 4 (reduced automatically if too wide)")
    p.add_argument("--columns", type=int, help="frames per row (default: automatic)")
    p.add_argument("--max-width", type=int, default=1024, help="max image width in px (default 1024, 0 = no limit)")
    p = add("inspect", cmd_inspect, "magnified region with grid + coordinates (region required: -r x,y,w,h)")
    p.add_argument("-f", "--frame", help="frame name or 1-based index (default: first frame)")
    p.add_argument("-r", "--region", type=_region, help="x,y,w,h (required unless --full)")
    p.add_argument("--full", action="store_true", help="whole frame (the old default)")
    p.add_argument("-z", "--zoom", type=int, default=24, help="screen px per sprite pixel (default 24)")
    p.add_argument("--indices", action="store_true", help="print palette index in each cell")
    p = add("preview", cmd_preview, "onion-skin preview of two frames")
    p.add_argument("a", help="first frame (name or 1-based index)")
    p.add_argument("b", help="second frame (name or 1-based index)")
    p.add_argument("-s", "--scale", type=int, default=8, help="integer upscale factor (default 8)")
    p = add("diff", cmd_diff, "highlight changed pixels between two frames in red")
    p.add_argument("a", help="first frame (name or 1-based index)")
    p.add_argument("b", help="second frame (name or 1-based index)")
    p.add_argument("--other", help="take frame b from another sprite source")
    p.add_argument("-s", "--scale", type=int, default=8, help="integer upscale factor (default 8)")
    p = add("quantize", cmd_quantize, "convert a PNG to a palette (optional downscale/dither)", src=False)
    p.add_argument("input", help="input image (PNG/JPEG/...)")
    p.add_argument("--palette", required=True, help="target palette name or .hex/.json path")
    p.add_argument("--dither", default="none", choices=["none", "bayer4", "floyd"], help="dithering (default none)")
    p.add_argument("--size", type=_size, help="downscale to WxH before quantizing")
    p.add_argument("--resample", default="box", choices=["box", "nearest", "lanczos"],
                   help="downscale filter (default box)")
    p.add_argument("-s", "--scale", type=int, default=1, help="integer upscale of the output PNG (default 1)")
    p.add_argument("--json", help="also save as grid sprite json")
    p = add("import", cmd_import, "import a PNG / sprite sheet / Unity atlas back into a grid JSON sprite "
            "(atlas.json next to the PNG is read automatically; -o = sprite .json path)", src=False)
    p.add_argument("input", help="PNG (sheet, strip, single frame or atlas.png)")
    p.add_argument("--project", help="write projects/<project>/<name>.json")
    p.add_argument("--name", help="sprite name / file stem (default: PNG stem)")
    p.add_argument("--frame", help="frame size WxH (grid slicing)")
    p.add_argument("--cols", type=int, help="columns (frame size derived when --frame is not given)")
    p.add_argument("--rows", type=int, help="rows")
    p.add_argument("--margin", type=int, default=0, help="border around the sheet in px")
    p.add_argument("--spacing", type=int, default=0, help="gap between cells in px")
    p.add_argument("--names", help="comma list of frame names (row-major)")
    p.add_argument("--anim", help="name all frames <anim>1..N as one animation")
    p.add_argument("--anim-rows", help="one animation per row, e.g. 'idle:4,walk:6' (count optional)")
    p.add_argument("--atlas", help="atlas.json to use (default: <png>.json / atlas.json next to the PNG)")
    p.add_argument("--no-atlas", action="store_true", help="ignore any atlas.json")
    p.add_argument("--palette", help="palette name/.hex/.json or a sprite source whose palette to use "
                   "(default: atlas source sprite, else exact image colours <= 64)")
    p.add_argument("--alpha-threshold", type=int, default=128, help="alpha >= this -> opaque (default 128)")
    p.add_argument("--dither", default="none", choices=["none", "bayer4", "floyd"],
                   help="dithering when remapping off-palette colours (default none)")
    p.add_argument("--skip-empty", action="store_true", help="drop fully transparent cells")
    p.add_argument("--fps", type=float, help="set all frame durations to 1000/fps")
    p.add_argument("--restore-offsets", action="store_true", help="atlas: shift cells back by their offsets "
                   "into the original canvas (source sprite size or --canvas)")
    p.add_argument("--canvas", help="canvas WxH for --restore-offsets")
    p.add_argument("--report", help="write the full JSON report here")
    p.add_argument("--json", action="store_true", help="print the JSON report")
    for nm in ("depixelize", "grid-detect"):
        hlp = ("clean up fake / upscaled pixel art: detect the block grid, 1 block -> 1 pixel, optional "
               "palette / K colours, PNG (+ sprite json)") if nm == "depixelize" else \
            "detect block size / offset / confidence of upscaled pixel art (report only)"
        p = add(nm, cmd_depixelize, hlp, src=False)
        p.add_argument("input", help="image (PNG/JPEG/...)")
        p.add_argument("--min-size", type=float, default=2, help="smallest block size to test (default 2)")
        p.add_argument("--max-size", type=float, default=32, help="largest block size to test (default 32)")
        p.add_argument("--json-report", action="store_true", help="print the JSON report")
        if nm == "grid-detect":
            p.set_defaults(report_only=True)
            continue
        p.add_argument("--report-only", action="store_true", help="only print detected size/offset/confidence")
        p.add_argument("--size", type=float, help="force the block size (skip detection)")
        p.add_argument("--offset", type=_offset_arg, help="force the grid offset x,y")
        p.add_argument("--sample", default="median", choices=["median", "center"],
                       help="block colour: median of the block interior or the centre pixel (default median)")
        p.add_argument("--palette", help="snap colours to this palette (name/.hex/.json/sprite)")
        p.add_argument("--colors", type=int, help="reduce to K colours (k-means)")
        p.add_argument("--merge", type=float, default=8.0, help="merge colours closer than this dE (0 = off)")
        p.add_argument("--transparent", default="none", help="none | auto (border colour) | RRGGBB -> transparent")
        p.add_argument("--tolerance", type=float, default=12.0, help="dE tolerance for --transparent")
        p.add_argument("--alpha-threshold", type=int, default=128, help="alpha >= this -> opaque (default 128)")
        p.add_argument("-s", "--scale", type=int, default=0, help="also write a nearest-scaled preview")
        p.add_argument("--sprite", help="also import the result as grid json (path)")
        p.add_argument("--project", help="also import into projects/<project>/<name>.json")
        p.add_argument("--name", help="sprite name for --project")
    p = add("blueprint", cmd_blueprint, "character proportion guide (16/32/48 chibi/normal; other sizes scaled, "
            "approximate): table + JSON + PNG (-o = folder, default output/blueprints/)", src=False)
    p.add_argument("--size", action="append", help="N or WxH (repeatable; default 32)")
    p.add_argument("--all", action="store_true", help="16, 32 and 48")
    p.add_argument("--style", default="chibi", help="chibi | normal")
    p.add_argument("-s", "--scale", type=int, help="PNG scale (default ~512 px wide grid)")
    p.add_argument("--overlay", help="sprite source drawn faintly under the guide (same size)")
    p.add_argument("-f", "--frame", help="overlay frame")
    p.add_argument("--json", action="store_true", help="print JSON instead of the table")
    p = add("outline", cmd_outline, "auto-outline frames (writes back to source unless -o)")
    p.add_argument("-f", "--frame", help="frame name/index or 'all' (default all)")
    p.add_argument("--color", help="outline colour (index, role name or in-palette hex)")
    p.add_argument("--selective", action="store_true", help="selective outline: a darker shade of the adjacent colour")
    p.add_argument("--connectivity", type=int, default=8, choices=[4, 8],
                   help="8 includes diagonal corners, 4 does not (default 8)")
    p.add_argument("--steps", type=int, default=1, help="selective: palette steps darker (default 1)")
    p.add_argument("--inside", action="store_true", help="recolor the shape's own edge instead of growing outward")
    p = add("shade", cmd_shade, "shade-assist: light from a side using a ramp")
    p.add_argument("-f", "--frame", help="frame name/index or 'all' (default all)")
    p.add_argument("--mask-color", help="shade pixels of this color (default all opaque)")
    p.add_argument("-r", "--region", type=_region, help="x,y,w,h region to shade (default all opaque)")
    p.add_argument("--ramp", help="comma list dark->light")
    p.add_argument("--light", default="top-left", help="light direction, e.g. top-left, top, right (default top-left)")
    p.add_argument("--depth", type=int, default=1, help="lit band width in px (default 1)")
    p.add_argument("--shadow-depth", type=int, help="shadow band width in px (default: --depth)")
    p = add("clean", cmd_clean, "report orphan pixels (optionally --remove)")
    p.add_argument("-f", "--frame", help="frame name/index or 'all' (default all)")
    p.add_argument("--remove", action="store_true", help="remove them (isolated -> transparent, others -> "
                   "most common neighbour colour)")
    p.add_argument("--isolated-only", action="store_true", help="only pixels with no opaque neighbour at all")
    p.add_argument("--connectivity", type=int, default=4, choices=[4, 8], help="neighbourhood (default 4)")
    p = add("frame", cmd_frame, "frame tools: copy, shift, flip-h, flip-v, mirror, recolor, onion, loopcheck, delete")
    p.add_argument("action", choices=["copy", "shift", "flip-h", "flip-v", "mirror", "recolor", "onion",
                                      "loopcheck", "delete"], help="frame operation")
    p.add_argument("a", nargs="?", help="frame (or source frame / 'all')")
    p.add_argument("b", nargs="?", help="second frame (copy dst, onion)")
    p.add_argument("--dx", type=int, default=0, help="shift: x offset in px (negative: --dx=-1)")
    p.add_argument("--dy", type=int, default=0, help="shift: y offset in px (negative: --dy=-1)")
    p.add_argument("--wrap", action="store_true", help="shift: wrap pixels around the edges")
    p.add_argument("--direction", default="lr", choices=["lr", "rl", "tb", "bt"],
                   help="mirror: copy left->right, right->left, top->bottom or bottom->top (default lr)")
    p.add_argument("--map", help="recolor map a=b,c=d")
    p.add_argument("--anim", help="loopcheck: animation to check")
    p.add_argument("-s", "--scale", type=int, default=8, help="onion: integer upscale factor (default 8)")
    p = add("templates", cmd_templates, "list animation templates (idle, walk, run, jump, attack, hurt, death)",
            src=False, out=False)
    p.add_argument("--show", help="print one template's data as JSON")
    p.add_argument("--templates", help="template JSON file (default: the bundled anim_templates.json)")
    p = add("anim-apply", cmd_anim_apply, "generate a rig animation from a template into a rig .json "
            "(writes back to the source unless -o)")
    p.add_argument("template", help="template name (see: spritewright templates)")
    p.add_argument("--frames", type=int, help="frame count (default: template's; walk has 6 and 8 tables)")
    p.add_argument("--name", help="animation name (default: template name)")
    p.add_argument("--scale", type=float, default=1.0, help="multiply all pixel offsets (rounded half away from 0)")
    p.add_argument("--fps", type=float, help="override template fps")
    p.add_argument("--no-loop", action="store_true", help="force loop=false")
    p.add_argument("--map", help="role=part overrides, e.g. head=eyes,weapon=staff")
    p.add_argument("--view", help="template view, e.g. front (walk/run for front-facing characters)")
    p.add_argument("--templates", help="template JSON file")
    for nm, fn, hlp in (("tween", cmd_tween, "tween a rig part (--part) or a frame region (--region) between "
                         "offsets with easing; integer pixels"),
                        ("oscillate", cmd_oscillate, "sine motion (breathing/floating/bounce) of a rig part or "
                         "frame region; integer pixels")):
        p = add(nm, fn, hlp + " (writes back to the source unless -o)")
        p.add_argument("--anim", help="animation (rig: created with --frames if missing; sprite: frames to use)")
        p.add_argument("--part", help="rig part name")
        p.add_argument("-r", "--region", type=_region, help="x,y,w,h region in frame sprites")
        p.add_argument("--frames", type=int, help="rig: animation frame count (create/extend)")
        if nm == "tween":
            p.add_argument("--from", dest="from_", type=_xy, help="start offset dx,dy")
            p.add_argument("--to", type=_xy, help="end offset dx,dy")
            p.add_argument("--keys", type=_keys, help="keyframes 'frame:dx,dy[:easing];...' (1-based)")
            p.add_argument("--start", type=int, default=1, help="first frame (1-based)")
            p.add_argument("--end", type=int, help="last frame (default: last)")
            p.add_argument("--ease", default="linear", help="linear, ease_in, ease_out, ease_in_out, smoothstep, "
                           "ease_out_back, bounce")
            p.add_argument("--add", action="store_true", help="rig: add to existing offsets instead of replacing")
        else:
            p.add_argument("--amp", type=float, required=True, help="amplitude in px")
            p.add_argument("--period", type=float, required=True, help="period in frames (should divide frame count)")
            p.add_argument("--phase", type=float, default=0.0, help="phase as fraction of the period")
            p.add_argument("--axis", default="y", choices=["x", "y"], help="motion axis (default y)")
            p.add_argument("--mode", default="sine", choices=["sine", "abs", "pos"], help="abs = bounce |sin|")
            p.add_argument("--no-loop", action="store_true", help="no seamless-loop warning")
            p.add_argument("--set", action="store_true", help="rig: replace offsets on that axis instead of adding")
            p.set_defaults(start=1, end=None)
    # ---- game layout / style guide (outputs/<Game>/...)
    root_help = "outputs root (default ./outputs, or env SPRITEWRIGHT_OUTPUTS)"
    p = add("game-new", cmd_game_new, "create outputs/<Game>/ style guide: game-style.md/.json, palette.hex, "
            "palette_preview.png", src=False, out=False)
    p.add_argument("name", help="game name ('aurora quest' -> Aurora_Quest)")
    p.add_argument("--mood", default="", help="comma list of mood keywords, e.g. cozy,retro")
    p.add_argument("--temperature", default="neutral", help="warm | cool | neutral")
    p.add_argument("--saturation", default="medium", help="low | medium | high")
    p.add_argument("--contrast", default="medium", help="low | medium | high")
    p.add_argument("--cell", default="32x32", help="cell size WxH for every sprite (default 32x32)")
    p.add_argument("--ppu", type=int, help="Pixels Per Unit (default: rule from cell height)")
    p.add_argument("--outline", default="selective", help="selective | black | none")
    p.add_argument("--light", default="top-left", help="top-left | top | top-right | left | right | ... | front")
    p.add_argument("--shading", type=int, default=2, help="shading layers per material 1..4 (default 2)")
    p.add_argument("--dither", default="none", help="none | limited | yes")
    p.add_argument("--max-colors", type=int, default=16, help="max colours per sprite (default 16)")
    p.add_argument("--proportions", default="chibi", help="chibi | normal")
    p.add_argument("--palette", default="pico-8", help="base palette name / .hex / .json (default pico-8)")
    p.add_argument("--colors", type=int, help="pick N (8-32) colours of the base palette (default all, max 32)")
    p.add_argument("--roles", help="role overrides: JSON file or '3=skin,#ffec27=gold'")
    p.add_argument("--description", help="one-paragraph description (default: generated)")
    p.add_argument("--force", action="store_true", help="overwrite an existing style guide (only on request)")
    p.add_argument("--root", help=root_help)
    p = add("game-style", cmd_game_style, "print + validate a game's style guide (exit 1 if invalid)",
            src=False, out=False)
    p.add_argument("game", help="game name (folder under outputs/)")
    p.add_argument("--json", action="store_true", help="print game-style.json")
    p.add_argument("--root", help=root_help)
    p = add("game-palette-add", cmd_game_palette_add, "add ONE user-approved colour with a role to the game "
            "palette (updates hex/json/md/preview)", src=False, out=False)
    p.add_argument("game", help="game name (folder under outputs/)")
    p.add_argument("hex", help="RRGGBB")
    p.add_argument("--role", required=True, help="unique role, e.g. lava")
    p.add_argument("--root", help=root_help)
    p = add("char-new", cmd_char_new, "create a character card outputs/<Game>/characters/<Char>/character.md "
            "(+ .json, source/<Char>_palette.json)", src=False, out=False)
    p.add_argument("game", help="game name (folder under outputs/)")
    p.add_argument("name", help="character name ('erica' -> Erica)")
    p.add_argument("--role", default="", help="character role, e.g. 'player, healer'")
    p.add_argument("--design", default="", help="short design note")
    p.add_argument("--cell", help="cell override WxH (default: game cell)")
    p.add_argument("--pivot", help="x,y sprite pixel | bottom-center | center (default: union bottom-center)")
    p.add_argument("--colors", help="comma list of game palette roles / indices / hex (default: whole palette)")
    p.add_argument("--kind", default="character", choices=["character", "prop", "tile"],
                   help="characters/ (default), props/ or tiles/")
    p.add_argument("--force", action="store_true", help="rewrite an existing card (keeps animations/log)")
    p.add_argument("--root", help=root_help)
    p = add("char-export", cmd_char_export, "export a character source into animations/<Anim>/ (sheet png/json, "
            "preview gif, unity-import-note.md), all-animations atlas, archive old versions, update card + "
            "outputs/README.md", src=False, out=False)
    p.add_argument("game", help="game name (folder under outputs/)")
    p.add_argument("name", help="character name")
    p.add_argument("src", help="sprite source (.py / rig json / grid json; relative -> the character's source/)")
    p.add_argument("--anims", help="comma list, e.g. Idle,Walk (default: all animations of the source)")
    p.add_argument("--fps", type=float, help="fps for animations without fps in the source")
    p.add_argument("--no-loop", help="comma list of animations exported with loop=false")
    p.add_argument("--preview-scale", type=int, default=4, help="GIF preview scale (default 4)")
    p.add_argument("--kind", default="character", choices=["character", "prop", "tile"],
                   help="characters/ (default), props/ or tiles/")
    p.add_argument("--root", help=root_help)
    p = add("build", cmd_build, "ONE call: run source/make_*.py, render, check (incl. game style), sheets; "
            "--final (default) also GIFs, unity notes, atlas, archive, card, README + review/<Anim>_contact.png; "
            "--draft only review/draft sheets + check. <= 5 lines; exit 1 on FAIL", src=False, out=False)
    p.add_argument("game", help="game name (folder under outputs/)")
    p.add_argument("character", help="character name")
    p.add_argument("animation", nargs="?", default="all", help="animation name or 'all' (default)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--draft", action="store_true", help="check + per-animation sheet only (review/draft/)")
    g.add_argument("--final", action="store_true", help="full delivery (default)")
    p.add_argument("--src", help="source file (default: auto from the character's source/)")
    p.add_argument("--fps", type=float, help="fps for animations without fps in the source")
    p.add_argument("--no-loop", help="comma list of animations exported with loop=false")
    p.add_argument("--preview-scale", type=int, default=4, help="GIF preview scale (final)")
    p.add_argument("--kind", default="character", choices=["character", "prop", "tile"],
                   help="characters/ (default), props/ or tiles/")
    p.add_argument("--json", action="store_true", help="machine-readable report")
    p.add_argument("--root", help=root_help)
    p = add("context", cmd_context, "compact style + character summary (<= 15 lines) to draw from; one line "
            "and exit 1 if the game/character is missing", src=False, out=False)
    p.add_argument("game", help="game name (folder under outputs/)")
    p.add_argument("character", nargs="?", help="character name (omit for the game summary only)")
    p.add_argument("--kind", default="character", choices=["character", "prop", "tile"],
                   help="characters/ (default), props/ or tiles/")
    p.add_argument("--root", help=root_help)
    p = add("outputs-index", cmd_outputs_index, "regenerate outputs/README.md (games, characters, animations)",
            src=False, out=False)
    p.add_argument("--root", help=root_help)
    p = add("export-json", cmd_export_json, "save any source (e.g. .py) as a grid .json")
    p = add("run", cmd_run, "run a .py drawing script with spritewright importable", src=False, out=False)
    p.add_argument("script", help="drawing script (.py)")
    p.add_argument("rest", nargs=argparse.REMAINDER, help="arguments passed to the script")
    p = add("install-skill", cmd_install_skill, "install the Claude Code skill (SKILL.md + reference/) into "
            "~/.claude/skills/spritewright/", src=False, out=False)
    p.add_argument("--target", help="skills root (default ~/.claude/skills); files go to <target>/spritewright/")
    p.add_argument("--dry-run", action="store_true", help="only print what would be written")
    p.add_argument("--uninstall", action="store_true", help="remove the installed skill folder")
    p.add_argument("--command", help="command line the skill uses to call the tool (default: the installed "
                   "'spritewright' entry point, else python + spritewright.py of this checkout)")
    return P


def cmd_install_skill(args):
    from .skill import install
    lines = install(target=args.target, dry_run=args.dry_run, uninstall=args.uninstall, command=args.command)
    print("\n".join(lines if (_v(args) or args.dry_run) else lines[-1:]))


def _utf8_console():
    """Print UTF-8 on any Windows console code page or pipe (no PYTHONIOENCODING needed). Harmless
    where reconfigure is unavailable (e.g. replaced streams)."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # pragma: no cover
            pass


def main(argv=None):
    _utf8_console()
    P = build_parser()
    args = P.parse_args(argv)
    try:
        rc = args.fn(args)
    except PixelError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return rc if isinstance(rc, int) else 0
