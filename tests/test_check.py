"""Tests: check (PASS/WARN/FAIL report for sources and Unity atlases).

Run standalone:  python tests/test_check.py
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


def _clean_sprite(lifts=(0, 0, 0), dup=False):
    """16x16, 3-frame walk: body block + a 2x2 marker moving 2 px per frame (no orphans)."""
    sp = ps.Sprite(16, 16, "pico-8", name="clean")
    for i, lift in enumerate(lifts):
        k = 0 if (dup and i == 1) else i
        cv = sp.new_frame(f"walk{i + 1}")
        cv.rect(4, 4 - lift, 8, 10, 12).rect(4 + 2 * k, 6 - lift, 2, 2, 8)
    sp.animations = {"walk": list(sp.frames)}
    return sp


def _by_id(rep, cid, group=None):
    return [c for g in rep["groups"] if group is None or g["name"] == group for c in g["checks"] if c["id"] == cid]


def _status(rep, cid, group=None):
    return {c["status"] for c in _by_id(rep, cid, group)}


def run(check, cli, tmp):
    tmp = Path(tmp)
    # ---- clean source passes
    rep = ps.check(_clean_sprite(), write=False)
    check("check: clean source has no WARN/FAIL", rep["summary"]["WARN"] == 0 and rep["summary"]["FAIL"] == 0
          and rep["exit_code"] == 0 and rep["summary_line"].startswith("check: "), rep["text"])

    # ---- clean atlas passes (atlas.json, folder and atlas.png inputs)
    good = tmp / "chk_good"
    ps.unity_sheet(_clean_sprite(), out_dir=good, preview_scale=0)
    rep = ps.check(good / "atlas.json", palette="pico-8", out=good / "report.json")
    check("check: clean atlas passes", rep["summary"]["FAIL"] == 0 and rep["summary"]["WARN"] == 0
          and _status(rep, "atlas.geometry") == {"PASS"} and _status(rep, "files.off_palette") == {"PASS"}, rep["text"])
    check("check: report json + txt written", (good / "report.json").is_file() and (good / "report.txt").is_file()
          and json.loads((good / "report.json").read_text(encoding="utf-8"))["summary"]["FAIL"] == 0)
    r2 = ps.check(good, palette="pico-8", write=False)
    r3 = ps.check(good / "atlas.png", palette="pico-8", write=False)
    check("check: folder / atlas.png inputs", r2["summary"] == rep["summary"] == r3["summary"])

    def broken(name, fn):
        d = tmp / name
        shutil.copytree(good, d)
        a = np.array(Image.open(d / "atlas.png").convert("RGBA"))
        a = fn(a)
        Image.fromarray(a, "RGBA").save(d / "atlas.png")
        return ps.check(d / "atlas.json", palette="pico-8", write=False)

    def first_opaque(a):
        ys, xs = np.nonzero(a[..., 3] == 255)
        return ys[0], xs[0]

    def semi(a):
        y, x = first_opaque(a)
        a[y, x, 3] = 128
        return a
    rep = broken("chk_semi", semi)
    check("check: semi-transparent pixel -> FAIL", _status(rep, "files.alpha") == {"FAIL"} and rep["exit_code"] == 1)

    def offpal(a):
        y, x = first_opaque(a)
        a[y, x, :3] = (1, 2, 3)
        return a
    rep = broken("chk_offpal", offpal)
    c = _by_id(rep, "files.off_palette")[0]
    check("check: off-palette pixel -> FAIL", c["status"] == "FAIL" and "#010203" in c["details"]["atlas.png"]["colors"],
          str(c))

    rep = broken("chk_size", lambda a: np.ascontiguousarray(a[:, :-1]))
    c = _by_id(rep, "atlas.geometry")[0]
    check("check: non-divisible sheet -> FAIL", c["status"] == "FAIL" and rep["exit_code"] == 1
          and any("is not a multiple of cell" in f for f in c["details"]["fail"]), str(c))

    # ---- foot drift (frame 2 lifted 3 px -> WARN, 6 px -> FAIL); rig-style body bob does not trigger it
    rep = ps.check(_clean_sprite(lifts=(0, 3, 0)), write=False)
    c = _by_id(rep, "anim.foot_drift")[0]
    check("check: foot drift detected", c["status"] == "WARN" and c["details"]["dy_from_pivot"]["walk2"] == 3, str(c))
    rep = ps.check(_clean_sprite(lifts=(0, 6, 0)), write=False)
    check("check: large foot drift -> FAIL", _status(rep, "anim.foot_drift") == {"FAIL"} and rep["exit_code"] == 1)
    rep = ps.check(ROOT / "examples/sprites/hero.py", atlas=False, write=False)
    check("check: hero body bob is not foot drift", _status(rep, "anim.foot_drift") == {"PASS"}
          and _status(rep, "anim.size_drift") == {"PASS"}, rep["text"])

    # ---- identical consecutive frames -> WARN (motion)
    rep = ps.check(_clean_sprite(dup=True), write=False)
    c = _by_id(rep, "anim.motion")[0]
    check("check: identical frames warn", c["status"] == "WARN" and c["details"]["identical"] == ["walk1->walk2"],
          str(c))

    # ---- loop seam: small steps, big jump back -> WARN; loop=false -> SKIP
    sp = ps.Sprite(16, 16, "pico-8", name="seam")
    for i in range(4):
        sp.new_frame(f"run{i + 1}").rect(2, 4, 12, 10, 12).rect(2 + 3 * i, 6, 2, 2, 8)
    sp.new_frame("run5").rect(2, 4, 12, 10, 12).rect(2, 6, 2, 2, 8).rect(2, 10, 12, 4, 9)
    rep = ps.check(sp, write=False)
    check("check: loop seam jump warns", _status(rep, "anim.loop_seam") == {"WARN"}, rep["text"])
    sp.extra["unity"] = {"loop": False}
    check("check: non-looping anim skips seam", _status(ps.check(sp, write=False), "anim.loop_seam") == {"SKIP"})

    # ---- orphans reported with coordinates
    sp = _clean_sprite()
    for x, y in ((5, 10), (9, 10), (5, 12), (10, 12)):  # inside the body: bbox unchanged
        sp.frame("walk2").pixel(x, y, 7)
    rep = ps.check(sp, write=False)
    c = _by_id(rep, "anim.orphans")[0]
    pts = {(p["x"], p["y"]) for p in c["details"].get("walk2", {}).get("pixels", [])}
    check("check: orphan count + coordinates", c["status"] == "WARN" and c["details"]["walk2"]["count"] == 4
          and (10, 12) in pts and rep["exit_code"] == 0, str(c)[:300])

    # ---- colour limit (WARN) and source+atlas auto-pairing for the hero rig
    check("check: colour limit warns", _status(ps.check(_clean_sprite(), write=False, max_colors=1),
                                               "colors.count") == {"WARN"})
    out = tmp / "chk_hero"
    ps.unity_sheet(ROOT / "examples/sprites/hero.py", out_dir=out, preview_scale=0)
    rep = ps.check(ROOT / "examples/sprites/hero.py", atlas=out, write=False)
    check("check: source + atlas (hero) no FAIL, atlas in sync", rep["exit_code"] == 0
          and _status(rep, "atlas.sync") == {"PASS"} and any(g["name"] == "atlas/idle" for g in rep["groups"]),
          rep["text"])

    # ---- CLI: exit code 0 on clean, 1 on FAIL
    cli("check", good / "atlas.json", "--palette", "pico-8", "-o", tmp / "chk_cli/ok.json", contains="0 FAIL")
    cli("check", tmp / "chk_semi", "--palette", "pico-8", "--no-write", expect=1, contains="files.alpha")
    cli("check", ROOT / "examples/sprites/slime.json", "--json", "--no-write", contains='"summary_line"')


if __name__ == "__main__":
    FAILS, N = [], [0]
    TMP = Path(tempfile.mkdtemp(prefix="spritewright_check_"))
    sys.stdout.reconfigure(errors="replace")

    def check(name, cond, detail=""):
        N[0] += 1
        print(f"[{'ok ' if cond else 'FAIL'}] {name}" + ("" if cond else f"  ({detail})"))
        if not cond:
            FAILS.append(name)

    def cli(*args, expect=0, contains=None):
        r = subprocess.run([sys.executable, str(ROOT / "spritewright.py"), *map(str, args)],
                           capture_output=True, text=True, cwd=str(ROOT), encoding="utf-8", errors="replace")
        out = r.stdout + r.stderr
        check("cli: " + " ".join(map(str, args))[:90],
              r.returncode == expect and (contains is None or contains in out), out[-400:])
        return out

    run(check, cli, TMP)
    print(f"\n{N[0] - len(FAILS)}/{N[0]} passed")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if FAILS else 0)
