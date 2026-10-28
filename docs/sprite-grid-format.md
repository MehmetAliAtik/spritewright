# Sprite source formats

Every command that takes `SRC` accepts one of three source types:

| Source | What it is |
|---|---|
| grid `.json` | frames drawn as text rows, one character per pixel |
| rig `.json` | a grid file with `parts` and `rig_animations`: the frames are composed from parts |
| `.py` script | Python that defines `build()` returning a `Sprite` (or a module-level `sprite`) |

`SRC` may be a path or a project-relative name: `examples/sprites/hero.py`, `my_project/hero` (looked up in
the current directory, `projects/` and, in a checkout, `examples/`). Editing commands (`outline`, `shade`,
`clean --remove`, `frame`, `anim-apply`, `tween`, `oscillate`, `attach-palette`) work on `.json` sources and
overwrite them unless `-o` is given; `export-json` turns a `.py` source into a grid `.json`.

The examples in [examples/sprites](../examples/sprites) cover each format: `slime.json` (grid),
`blob_rig.json` (rig), `hero.py` (script).

## Grid JSON

```json
{
  "name": "slime",
  "width": 16,
  "height": 16,
  "palette": "pico-8",
  "chars": {"O": 0, "G": 11, "g": "foliage_shadow", "l": "#fff1e8"},
  "default_duration": 100,
  "frames": {
    "idle1": {"duration": 300, "rows": ["................", "......OOOO......", "..."]},
    "idle2": ["................", "..."]
  },
  "animations": {"idle": ["idle1", "idle2"]}
}
```

| Key | Required | Meaning |
|---|---|---|
| `width`, `height` | yes | canvas size in px (sprites: 16-256) |
| `name` | no | sprite name (default: file stem) |
| `palette` | no | palette name (`pico-8`, any `<name>.hex` in a palette folder), a path relative to this file (`.hex` / `.json`), an object `{"role": "RRGGBB"}` or a list of hex colours. If omitted, the palette is built from the hex values in `chars`. |
| `chars` | yes | one character -> colour (palette index, role name or in-palette hex) |
| `frames` | yes | object `name -> {"duration": ms, "rows": [...]}` or `name -> [rows]`; a list of `{"name", "rows", "duration"}` also works |
| `default_duration` | no | ms for frames without `duration` (default 100) |
| `animations` | no | `name -> [frame names]`; without it, animations are derived from frame names (`walk1`, `walk2` -> `walk`) |
| `pivot`, `unity` | no | export settings, see below |

Rules:

- `.` is transparent. Colour characters are `A-Z a-z 0-9` and `# @ $ % & * + = ? !`.
- Every row has exactly `width` characters and every frame exactly `height` rows.
- Colours must be in the palette (strict mode): an unknown hex is an error, not a silent remap.
- Errors name the exact place: `frame 'idle2' row 3 (y=2): length 15, expected 16`,
  `frame 'idle1' row 2 (y=1) col 5 (x=4): unknown char 'Z'`, `chars['X'] = '#123456': ... is not in palette`.

`spritewright validate SRC` parses a file and reports such errors; `ascii SRC -f F` prints a frame as text.

## Rig JSON

A rig is a grid file whose frames are built from parts. Each part is drawn once (plus optional alternate
drawings); each animation frame moves, flips, hides or swaps parts by whole pixels.

```json
{
  "name": "blob", "width": 16, "height": 16, "palette": "pico-8",
  "chars": {"r": 2, "R": 8, "E": 0, "k": 0, "f": 9},
  "parts": {
    "body": {"z": 0, "x": 4, "y": 8, "rows": ["..rrrr..", ".rRRRRr.", "rRRRRRRr"]},
    "eyes": {"z": 1, "x": 6, "y": 10, "rows": ["E..E"], "alts": {"blink": ["...."]}},
    "feet": {"z": -1, "x": 4, "y": 13, "rows": ["ff....ff"]}
  },
  "rig_animations": {
    "idle": {
      "durations": [400, 200],
      "fps": 5, "loop": true,
      "frames": [
        {},
        {"body": [0, 1], "eyes": {"dy": 1, "swap": "blink"}}
      ]
    }
  },
  "rig_outline": {"color": "k", "connectivity": 4}
}
```

