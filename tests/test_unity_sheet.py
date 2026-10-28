"""Tests: unity-sheet (fixed cells, foot pivot, strips + atlas + atlas.json + previews).

Run standalone:  python tests/test_unity_sheet.py
Also executed by tests/smoke_test.py (shared counters).
"""
import json
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


def _synthetic():
    """24x24 sprite: idle (2 frames) + walk (4 frames, varying width, frame 3 lifted 2 px)."""
    sp = ps.Sprite(24, 24, "pico-8", name="syn")
    for i in range(2):
        sp.new_frame(f"idle{i + 1}").rect(8, 10 + i, 6, 12 - i, 8)
    for i in range(4):
        w = 6 + i
        lift = 2 if i == 2 else 0
        sp.new_frame(f"walk{i + 1}").rect(5 + i, 9 - lift, w, 13, 12).pixel(5 + i, 21 - lift, 7)
    sp.animations = {"idle": ["idle1", "idle2"], "walk": ["walk1", "walk2", "walk3", "walk4"]}
    return sp


def _cells(img, cw, ch):
    a = np.asarray(img.convert("RGBA"))
    for r in range(img.height // ch):
        for c in range(img.width // cw):
            yield r, c, a[r * ch:(r + 1) * ch, c * cw:(c + 1) * cw]


def _foot(cell):
    ys, xs = np.nonzero(cell[..., 3] > 0)
    if not len(xs):
        return None
    return int(xs.min() + (xs.max() - xs.min() + 1) // 2), int(ys.max())


def run(check, cli, tmp):
    tmp = Path(tmp)
    # ---- synthetic multi-animation sprite, auto alignment
    out = tmp / "unity_syn"
    rep = ps.unity_sheet(_synthetic(), out_dir=out, align="auto", fps=10, no_loop=["walk"], preview_scale=3)
    cw, ch = rep["cell"]
    atlas = Image.open(out / "atlas.png")
    a = np.asarray(atlas.convert("RGBA"))
    check("unity: atlas dims divisible by cell", atlas.width % cw == 0 and atlas.height % ch == 0
          and atlas.size == (rep["columns"] * cw, rep["rows"] * ch), f"{atlas.size} cell {cw}x{ch}")
    check("unity: rows = animations, cols = longest", rep["rows"] == 2 and rep["columns"] == 4)
    check("unity: alpha only 0/255 (atlas)", set(np.unique(a[..., 3]).tolist()) <= {0, 255})
    empty = [cell for r, c, cell in _cells(atlas, cw, ch) if r == 0 and c >= 2]
    check("unity: unused cells fully transparent", len(empty) == 2 and all(int(e[..., 3].max()) == 0 for e in empty))
    ax, ay = rep["pivot"]["pixel"]["x"], rep["pivot"]["pixel"]["y"]
    feet = [_foot(cell) for r, c, cell in _cells(atlas, cw, ch) if not (r == 0 and c >= 2)]
    check("unity: auto pivot lands on same cell pixel in every frame", len(feet) == 6
          and all(f == (ax, ay) for f in feet), f"{feet} vs {(ax, ay)}")
    strips = sorted(p.name for p in (out / "sheets").glob("*.png"))
    check("unity: strip count = animation count", strips == ["idle.png", "walk.png"], str(strips))
    s = Image.open(out / "sheets/walk.png")
    sa = np.asarray(s.convert("RGBA"))[..., 3]
    check("unity: strip = n * cell, alpha 0/255", s.size == (4 * cw, ch) and set(np.unique(sa).tolist()) <= {0, 255})
    d = json.loads((out / "atlas.json").read_text(encoding="utf-8"))
    need = {"cell", "rows", "columns", "pivot", "animations", "frames", "meta", "spacing", "margin", "unity"}
    an = {x["name"]: x for x in d["animations"]}
    check("unity: atlas.json fields", need <= set(d) and {"pixel", "normalized"} <= set(d["pivot"])
          and all({"name", "row", "frame_count", "fps", "loop", "durations"} <= set(x) for x in d["animations"])
          and d["spacing"] == 0 and d["margin"] == 0, str(sorted(d)))
    check("unity: fps/loop per animation", an["walk"]["fps"] == 10 and an["walk"]["loop"] is False
          and an["idle"]["loop"] is True and an["walk"]["frame_count"] == 4 and an["walk"]["row"] == 1)
    check("unity: bottom-center pivot normalized", d["pivot"]["normalized"] == {"x": 0.5, "y": 0.0}
          and d["pivot"]["unity_preset"] == "Bottom")
    check("unity: previews + note written", (out / "preview/atlas_x3.png").is_file()
          and (out / "preview/walk.gif").is_file() and (out / "UNITY_IMPORT.txt").is_file()
          and "Grid By Cell Size" in (out / "UNITY_IMPORT.txt").read_text(encoding="utf-8"))

    # ---- fixed (default) alignment keeps intentional motion: walk3 is lifted 2 px
    rep2 = ps.unity_sheet(_synthetic(), out_dir=tmp / "unity_fixed", preview_scale=0)
    cw2, ch2 = rep2["cell"]
    f2 = {(r, c): _foot(cell) for r, c, cell in _cells(Image.open(tmp / "unity_fixed/atlas.png"), cw2, ch2)}
    check("unity: fixed pivot preserves lift (no bbox re-alignment)",
          f2[(1, 0)][1] - f2[(1, 2)][1] == 2 and f2[(1, 0)][1] == rep2["pivot"]["pixel"]["y"], str(f2))

    # ---- part rig .py (hero): bob preserved, feet fixed, widths even
    out3 = tmp / "unity_hero"
    rep3 = ps.unity_sheet(ROOT / "examples/sprites/hero.py", out_dir=out3, preview_scale=0)
    cw3, ch3 = rep3["cell"]
    cells = [cell for _, _, cell in _cells(Image.open(out3 / "atlas.png"), cw3, ch3)]
    tops = [int(np.nonzero(c[..., 3].any(1))[0].min()) for c in cells]
    check("unity: hero feet on pivot pixel in every frame",
          all(_foot(c) == (rep3["pivot"]["pixel"]["x"], rep3["pivot"]["pixel"]["y"]) for c in cells))
    check("unity: hero body bob kept (top differs by 1)", tops[1] - tops[0] == 1, str(tops))

    # ---- grid JSON with source pivot / fps / loop settings
    d = json.loads((ROOT / "examples/sprites/slime.json").read_text(encoding="utf-8"))
    d["pivot"] = {"x": 8, "y": 15}
    d["unity"] = {"animations": {"idle": {"fps": 6, "loop": False}}}
    src = tmp / "slime_unity.json"
    src.write_text(json.dumps(d), encoding="utf-8")
    rep4 = ps.unity_sheet(src, out_dir=tmp / "unity_slime", cell=(20, 20), preview_scale=0)
    i4 = rep4["animations"][0]
    check("unity: source pivot + fps/loop honoured", rep4["pivot"]["source"]["mode"] == "point"
          and i4["fps"] == 6 and i4["loop"] is False and rep4["cell"] == (20, 20))
    rep5 = ps.unity_sheet(ROOT / "examples/sprites/blob_rig.json", out_dir=tmp / "unity_blob", preview_scale=0)
    check("unity: rig json exports", rep5["rows"] == 1 and rep5["columns"] == 2)

    # ---- error on a cell smaller than the content
    try:
        ps.unity_sheet(_synthetic(), out_dir=tmp / "unity_err", cell=(8, 8), preview_scale=0)
        check("unity: error on too-small cell", False)
    except ps.PixelError as e:
        check("unity: error on too-small cell", "smaller than the content" in str(e), str(e))

    # ---- CLI
    cli("unity-sheet", ROOT / "examples/sprites/hero.py", "-o", tmp / "unity_cli", "--preview-scale", "2",
        "--verbose", contains="Unity import note")
    cli("unity-sheet", ROOT / "examples/sprites/hero.py", "-o", tmp / "unity_cli2", "--cell", "16x16",
        expect=2, contains="smaller than the content")


if __name__ == "__main__":
    FAILS, N = [], [0]
    TMP = Path(tempfile.mkdtemp(prefix="spritewright_unity_"))

    def check(name, cond, detail=""):
        N[0] += 1
        print(f"[{'ok ' if cond else 'FAIL'}] {name}" + ("" if cond else f"  ({detail})"))
        if not cond:
            FAILS.append(name)

    def cli(*args, expect=0, contains=None):
        r = subprocess.run([sys.executable, str(ROOT / "spritewright.py"), *map(str, args)],
                           capture_output=True, text=True, cwd=str(ROOT), encoding="utf-8")
        out = r.stdout + r.stderr
        check("cli: " + " ".join(map(str, args))[:90],
              r.returncode == expect and (contains is None or contains in out), out[-400:])
        return out

    run(check, cli, TMP)
    print(f"\n{N[0] - len(FAILS)}/{N[0]} passed")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if FAILS else 0)
