"""One-call pipeline + compact context for an AI driver (token-efficient).

    rep = ps.build("Test_Game", "Test_Hero", "all")              # --final (default)
    rep = ps.build("Test_Game", "Test_Hero", "Walk", mode="draft")
    lines = ps.context("Test_Game", "Test_Hero")                  # <= 15 short lines

build(game, character, animation|all, mode):
  1. source: every characters/<C>/source/make_*.py is run first (its stdout is captured), then the
     source is picked: --src, else the file named in the card's animations[*].source, else
     <x>.json for make_<x>.py, else the only rig/grid .json (not *_palette.json), else the only .py.
  2. final (default) = char-export (sheets, GIFs, unity-import-note.md, all-animations atlas,
     archive of the previous version, card + outputs/README.md) + check (source + atlas + game
     style) + ONE contact sheet of the built animation(s): review/<Anim>_contact.png
     (review/All_contact.png for 'all'). Report: review/<Char>_check.{json,txt}.
  3. draft = per-animation sheet only, written to review/draft/<Char>_<Anim>_sheet.{png,json},
     + check of those sheets (report review/<Char>_check.{json,txt}). Nothing else is touched: no GIF,
     no unity note, no atlas, no archive, no card / README update, animations/ stays as delivered.
  Exit code (CLI): 0 = no FAIL, 1 = check FAIL, 2 = error.
"""
from __future__ import annotations

import contextlib
import io
import json
import runpy
import sys
from pathlib import Path

from .errors import PixelError
from .palette import ROOT


# --------------------------------------------------------------------------- source discovery
def find_source(adir, card=None):
    """-> (source path | None, [make_*.py paths]) without running anything."""
    sdir = Path(adir) / "source"
    if not sdir.is_dir():
        return None, []
    makes = sorted(sdir.glob("make_*.py"))
    named = [v.get("source") for v in (card or {}).get("animations", {}).values() if v.get("source")]
    for n in sorted(set(named), key=named.count, reverse=True):
        if (sdir / n).is_file():
            return (sdir / n).resolve(), makes
    for m in makes:
        j = sdir / (m.stem[len("make_"):] + ".json")
        if j.is_file():
            return j.resolve(), makes
    jsons = [p for p in sorted(sdir.glob("*.json")) if not p.stem.lower().endswith("_palette")]
    if len(jsons) == 1:
        return jsons[0].resolve(), makes
    pys = [p for p in sorted(sdir.glob("*.py")) if p not in makes]
    if not jsons and len(pys) == 1:
        return pys[0].resolve(), makes
    if not jsons and not pys and len(makes) == 1:
        return makes[0].resolve(), makes  # the make script itself defines build()
    return None, makes


def run_make(make, verbose=False):
    """Run a make_*.py script as __main__ (stdout captured unless verbose). -> captured text."""
    buf = io.StringIO()
    old_argv = sys.argv
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    sys.argv = [str(make)]
    try:
        if verbose:
            runpy.run_path(str(make), run_name="__main__")
        else:
            with contextlib.redirect_stdout(buf):
                runpy.run_path(str(make), run_name="__main__")
    except SystemExit as e:
        if e.code not in (None, 0):
            raise PixelError(f"{make.name} exited with {e.code}")
    except PixelError as e:
        raise PixelError(f"{make.name}: {e}")
    except Exception as e:  # noqa: BLE001 - script errors are reported in one line
        raise PixelError(f"{make.name} failed: {type(e).__name__}: {e}")
    finally:
        sys.argv = old_argv
    return buf.getvalue()


def _load(game, character, kind, root):
    from . import layout
    from .style import load_style
    st = load_style(game, root)
    cname = layout.normalize_name(character)
    adir = layout.asset_dir(st["name"], cname, kind, root)
    card = layout.load_card(adir, kind)
    if card is None:
        raise PixelError(f"{kind} {cname} not found in {st['name']} (create it with char-new {st['name']} {cname})")
    return st, cname, adir, card


# --------------------------------------------------------------------------- check merge (draft)
def _merge_checks(reps, labels):
    from .check import STATUSES, report_text
    groups, seen = [], set()
    for rep, A in zip(reps, labels):
        for g in rep["groups"]:
            name = g["name"]
            if name == "source":
                if name in seen:
                    continue
            elif name == "atlas":
                name = f"sheet/{A}"
            elif name == "game-style":
                name = f"game-style/{A}"
            seen.add(name)
            groups.append({"name": name, "checks": g["checks"]})
    allc = [c for g in groups for c in g["checks"]]
    summary = {s: sum(c["status"] == s for c in allc) for s in STATUSES}
    summary["SKIP"] = sum(c["status"] == "SKIP" for c in allc)
    first = reps[0]
    rep = {"tool": "spritewright check", "sprite": first["sprite"],
           "inputs": dict(first["inputs"], atlas=", ".join(r["inputs"]["atlas"] or "" for r in reps)),
           "thresholds": first["thresholds"], "groups": groups, "summary": summary,
           "summary_line": f"check: {summary['PASS']} PASS, {summary['WARN']} WARN, {summary['FAIL']} FAIL",
           "exit_code": 1 if summary["FAIL"] else 0}
    rep["text"] = report_text(rep)
    rep["checks"] = allc
    return rep


