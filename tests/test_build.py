"""Tests: build (draft/final) + context + quiet output + e2e bug fixes.

Run standalone:  python tests/test_build.py
Also executed by tests/smoke_test.py (shared counters). Everything is written below a temp outputs root
(--root) and SPRITEWRIGHT_OUTPUT points to a temp dir, so neither outputs/ nor output/ is touched.
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
from PIL import Image  # noqa: E402

import spritewright as ps  # noqa: E402

BODY = ["..oooooo..", ".ohhhhhso.", "ohhhhhssso", "ohhhssssso", "ohhsssssdo",
        "ohsssssddo", "osssssdddo", "ossssddddo", ".osdddddo.", "..oooooo.."]

MAKE = '''import json
from pathlib import Path
HERE = Path(__file__).resolve().parent
D = {D}
(HERE / "hero.json").write_text(json.dumps(D, indent=2), encoding="utf-8")
print("wrote", HERE / "hero.json")
'''


def _rig_dict():
    return {"name": "hero", "width": 24, "height": 24, "palette": "Hero_palette.json",
            "chars": {"o": "outline", "h": "highlight", "s": "skin", "d": "danger"},
            "parts": {"body": {"z": 0, "x": 7, "y": 10, "rows": BODY},
                      "feet": {"z": -1, "x": 8, "y": 20, "rows": ["oo....oo", "oo....oo"]}},
            "rig_animations": {
                "idle": {"fps": 5, "loop": True, "durations": [250, 150, 250, 150],
                         "frames": [{}, {"body": [0, 1]}, {"body": [0, 1]}, {}]},
                "walk": {"fps": 8, "loop": True, "frames": [{}, {"body": [1, 0]}, {"body": [0, 1]},
                                                            {"body": [-1, 0]}, {}, {"body": [0, 1]}]}}}


def _lines(out):
    return [ln for ln in out.strip().splitlines() if ln.strip()]


def _files(d):
    return sorted(str(p.relative_to(d)).replace("\\", "/") for p in Path(d).rglob("*") if p.is_file())


def run(check, cli, tmp):
    R = tmp / "build_root"
    G = R / "Build_Game"
    cli("game-new", "build game", "--palette", "pico-8", "--root", R, contains="Build_Game")
    st = ps.load_style("Build_Game", R)
    roles = [e["role"] for e in st["palette"]]
    hues = ("red", "orange", "yellow", "green", "teal", "blue", "purple", "pink", "grey", "brown")
    check("game-new: usage roles, no hue names", {"outline", "highlight", "shadow_dark", "skin", "danger",
                                                  "background", "accent"} <= set(roles)
          and not any(r.split("_")[0] in hues for r in roles), str(roles))
    check("game-new: roles deterministic", ps.style.auto_roles([e["hex"] for e in st["palette"]]) == roles)
    out = cli("char-new", "Build_Game", "hero", "--colors", "outline,highlight,skin,danger", "--root", R)
    check("quiet: char-new one line", len(_lines(out)) == 1, out)
    H = G / "characters" / "Hero"
    (H / "source" / "make_hero.py").write_text(MAKE.replace("{D}", repr(_rig_dict())), encoding="utf-8")
    readme0 = (R / "README.md").read_text(encoding="utf-8")
    card0 = (H / "character.json").read_text(encoding="utf-8")

    # ---- draft: only review/draft sheets + check report
    out = cli("build", "Build_Game", "Hero", "all", "--draft", "--root", R, contains="PASS build Hero")
    check("build --draft: <= 5 lines", len(_lines(out)) <= 5, out)
    files = _files(H)
    want = {"review/draft/Hero_Idle_sheet.png", "review/draft/Hero_Idle_sheet.json",
            "review/draft/Hero_Walk_sheet.png", "review/draft/Hero_Walk_sheet.json",
            "review/Hero_check.json", "review/Hero_check.txt"}
    check("build --draft: expected files only", want <= set(files) and not any(f.endswith(".gif") for f in files)
          and not any(f.startswith("animations/") for f in files) and "source/hero.json" in files
          and not any(f.endswith("unity-import-note.md") for f in files), str(files))
    check("build --draft: README + card untouched", (R / "README.md").read_text(encoding="utf-8") == readme0
          and (H / "character.json").read_text(encoding="utf-8") == card0)
    out = cli("build", "Build_Game", "Hero", "walk", "--draft", "--json", "--root", R)
    try:
        js = json.loads(out)
    except Exception:
        js = {}
    check("build --json: machine report", js.get("status") == "PASS" and list(js.get("animations", {})) == ["Walk"]
          and js.get("mode") == "draft" and "summary" in js, out[-300:])

    # ---- final: full delivery + one review contact sheet
    out = cli("build", "Build_Game", "Hero", "--root", R, contains="(final)")
    L = _lines(out)
    contact = H / "review" / "All_contact.png"
    check("build --final: <= 5 lines, prints review contact path", len(L) <= 5 and str(contact) in out, out)
    A = H / "animations"
    want = [A / "Idle" / "Hero_Idle_sheet.png", A / "Idle" / "Hero_Idle_preview.gif", A / "Idle" / "unity-import-note.md",
            A / "Walk" / "Hero_Walk_sheet.json", A / "Walk" / "Hero_Walk_preview.gif",
            A / "Hero_all_animations_atlas.png", A / "Hero_all_animations_atlas.json", contact]
    check("build --final: full file set", all(p.is_file() for p in want), str([str(p) for p in want if not p.is_file()]))
    check("build --final: contact <= 1024 px, one row per animation", contact.is_file()
          and Image.open(contact).size[0] <= 1024 and Image.open(contact).size[1] < Image.open(contact).size[0])
    readme = (R / "README.md").read_text(encoding="utf-8")
    card = json.loads((H / "character.json").read_text(encoding="utf-8"))
    check("build --final: README + card updated", "**Hero**" in readme and "Idle (4f" in readme
          and list(card["animations"]) == ["Idle", "Walk"])
    check("fps fix: declared fps reported, durations kept", card["animations"]["Idle"]["fps"] == 5
          and json.loads((A / "Idle" / "Hero_Idle_sheet.json").read_text(encoding="utf-8"))["animations"][0][
              "durations"] == [250, 150, 250, 150])
    out = cli("build", "Build_Game", "Hero", "Walk", "--root", R)
    check("build one animation -> review/Walk_contact.png", (H / "review" / "Walk_contact.png").is_file()
          and len(_lines(out)) <= 5, out)
    cli("build", "Build_Game", "Nobody", "--root", R, expect=2, contains="char-new")

    # ---- atlas.sync case bug (source idle/walk vs atlas Idle/Walk)
    rep = ps.check(H / "source" / "hero.json", atlas=A / "Hero_all_animations_atlas.json", write=False)
    sync = next(c for c in rep["checks"] if c["id"] == "atlas.sync")
    check("check: atlas.sync matches Title_Case names", sync["status"] == "PASS"
          and not sync["details"].get("not_exported"), str(sync))

    # ---- contact on exported atlas / sheet (json + png)
    c1 = tmp / "atlas_contact.png"
    cli("contact", A / "Hero_all_animations_atlas.json", "-o", c1)
    c2 = tmp / "sheet_contact.png"
    cli("contact", A / "Walk" / "Hero_Walk_sheet.png", "-s", "40", "-o", c2)
    check("contact: atlas json + sheet png work, width capped", c1.is_file() and c2.is_file()
          and Image.open(c2).size[0] <= 1024)

    # ---- context
    out = cli("context", "Build_Game", "Hero", "--root", R, contains="Walk:6@8")
    check("context: <= 15 lines with pivot/colours/source", len(_lines(out)) <= 15 and "pivot" in out
          and "outline" in out and "hero.json" in out, out)
    out = cli("context", "Build_Game", "--root", R, contains="cell 32x32")
    check("context game only: <= 15 lines", len(_lines(out)) <= 15, out)
    out = cli("context", "No_Game", "--root", R, expect=1)
    check("context: missing game -> exactly one line", len(_lines(out)) == 1, out)
    out = cli("context", "Build_Game", "Ghost", "--root", R, expect=1)
    check("context: missing character -> exactly one line", len(_lines(out)) == 1, out)

    # ---- quiet default = one line
    slime = ROOT / "examples/sprites/slime.json"
    for args in (("palettes",), ("render", slime, "-o", tmp / "q_r.png"), ("sheet", slime, "-o", tmp / "q_s.png"),
                 ("gif", slime, "-o", tmp / "q.gif"), ("templates",), ("info", slime),
                 ("game-style", "Build_Game", "--root", R), ("palette-show", "pico-8")):
        out = cli(*args)
        check(f"quiet: {args[0]} one line", len(_lines(out)) == 1, out[-300:])
    out = cli("info", slime, "--verbose")
    check("quiet: --verbose gives details", len(_lines(out)) > 3)
    out = cli("check", slime, "--no-write")
    check("quiet: check = summary + one line per issue", _lines(out)[0].startswith("check:")
          and all(ln.startswith(("WARN", "FAIL", "...")) for ln in _lines(out)[1:]), out)

    # ---- inspect requires a region
    out = cli("inspect", slime, expect=2, contains="-r x,y,w,h")
    check("inspect without region: one-line hint", len(_lines(out)) == 1, out)
    cli("inspect", slime, "--full", "-o", tmp / "insp_full.png")

    # ---- tests never create ./output in the checkout (SPRITEWRIGHT_OUTPUT points to the temp dir)
    check("no stray ./output folder", not (ROOT / "output").exists())


if __name__ == "__main__":
    FAILS, N = [], [0]
    TMP = Path(tempfile.mkdtemp(prefix="spritewright_build_"))
    os.environ["SPRITEWRIGHT_OUTPUT"] = str(TMP / "output")
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
