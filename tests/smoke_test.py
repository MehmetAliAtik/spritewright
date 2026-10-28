"""Smoke test: every CLI command once + grid error messages + core API checks.

Run:  python tests/smoke_test.py      (exit code 0 = pass; --keep keeps the temp folder)
All outputs go to a temp dir; project files are not modified.
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
import spritewright as ps  # noqa: E402

PY = sys.executable
# source checkout: python spritewright.py; a copy of tests/ next to no package: the installed one (-m)
if (ROOT / "spritewright" / "__init__.py").is_file():
    CLI = [PY, str(ROOT / "spritewright.py")]
else:
    CLI = [PY, "-m", "spritewright"]
TMP = Path(tempfile.mkdtemp(prefix="spritewright_smoke_"))
# every default output (output/<project>/, outputs/, projects/) goes below TMP; subprocesses inherit this
os.environ["SPRITEWRIGHT_OUTPUT"] = str(TMP / "output")
os.environ["SPRITEWRIGHT_OUTPUTS"] = str(TMP / "outputs")
os.environ["SPRITEWRIGHT_PROJECTS"] = str(TMP / "projects")
for _k in ("SPRITEWRIGHT_PALETTES", "PIXELSTUDIO_OUTPUT", "PIXELSTUDIO_OUTPUTS"):
    os.environ.pop(_k, None)
FAILS = []
COUNT = 0


def cli(*args, expect=0, contains=None):
    global COUNT
    COUNT += 1
    r = subprocess.run([*CLI, *map(str, args)], capture_output=True,
                       text=True, cwd=str(ROOT), encoding="utf-8", errors="replace")
    out = r.stdout + r.stderr
    ok = r.returncode == expect and (contains is None or contains in out)
    tag = "ok " if ok else "FAIL"
    print(f"[{tag}] {' '.join(map(str, args))[:110]}")
    if not ok:
        FAILS.append((args, r.returncode, out.strip()[-800:]))
        print("      ", out.strip()[-800:].replace("\n", "\n       "))
    return out


def check(name, cond, detail=""):
    global COUNT
    COUNT += 1
    print(f"[{'ok ' if cond else 'FAIL'}] api: {name}")
    if not cond:
        FAILS.append((name, detail, ""))


def _portrait(path):
    """Smooth 160x160 RGB test image (gradient + discs) for quantize."""
    from PIL import Image, ImageDraw
    ys, xs = np.mgrid[0:160, 0:160]
    arr = np.stack([xs * 255 // 159, ys * 255 // 159, (xs + ys) * 255 // 318], -1).astype(np.uint8)
    im = Image.fromarray(arr, "RGB")
    d = ImageDraw.Draw(im)
    d.ellipse([40, 30, 120, 110], fill=(230, 190, 150))
    d.ellipse([60, 55, 72, 67], fill=(30, 30, 60))
    d.ellipse([88, 55, 100, 67], fill=(30, 30, 60))
    d.rectangle([30, 115, 130, 159], fill=(90, 40, 140))
    im.save(path)
    return path


def synthetic_palette(path, n=24):
    """Test-only palette file: n synthetic colours (an HSV sweep), not a copy of any published palette."""
    import colorsys
    cols = []
    for i in range(n):
        r, g, b = colorsys.hsv_to_rgb((i * 0.618034) % 1.0, 0.35 + 0.6 * (i % 3) / 2, 0.25 + 0.7 * (i % 5) / 4)
        cols.append("%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255)))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(cols) + "\n", encoding="utf-8")
    return Path(path)


def main():
    slime = TMP / "slime.json"
    shutil.copy(ROOT / "examples/sprites/slime.json", slime)
    rig = ROOT / "examples/sprites/blob_rig.json"
    hero = ROOT / "examples/sprites/hero.py"
    portrait = _portrait(TMP / "portrait.png")  # synthetic RGB image (no dependency on old output/ files)

    synth = synthetic_palette(TMP / "pals" / "synth-24.hex")
    # --- palettes / colors
    cli("palettes", contains="pico-8")
    cli("palette-show", "pico-8", "-o", TMP / "swatch.png", contains="#1d2b53")
    cli("palette-create", TMP / "custom.json", "skin=f2c39b", "ink=101820", contains="2 colors")
    cli("palette-create", TMP / "custom2.json", "skin=f2c39b", "--base", "pico-8", "--extend",
        contains="17 colors")
    cli("ramp", "f2c39b", "--steps", "5", "-o", TMP / "ramp.png", contains="ramp:")
    cli("ramp", "3060c0", "--palette", "pico-8", contains="indices:")
    # user palette folders: a .hex path, then by name via SPRITEWRIGHT_PALETTES
    cli("palette-show", synth, contains="synth-24 (24)")
    os.environ["SPRITEWRIGHT_PALETTES"] = str(synth.parent)
    cli("palettes", contains="synth-24(24)")
    cli("palette-show", "synth-24", contains="synth-24 (24)")
    check("palette dirs: env folder first, bundled last", ps.palette_dirs()[0].resolve() == synth.parent.resolve()
          and ps.palette_dirs()[-1].resolve() == ps.paths.BUNDLED_PALETTES.resolve())
    os.environ.pop("SPRITEWRIGHT_PALETTES")
    cli("palette-show", "synth-24", expect=2, contains="SPRITEWRIGHT_PALETTES")
    # --- project / inspection
    cli("new", "_smoketmp", "s1", "--size", "16x16", "--palette", "pico-8", "--frames", "a1,a2",
        contains="created")
    check("new writes below SPRITEWRIGHT_PROJECTS", (TMP / "projects" / "_smoketmp" / "s1.json").is_file()
          and not (ROOT / "projects" / "_smoketmp").exists())
    cli("validate", slime, contains="OK")
    cli("validate", rig, contains="OK")
    cli("info", hero, contains="idle")
    cli("ascii", slime, "-f", "idle1", contains="#000000")
    # --- output
    cli("render", slime, "-f", "idle1", "-s", "8", "-o", TMP / "r.png")
    cli("render", rig, "-f", "1", "-s", "4", "--bg", "checker", "-o", TMP / "r2.png")
    cli("sheet", slime, "-o", TMP / "sheet.png")
    cli("gif", rig, "-a", "idle", "-s", "6", "-o", TMP / "a.gif", contains='"verified": true')
    cli("gif", slime, "--fps", "4", "--bg", "#202030", "-o", TMP / "b.gif", contains='"verified": true')
    cli("gif", slime, "--apng", "-o", TMP / "a.png", contains='"verified": true')
    cli("contact", hero, "-o", TMP / "contact.png")
    cli("inspect", slime, "-f", "idle1", "-r", "4,6,8,6", "-z", "20", "--indices", "-o", TMP / "insp.png")
    cli("preview", slime, "idle1", "idle2", "-o", TMP / "onion.png")
    cli("diff", slime, "idle1", "idle2", "-o", TMP / "diff.png", contains="pixels differ")
    cli("quantize", portrait, "--palette", "pico-8", "--size", "64x64",
        "-o", TMP / "q1.png", "--json", TMP / "q1.json")
    cli("quantize", portrait, "--palette", synth, "--size", "48x48",
        "--dither", "bayer4", "-o", TMP / "q2.png")
    cli("quantize", portrait, "--palette", "pico-8", "--size", "32x32",
        "--dither", "floyd", "-o", TMP / "q3.png")
    cli("validate", TMP / "q1.json", contains="OK")
    # --- helpers that modify sources (on the temp copy)
    cli("outline", slime, "--selective", "--connectivity", "4", "-o", TMP / "s_sel.json", contains="saved")
    cli("outline", slime, "-f", "idle1", "--color", "1", "-o", TMP / "s_out.json", contains="saved")
    cli("shade", slime, "--mask-color", "11", "--ramp", "1,3,11,10", "--depth", "1", contains="saved")
    cli("clean", slime, contains="orphan")
    cli("clean", slime, "--remove", "--isolated-only", contains="orphan")
    cli("frame", slime, "copy", "idle1", "idle3", contains="saved")
    cli("frame", slime, "shift", "idle3", "--dx", "1", "--dy", "-1", "--wrap", contains="saved")
    cli("frame", slime, "flip-h", "idle3", contains="saved")
    cli("frame", slime, "flip-v", "idle3", contains="saved")
    cli("frame", slime, "mirror", "idle3", "--direction", "lr", contains="saved")
    cli("frame", slime, "recolor", "idle3", "--map", "11=8,3=7", contains="saved")
    cli("frame", slime, "onion", "idle1", "idle3", "-o", TMP / "on2.png")
    cli("frame", slime, "loopcheck", "--anim", "idle", contains="diff")
    cli("frame", slime, "delete", "idle3", contains="saved")
    cli("attach-palette", slime, synth, "--snap", "-o", TMP / "s64.json", contains="saved")
    cli("export-json", hero, "-o", TMP / "hero_export.json")
    cli("validate", TMP / "hero_export.json", contains="OK")
    cli("run", ROOT / "examples/sprites/hero.py", contains="verified")
    cli("outline", hero, "--color", "0", expect=2, contains=".py script")

    # --- grid error messages
    base = json.loads((ROOT / "examples/sprites/slime.json").read_text(encoding="utf-8"))

    def bad(mutate, needle):
        d = json.loads(json.dumps(base))
        mutate(d)
        p = TMP / "bad.json"
        p.write_text(json.dumps(d), encoding="utf-8")
        cli("validate", p, expect=2, contains=needle)

    bad(lambda d: d["frames"]["idle2"]["rows"].__setitem__(2, "." * 15),
        "frame 'idle2' row 3 (y=2): length 15, expected 16")
    bad(lambda d: d["frames"]["idle1"]["rows"].__setitem__(1, "....Z..........."),
        "frame 'idle1' row 2 (y=1) col 5 (x=4): unknown char 'Z'")
    bad(lambda d: d["chars"].__setitem__("X", "#123456"), "is not in palette 'pico-8'")
    bad(lambda d: d["frames"]["idle1"]["rows"].pop(), "has 15 rows, expected 16")
    bad(lambda d: d["chars"].__setitem__("XY", 1), "must be exactly one character")
    bad(lambda d: d["animations"].__setitem__("run", ["run1"]), "unknown frame 'run1'")

    # --- API checks
    cv = ps.Canvas(32, 32, "pico-8")
    try:
        cv.pixel(0, 0, "#123456")
        check("strict mode rejects off-palette", False)
    except ps.ColorError as e:
        check("strict mode rejects off-palette", "not in palette" in str(e))
    try:
        cv.pixel(0, 0, 99)
        check("index range error", False)
    except ps.ColorError as e:
        check("index range error", "out of range" in str(e))
    cv.symmetry("x")
    cv.pixel(3, 5, 4).line(0, 10, 10, 20, 9).ellipse(2, 2, 9, 7, 6, fill=False)
    cv.symmetry(None)
    check("symmetry x mirrors all ops", np.array_equal(cv.data, cv.data[:, ::-1]))
    e = ps.Canvas(32, 32, "pico-8").ellipse(4, 6, 20, 13, 3)
    check("ellipse fits bbox exactly", e.bbox() == (4, 6, 20, 13), str(e.bbox()))
    check("ellipse symmetric", np.array_equal(e.data[6:19, 4:24], e.data[6:19, 4:24][:, ::-1])
          and np.array_equal(e.data[6:19, 4:24], e.data[6:19, 4:24][::-1, :]))
    p = ps.Canvas(16, 16, "pico-8").polygon([(1, 1), (14, 1), (8, 14)], 8)
    check("polygon filled", p.data[5, 8] == 8 and p.data[1, 1] == 8 and p.data[14, 1] == -1)
    f = ps.Canvas(16, 16, "pico-8").rect(2, 2, 10, 10, 1, fill=False).flood_fill(5, 5, 9)
    check("flood fill bounded", f.data[5, 5] == 9 and f.data[0, 0] == -1)
    g = ps.Canvas(32, 16, "pico-8").gradient(None, 7, 1, direction="h")
    check("gradient uses ramp", g.data[0, 0] == 7 and g.data[0, 31] == 1 and len(g.colors_used()) >= 3)
    d = ps.Canvas(16, 16, "pico-8").dither((0, 0, 16, 16), 7, 0, pattern="bayer4", level=25)
    check("dither 25%", d.colors_used().get(7) == 64)
    s = ps.Canvas(8, 8, "pico-8").draw_grid(0, 0, ["AB", "A."], {"A": 8, "B": 12})
    t = ps.Canvas(16, 16, "pico-8").stamp(s, 4, 4, flip_h=True, rotate=90)
    check("stamp flip+rotate", t.colors_used() == {8: 2, 12: 1})
    st = ps.LayerStack(16, 16, "pico-8")
    st.add("a").rect(0, 0, 16, 16, 7)
    st.add("b", opacity=0.5).rect(0, 0, 8, 16, 0)
    st.add("c", blend="multiply").rect(8, 0, 8, 16, 12)
    fl = st.flatten()
    check("layer flatten snaps to palette", fl.data.min() >= 0 and fl.data[0, 0] not in (7, 0))
    o = ps.Canvas(16, 16, "pico-8").rect(4, 4, 8, 8, 15).outline(selective=True)
    check("selective outline darker", o.data[3, 6] >= 0 and ps.luminance(o.palette.colors[o.data[3, 6]])
          < ps.luminance(o.palette.colors[15]))
    o4 = ps.Canvas(16, 16, "pico-8").rect(4, 4, 8, 8, 15).outline(1, connectivity=4)
    check("4-conn outline skips corners", o4.data[3, 3] == -1 and o4.data[3, 4] == 1)
    c = ps.Canvas(16, 16, "pico-8").rect(2, 2, 6, 6, 3)
    c.pixel(12, 12, 8)
    orph = c.orphans()
    check("orphan detection", len(orph) == 1 and orph[0]["isolated"])
    ramp = ps.generate_ramp("3060c0", 5)
    check("ramp 5 steps dark->light", len(ramp) == 5 and ps.luminance(ps.parse_hex(ramp[0]))
          < ps.luminance(ps.parse_hex(ramp[4])))
    sp = ps.load_sprite(rig)
    check("rig json builds frames", list(sp.frames) == ["idle1", "idle2"] and sp.loop_check("idle") > 0)
    try:
        r = ps.Rig(16, 16, "pico-8")
        r.part("a")
        r.animation("x", [{"a": {"dx": 0.5}}])
        check("subpixel offsets rejected", False)
    except ps.PixelError as ex:
        check("subpixel offsets rejected", "integer" in str(ex))

    # --- unity-sheet (tests/test_unity_sheet.py)
    sys.path.insert(0, str(ROOT / "tests"))
    import test_unity_sheet
    test_unity_sheet.run(check, cli, TMP)

    # --- check (tests/test_check.py)
    import test_check
    test_check.run(check, cli, TMP)

    # --- animation helpers (tests/test_anim.py)
    import test_anim
    test_anim.run(check, cli, TMP)

    # --- import / depixelize / blueprint (tests/test_import.py)
    import test_import
    test_import.run(check, cli, TMP)

    # --- Claude Code skill + installer (tests/test_skill.py)
    import test_skill
    test_skill.run(check, cli, TMP)

    # --- game layout + style guide (tests/test_layout.py)
    import test_layout
    test_layout.run(check, cli, TMP)

    # --- build / context / quiet output / e2e bug fixes (tests/test_build.py)
    import test_build
    test_build.run(check, cli, TMP)

    # --- release hygiene: --version, help texts, English, no personal paths (tests/test_release.py)
    import test_release
    test_release.run(check, cli, TMP)

    print(f"\n{COUNT - len(FAILS)}/{COUNT} passed; temp outputs in {TMP}")
    if FAILS:
        print("FAILURES:")
        for f_ in FAILS:
            print("  ", f_[0], f_[1])
        sys.exit(1)
    if "--keep" not in sys.argv:
        shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    main()
