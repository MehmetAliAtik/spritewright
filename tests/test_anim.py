"""Tests: easing, tween, keyframes, oscillate, templates, CLI templates/anim-apply/tween/oscillate.

Run standalone:  python tests/test_anim.py
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
import spritewright as ps  # noqa: E402
from spritewright import anim  # noqa: E402


def _synthetic_rig(parts=("head", "body", "arm_l", "arm_r", "leg_l", "leg_r", "weapon"), alts=()):
    """32x32 rig with small boxes per part (pico-8)."""
    boxes = {"head": (12, 4, 8, 7, 15), "body": (11, 11, 10, 9, 12), "arm_l": (9, 12, 2, 6, 15),
             "arm_r": (21, 12, 2, 6, 15), "leg_l": (12, 20, 3, 6, 1), "leg_r": (17, 20, 3, 6, 1),
             "weapon": (23, 8, 1, 9, 6), "eyes": (14, 6, 4, 1, 0)}
    rig = ps.Rig(32, 32, "pico-8", name="synth")
    for z, p in enumerate(parts):
        x, y, w, h, c = boxes[p]
        rig.part(p, z=z, x=x, y=y, w=w, h=h).rect(0, 0, w, h, c)
    for p, a in alts:
        rig.alt(p, a).rect(0, 0, 1, 1, 8)
    return rig


def _rig_json(path, parts=("head", "body", "arm_l", "arm_r", "leg_l", "leg_r")):
    rig = _synthetic_rig(parts)
    rig.animation("idle", [{}])
    d = anim.rig_to_dict(rig)
    Path(path).write_text(json.dumps(d, indent=2), encoding="utf-8")
    return path


def run(check, cli, tmp):
    tmp = Path(tmp)
    # ---- easing: exact endpoints, monotonic (non-overshooting ones)
    ts = [i / 100 for i in range(101)]
    for n, f in anim.EASINGS.items():
        check(f"anim: easing {n} endpoints exact", f(0.0) == 0 and abs(f(1.0) - 1) < 1e-12)
    mono = all(all(f(a) <= f(b) + 1e-12 for a, b in zip(ts, ts[1:]))
               for n, f in anim.EASINGS.items() if n not in ("ease_out_back", "bounce"))
    check("anim: easings monotonic (except ease_out_back/bounce)", mono)
    check("anim: ease_out_back overshoots", max(anim.ease_out_back(t) for t in ts) > 1.0)
    check("anim: round half away from zero", [anim.round_half_away(v) for v in (0.5, -0.5, 1.5, 2.4, -2.6)]
          == [1, -1, 2, 2, -3])

    # ---- tween: integer only, exact endpoints, monotonic
    ok = True
    for e in anim.EASINGS:
        for n in (2, 3, 5, 7, 12):
            v = anim.tween((0, 0), (5, -7), n, e)
            ok &= len(v) == n and v[0] == (0, 0) and v[-1] == (5, -7)
            ok &= all(isinstance(a, int) and isinstance(b, int) for a, b in v)
    check("anim: tween integer + exact endpoints (all easings)", ok)
    lin = anim.tween(0, 10, 11, "linear")
    check("anim: linear tween 0..10", lin == list(range(11)))
    eo = anim.tween(0, -6, 5, "ease_out")
    check("anim: ease_out front-loaded + monotonic", eo[1] <= -3 and all(a >= b for a, b in zip(eo, eo[1:])), eo)
    kf = anim.keyframes([(2, (0, 0)), (4, (0, -3), "ease_out"), (6, (2, 0))], 7)
    check("anim: keyframes hit keys, hold outside", kf[0] == (0, 0) and kf[1] == (0, 0) and kf[3] == (0, -3)
          and kf[5] == (2, 0) and kf[6] == (2, 0), kf)

    # ---- oscillate: seamless when period divides frames, warning otherwise
    o = anim.oscillate(8, 2, 4)
    check("anim: oscillate sine values", o == [0, 2, 0, -2, 0, 2, 0, -2], o)
    nxt = anim.oscillate(9, 2, 4)[-1]
    check("anim: oscillate seamless loop (frame N == frame 0)", nxt == o[0] and anim.loop_warning(8, 4) is None)
    check("anim: oscillate warns when period does not divide frames", anim.loop_warning(6, 4) is not None)
    check("anim: oscillate abs = bounce (>= 0)", min(anim.oscillate(8, 2, 8, mode="abs")) == 0
          and max(anim.oscillate(8, 2, 8, mode="abs")) == 2)
    r = _synthetic_rig()
    w_ok = anim.rig_oscillate(r, "float", "body", 1, 4, frames=8)
    w_bad = anim.rig_oscillate(r, "float2", "body", 1, 3, frames=8)
    check("anim: rig_oscillate warning only for non-dividing period", w_ok == [] and len(w_bad) == 1)
    check("anim: rig_oscillate writes ints", all(isinstance(f.get("body", {}).get("dy", 0), int)
                                                for f in r.animations["float"]["frames"]))

    # ---- rig tween + multi-part keyframes
    r = _synthetic_rig()
    anim.rig_tween(r, "jump", "body", (0, 0), (0, -4), start=2, end=5, easing="ease_out", frames=6)
    dys = [f.get("body", {}).get("dy", 0) for f in r.animations["jump"]["frames"]]
    check("anim: rig_tween frame range exact", len(dys) == 6 and dys[1] == 0 and dys[4] == -4, dys)
    anim.rig_keyframes(r, "wave", {"arm_r": [(1, (0, 0)), (3, (0, -3))], "head": [(1, (0, 0)), (4, (1, 0))]},
                       frames=4)
    fr = r.animations["wave"]["frames"]
    check("anim: rig_keyframes multiple parts", fr[2]["arm_r"]["dy"] == -3 and fr[3]["head"]["dx"] == 1
          and fr[3]["arm_r"]["dy"] == -3)
    sp = r.build()
    check("anim: tweened rig builds", "jump6" in sp.frames and sp.frame("jump5").diff_count(sp.frame("jump1")) > 0)

    # ---- region tween in a plain frame sprite
    fsp = ps.Sprite(16, 16, "pico-8", name="fs")
    for i in range(4):
        fsp.new_frame(f"bob{i + 1}").rect(6, 6, 4, 4, 8)
    offs = anim.tween_region(fsp, (6, 6, 4, 4), (0, 0), (0, -3), "bob")
    check("anim: tween_region moves pixels", offs[-1] == (0, -3) and fsp.frame("bob4").bbox() == (6, 3, 4, 4)
          and fsp.frame("bob1").bbox() == (6, 6, 4, 4))

    # ---- templates: every template applies with declared frames/fps/loop
    lib = anim.load_templates()
    for tn, t in lib["templates"].items():
        rr = _synthetic_rig(alts=(("head", "blink"), ("body", "hurt")))
        rep = anim.apply_template(rr, tn, lib=lib)
        a = rr.animations[tn]
        sp = anim.build_sprite(rr)
        names = sp.get_animations()[tn]
        exp_fps = float(t["fps"])
        check(f"anim: template {tn} -> {rep['frames']} frames {rep['fps']:g} fps loop={rep['loop']}",
              len(a["frames"]) == t["frames"] == len(names) and rep["fps"] == exp_fps
              and rep["loop"] == t.get("loop", True)
              and sp.extra["unity"]["animations"][tn] == {"fps": exp_fps, "loop": t.get("loop", True)}
              and all(isinstance(s.get(k, 0), int) for f in a["frames"] for s in f.values() for k in ("dx", "dy")))
    rr = _synthetic_rig()
    rep = anim.apply_template(rr, "walk", frames=8, scale=2)
    lx = [f.get("leg_l", {}).get("dx", 0) for f in rr.animations["walk"]["frames"]]
    check("anim: walk 8-frame table + scale", len(lx) == 8 and max(lx) == 2 and min(lx) == -2, lx)
    rep = anim.apply_template(rr, "walk", frames=6, view="front", name="walk_front")
    check("anim: walk front view (no leg dx)", all("dx" not in f.get("leg_l", {})
                                                   for f in rr.animations["walk_front"]["frames"]))
    hb = anim.apply_template(_synthetic_rig(alts=(("body", "hurt"),)), "hurt")
    check("anim: hurt flash uses alt when present", not any("flash" in n for n in hb["notes"]))
    # body carries head: body dy must move the head too (no detaching)
    rr = _synthetic_rig()
    anim.apply_template(rr, "idle", frames=4)
    fr = rr.animations["idle"]["frames"]
    check("anim: head rides body offsets", all(f.get("head", {}).get("dy", 0) == f.get("body", {}).get("dy", 0)
                                              for f in fr) and any(f.get("body", {}).get("dy", 0) for f in fr))

    # ---- missing parts skipped gracefully
    blob = _synthetic_rig(parts=("body", "eyes"))
    rep = anim.apply_template(blob, "walk")
    check("anim: missing parts skipped with a note", len(blob.animations["walk"]["frames"]) == 6
          and any("skipped" in n and "leg_l" in n for n in rep["notes"]), rep["notes"])
    rep = anim.apply_template(blob, "idle", roles={"head": "eyes"})
    check("anim: role override maps head -> eyes", rep["roles"].get("head") == "eyes")

    # ---- rig JSON round trip + fps/loop reach unity-sheet
    rj = _rig_json(tmp / "anim_rig.json")
    d, rg, p = anim.load_rig_json(rj)
    anim.apply_template(rg, "death")
    anim.save_rig_json(d, rg, p, ["death"])
    sp = ps.load_sprite(p)
    out = tmp / "anim_unity"
    ps.unity_sheet(sp, out_dir=out, preview_scale=0)
    meta = json.loads((out / "atlas.json").read_text(encoding="utf-8"))
    death = [a for a in meta["animations"] if a["name"] == "death"][0] if isinstance(meta.get("animations"), list) \
        else meta["animations"]["death"]
    check("anim: death fps/loop flow into unity-sheet", death["fps"] == 8 and death["loop"] is False, death)

    # ---- CLI
    out = cli("templates", contains="walk")
    check("anim: cli templates lists all", all(t in out for t in ("idle", "run", "jump", "attack", "hurt", "death")))
    cj = _rig_json(tmp / "cli_rig.json")
    o2 = tmp / "cli_rig_out.json"
    cli("anim-apply", cj, "walk", "--frames", "8", "--scale", "1", "-o", o2, contains="saved")
    dd = json.loads(o2.read_text(encoding="utf-8"))
    w = dd["rig_animations"]["walk"]
    check("anim: cli anim-apply wrote rig json (-o, source untouched)", len(w["frames"]) == 8 and w["fps"] == 10
          and w["loop"] is True and "walk" not in json.loads(Path(cj).read_text(encoding="utf-8"))["rig_animations"])
    cli("anim-apply", o2, "attack", "--name", "slash", contains="skipped (no matching part): weapon")
    cli("anim-apply", o2, "nope", expect=2, contains="no template")
    cli("tween", o2, "--anim", "slash", "--part", "head", "--from", "0,0", "--to", "0,-2", "--ease", "ease_out",
        contains="slash/head: 0,0")
    cli("oscillate", o2, "--anim", "walk", "--part", "body", "--amp", "1", "--period", "3",
        contains="warning: oscillate: period 3")
    cli("info", o2, "--verbose", contains="slash: slash1")
    fs = tmp / "fs.json"
    fsp2 = ps.Sprite(16, 16, "pico-8", name="fs")
    for i in range(4):
        fsp2.new_frame(f"bob{i + 1}").rect(6, 6, 4, 4, 8)
    fsp2.save(fs)
    cli("oscillate", fs, "--anim", "bob", "-r", "6,6,4,4", "--amp", "1", "--period", "4", contains="saved")
    check("anim: cli oscillate region moved frame 2", ps.load_sprite(fs).frame("bob2").bbox() == (6, 7, 4, 4))


if __name__ == "__main__":
    FAILS, N = [], [0]
    TMP = Path(tempfile.mkdtemp(prefix="spritewright_anim_"))
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
