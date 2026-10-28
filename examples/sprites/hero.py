"""Example: 32x32 hero, 2-frame idle built with the part rig (body bob 1px + blink).

Run:  python spritewright.py run examples/sprites/hero.py      (exports to output/sprites/)
Load: python spritewright.py gif examples/sprites/hero.py             (CLI uses build())
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import spritewright as ps  # noqa: E402

HERE = Path(__file__).resolve().parent


def palette():
    pal = ps.Palette.load("pico-8").copy("hero-pico8")
    for name, idx in {"outline": 0, "hair_dk": 2, "hair": 4, "hair_lt": 9, "skin": 15,
                      "skin_dk": 13, "blush": 14, "eye": 1, "white": 7, "mouth": 2,
                      "tunic_lt": 11, "tunic": 3, "tunic_dk": 1, "belt": 4, "buckle": 10,
                      "pants": 2, "pants_lt": 13, "boot": 4}.items():
        pal.set_name(name, idx)
    pal.save(HERE / "hero_palette.json")
    return pal


C = {"H": "hair_dk", "h": "hair", "l": "hair_lt", "S": "skin", "s": "skin_dk", "b": "blush",
     "E": "eye", "W": "white", "m": "mouth", "g": "tunic_lt", "G": "tunic", "d": "tunic_dk",
     "B": "belt", "Y": "buckle", "P": "pants", "p": "pants_lt", "K": "boot"}

HEAD = [
    "....HHHHHH....",
    "..HHhhllhhHH..",
    ".HhhhllhhhhhH.",
    ".HhhlhhhhhhhH.",
    "HhhhhhhhhhhhhH",
    "HhhhShhhhShhhH",
    "HhSSSShhSSSShH",
    "HSSSSSSSSSSSSH",
    "HSSEWSSSSEWSSH",
    "HSSEESSSSEESSH",
    ".SbSSSSSSSSbS.",
    ".SSSSSmmSSSSS.",
    "..sSSSSSSSSs..",
]
BLINK_EYES = [  # rows 8-9 of the head replaced
    "HSSSSSSSSSSSSH",
    "HSSEESSSSEESSH",
]
BODY = [
    "....sSSs....",
    "..gGGGGGGd..",
    ".dgGGGGGGGd.",
    ".dgGGGGGGGd.",
    ".BBBBYYBBBB.",
    ".dgGGGGGGGd.",
    ".dddddddddd.",
]
ARM_L = [".g", "gG", "gG", "SS", "Ss"]
ARM_R = ["d.", "Gd", "Gd", "SS", "sS"]
LEGS = [
    "..pPP..pPP..",
    "..pPP..pPP..",
    "..KKK..KKK..",
    ".KKKK..KKKK.",
]


def build():
    pal = palette()
    rig = ps.Rig(32, 32, pal, name="hero")
    rig.part("legs", z=0).draw_grid(10, 26, LEGS, C)
    rig.part("body", z=1).draw_grid(10, 19, BODY, C)
    rig.part("arm_l", z=2).draw_grid(9, 20, ARM_L, C)
    rig.part("arm_r", z=2).draw_grid(21, 20, ARM_R, C)
    rig.part("head", z=3).draw_grid(9, 6, HEAD, C)
    rig.alt("head", "blink").draw_grid(9, 14, BLINK_EYES, C)
    bob = {"dx": 0, "dy": 1}
    rig.animation("idle", [
        {},
        {"head": {**bob, "swap": "blink"}, "body": bob, "arm_l": bob, "arm_r": bob},
    ], duration=[450, 250])
    sp = rig.build(outline="outline", connectivity=8)
    sp.name = "hero"
    return sp


if __name__ == "__main__":
    sp = build()
    out = ps.output_dir("test")
    sp.save(HERE / "hero.json")  # editable grid copy of the generated frames
    print(ps.gif(sp, out / "hero_idle.gif", anim="idle", scale=8))
    print(ps.apng(sp, out / "hero_idle_apng.png", anim="idle", scale=8))
    print(ps.sheet(sp, out / "hero_sheet.png"))
    print(ps.contact_sheet(sp, out / "hero_contact.png", scale=8))
    print(ps.render(sp.frame("idle1"), out / "hero_idle1.png", scale=8))
    print(ps.onion(sp, "idle1", "idle2", out / "hero_onion.png") and "onion ok")
    print("loop diff:", sp.loop_check("idle"))
