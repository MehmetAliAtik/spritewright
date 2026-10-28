"""Tests: game/character project layout (outputs/<Game>/...) + style guide + game-style check.

Run standalone:  python tests/test_layout.py
Also executed by tests/smoke_test.py (shared counters). Everything is written below a temp outputs
root (--root / root=...); the real outputs/ folder is never touched.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import spritewright as ps  # noqa: E402
from spritewright.check import _light_violation  # noqa: E402

BODY = [
    "..oooooo..",
    ".olllllso.",
    "olllllssso",
    "olllssssso",
    "ollsssssdo",
    "olsssssddo",
    "osssssdddo",
    "ossssddddo",
    ".osdddddo.",
    "..oooooo..",
]


def _rig(path):
    d = {"name": "erica", "width": 24, "height": 24, "palette": "Erica_palette.json",
         "chars": {"o": "outline", "l": "highlight", "s": "skin", "d": "danger"},
         "parts": {"body": {"z": 0, "x": 7, "y": 10, "rows": BODY},
                   "feet": {"z": -1, "x": 8, "y": 20, "rows": ["oo....oo", "oo....oo"]}},
         "rig_animations": {
             "idle": {"fps": 4, "loop": True, "frames": [{}, {"body": [0, 1]}, {"body": [0, 1]}, {}]},
             "walk": {"fps": 8, "loop": True, "frames": [{}, {"body": [1, 0]}, {"body": [0, 1]},
                                                         {"body": [-1, 0]}, {}, {"body": [0, 1]}]}}}
    path.write_text(json.dumps(d, indent=2), encoding="utf-8")
    return path


def _statuses(rep, group="game-style"):
    return {c["id"]: c["status"] for g in rep["groups"] if g["name"] == group for c in g["checks"]}


def run(check, cli, tmp):
    R = tmp / "outputs_root"
    G = R / "Aurora_Quest"

    # ---- name normalization
    nn = ps.normalize_name
    check("layout: normalize names", nn("aurora quest") == "Aurora_Quest" and nn("erica") == "Erica"
          and nn("walk") == "Walk" and nn("run-fast") == "Run_Fast" and nn("  big_boss  ") == "Big_Boss"
          and nn("AuroraQuest") == "AuroraQuest")
    bad = []
    for s in ("a/b", "caf\u00e9", "", "3d game", "x.y"):
        try:
            nn(s)
            bad.append(s)
        except ps.PixelError:
            pass
    check("layout: invalid names rejected", not bad, str(bad))
    old = os.environ.get("SPRITEWRIGHT_OUTPUTS")
    os.environ["SPRITEWRIGHT_OUTPUTS"] = str(R)
    check("layout: env root override", ps.outputs_root() == R and ps.outputs_root(tmp) == tmp)
    if old is None:
        os.environ.pop("SPRITEWRIGHT_OUTPUTS")
    else:
        os.environ["SPRITEWRIGHT_OUTPUTS"] = old
    if old is not None:
        os.environ.pop("SPRITEWRIGHT_OUTPUTS")
    check("layout: default root is ./outputs (cwd, never the package)", ps.layout.outputs_root() == Path.cwd() / "outputs"
          and ps.outputs_root() != ROOT / "spritewright" / "outputs")
    if old is not None:
        os.environ["SPRITEWRIGHT_OUTPUTS"] = old

    # ---- game-new
    cli("game-new", "aurora quest", "--mood", "cozy,retro", "--temperature", "warm", "--saturation", "medium",
        "--contrast", "high", "--cell", "32x32", "--ppu", "32", "--outline", "selective", "--light", "top-left",
        "--shading", "2", "--dither", "none", "--max-colors", "16", "--proportions", "chibi",
        "--palette", "pico-8", "--root", R, contains="Aurora_Quest")
    files = [G / f for f in ("game-style.md", "game-style.json", "palette.hex", "palette_preview.png")]
    check("game-new: 4 style files", all(f.is_file() for f in files), str([f.name for f in files if not f.exists()]))
    st = json.loads((G / "game-style.json").read_text(encoding="utf-8"))
    pal = st["palette"]
    roles = [e["role"] for e in pal]
    check("game-new: palette 8-32 with unique roles", 8 <= len(pal) <= 32 and len(set(roles)) == len(roles)
          and {"outline", "shadow_dark", "highlight", "skin", "accent", "danger", "background"} <= set(roles), str(roles))
    hexlines = (G / "palette.hex").read_text(encoding="utf-8").split()
    check("game-new: palette.hex = json palette", hexlines == [e["hex"] for e in pal])
    check("game-new: json visual rules", st["cell"] == [32, 32] and st["ppu"] == 32 and st["outline"] == "selective"
          and st["light"] == "top-left" and st["max_colors"] == 16 and st["proportions"] == "chibi"
          and st["dither"] == "none" and st["shading"] == 2 and st["mood"] == ["cozy", "retro"]
          and 5 <= len(st["rules"]["do"]) <= 8 and 5 <= len(st["rules"]["dont"]) <= 8 and st["ramps"])
    md = (G / "game-style.md").read_text(encoding="utf-8")
    check("game-new: md sections", all(s in md for s in ("## Mood", "## Theme & colour direction", "## Palette",
                                                         "## Ramps", "## Visual rules", "## Do", "## Don't")))
    check("game-new: preview png", Image.open(G / "palette_preview.png").size[0] > 100)
    cli("game-style", "Aurora_Quest", "--root", R, contains="style: OK")
    cli("game-new", "Aurora_Quest", "--root", R, expect=2, contains="already exists")
    cli("game-new", "Small", "--palette", "pico-8", "--colors", "8", "--temperature", "cool", "--outline",
        "black", "--roles", "0=ink", "--root", R, contains="8 colours")
    sm = ps.load_style("Small", R)
    check("game-new: subset of 8 + role override", len(sm["palette"]) == 8 and sm["palette"][0]["role"] == "ink"
          and all(e["hex"] in [ps.to_hex(c) for c in ps.Palette.load("pico-8").colors] for e in sm["palette"]))
    cli("game-new", "Too_Many", "--colors", "40", "--root", R, expect=2, contains="8-32")
    cli("game-new", "Bad_Name/x", "--root", R, expect=2, contains="invalid characters")

    # ---- char-new
    cli("char-new", "Aurora_Quest", "bob", "--colors", "outline,#123456", "--root", R, expect=2,
        contains="not in the Aurora_Quest game palette")
    check("char-new: rejected card not written", not (G / "characters" / "Bob" / "character.md").exists())
    cli("char-new", "aurora quest", "erica", "--role", "player hero", "--design", "red scarf, round face",
        "--colors", "outline,highlight,skin,danger", "--root", R, contains="Erica")
    E = G / "characters" / "Erica"
    card = json.loads((E / "character.json").read_text(encoding="utf-8"))
    cpal = ps.Palette.load(E / "source" / "Erica_palette.json")
    check("char-new: card + palette subset", (E / "character.md").is_file() and card["cell"] == [32, 32]
          and [c["role"] for c in card["colors"]] == ["outline", "highlight", "skin", "danger"]
          and len(cpal) == 4 and set(cpal.names) == {"outline", "highlight", "skin", "danger"})

    # ---- char-export
    _rig(E / "source" / "erica_rig.json")
    cli("char-export", "Aurora_Quest", "Erica", "erica_rig.json", "--root", R, contains="atlas")
    A = E / "animations"
    want = []
    for an, n in (("Idle", 4), ("Walk", 6)):
        want += [A / an / f"Erica_{an}_sheet.png", A / an / f"Erica_{an}_sheet.json",
                 A / an / f"Erica_{an}_preview.gif", A / an / "unity-import-note.md"]
    want += [A / "Erica_all_animations_atlas.png", A / "Erica_all_animations_atlas.json"]
    missing = [str(p.relative_to(E)) for p in want if not p.is_file()]
    check("char-export: exact filenames", not missing, str(missing))
    if not missing:
        ij = json.loads((A / "Idle" / "Erica_Idle_sheet.json").read_text(encoding="utf-8"))
        wj = json.loads((A / "Walk" / "Erica_Walk_sheet.json").read_text(encoding="utf-8"))
        aj = json.loads((A / "Erica_all_animations_atlas.json").read_text(encoding="utf-8"))
        ii = Image.open(A / "Idle" / "Erica_Idle_sheet.png")
        wi = Image.open(A / "Walk" / "Erica_Walk_sheet.png")
        ai = Image.open(A / "Erica_all_animations_atlas.png")
        check("char-export: sheets are horizontal strips of 32x32", ii.size == (4 * 32, 32) and wi.size == (6 * 32, 32)
              and ij["frame_size"] == {"w": 32, "h": 32} and ij["rows"] == 1 and ij["columns"] == 4
              and ij["spacing"] == 0 and ij["fps"] == 4 and ij["loop"] is True and wj["fps"] == 8
              and "pivot" in ij and ij["animation"] == "Idle", str(ii.size))
        alpha = np.asarray(ai.convert("RGBA"))[..., 3]
        check("char-export: atlas one row per animation, same cell", ai.size == (6 * 32, 2 * 32)
              and [a["name"] for a in aj["animations"]] == ["Idle", "Walk"] and aj["cell"] == ij["cell"] == wj["cell"]
              and aj["pivot"]["pixel"] == ij["pivot"]["pixel"] and set(np.unique(alpha)) <= {0, 255})
        check("char-export: meta.source stored relative (no absolute paths on disk)",
              ij["meta"]["source"] == "../../source/erica_rig.json"
              and aj["meta"]["source"] == "../source/erica_rig.json", f'{ij["meta"]["source"]} {aj["meta"]["source"]}')
        check("char-export: atlas rows equal the sheets",
              np.array_equal(np.asarray(ai.convert("RGBA"))[32:64, :], np.asarray(wi.convert("RGBA")))
              and np.array_equal(np.asarray(ai.convert("RGBA"))[0:32, :128], np.asarray(ii.convert("RGBA"))))
    cmd = (E / "character.md").read_text(encoding="utf-8")
    card = json.loads((E / "character.json").read_text(encoding="utf-8"))
    check("char-export: card animations + change log", list(card["animations"]) == ["Idle", "Walk"]
          and "| Idle | 4 |" in cmd and "| Walk | 6 |" in cmd and "Walk exported" in cmd)
    readme = (R / "README.md").read_text(encoding="utf-8")
    check("char-export: outputs README index", "## Aurora_Quest" in readme and "**Erica**" in readme
          and "Idle (4f" in readme and "Walk (6f" in readme and "Last updated:" in readme and "## Small" in readme)

    # ---- re-export archives the previous version (never deletes)
    before = (A / "Idle" / "Erica_Idle_sheet.png").read_bytes()
    cli("char-export", "Aurora_Quest", "Erica", E / "source" / "erica_rig.json", "--anims", "idle", "--fps", "5",
        "--root", R, contains="archived previous version")
    arch = sorted((A / "Idle" / "_archive").glob("*")) if (A / "Idle" / "_archive").is_dir() else []
    old_png = arch[0] / "Erica_Idle_sheet.png" if arch else None
    check("re-export: old version in _archive/<timestamp>/", len(arch) == 1 and old_png.is_file()
          and old_png.read_bytes() == before and (arch[0] / "Erica_Idle_sheet.json").is_file()
          and (A / "Idle" / "Erica_Idle_sheet.png").is_file() and len(arch[0].name) >= 17, str(arch))
    nj = json.loads((A / "Idle" / "Erica_Idle_sheet.json").read_text(encoding="utf-8"))
    check("re-export: new version current, Walk untouched, atlas archived",
          nj["animation"] == "Idle" and nj["fps"] == 4 and not (A / "Walk" / "_archive").exists() and (A / "_archive").is_dir()
          and json.loads((A / "Erica_all_animations_atlas.json").read_text(encoding="utf-8"))["rows"] == 2)
    cli("char-export", "Aurora_Quest", "Erica", "erica_rig.json", "--anims", "Idle", "--root", R)
    check("re-export twice: second archive kept too", len(list((A / "Idle" / "_archive").glob("*"))) == 2)
    cli("char-export", "Aurora_Quest", "Erica", "erica_rig.json", "--anims", "Jump", "--root", R, expect=2,
        contains="not in erica_rig.json")
    cli("char-export", "Aurora_Quest", "Nobody", "erica_rig.json", "--root", R, expect=2, contains="char-new")

    # ---- check: game-style group
    sheet_j = A / "Walk" / "Erica_Walk_sheet.json"
    wrep = ps.check(sheet_j, out=A / "Walk")
    saved = json.loads(Path(wrep["paths"]["json"]).read_text(encoding="utf-8"))["inputs"]
    txt = Path(wrep["paths"]["txt"]).read_text(encoding="utf-8")
    check("check: saved report paths are relative", saved["atlas"] == "Erica_Walk_sheet.json"
          and saved["source"] == "../../source/erica_rig.json" and str(ROOT) not in txt, f"{saved} {txt[:200]}")
    rep = ps.check(sheet_j, write=False)
    s = _statuses(rep)
    check("check: game auto-detected inside outputs/<Game>/", rep["inputs"].get("game") == "Aurora_Quest"
          and s.get("game.off_palette") == "PASS" and s.get("game.cell") == "PASS"
          and s.get("game.color_limit") == "PASS" and s.get("game.char_colors") == "PASS"
          and s.get("game.light") in ("PASS", "WARN") and rep["exit_code"] == 0, str(s))
    bad_dir = tmp / "bad_sheet"
    shutil.copytree(A / "Walk", bad_dir, ignore=shutil.ignore_patterns("_archive"))
    p = bad_dir / "Erica_Walk_sheet.png"
    arr = np.array(Image.open(p).convert("RGBA"))
    ys, xs = np.nonzero(arr[..., 3] == 255)
    arr[ys[0], xs[0], :3] = (0x12, 0x34, 0x56)
    Image.fromarray(arr, "RGBA").save(p)
    out = cli("check", bad_dir / "Erica_Walk_sheet.json", "--game", "Aurora_Quest", "--root", R, "--no-write",
              "--verbose", expect=1, contains="game.off_palette")
    check("check --game: off-palette pixel -> FAIL", "FAIL  game.off_palette" in out and "#123456" in out, out[-600:])
    rep = ps.check(bad_dir / "Erica_Walk_sheet.json", write=False)
    check("check: no game group outside outputs without --game", "game-style" not in [g["name"] for g in rep["groups"]])
    wrong = E / "wrong_cell"
    cli("unity-sheet", E / "source" / "erica_rig.json", "-o", wrong, "--cell", "40x40", "--preview-scale", "0")
    out = cli("check", wrong / "atlas.json", "--no-write", "--verbose", expect=1, contains="game.cell")
    check("check: wrong cell -> FAIL (auto-detected game + card)", "FAIL  game.cell" in out
          and "40x40" in out and "32x32" in out, out[-600:])
    rep = ps.check(E / "source" / "erica_rig.json", atlas=False, write=False)
    s = _statuses(rep)
    check("check: source inside game folder gets game group", s.get("game.off_palette") == "PASS"
          and s.get("game.cell") == "PASS", str(s))
    # card colours WARN: card limited to 2 colours, art uses 4 game colours
    card2 = dict(card, colors=[c for c in card["colors"] if c["role"] in ("outline", "skin")])
    (E / "character.json").write_text(json.dumps(card2, indent=2), encoding="utf-8")
    rep = ps.check(sheet_j, write=False)
    check("check: colours outside the card -> WARN only", _statuses(rep).get("game.char_colors") == "WARN"
          and rep["exit_code"] == 0)
    (E / "character.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    # light heuristic on synthetic shapes (top-left light)
    cv = ps.Canvas(12, 12, "pico-8").rect(1, 1, 10, 10, 0)
    cv.rect(2, 2, 4, 4, 7).rect(6, 6, 4, 4, 1)   # light top-left, dark bottom-right
    rev = ps.Canvas(12, 12, "pico-8").rect(1, 1, 10, 10, 0).rect(2, 2, 4, 4, 1).rect(6, 6, 4, 4, 7)
    check("check: light heuristic", _light_violation(cv, (-1, -1), True) is False
          and _light_violation(rev, (-1, -1), True) is True)

    # ---- game-palette-add
    h0 = Image.open(G / "palette_preview.png").size
    cli("game-palette-add", "Aurora_Quest", "ff8800", "--role", "lava", "--root", R, contains="added #ff8800")
    st2 = json.loads((G / "game-style.json").read_text(encoding="utf-8"))
    md2 = (G / "game-style.md").read_text(encoding="utf-8")
    hx2 = (G / "palette.hex").read_text(encoding="utf-8").split()
    check("game-palette-add: hex/json/md/preview updated", len(st2["palette"]) == len(pal) + 1
          and st2["palette"][-1] == {"index": len(pal), "hex": "ff8800", "role": "lava"} and hx2[-1] == "ff8800"
          and "`#ff8800` | lava" in md2 and "lava" in md2.split("## Change log")[1]
          and Image.open(G / "palette_preview.png").size != h0)
    cli("game-palette-add", "Aurora_Quest", "ff8800", "--role", "lava2", "--root", R, expect=2, contains="already")
    cli("game-palette-add", "Aurora_Quest", "00ff88", "--role", "skin", "--root", R, expect=2, contains="already used")
    cli("game-style", "Aurora_Quest", "--root", R, contains="style: OK")
    cli("char-new", "Aurora_Quest", "Ember", "--colors", "outline,lava", "--kind", "prop", "--root", R,
        contains="prop Ember")
    check("layout: prop card under props/", (G / "props" / "Ember" / "prop.md").is_file()
          and "Props:" in (R / "README.md").read_text(encoding="utf-8"))
    cli("outputs-index", "--root", R, contains="README.md")


if __name__ == "__main__":
    FAILS, N = [], [0]
    TMP = Path(tempfile.mkdtemp(prefix="spritewright_layout_"))
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    def check(name, cond, detail=""):
        N[0] += 1
        print(f"[{'ok ' if cond else 'FAIL'}] {name}" + ("" if cond else f"  ({str(detail)[:600]})"))
        if not cond:
            FAILS.append(name)

    def cli(*args, expect=0, contains=None):
        r = subprocess.run([sys.executable, str(ROOT / "spritewright.py"), *map(str, args)],
                           capture_output=True, text=True, cwd=str(ROOT), encoding="utf-8", errors="replace")
        out = r.stdout + r.stderr
        check("cli: " + " ".join(map(str, args))[:90],
              r.returncode == expect and (contains is None or contains in out), out[-600:])
        return out

    run(check, cli, TMP)
    print(f"\n{N[0] - len(FAILS)}/{N[0]} passed")
    if not FAILS:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if FAILS else 0)
