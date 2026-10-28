"""Demo: hero rig with split legs -> examples/sprites/hero_anim.json, idle from a template (API).

Run:   python spritewright.py run examples/sprites/make_hero_anim.py
Then:  python spritewright.py anim-apply examples/sprites/hero_anim walk --frames 6
Reuses the drawings of hero.py (not modified); legs are split into leg_l / leg_r so walk can move them.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import runpy  # noqa: E402

import spritewright as ps  # noqa: E402
from spritewright import anim  # noqa: E402

HERE = Path(__file__).resolve().parent
H = runpy.run_path(str(HERE / "hero.py"), run_name="hero_assets")  # constants only (no __main__)


def build_rig():
    pal = ps.Palette.load("hero_palette.json", base_dir=HERE)
    C = H["C"]
    rig = ps.Rig(32, 32, pal, name="hero_anim")
    legs = H["LEGS"]
    rig.part("leg_l", z=0).draw_grid(10, 26, [r[:6] for r in legs], C)
    rig.part("leg_r", z=0).draw_grid(16, 26, [r[6:] for r in legs], C)
    rig.part("body", z=1).draw_grid(10, 19, H["BODY"], C)
    rig.part("arm_l", z=2).draw_grid(9, 20, H["ARM_L"], C)
    rig.part("arm_r", z=2).draw_grid(21, 20, H["ARM_R"], C)
    rig.part("head", z=3).draw_grid(9, 6, H["HEAD"], C)
    rig.alt("head", "blink").draw_grid(9, 14, H["BLINK_EYES"], C)
    return rig


if __name__ == "__main__":
    rig = build_rig()
    rep = anim.apply_template(rig, "idle")
    print(f"idle: {rep['frames']} frames, {rep['fps']:g} fps, notes: {rep['notes']}")
    d = anim.rig_to_dict(rig, base_dir=HERE, outline="outline", connectivity=8)
    out = HERE / "hero_anim.json"
    import json
    out.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
    print("saved", out)
