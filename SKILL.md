---
name: spritewright
description: >-
  Create pixel art with the local spritewright tool (Python, no GUI): characters, props, tiles, sprite
  frame animations (idle, walk, run, jump, attack, hurt, death), sprite sheets, GIF previews and Unity
  sprite atlases with import notes, quality checks, game style guides / palettes / character cards under
  outputs/<Game>/, importing or cleaning PNG sheets and fake pixel art. Use whenever the user asks for
  pixel art, a sprite, sprite sheet, pixel animation, sprite GIF or a Unity atlas, in English or Turkish
  (e.g. "make a 16x16 slime with a bounce GIF", "32x32 knight, 4 frame idle, 6 frame walk", "add an attack
  animation", "piksel karakter çiz", "32x32 şövalye, 4 frame idle, 6 frame yürüme animasyonu"). Not for
  photo editing, vector art, UI mockups or 3D.
---

# spritewright

`PS <cmd>` = `spritewright <cmd>` (install/update this skill with `spritewright install-skill`, which writes the
exact command for this machine; from a clone: `python <repo>/spritewright.py install-skill`). Output is one line by default (`--verbose` only when needed).
Read the `reference/` files next to this SKILL.md ONLY when a step needs them: commands.md (all options),
api.md (API + make script skeleton), animation.md (walk cycle), anatomy.md, style-system.md (layout,
palette rules), troubleshooting.md.

## Flow (game/character requests)
1. `PS context <Game> [<Char>]` — style, palette roles, cell, pivot, animations, source path (<=15 lines). Skip when only rebuilding.
2. Draw: edit/add `characters/<Char>/source/make_<char>.py` (Rig parts, alts, animations). Existing
   character → keep the source, add only the new animation's part motion (parts/derive, no rewrite).
3. `PS build <Game> <Char> <Anim|all>` (`--draft` if the user asked for a draft). Runs make_*.py,
   renders, checks (game style included), exports sheets/GIF/atlas/notes/card/README, ≤5 lines.
4. Inspect only if build reports WARN/FAIL or it is the first drawing of this character: open the printed
   review contact sheet once; zoom with `PS inspect SRC -f F -r x,y,w,h` on the flagged region only.
5. Fix in the source, rebuild. 1 correction round by default; up to 2 more only while check FAILs.
6. Deliver ≤3 lines: main paths + check summary + unity-import-note path (do not paste the note).

## Rules
- Game and character exist → draw without asking. Game missing → ask ≤4 short questions (mood, colours,
  cell size, outline), `PS game-new`, get palette approval, then `PS char-new`. Character missing → `char-new`.
- Never read game-style.md / character.md (use `context`). Never hand-write or read outputs/README.md,
  folders, unity-import-note.md, palette_preview.png or _archive/ — the scripts maintain them.
- Game palette only; new colour = user approval (`game-palette-add`). Style changes only on explicit request.
- Visual check: `check` first; open images only if it flags a problem or on a first drawing; one contact sheet per build. Draft = no images.
- New animation for an existing character: only review the changed frames. 64x64+: Canvas shapes
  (ellipse/polygon/line) + `symmetry`, not hand grids. No game named: projects/<p>/ (style-system.md).

## Main commands (full list + options: reference/commands.md)
- `PS context GAME [CHAR]` — compact drawing context; one line + exit 1 if missing.
- `PS build GAME CHAR [ANIM|all] [--draft|--final] [--verbose|--json]` — compile, check, deliver; exit 1 on FAIL.
- `PS check SRC|atlas.json [--verbose]` — summary + one line per WARN/FAIL.
- `PS contact SRC|atlas.json` — all frames in one image (4x, width ≤1024).
- `PS inspect SRC -f F -r x,y,w,h` — magnified region (region required).
- `PS game-new NAME`, `PS char-new GAME CHAR`, `PS game-palette-add GAME HEX --role R`, `PS anim-apply RIG.json
  TEMPLATE`, `PS templates`, `PS blueprint --size N --style chibi`.

## Pixel-art rules
1. Clean 1px outline (auto or selective); no double or broken outlines.
2. One light direction (game style) for every frame: lit side light, far side dark.
3. Few colours: 3-4 hue-shifted steps per material, never more than the game max.
4. Alpha only 0/255; no semi-transparent anti-aliasing.
5. No orphan pixels except deliberate highlights.
6. Readable silhouette at 1x; exaggerate head, hands, weapon.
7. No pillow shading or banding; shade by form in clusters.
8. Fixed pivot: feet on the same row each frame; parts move/swap, never grow; loops close seamlessly.
