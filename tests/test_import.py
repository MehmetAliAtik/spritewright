"""Tests: import (PNG/sheet/atlas -> grid JSON), grid detection / depixelize, blueprint.

Run standalone:  python tests/test_import.py
Also executed by tests/smoke_test.py (shared counters).
"""
import io
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
from PIL import Image, ImageFilter  # noqa: E402

import spritewright as ps  # noqa: E402
from spritewright import blueprint as bpm  # noqa: E402
from spritewright import importer as imp  # noqa: E402

PICO = ps.Palette.load("pico-8")


def _frames(n=6, w=8, h=8):
    """n distinct 8x8 frames (pico-8): a block moving 1 px per frame + a marker colour per frame."""
    out = []
    for i in range(n):
        cv = ps.Canvas(w, h, "pico-8")
        cv.rect(1 + (i % 3), 2, 4, 4, 8).pixel(0, h - 1, 1 + i)
        out.append(cv)
    return out


def _sheet(frames, cols, margin=0, spacing=0):
    w, h = frames[0].size
    rows = -(-len(frames) // cols)
    W = 2 * margin + cols * w + (cols - 1) * spacing
    H = 2 * margin + rows * h + (rows - 1) * spacing
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for i, cv in enumerate(frames):
        r, c = divmod(i, cols)
        img.paste(cv.to_image(1), (margin + c * (w + spacing), margin + r * (h + spacing)))
    return img


def _fake(src_img, scale, ox, oy, blur=0.0, noise=0.0, jpeg=0, bg=(255, 0, 255), seed=1):
    W, H = int(round(src_img.width * scale)), int(round(src_img.height * scale))
    up = src_img.resize((W, H), Image.NEAREST)
    cnv = Image.new("RGBA", (W + ox + 3, H + oy + 4), bg + (255,))
    cnv.alpha_composite(up, (ox, oy))
    img = cnv.convert("RGB")
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    if noise:
        a = np.asarray(img).astype(float) + np.random.default_rng(seed).normal(0, noise, (img.height, img.width, 3))
        img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    if jpeg:
        b = io.BytesIO()
        img.save(b, "JPEG", quality=jpeg)
        img = Image.open(io.BytesIO(b.getvalue())).convert("RGB")
    return img


def _crop_mismatch(a, b):
    """Pixel mismatch of two RGBA arrays after cropping both to their opaque bbox (-1 = shape differs)."""
    def crop(x):
        ys, xs = np.nonzero(x[..., 3] > 0)
        return x[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    a, b = crop(np.asarray(a)), crop(np.asarray(b))
    if a.shape != b.shape:
        return -1
    return int(np.any(a != b, -1).sum())


def run(check, cli, tmp):
    tmp = Path(tmp)
    fr = _frames()

    # ---- slicing with margin / spacing
    sheet = tmp / "imp_sheet.png"
    _sheet(fr, 3, margin=2, spacing=1).save(sheet)
    sp, rep = ps.import_image(sheet, out=tmp / "imp_sheet.json", frame="8x8", margin=2, spacing=1,
                              palette="pico-8", names="a,b,c,d,e,f")
    same = all((sp.frame(n).data == fr[i].data).all() for i, n in enumerate("abcdef"))
    check("import: margin/spacing slicing exact", same and list(sp.frames) == list("abcdef") and rep["exact"]
          and rep["frames"][4]["rect"] == [11, 11, 8, 8], json.dumps(rep["frames"][:2], default=str))
    sp2, _ = ps.import_image(sheet, out=tmp / "imp_sheet2.json", cols=3, rows=2, margin=2, spacing=1,
                             palette="pico-8", anim="run")
    check("import: --cols/--rows + --anim naming", sp2.w == 8 and list(sp2.frames)[0] == "run1"
          and sp2.get_animations() == {"run": [f"run{i}" for i in range(1, 7)]}
          and ps.load_sprite(tmp / "imp_sheet2.json").frame("run6").diff_count(fr[5]) == 0)
    try:
        ps.import_image(sheet, out=tmp / "x.json", cols=4, rows=2, margin=2, spacing=1, palette="pico-8")
        check("import: bad cols rejected", False)
    except ps.PixelError as e:
        check("import: bad cols rejected", "does not divide" in str(e), str(e))

    # ---- anim rows + skip empty
    rows_img = _sheet(fr[:3] + [ps.Canvas(8, 8, "pico-8")] + fr[3:5], 4)
    rows_png = tmp / "imp_rows.png"
    rows_img.save(rows_png)
    sp3, rep3 = ps.import_image(rows_png, out=tmp / "imp_rows.json", frame="8x8", palette="pico-8",
                                anim_rows="idle:3,walk")
    check("import: --anim-rows names rows, trailing empty cells dropped",
          sp3.get_animations() == {"idle": ["idle1", "idle2", "idle3"], "walk": ["walk1", "walk2"]}
          and sp3.frame("walk2").diff_count(fr[4]) == 0, str(sp3.get_animations()))
    sp4, rep4 = ps.import_image(rows_png, out=tmp / "imp_skip.json", frame="8x8", palette="pico-8", skip_empty=True)
    check("import: --skip-empty", len(sp4.frames) == 5 and rep4["notes"], str(list(sp4.frames)))

    # ---- off-palette remap + semi-alpha threshold reported
    arr = np.array(fr[0].to_image(1))
    arr[2, 2, :3] = (250, 5, 80)        # near pico red ff004d
    arr[3, 3, :3] = (250, 5, 80)
    arr[0, 0] = (255, 241, 232, 100)    # semi alpha -> transparent
    arr[0, 1] = (255, 241, 232, 200)    # semi alpha -> opaque
    off = tmp / "imp_off.png"
    Image.fromarray(arr, "RGBA").save(off)
    sp5, rep5 = ps.import_image(off, out=tmp / "imp_off.json", palette="pico-8")
    m = rep5["color_mapping"].get("fa0550", {})
    check("import: off-palette pixels remapped + reported", rep5["remapped_total"] == 2
          and m.get("to") == "ff004d" and m.get("count") == 2 and 0 < rep5["max_distance"] < 20
          and rep5["frames"][0]["remapped"] == 2 and not rep5["exact"], json.dumps(rep5["color_mapping"]))
    check("import: semi-alpha thresholded + counted", rep5["semi_alpha_total"] == 2
          and rep5["semi_to_opaque"] == 1 and rep5["semi_to_transparent"] == 1
          and sp5.frame(0).data[0, 0] == -1 and sp5.frame(0).data[0, 1] == 7)

    # ---- auto palette
    sp6, rep6 = ps.import_image(sheet, out=tmp / "auto" / "auto.json", frame="8x8", margin=2, spacing=1)
    check("import: auto palette (exact colours) saved next to sprite",
          rep6["palette_source"].startswith("auto") and rep6["exact"] and (tmp / "auto" / "auto_palette.json").is_file()
          and ps.load_sprite(tmp / "auto" / "auto.json").frame(5).to_rgba().tolist() == fr[5].to_rgba().tolist())
    noisy = np.random.default_rng(3).integers(0, 255, (16, 16, 4), dtype=np.uint8)
    noisy[..., 3] = 255
    try:
        ps.import_image(noisy, out=tmp / "n.json")
        check("import: >64 colours without palette -> error", False)
    except ps.PixelError as e:
        check("import: >64 colours without palette -> error", "--palette" in str(e), str(e))

    # ---- atlas round trip (unity-sheet -> import): exact cells, names, fps/loop, pivot, restore offsets
    src = ps.Sprite(24, 24, "pico-8", name="rt")
    for i in range(4):
        src.new_frame(f"idle{i + 1}").rect(8, 6 + (i % 2), 8, 16 - (i % 2), 12).pixel(9 + i, 8, 8)
    for i in range(3):
        src.new_frame(f"hit{i + 1}").rect(6 + i, 4, 10, 18, 9 + i)
    src.extra["unity"] = {"animations": {"idle": {"fps": 6, "loop": True}, "hit": {"fps": 12, "loop": False}}}
    src_path = tmp / "rt_src.json"
    src.save(src_path)
    out_dir = tmp / "rt_unity"
    urep = ps.unity_sheet(src_path, out_dir=out_dir, preview_scale=0)
    atlas_png = Path(urep["atlas"])
    isp, irep = ps.import_image(atlas_png, out=tmp / "rt_import.json")
    atl = np.array(Image.open(atlas_png).convert("RGBA"))
    ad = json.loads((out_dir / "atlas.json").read_text(encoding="utf-8"))
    mism = 0
    for k, f in ad["frames"].items():
        r = f["frame"]
        mism += int(np.any(atl[r["y"]:r["y"] + r["h"], r["x"]:r["x"] + r["w"]]
                           != isp.frame(f["source_frame"]).to_rgba(), -1).sum())
    ua = (isp.extra.get("unity") or {}).get("animations", {})
    check("import: atlas.json auto-read, round trip exact", irep["atlas"] and mism == 0 and irep["exact"]
          and list(isp.frames) == list(src.frames) and isp.get_animations() == src.get_animations(), f"{mism}")
    check("import: atlas fps/loop/pivot recovered", ua.get("hit") == {"fps": 12.0, "loop": False}
          and ua.get("idle", {}).get("fps") == 6.0 and isp.extra.get("pivot") == ad["pivot"]["pixel"], str(ua))
    rsp, _ = ps.import_image(atlas_png, out=tmp / "rt_restored.json", restore_offsets=True)
    check("import: --restore-offsets gives the source frames back", (rsp.w, rsp.h) == (24, 24)
          and all((rsp.frame(n).data == src.frame(n).data).all() for n in src.frames))
    urep2 = ps.unity_sheet(tmp / "rt_import.json", out_dir=tmp / "rt_unity2", preview_scale=0)
    a2 = np.array(Image.open(urep2["atlas"]).convert("RGBA"))
    check("import: re-export of the import reproduces atlas.png", a2.shape == atl.shape and (a2 == atl).all())

    # ---- grid detection on synthetic fake pixel art
    rng = np.random.default_rng(7)
    base = np.full((20, 24), -1, np.int16)
    for _ in range(40):  # blocky random shapes
        x, y = rng.integers(0, 22), rng.integers(0, 18)
        base[y:y + rng.integers(1, 4), x:x + rng.integers(1, 5)] = rng.integers(1, 16)
    art = ps.Canvas.from_array(base, "pico-8").to_image(1)
    ok, detail = True, []
    for scale, ox, oy, blur, noise in ((3, 1, 2, 0.0, 2.0), (5, 3, 0, 0.6, 3.0), (8, 5, 6, 0.8, 3.0),
                                       (11, 2, 9, 1.0, 4.0), (6.5, 2, 1, 0.5, 2.0)):
        img = _fake(art, scale, ox, oy, blur, noise, bg=(0, 0, 0))
        det = ps.detect_grid(img)
        out, _ = ps.depixelize(img, palette="pico-8", transparent="auto")
        mm = _crop_mismatch(out, art.convert("RGBA"))
        good = abs(det["size_float"] - scale) <= 0.06 and mm == 0
        if float(scale).is_integer():
            good = good and det["size"] == scale and tuple(det["offset"]) == (ox % scale, oy % scale)
        ok &= good
        detail.append(f"{scale}:{det['size']}@{det['offset']} mism={mm} conf={det['confidence']}")
    check("depixelize: block size/offset detected + pixels recovered (3,5,8,11,6.5 px, blur/noise)", ok,
          "; ".join(detail))
    hero = ps.load_sprite(ROOT / "examples/sprites/hero.py").frame(0).to_image(1)
    res = []
    for scale, ox, oy in ((8, 3, 5), (7, 2, 4)):
        img = _fake(hero, scale, ox, oy, blur=0.8, noise=3.0, jpeg=85)
        out, rep = ps.depixelize(img, palette=ROOT / "examples/sprites/hero_palette.json", transparent="auto")
        res.append((rep["detect"]["size"], tuple(rep["detect"]["offset"]), _crop_mismatch(out, hero)))
    check("depixelize: JPEG'd + blurred hero x8/x7 recovered exactly", res == [(8, (3, 5), 0), (7, (2, 4), 0)],
          str(res))
    out, rep = ps.depixelize(_fake(art, 4, 1, 1, noise=2.0, bg=(0, 0, 0)), colors=6)
    check("depixelize: --colors K limits colours", rep["colors"] <= 6 and rep["quantize"]["mode"] == "kmeans")

    # ---- blueprint
    bad = []
    for st in ("chibi", "normal"):
        for n in (16, 32, 48):
            b = ps.get_blueprint(n, st)
            miss = [k for k in bpm.REQUIRED if k not in b]
            if miss or bpm.points_inside(b) or b["approximate"] or b["size"] != [n, n] \
                    or not b["head_top"] < b["eye_line"] < b["chin"] <= b["neck"] < b["waist"] < b["ground"] \
                    or not b["shoulders"]["y"] < b["knees"]["y"] < b["feet"]["y"] < b["ground"] \
                    or b["pivot"] != [b["center_x"], b["ground"]]:
                bad.append(f"{st}{n}: {miss} {bpm.points_inside(b)}")
    check("blueprint: 16/32/48 chibi+normal have all keys, ordered, inside canvas", not bad, "; ".join(bad))
    b24 = ps.get_blueprint("24x24", "chibi")
    e = b24["eye_left"][0] + b24["eye_size"][0] - 1
    check("blueprint: arbitrary size scaled + flagged approximate (symmetric)", b24["approximate"]
          and not bpm.points_inside(b24) and b24["base_template"] in ("chibi_16", "chibi_32")
          and 2 * b24["center_x"] - 1 - e == b24["eye_right"][0], json.dumps(b24))
    bp32, paths = ps.save_blueprint(32, "chibi", out_dir=tmp / "bp", overlay=str(ROOT / "examples/sprites/hero.py"))
    im = Image.open(paths["png"])
    check("blueprint: PNG/JSON/TXT written", im.width >= 32 * 8 and paths["json"].is_file()
          and "eye line" in paths["txt"].read_text(encoding="utf-8"))
    st = ps.LayerStack(32, 32, "pico-8")
    st.add("body").rect(10, 10, 4, 4, 8)
    g = ps.add_blueprint_layer(st)
    check("blueprint: hidden underlay layer not flattened", not st.layer("blueprint").visible
          and (g.data >= 0).sum() > 20 and st.flatten().colors_used() == {8: 16})

    # ---- CLI
    out = cli("import", sheet, "-o", tmp / "cli_imp.json", "--frame", "8x8", "--margin", "2", "--spacing", "1",
              "--palette", "pico-8", "--report", tmp / "cli_imp_report.json", "--verbose", contains="EXACT")
    check("cli import report json", (tmp / "cli_imp_report.json").is_file() and "frame6" in out)
    cli("import", sheet, "--frame", "8x8", expect=2, contains="--project")  # needs project or -o
    fake_png = tmp / "fake.png"
    _fake(hero, 8, 3, 5, blur=0.6, noise=2.0).save(fake_png)
    cli("grid-detect", fake_png, contains="block size: 8 px")
    cli("depixelize", fake_png, "--report-only", contains="offset: x=3 y=5")
    cli("depixelize", fake_png, "-o", tmp / "fake_clean.png", "--palette", ROOT / "examples/sprites/hero_palette.json",
        "--transparent", "auto", "--sprite", tmp / "fake_clean.json", "-s", "4", contains="EXACT")
    check("cli depixelize -> png + sprite", (tmp / "fake_clean.png").is_file()
          and ps.load_sprite(tmp / "fake_clean.json").w >= 32)
    cli("blueprint", "--all", "-o", tmp / "bp_cli", contains="chibi_48x48.png")
    cli("blueprint", "--size", "20x24", "--style", "normal", "-o", tmp / "bp_cli", contains="APPROXIMATE")
    cli("blueprint", "--style", "anime", "-o", tmp / "bp_cli", expect=2, contains="unknown blueprint style")


if __name__ == "__main__":
    FAILS, N = [], [0]

    def _check(name, cond, detail=""):
        N[0] += 1
        print(f"[{'ok ' if cond else 'FAIL'}] api: {name}")
        if not cond:
            FAILS.append((name, detail))
            print("      ", str(detail)[:600])

    def _cli(*args, expect=0, contains=None):
        N[0] += 1
        r = subprocess.run([sys.executable, str(ROOT / "spritewright.py"), *map(str, args)], capture_output=True,
                           text=True, cwd=str(ROOT), encoding="utf-8", errors="replace")
        out = r.stdout + r.stderr
        ok = r.returncode == expect and (contains is None or contains in out)
        print(f"[{'ok ' if ok else 'FAIL'}] {' '.join(map(str, args))[:110]}")
        if not ok:
            FAILS.append((args, out[-600:]))
            print("      ", out[-600:])
        return out

    T = Path(tempfile.mkdtemp(prefix="spritewright_import_"))
    run(_check, _cli, T)
    print(f"\n{N[0] - len(FAILS)}/{N[0]} passed")
    shutil.rmtree(T, ignore_errors=True)
    sys.exit(1 if FAILS else 0)
