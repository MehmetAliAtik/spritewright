# Anatomy / proportions

`PS blueprint --size <cell> --style chibi|normal [-o DIR]` writes a .png/.json/.txt guide (head box, eye
line, shoulders, hips, feet, ground line, centre axis; sprite pixels, x right / y down). Read the .txt
(not the png) and place parts at those coordinates. 16/32/48 are exact templates; other sizes are scaled
(APPROXIMATE). `--overlay SRC` draws your sprite under the guide for a proportion check.

- chibi (default for 16-32 px): ~2-2.5 heads tall, head 40-50 % of height, big eyes on the eye line,
  short limbs, hands 2x2 px at 32 px.
- normal: ~4-6 heads tall (needs ≥48 px to read), head ~20 %, longer legs (hip at ~half height).
- Pivot = feet: bottom-centre of the union bbox unless the card sets one (`char-new --pivot x,y`).
  The foot row must stay identical across frames (except airborne frames).
- Keep 1 px gaps between arm and torso where possible; exaggerate head, hands, weapon for silhouette.
- Side view facing right is the default for walking characters; 3/4 or front for idle-only sprites.
- 64x64+: build forms with ellipse/polygon/line + `symmetry("x")`; add detail clusters after the shapes.
