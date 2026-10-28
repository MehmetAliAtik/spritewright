# Style guide and character card format

A game lives in `outputs/<Game>/` (or `--root DIR`, or env `SPRITEWRIGHT_OUTPUTS`). The files are written
by `game-new`, `game-palette-add`, `char-new`, `char-export` and `build`; edit them through those commands,
not by hand. The bundled example is [examples/Test_Game](../examples/Test_Game).

Names are normalized to English Title_Case without spaces: `"aurora quest"` becomes `Aurora_Quest`,
`walk` becomes `Walk`. Names with `/`, `.` or non-ASCII letters are rejected.

## Game style guide

| File | Purpose |
|---|---|
| `game-style.json` | machine-readable guide; read by `context`, `check`, `build`, `char-new` |
| `game-style.md` | the same guide for humans (description, palette table, ramps, rules, do / don't) |
| `palette.hex` | the game palette, one `RRGGBB` per line, in index order (must match the JSON) |
| `palette_preview.png` | swatches labelled with index and role |

`spritewright game-style <Game>` validates all four (exit code 1 if invalid).

### game-style.json

```json
{
  "schema": "spritewright.game-style/1",
  "name": "Test_Game",
  "description": "Test Game: a cozy, retro pixel-art game with warm colours ...",
  "mood": ["cozy", "retro"],
  "theme": {"temperature": "warm", "saturation": "medium", "contrast": "high"},
  "palette_source": "pico-8",
  "palette": [
    {"index": 0, "hex": "000000", "role": "outline"},
    {"index": 1, "hex": "1d2b53", "role": "shadow_dark"}
  ],
  "cell": [32, 32],
  "ppu": 32,
  "outline": "selective",
  "light": "top-left",
  "shading": 2,
  "dither": "none",
  "max_colors": 16,
  "proportions": "chibi",
  "ramps": {
    "skin": {"base": "ffccaa", "ramp": ["5d2f32", "ae7266", "ffccaa", "ffe7bd", "fff9d0"],
             "in_palette": [5, 4, 15, 7], "in_palette_hex": ["5f574f", "ab5236", "ffccaa", "fff1e8"]}
  },
  "rules": {"do": ["..."], "dont": ["..."]},
  "created": "2026-10-28 07:54",
  "updated": "2026-10-28 07:54",
  "changelog": [{"date": "2026-10-28 07:54", "text": "style guide created (16 colours from pico-8)"}]
}
```

| Field | Type / allowed values | Set by (`game-new` option) |
|---|---|---|
| `description` | text | `--description` (default: generated) |
| `mood` | list of keywords | `--mood cozy,retro` |
| `theme.temperature` | `warm`, `cool`, `neutral` | `--temperature` |
| `theme.saturation`, `theme.contrast` | `low`, `medium`, `high` | `--saturation`, `--contrast` |
| `palette_source` | base palette name or path | `--palette` (default `pico-8`) |
| `palette` | 8-32 entries `{index, hex, role}`; hex and role unique | `--colors N`, `--roles`, `game-palette-add` |
| `cell` | `[w, h]`, 1-256 px | `--cell 32x32` |
| `ppu` | integer >= 1 | `--ppu` (default: smallest of 16/32/64/128/256 >= cell height) |
| `outline` | `selective`, `black`, `none` | `--outline` |
| `light` | `top-left`, `top`, `top-right`, `left`, `right`, `bottom-left`, `bottom`, `bottom-right`, `front` | `--light` |
| `shading` | shade steps per material, 1-4 | `--shading` |
| `dither` | `none`, `limited`, `yes` | `--dither` |
| `max_colors` | colours per sprite, 2-32 | `--max-colors` |
| `proportions` | `chibi`, `normal` | `--proportions` |
| `ramps` | per key role: a hue-shifted ramp (`ramp`) and its closest palette colours (`in_palette`, `in_palette_hex`) | generated |
| `rules.do`, `rules.dont` | 5-8 short rules each | generated from the settings |

### Palette roles

A role is a lowercase usage name (`[a-z][a-z0-9_]*`) given to each palette colour. `game-new` assigns roles
from brightness, hue and saturation - for example `outline`, `shadow_dark`, `shadow`, `highlight`, `skin`,
`skin_shadow`, `hair`, `danger`, `background`, `accent`, `foliage`, `sky`, `stone` - and family names
(`foliage_shadow`, `gold_light`, ...) for the rest. Override them with `--roles`, either a JSON file or a
list such as `"3=skin,#ffec27=gold"` (index or hex = role). The validator warns when there is no outline,
no shadow (`shadow` / `shadow_dark`) or no light (`light` / `highlight`) colour.

Drawing scripts and `--colors` lists refer to colours by role, index or in-palette hex. A new colour is
added only with `game-palette-add <Game> RRGGBB --role R`, which updates the `.json`, `.md`, `.hex` and
preview together.

### Checks tied to the style guide

Inside `outputs/<Game>/` (or with `check --game <Game>`) the `game` check group runs:
`game.off_palette` (colour outside the game palette, FAIL), `game.color_limit` (more than `max_colors`,
FAIL), `game.cell` (sheet cell differs from the card cell, FAIL), `game.char_colors` (colour not on the
character card, WARN) and `game.light` (lit side darker than the shadow side, WARN only; a heuristic).

## Character card

`char-new <Game> <Name>` writes `characters/<Name>/character.json`, `character.md` and
`source/<Name>_palette.json`. Props and tiles use the same files under `props/` and `tiles/`
(`--kind prop|tile`).

```json
{
  "schema": "spritewright.card/1",
  "kind": "character",
  "name": "Test_Hero",
  "game": "Test_Game",
  "role": "player, small adventurer",
  "design": "chibi adventurer, side view facing right: orange hair, green tunic ...",
  "cell": [32, 32],
  "cell_override": false,
  "pivot": null,
  "colors": [{"index": 0, "hex": "000000", "role": "outline"}, {"index": 15, "hex": "ffccaa", "role": "skin"}],
  "palette_file": "source/Test_Hero_palette.json",
  "animations": {
    "Walk": {"frames": 6, "fps": 10.0, "loop": true, "sheet": "animations/Walk/Test_Hero_Walk_sheet.png",
             "source": "test_hero.json", "updated": "2026-10-28 07:54"}
  },
  "created": "2026-10-28 07:54",
  "updated": "2026-10-28 07:54",
  "changelog": [{"date": "2026-10-28 07:54", "text": "card created (9 colours, cell 32x32)"}]
}
```

| Field | Meaning | Set by |
|---|---|---|
| `role`, `design` | free text used by `context` | `--role`, `--design` |
| `cell`, `cell_override` | the cell every animation of this character uses; the game cell unless overridden | `--cell WxH` |
| `pivot` | `null` (bottom-centre of the union bounding box of all frames), `{"x", "y"}` sprite pixel, `"bottom-center"` or `"center"` | `--pivot` |
| `colors` | the subset of the game palette this character uses | `--colors outline,skin,3,#ff004d` (default: whole palette) |
| `palette_file` | palette JSON for the drawing script, relative to the card | generated |
| `animations` | one entry per exported animation | `char-export` / `build` |
| `changelog` | creation and every export | generated |

`char-new --force` rewrites the card (keeping the animation list and the change log), for example after a
colour was added to the game palette.

### Character palette file

`source/<Name>_palette.json` maps roles to colours; scripts load it with `ps.Palette.load(...)`:

```json
{"name": "Test_Hero-palette", "colors": {"outline": "000000", "skin": "ffccaa", "hair": "ffa300"}}
```

Any palette JSON may also use a plain list: `{"name": "my-palette", "colors": ["000000", "1d2b53"]}`.

## Where things are stored

All paths written into these files are relative to the file that stores them (with `/` separators), so a
game folder can be moved, shared or committed without leaking absolute paths.
