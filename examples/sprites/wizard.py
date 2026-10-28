"""Example: 64x64 detail test - young wizard bust waving.

Uses the drawing API: layers, symmetry for the face, polygon/ellipse, dithered gradient (hat),
dither (blush), shade-assist with ramps, per-layer selective outline, hand drawn with draw_grid.
Run:  python spritewright.py run examples/sprites/wizard.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import spritewright as ps  # noqa: E402

HERE = Path(__file__).resolve().parent

NAMES = {"ink": 0, "navy": 1, "skin_dd": 2, "skin_d": 4, "skin_s": 14, "skin": 15, "skin_l": 7,
         "hair_dd": 2, "hair_d": 4, "hair": 9, "hair_l": 10, "hat_d": 13, "hat": 12, "hat_l": 6,
         "robe_d": 2, "robe": 8, "robe_l": 14, "gold_d": 9, "gold": 10, "gold_l": 7,
         "white": 7, "iris": 12, "mouth": 2, "tongue": 8, "blush": 14}  # PICO-8 indices

RAMPS = {
    "skin": ["skin_dd", "skin_d", "skin_s", "skin", "skin_l"],
    "hair": ["hair_dd", "hair_d", "hair", "hair_l"],
    "hat": ["ink", "navy", "hat_d", "hat", "hat_l"],
    "robe": ["ink", "navy", "robe_d", "robe", "robe_l"],
    "gold": ["hair_d", "gold_d", "gold", "gold_l"],
}

HAND = [  # open palm, fingers up (13 x 16); 1px gaps become dark finger lines via outline
    ".....lS......",
    "..lS.SS......",
    "..SS.SS.lS...",
    "..SS.SS.SS.lS",
    "..SS.SS.SS.SS",
    "..SS.SS.SS.SS",
    "..SS.SS.SS.SS",
    "l.SSsSSsSSsSs",
    "SS.SSSSSSSSSs",
    "SSsSSSSSSSSSs",
    ".SSSSSSSSSSss",
    "..SSSSSSSSSs.",
    "..sSSSSSSSss.",
    "...ssSSSSss..",
    "....ssssss...",
    "....dsssss...",
]
HAND_C = {"S": "skin", "s": "skin_s", "l": "skin_l", "d": "skin_d"}

EYE = [".EE.", "EHPE", "EPPE", "EPIE", ".EE."]
EYE_C = {"E": "ink", "H": "white", "P": "ink", "I": "iris"}
MOUTH = ["M......M", ".MMMMMM.", "..MTTM..", "...MM..."]
MOUTH_C = {"M": "mouth", "T": "tongue"}
STAR = [".Y.", "YWY", ".Y."]
STAR_C = {"Y": "gold", "W": "gold_l"}


def palette():
    pal = ps.Palette.load("pico-8").copy("wizard-pico8")
    for n, i in NAMES.items():
        pal.set_name(n, i)
    pal.save(HERE / "wizard_palette.json")
    return pal


def build():
    pal = palette()
    W = H = 64
    st = ps.LayerStack(W, H, pal)
    body = st.add("body")
    head = st.add("head")
    hat = st.add("hat")
    arm = st.add("arm")

    # --- robe (symmetric) with V collar
    body.polygon([(10, 63), (13, 53), (20, 48), (28, 46), (35, 46), (43, 48), (50, 53), (53, 63)], "robe_d")
    body.polygon([(27, 46), (36, 46), (31, 53), (32, 53)], "skin_s")
    with body.mirrored("x"):
        body.line(26, 46, 31, 54, "gold")
        body.line(31, 55, 31, 63, "gold")
    body.rect(28, 43, 8, 4, "skin_s")           # neck in shadow
    body.shade(body.mask("robe_d"), ramp=RAMPS["robe"], depth=2, shadow_depth=2)

    # --- head
    head.ellipse(18, 14, 28, 31, "skin")
    with head.mirrored("x"):
        head.ellipse(15, 31, 5, 7, "skin")         # ears
    head.shade(head.mask("skin"), ramp=RAMPS["skin"], depth=1, shadow_depth=2)
    with head.mirrored("x"):
        head.pixel(17, 34, "skin_d")
        head.pixel(17, 33, "skin_s")
        # hair: sideburns + bangs under the brim
        head.polygon([(18, 24), (23, 24), (22, 30), (20, 35), (18, 32)], "hair")
        head.polygon([(18, 23), (31, 23), (31, 26), (29, 27), (27, 25), (25, 28), (23, 26), (21, 28), (19, 27)], "hair")
        # brows (raised, friendly)
        head.line(23, 29, 24, 28, "hair_d")
        head.line(25, 28, 26, 28, "hair_d")
        head.pixel(27, 29, "hair_d")
        # eyes, blush (checker dither), mouth
        head.draw_grid(24, 31, EYE, EYE_C)
        head.dither((21, 37, 4, 2), "blush", pattern="checker", level=0.5)
        head.draw_grid(28, 39, MOUTH, MOUTH_C)
    head.pixel(37, 32, "white").pixel(38, 32, "ink")  # same highlight side for both eyes
    head.pixel(37, 34, "ink").pixel(38, 34, "iris")     # iris on the same side: no cross-eye
    head.pixel(32, 36, "skin_s").pixel(32, 37, "skin_d")  # nose
    head.shade(head.mask("hair"), ramp=RAMPS["hair"], depth=1, shadow_depth=1)

    # --- hat: crooked cone with dithered diagonal gradient, brim, band, stars
    cone = hat.shape_mask("polygon", [(19, 19), (32, 7), (47, 0), (41, 10), (45, 19)])
    hat.gradient(cone, None, ramp=["hat_l", "hat", "hat_d", "navy"], direction="d")
    hat.ellipse(8, 16, 48, 9, "hat_d")
    hat.shade(hat.mask("hat_d") & hat.shape_mask("ellipse", 8, 16, 48, 9),
              ramp=RAMPS["hat"], depth=1, shadow_depth=2)
    hat.rect(20, 16, 25, 2, "robe")
    hat.dither((20, 16, 25, 2), "robe_l", pattern="bayer2", level=0.25)
    hat.draw_grid(31, 10, STAR, STAR_C)
    hat.draw_grid(37, 5, STAR, STAR_C)
    hat.pixel(41, 13, "gold_l")
    hat.pixel(26, 14, "gold_l")

    # --- raised waving arm: sleeve + hand
    arm.polygon([(43, 63), (45, 52), (50, 46), (58, 46), (57, 53), (53, 63)], "robe")
    arm.shade(arm.mask("robe"), ramp=RAMPS["robe"], depth=1, shadow_depth=2)
    arm.rect(50, 45, 8, 2, "gold")                # cuff
    arm.draw_grid(47, 30, HAND, HAND_C)

    ramps = list(RAMPS.values())
    # inner outlines where layers overlap (arm one step darker so the hand separates from the face)
    for name, steps in (("hat", 2), ("arm", 3), ("head", 2)):
        st[name].outline(selective=True, ramps=ramps, steps=steps, connectivity=8)
    flat = st.flatten()
    flat.outline(selective=True, ramps=ramps, steps=2, connectivity=8)

    sp = ps.Sprite(W, H, pal, name="wizard")
    sp.add_frame("portrait", flat, 1000)
    return sp


if __name__ == "__main__":
    sp = build()
    out = ps.output_dir("test")
    sp.save(HERE / "wizard.json")
    cv = sp.frame("portrait")
    print(ps.render(cv, out / "wizard_portrait.png", scale=8))
    print(ps.inspect(cv, out / "wizard_inspect_eyes.png", region=(20, 26, 24, 18), zoom=28))
    print(ps.inspect(cv, out / "wizard_inspect_hand.png", region=(44, 27, 18, 22), zoom=28, indices=True))
    print(ps.inspect(cv, out / "wizard_inspect_full.png", zoom=12))
    print("orphans:", len(cv.orphans()))
