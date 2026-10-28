# examples/sprites

- `hero.py` -> 32x32 hero (PICO-8, named palette `hero_palette.json`), part rig: legs/body/arm_l/arm_r/head (+ `blink` alt). Idle: body bob 1px + blink, auto-outline `outline` (8-conn). `hero.json` = generated frames as editable grid.
- `wizard.py` -> 64x64 wizard bust waving. Layers body/head/hat/arm, symmetric face, dithered hat gradient, checker blush, shade-assist with ramps, per-layer selective outline (arm steps=3 so the hand separates from the face). Palette `wizard_palette.json`.
- `slime.json` -> 16x16 grid-format sample (2 frames). `blob_rig.json` -> grid-format part rig sample.
- Next ideas: hero run/walk cycle = new rig animation in `hero.py` (move legs/arms parts).