| Key | Meaning |
|---|---|
| `parts.<name>.rows` | the part's drawing (its own box; all rows the same length) |
| `parts.<name>.x`, `.y` | top-left of the part's box in sprite pixels |
| `parts.<name>.z` | drawing order, low first (far limbs low, near limbs high) |
| `parts.<name>.alts` | alternate drawings of the same box size, used with `swap` |
| `rig_animations.<anim>.frames` | one spec per frame: `{part: [dx, dy]}` or `{part: {...}}` (see below); `{}` = rest pose |
| `rig_animations.<anim>.duration` / `durations` | ms for every frame, or a list per frame (default 150) |
| `rig_animations.<anim>.fps`, `.loop` | optional; used by `unity-sheet`, `check`, `build` |
| `rig_outline` | outline added to every composed frame: `{"color": "k"}` (a char or a colour) or `{"selective": true}`, plus `connectivity` 4 or 8 |

Per-part frame spec keys: `dx`, `dy` (integers, y down), `flip_h`, `flip_v` (flip inside the part's box),
`visible` (false hides the part), `swap` (alt name, `null` = base drawing), `z` (draw order for this
frame). Offsets are integers only; `0.5` is rejected.

Frames are named `<anim><n>` (`idle1`, `idle2`). **There is no parenting**: a part moves only by its own
offset, so a body bob must give the head and arms the same `dy`. (Animation templates add parent
offsets for you through their `_hierarchy`, see [animation-templates.md](animation-templates.md).)

The same rig can be built in Python (`ps.Rig`, `rig.part`, `rig.alt`, `rig.animation`) and saved with
`anim.rig_to_dict` / `anim.save_rig_json`; see [skill/reference/api.md](../skill/reference/api.md).

## Python scripts

```python
import spritewright as ps

def build():
    pal = ps.Palette.load("pico-8")
    sp = ps.Sprite(16, 16, pal, name="coin")
    cv = sp.new_frame("spin1")
    cv.circle(8, 8, 5, 10).outline(0)
    return sp
```

A `.py` source must define `build()` returning a `ps.Sprite` (or a module-level `sprite`). Drawing scripts
for the game layout (`characters/<Char>/source/make_<char>.py`) instead write their rig JSON when run;
`build` runs them first and then uses the JSON. Use `spritewright run script.py` to run a script with
`spritewright` importable from a checkout.

## Export settings in a source

Optional top-level keys (grid / rig JSON), or `sprite.extra` for `.py` sources:

```json
"pivot": {"x": 16, "y": 31},
"unity": {"align": "fixed", "padding": 1, "cell": [32, 32], "fps": 8, "loop": true,
          "animations": {"death": {"fps": 10, "loop": false}}}
```

- `pivot`: the foot point in sprite pixels, or `"bottom-center"` / `"center"`. Default: bottom-centre of
  the union bounding box of all exported frames. The pivot lands on the same cell pixel in every frame.
- `unity.align`: `fixed` (one pivot for all frames, keeps intentional bob/jump; default) or `auto`
  (per-frame foot detection).
- FPS priority: source, then `--fps`, then the frame durations. Loop is on unless `--no-loop` or the
  source says `false`.

## Output metadata (sheets and atlases)

`sheet`, `unity-sheet`, `char-export` and `build` write JSON next to every PNG. The layout follows
Aseprite's JSON sheet format so other tools can read it:

- `frames`: one entry per cell with `frame {x, y, w, h}`, `duration`, `animation`, `index`,
  `source_frame` and the integer `offset` applied for pivot alignment.
- `meta`: `image`, `size`, `frameTags` (`name`, `from`, `to`, `direction`), `source` (relative path of the
  sprite source).
- Unity sheets add `cell`, `rows`, `columns`, `spacing` and `margin` (always 0), `padding`,
  `pivot` (`pixel` with y down, `pixel_from_bottom`, `normalized` for Unity's custom pivot,
  `unity_preset`), `animations` (`name`, `row`, `frame_count`, `fps`, `loop`, `durations`, `times`,
  `length`) and `unity` (`pixels_per_unit`, `sprite_mode`, `filter_mode`, `compression`, `slice`, `pivot`).

`import` reads these files back (`atlas.json` next to a PNG is used automatically), restoring frame names,
animations, durations, fps/loop and the pivot.
