# Style system and project layout

Names are English Title_Case without spaces (commands normalize: "aurora quest" → Aurora_Quest).
```
outputs/README.md                         auto index (never edit by hand)
outputs/<Game>/game-style.md|.json, palette.hex, palette_preview.png
outputs/<Game>/characters/<Char>/character.md|.json      card: role, design, cell, pivot, colours, anims, log
    source/        make_<char>.py, <char>.json (rig), <Char>_palette.json (subset of the game palette)
    animations/<Anim>/<Char>_<Anim>_sheet.png|.json, <Char>_<Anim>_preview.gif, unity-import-note.md,
                   _archive/<YYYY-MM-DD_HHMMSS>/          previous versions, never deleted
    animations/<Char>_all_animations_atlas.png|.json     one row per animation, same cell
    review/        <Anim>_contact.png | All_contact.png (build --final), <Char>_check.json|txt,
                   draft/<Char>_<Anim>_sheet.png|json (build --draft) — AI review working files
outputs/<Game>/props/<Prop>/..., tiles/<Tileset>/...     (--kind prop|tile)
outputs/Unsorted/                         old output/ content
```

## Workflow rules
1. Start with `PS context <Game> [<Char>]`; never read game-style.md / character.md / README.md.
2. Game missing → ask at most 4 short questions (mood, colour direction, cell size, outline), then
   `PS game-new <Game> --mood cozy,retro --temperature warm --cell 32x32 --outline selective --palette
   pico-8`. Show the palette (`PS context <Game>`) and get the user's approval before
   drawing (palette approval rule). Roles are usage names (outline, highlight, shadow_dark, skin,
   skin_shadow, hair, hair_shadow, danger, background, accent, foliage, ...); override `--roles "3=skin"`.
3. Character missing → `PS char-new <Game> <Char> --role "..." --design "..." --colors outline,skin,...`.
4. Colours only from the game palette. A needed new colour → ask the user; on approval
   `PS game-palette-add <Game> RRGGBB --role R`, then `PS char-new <Game> <Char> --force --colors ...`.
5. The style guide is frozen: change it only when the user explicitly asks for a style change
   (then `PS game-new <Game> ... --force`). Existing guides keep their roles as they are.
6. Every animation uses the card cell (= game cell unless `char-new --cell`), so sheets and atlas slice
   identically in Unity. `build` handles export, archive, card, README, notes.

## check game-style group (automatic inside outputs/<Game>/, elsewhere `--game G`)
game.off_palette / game.color_limit / game.cell → FAIL; game.char_colors (colour not on the card) → WARN;
game.light → WARN only (heuristic: interior split in thirds along the light vector; lit third must not
be darker than the opposite third).

## Loose requests (no game)
Sources in `projects/<p>/` (notes.md, palette json, make_<name>.py, rig json), outputs in `output/<p>/`:
`PS run projects/<p>/make_<name>.py`, `PS unity-sheet <p>/<name> -o output/<p>/<name>`,
`PS check <p>/<name> --atlas output/<p>/<name>`.
