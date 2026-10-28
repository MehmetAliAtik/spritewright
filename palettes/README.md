# Palettes

## Bundled

spritewright ships exactly one palette, inside the package: `spritewright/palettes/pico-8.hex`
(the 16-colour PICO-8 palette by Lexaloffle Games). Lexaloffle's PICO-8 FAQ releases the palette under
**CC0** (public domain), so it can be redistributed freely. It is the default palette of every command
(`new`, `game-new`, ...).

## Adding more palettes

Any palette in Lospec's `.hex` format (one `RRGGBB` per line) works. Either pass a path wherever a
palette is expected (`--palette path/to/my.hex`, `.json` palettes with names work too), or drop
`<name>.hex` into one of these folders and use it by name (`--palette <name>`). Search order, first
match wins:

1. every folder listed in the `SPRITEWRIGHT_PALETTES` environment variable (separated like `PATH`)
2. `./palettes` in the current working directory
3. `~/.spritewright/palettes`
4. this folder (`palettes/` of a source checkout)
5. the palettes bundled with the package (pico-8)

`spritewright palettes` lists every palette it can find.

## Where to download others

Popular palettes on [Lospec](https://lospec.com/palette-list). Each page has a `.hex` download; the
direct link is `https://lospec.com/palette-list/<slug>.hex`:

| Palette | Colours | Page | .hex download |
|---|---|---|---|
| Sweetie 16 | 16 | https://lospec.com/palette-list/sweetie-16 | https://lospec.com/palette-list/sweetie-16.hex |
| Endesga 32 | 32 | https://lospec.com/palette-list/endesga-32 | https://lospec.com/palette-list/endesga-32.hex |
| Endesga 64 | 64 | https://lospec.com/palette-list/endesga-64 | https://lospec.com/palette-list/endesga-64.hex |
| Resurrect 64 | 64 | https://lospec.com/palette-list/resurrect-64 | https://lospec.com/palette-list/resurrect-64.hex |
| AAP-64 | 64 | https://lospec.com/palette-list/aap-64 | https://lospec.com/palette-list/aap-64.hex |

These palettes are made by their respective authors and are **not** distributed with spritewright.
Check each author's terms (linked from the Lospec page) before you use or redistribute one.

Example (download into the user palette folder, then use it by name):

```sh
mkdir -p ~/.spritewright/palettes
curl -o ~/.spritewright/palettes/endesga-32.hex https://lospec.com/palette-list/endesga-32.hex
spritewright game-new "my game" --palette endesga-32 --colors 16
```