def _write_check(rep, review, cname):
    review.mkdir(parents=True, exist_ok=True)
    jp = review / f"{cname}_check.json"
    from .check import portable_report
    body, text = portable_report(rep, review)
    jp.write_text(json.dumps(body, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    tp = jp.with_suffix(".txt")
    tp.write_text(text + "\n", encoding="utf-8")
    return jp, tp


# --------------------------------------------------------------------------- build
def build(game, character, animation="all", mode="final", src=None, fps=None, no_loop=(), preview_scale=4,
          kind="character", root=None, verbose=False):
    """Compile + render + check + deliver one character (see module doc). Returns a report dict:
    {status, mode, game, character, source, animations{A: {...}}, summary, issues, paths, exit_code,
    check_text, made, export}."""
    from . import export as ex
    from . import layout
    from .check import check, issue_lines
    from .sprite import load_sprite
    if mode not in ("draft", "final"):
        raise PixelError(f"mode must be draft or final, got {mode!r}")
    st, cname, adir, card = _load(game, character, kind, root)
    gname = st["name"]
    found, makes = find_source(adir, card)
    made = []
    for m in makes:
        run_make(m, verbose=verbose)
        made.append(str(m))
    if src:
        srcp = layout._resolve_export_source(src, adir)
    else:
        found, _ = find_source(adir, card)  # the make script may have just created it
        if found is None:
            raise PixelError(f"no unique source in {adir / 'source'}; pass --src FILE")
        srcp = found
    anims = None if str(animation).lower() in ("all", "*", "") else [animation]
    review = adir / "review"
    rep = {"mode": mode, "game": gname, "character": cname, "source": str(srcp), "made": made,
           "animations": {}, "paths": {}}
    if mode == "draft":
        sp = load_sprite(srcp)
        sel, disp = layout.select_anims(sp, srcp, anims)
        prep = layout.prepare_export(st, card, sp, sel, disp, fps=fps, no_loop=no_loop)
        ddir = review / "draft"
        reps, labels, sheets = [], [], []
        for a in sel:
            A = disp[a]
            _, e, png, jp = layout.write_anim_sheet(prep, a, A, cname, gname, ddir)
            sheets.append(str(png))
            rep["animations"][A] = {"frames": e["frame_count"], "fps": e["fps"], "loop": e["loop"],
                                    "sheet": str(png), "json": str(jp)}
            reps.append(check(srcp, atlas=jp, game=gname, game_root=root, write=False))
            labels.append(A)
        chk = _merge_checks(reps, labels)
        rep["paths"]["sheets"] = sheets
    else:
        exp = layout.char_export(gname, cname, srcp, anims=anims, fps=fps, no_loop=no_loop,
                                 preview_scale=preview_scale, kind=kind, root=root)
        rep["export"] = exp
        for A, v in exp["animations"].items():
            rep["animations"][A] = {k: v[k] for k in ("frames", "fps", "loop", "sheet", "json", "gif", "note")}
        chk = check(srcp, atlas=exp["atlas_json"], game=gname, game_root=root, write=False)
        built = list(exp["animations"])
        label = built[0] if len(built) == 1 else "All"
        rows = [[f"{A}__{i}" for i in range(exp["animations"][A]["frames"])] for A in built]
        contact = ex.contact_sheet(exp["atlas_json"], review / f"{label}_contact.png", scale=4, rows=rows)
        rep["paths"].update({"atlas": exp["atlas"], "atlas_json": exp["atlas_json"], "contact": str(contact),
                             "notes": [v["note"] for v in exp["animations"].values()],
                             "card": exp["card"], "index": exp["index"]})
    jp, tp = _write_check(chk, review, cname)
    rep["paths"]["check"] = str(tp)
    rep["summary"] = {k: chk["summary"][k] for k in ("PASS", "WARN", "FAIL")}
    rep["issues"] = issue_lines(chk)
    rep["check_text"] = chk["text"]
    rep["exit_code"] = chk["exit_code"]
    rep["status"] = "FAIL" if chk["exit_code"] else "PASS"
    return rep


def _brace(paths):
    """['D:/x/Idle/n.md', 'D:/x/Walk/n.md'] -> 'D:/x/{Idle,Walk}/n.md' (common prefix/suffix)."""
    paths = [str(p) for p in paths]
    if len(paths) <= 1:
        return paths[0] if paths else ""
    import os
    pre = os.path.commonprefix(paths)
    suf = os.path.commonprefix([p[::-1] for p in paths])[::-1]
    sep = max(pre.rfind("\\"), pre.rfind("/")) + 1
    pre = pre[:sep]
    k = min(len(suf), min(len(p) - len(pre) for p in paths))
    suf = suf[len(suf) - k:]
    first = suf.find("\\") if "\\" in suf else suf.find("/")
    suf = suf[first:] if first >= 0 else ""
    mids = [p[len(pre):len(p) - len(suf)] for p in paths]
    return f"{pre}{{{','.join(mids)}}}{suf}"


def build_lines(rep, max_issue_chars=220):
    """Quiet build output: <= 5 lines."""
    s = rep["summary"]
    anims = ", ".join(f"{A} {v['frames']}f@{v['fps']:g}" for A, v in rep["animations"].items())
    label = "all" if len(rep["animations"]) > 1 else next(iter(rep["animations"]), "")
    L = [f"{rep['status']} build {rep['character']} {label} ({rep['mode']}): {anims} | check {s['PASS']} PASS, "
         f"{s['WARN']} WARN, {s['FAIL']} FAIL"]
    P = rep["paths"]
    if rep["mode"] == "draft":
        L.append(f"sheet  {_brace(P['sheets'])}")
    else:
        L.append(f"atlas  {P['atlas']}")
        L.append(f"review {P['contact']}")
        L.append(f"notes  {_brace(P['notes'])}")
    if rep["issues"]:
        txt = "; ".join(i.split("] ", 1)[0] + "]" if "] " in i else i for i in rep["issues"])
        if len(txt) > max_issue_chars:
            txt = txt[:max_issue_chars - 3] + "..."
        L.append(f"issues {txt} (details: {P['check']})")
    return L


# --------------------------------------------------------------------------- context
def context(game, character=None, root=None, kind="character"):
    """Compact style / character summary for drawing (<= 15 lines). Raises PixelError if missing."""
    from . import layout
    from .style import load_style
    gname = layout.normalize_name(game)
    gdir = layout.game_dir(gname, root)
    if not (gdir / "game-style.json").is_file():
        raise PixelError(f"game {gname} not found ({gdir}); ask the user, then game-new {gname}")
    st = load_style(gname, root)
    W, H = st["cell"]
    pal = st["palette"]
    L = [f"{st['name']}: cell {W}x{H}, PPU {st['ppu']}, outline {st['outline']}, light {st['light']}, shading "
         f"{st['shading']}, dither {st['dither']}, {st['proportions']} proportions",
         f"colours: palette {len(pal)}, max {st['max_colors']} per sprite (game palette only; new colour = ask user)"]
    per = 8 if len(pal) <= 16 else 11
    for i in range(0, len(pal), per):
        L.append("palette: " + " ".join(f"{e['role']}={e['hex']}" for e in pal[i:i + per]))
    if not character:
        chars = []
        for k, (folder, _) in layout.KINDS.items():
            d = gdir / folder
            if d.is_dir():
                chars += [p.name for p in sorted(d.iterdir()) if p.is_dir()]
        L.append("assets: " + (", ".join(chars) if chars else "none yet"))
        return L
    cname = layout.normalize_name(character)
    adir = layout.asset_dir(st["name"], cname, kind, root)
    card = layout.load_card(adir, kind)
    if card is None:
        raise PixelError(f"{kind} {cname} not found in {st['name']}; char-new {st['name']} {cname} --role ... "
                         f"--design ...")
    piv = card.get("pivot")
    piv_s = "bottom-center of union bbox (default)" if piv is None else (
        f"{piv[0]},{piv[1]}" if isinstance(piv, list) else str(piv))
    cw, ch = card["cell"]
    L.append(f"{cname} ({kind}): cell {cw}x{ch}, pivot {piv_s}, role {card.get('role') or '-'}")
    if card.get("design"):
        d = card["design"]
        L.append("design: " + (d if len(d) <= 160 else d[:157] + "..."))
    L.append(f"colours ({len(card['colors'])}): " + ", ".join(c["role"] for c in card["colors"]))
    an = card.get("animations") or {}
    L.append("animations: " + (", ".join(f"{a}:{v['frames']}@{v['fps']:g}{'' if v.get('loop', True) else ' once'}"
                                         for a, v in an.items()) or "none yet"))
    src, makes = find_source(adir, card)
    s = f"source: {src}" if src else f"source: none yet ({adir / 'source'})"
    if makes and (src is None or Path(src) not in [m.resolve() for m in makes]):
        s += f" (make: {', '.join(m.name for m in makes)})"
    L.append(s)
    return L
