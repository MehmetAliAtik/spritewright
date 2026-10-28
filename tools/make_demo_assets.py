"""Regenerate the README demo images in docs/assets/ from the bundled example (examples/Test_Game).

    python tools/make_demo_assets.py

Writes upscaled copies (nearest neighbour) on a solid background so they read well on light and dark
GitHub themes. The originals in examples/ stay 1x.
"""
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
CHAR = ROOT / "examples" / "Test_Game" / "characters" / "Test_Hero"
OUT = ROOT / "docs" / "assets"
BG = "#83769c"  # PICO-8 lavender: mid-tone, readable in both themes
ATLAS_SCALE = 6
GIF_SCALE = 8


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    atlas = Image.open(CHAR / "animations" / "Test_Hero_all_animations_atlas.png").convert("RGBA")
    big = atlas.resize((atlas.width * ATLAS_SCALE, atlas.height * ATLAS_SCALE), Image.NEAREST)
    canvas = Image.new("RGBA", big.size, BG)
    canvas.alpha_composite(big)
    canvas.convert("RGB").quantize(colors=32, method=Image.Quantize.MEDIANCUT).save(
        OUT / "test_hero_atlas.png", optimize=True)
    src = CHAR / "source" / "test_hero.json"
    for anim in ("walk", "idle"):
        subprocess.run([sys.executable, str(ROOT / "spritewright.py"), "gif", str(src), "-a", anim,
                        "-s", str(GIF_SCALE), "--bg", BG, "-o", str(OUT / f"test_hero_{anim}.gif")],
                       check=True, cwd=str(ROOT))
    total = 0
    for p in sorted(OUT.iterdir()):
        total += p.stat().st_size
        print(f"{p.relative_to(ROOT).as_posix()}  {p.stat().st_size / 1024:.1f} KB")
    print(f"total {total / 1024:.1f} KB")


if __name__ == "__main__":
    main()
