# spritewright commands

`PS <cmd>` = the command written into SKILL.md by the installer: `spritewright <cmd>` (pip / pipx / uv install)
or `python <repo>/spritewright.py <cmd>` (source checkout).
Every command accepts `--verbose` (full lists / reports / logs); default output is one line (check: one
summary line + one line per WARN/FAIL; build: ≤5 lines; context: ≤15 lines). File outputs are identical
in both modes. `SRC` = sprite .json / .py path or project-relative name (`examples/sprites/hero.py`). `PS <cmd> -h` = all flags
(the repository also has a generated reference of every option: docs/commands.md).

## Command reference

### Game / character pipeline (outputs/<Game>/)
- `build GAME CHAR [ANIM|all] [--draft|--final] [--src FILE --fps N --no-loop a,b --preview-scale 4 --kind character|prop|tile --root R --json]` — one call: runs every `source/make_*.py` (stdout captured), picks the source (card's source, else `<x>.json` of `make_<x>.py`, else the only rig json), then
  - `--final` (default): char-export (per-animation `animations/<Anim>/<Char>_<Anim>_sheet.png|json`, `_preview.gif`, `unity-import-note.md`, all-animations atlas, previous version archived, card + outputs/README.md updated) + check of source + atlas + game style + ONE contact sheet `review/<Anim>_contact.png` (`review/All_contact.png` for all);
  - `--draft`: only `review/draft/<Char>_<Anim>_sheet.png|json` + check of those sheets; no GIF, no note, no atlas, no archive, card/README/animations untouched.
  Both write `review/<Char>_check.json|txt`. Exit 0 PASS, 1 check FAIL, 2 error.
- `context GAME [CHAR] [--kind K --root R]` — cell, PPU, outline, light, shading, dither, proportions, palette `role=hex`, max colours; character: cell, pivot, design, colour roles, animations `Name:frames@fps`, source path. Missing game/char → one line, exit 1.
- `game-new NAME [--mood a,b --temperature warm|cool|neutral --saturation/--contrast low|medium|high --cell 32x32 --ppu N --outline selective|black|none --light top-left --shading 2 --dither none|limited|yes --max-colors 16 --proportions chibi|normal --palette P --colors N --roles "3=skin" --description T --force --root R]` — style guide files; palette roles are usage names (outline, highlight, shadow_dark, skin, skin_shadow, hair, hair_shadow, danger, background, accent, foliage, water_shadow ...).
- `game-style GAME [--json --root R]` — validate the style guide (exit 1 if invalid); `--verbose` prints it.
- `game-palette-add GAME RRGGBB --role R [--root R]` — add one colour, ONLY after the user approved it.
- `char-new GAME CHAR [--role T --design T --cell WxH --pivot x,y --colors skin,accent,3 --kind character|prop|tile --force --root R]` — card + `source/<Char>_palette.json`.
- `char-export GAME CHAR SRC [--anims Idle,Walk --fps N --no-loop a --preview-scale 4 --kind K --root R]` — export only (build calls it).
- `outputs-index [--root R]` — regenerate outputs/README.md.

### Review / quality
- `check SRC|atlas.json|DIR [--atlas DIR --no-atlas --palette P --max-colors 16 --size-drift 2 --size-drift-fail 6 --foot-drift 1 --foot-drift-fail 4 --motion-min-px 2 --motion-min-ratio 0.01 --seam-factor 2 --orphans 3 --connectivity 4|8 --game G --root R --json --no-write -o]` — PASS/WARN/FAIL, exit 1 on FAIL.
- `contact SRC|atlas.json|sheet.png [-s 4 --columns N --max-width 1024 -o]` — all frames in one image; scale auto-reduced to keep width ≤ max; default path for files inside a game asset: its `review/`.
- `inspect SRC -r x,y,w,h [-f F -z 24 --indices --full -o]` — magnified region with coordinates; region required (`--full` = whole frame, the old default).
- `preview SRC A B [-s 8 -o]` — onion skin of two frames. `diff SRC A B [--other SRC2 -s 8 -o]` — changed pixels in red.
- `info SRC` / `validate SRC` / `ascii SRC [-f F]` — summary (frames, anims, loop diffs) / precise parse errors / text grid.
- `clean SRC [--remove --isolated-only --connectivity 4|8 -f F -o]` — report/remove orphan pixels.
- `blueprint [--size 32 | --all] [--style chibi|normal --overlay SRC -f F --json -s N -o DIR]` — proportion guide (.png/.json/.txt).

### Output / export
- `render SRC [-f F -s 8 --bg hex|checker -o]` — one frame PNG.
- `sheet SRC [-s 1 --columns N --padding P -o]` — generic sheet PNG + JSON.
- `gif SRC [-a ANIM --fps N -s 8 --bg hex --apng -o]` — animated GIF/APNG (self-verified).
- `unity-sheet SRC [-o DIR --cell WxH --padding 1 --pivot bottom-center|center|auto|x,y --align fixed|auto --anchor x,y --fps N --no-loop a,b --anims a,b --preview-scale 4 --ppu N]` — loose-project Unity atlas + strips + atlas.json + preview/ + UNITY_IMPORT.txt.
- `export-json SRC -o x.json` — save any source (.py) as grid JSON.
- `run SCRIPT.py [args]` — run a drawing script with spritewright importable.
- `install-skill [--target DIR --dry-run --uninstall --command CMD]` — install this skill into
  `~/.claude/skills/spritewright/` (SKILL.md + reference/).

### Palettes
- `palettes` — available palettes: bundled pico-8 + any `<name>.hex` in `./palettes`, `~/.spritewright/palettes`
  or `SPRITEWRIGHT_PALETTES` (a .hex/.json path also works wherever a palette is expected).
- `palette-show P [-o swatch.png]` — colours (one line; `--verbose` with indices/names).
- `palette-create OUT name=RRGGBB ... [--base P --extend|--snap --name N]` — custom palette.
- `attach-palette SRC P [--snap --copy-to-project -o]` — move a sprite to another palette.
- `ramp HEX [--steps 5 --hue-shift 14 --palette P -o]` — hue-shifted ramp.
- `quantize IN.png --palette P [--dither none|bayer4|floyd --size WxH --resample box|nearest|lanczos -s 1 --json out.json -o]` — image → palette.

### Editing (overwrite the source .json unless -o)
- `new PROJECT NAME [--size 32x32 --palette P --frames a,b]` — blank grid sprite + notes.md.
- `outline SRC [-f F --color C | --selective] [--connectivity 4|8 --steps N --inside -o]`.
- `shade SRC --ramp a,b,c [--mask-color C | -r x,y,w,h] [--light top-left --depth 1 --shadow-depth N -f F -o]`.
- `frame SRC copy|shift|flip-h|flip-v|mirror|recolor|onion|loopcheck|delete [a] [b] [--dx --dy --wrap --direction lr --map 1=2 --anim A -s 8 -o]`.

### Animation
- `templates [--show walk --templates FILE]` — templates (idle, walk, run, jump, attack, hurt, death), views, easings.
- `anim-apply RIG.json TEMPLATE [--frames N --name N --scale 2 --fps N --no-loop --map head=helmet --view front --templates FILE -o]`.
- `tween RIG.json --anim A (--part P | -r x,y,w,h) (--from=dx,dy --to=dx,dy | --keys "1:0,0;3:0,-3:ease_out;6:0,0") [--frames N --start --end --ease E --add -o]`.
- `oscillate RIG.json --anim A (--part P | -r x,y,w,h) --amp 1 --period 4 [--phase 0.25 --axis y --mode sine|abs|pos --frames N --set --no-loop -o]`.

### Import / cleanup
- `import PNG [--project P --name N | -o x.json] [--frame WxH | --cols N --rows M] [--margin --spacing --anim-rows idle:4,walk:6 --anim A --names a,b --atlas J --no-atlas --palette P --alpha-threshold 128 --dither D --restore-offsets --canvas WxH --skip-empty --fps N --report r.json --json]` — PNG/sheet/atlas → grid JSON.
- `depixelize IMG [--palette P | --colors K | --merge 8] [--transparent auto|RRGGBB --tolerance 12 --size N --offset x,y --sample median|center -s 8 --sprite x.json | --project P --name N --report-only --json-report -o]` — fake/AI pixel art → 1 block = 1 pixel.
- `grid-detect IMG [--min-size 2 --max-size 32 --json-report]` — block size / offset / confidence only.

All default folders are relative to the current directory: scratch outputs of loose commands go to
`output/<project>/` (env `SPRITEWRIGHT_OUTPUT`), game outputs to `outputs/` (`--root` or env
`SPRITEWRIGHT_OUTPUTS`), loose projects to `projects/` (env `SPRITEWRIGHT_PROJECTS`). Tests (checkout):
`python tests/smoke_test.py`.
