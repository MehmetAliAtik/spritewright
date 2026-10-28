"""Test_Hero (Test_Game): chibi adventurer, side view facing right, 32x32, pivot = feet (16,30)."""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[5]  # repo root (examples/Test_Game/characters/Test_Hero/source)
sys.path.insert(0, str(ROOT))
import spritewright as ps
from spritewright import anim
HERE = Path(__file__).resolve().parent

C = {"h": "hair", "H": "gold", "r": "brown", "k": "skin", "s": "brown", "e": "outline",
     "g": "foliage", "G": "foliage_shadow", "b": "brown", "y": "gold"}   # PICO-8 game palette roles

HEAD = [  # x=9, y=5 (14x13), face to the right
    "....hhhhhhh...",
    "..hhHHHHhhhh..",
    ".hhHHhhhhhhhh.",
    ".hhhhhhhhhhhhh",
    "rhhhhhhhhhhhhh",
    "rhhhhhhhhhhhhh",
    "rrhhhkkhkkhkkk",
    "rrhhkkkkkkekkk",
    "rrrhkkkkkkekkk",
    ".rrhkkkkkkkkkk",
    ".rrrkkkkkkkksk",
    "..rrrkkkkkkkk.",
    ".....kkkkss...",
]
BODY = [  # x=12, y=18
    ".ggggggg.",
    ".gggggggG",
    ".ggggggGG",
    ".bbbbbybb",
    ".ggggggGG",
    ".gggggGGG",
]
# legs: 9x6 grids at x=11, y=24 (hip = cols 4-5); foot bottom row = y29
LEG = {
    "stand": ["....kk...", "....kk...", "....bb...", "....bb...", "....bbb..", "....bbbb."],
    "mid":   ["....kk...", "....kk...", ".....kk..", ".....bb..", ".....bbb.", ".....bbbb"],
    "fwd":   ["....kk...", ".....kk..", ".....bb..", "......bb.", "......bbb", "......bbb"],
    "back":  ["....kk...", "...kk....", "..kk.....", "..bb.....", ".bbb.....", "..bbb...."],
    "backlift": ["....kk...", "...kk....", "..kk.....", "..bb.....", ".bbb.....", "........."],
    "pass":  ["....kk...", "....kkk..", "....bbb..", "....bbbb.", ".........", "........."],
}
# arms: 6x4 grids at x=13, y=19 (shoulder = cols 2-3)
ARM = {
    "mid":  ["..GG..", "..ks..", "..ks..", "..kk.."],
    "fwd":  ["..GG..", "...ks.", "....ks", "....kk"],
    "back": ["..GG..", ".ks...", "ks....", "kk...."],
}
FAR = {"k": "brown", "s": "brown", "G": "shadow_dark", "b": "shadow"}   # far limbs darker


def palette():
    return ps.Palette.load(HERE / "Test_Hero_palette.json")


def build_rig():
    pal = palette()
    rig = ps.Rig(32, 32, pal, name="test_hero")
    far = dict(C, **FAR)
    rig.part("arm_l", z=0).draw_grid(12, 19, ARM["mid"], far)
    rig.part("leg_l", z=1).draw_grid(11, 24, LEG["stand"], far)
    rig.part("leg_r", z=2).draw_grid(11, 24, LEG["stand"], C)
    rig.part("body", z=3).draw_grid(12, 18, BODY, C)
    rig.part("head", z=4).draw_grid(9, 5, HEAD, C)
    rig.part("arm_r", z=5).draw_grid(13, 19, ARM["mid"], C)
    for pose, g in LEG.items():
        rig.alt("leg_l", pose, copy=False).draw_grid(11, 24, g, far)
        rig.alt("leg_r", pose, copy=False).draw_grid(11, 24, g, C)
    for pose, g in ARM.items():
        rig.alt("arm_l", pose, copy=False).draw_grid(12, 19, g, far)
        rig.alt("arm_r", pose, copy=False).draw_grid(13, 19, g, C)
    rig.alt("head", "blink").draw_grid(19, 12, ["k"], C)   # eye closes to its lower pixel
    return rig


def walk(rig):
    #        near leg     far leg     near arm  far arm  bob
    keys = [("fwd",      "back",     "back",   "fwd",   0),   # contact A
            ("mid",      "backlift", "back",   "fwd",   1),   # down
            ("stand",    "pass",     "mid",    "mid",   0),   # passing
            ("back",     "fwd",      "fwd",    "back",  0),   # contact B
            ("backlift", "mid",      "fwd",    "back",  1),   # down
            ("pass",     "stand",    "mid",    "mid",   0)]   # passing
    frames = []
    for nl, fl, na, fa, dy in keys:
        frames.append({"leg_r": {"swap": nl}, "leg_l": {"swap": fl},
                       "arm_r": {"swap": na, "dy": dy}, "arm_l": {"swap": fa, "dy": dy},
                       "body": (0, dy), "head": (0, dy)})
    rig.animation("walk", frames, duration=100)


def idle(rig):
    body, head = [0, 1, 1, 0], [0, 0, 1, 1]          # head lags the torso by one frame
    frames = [{"body": (0, b), "head": (0, h), "arm_r": (0, b), "arm_l": (0, b)}
              for b, h in zip(body, head)]
    frames[3]["head"] = {"dy": 1, "swap": "blink"}
    rig.animation("idle", frames, duration=[250, 150, 250, 150])


if __name__ == "__main__":
    rig = build_rig()
    idle(rig)
    walk(rig)
    d = anim.rig_to_dict(rig, base_dir=HERE, outline="outline", connectivity=8)
    (HERE / "test_hero.json").write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
    print("wrote", (HERE / "test_hero.json").name)
