# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-28

First public release.

### Added

- `spritewright` command-line tool (also `python spritewright.py` from a checkout and
  `python -m spritewright`) and the `spritewright` Python package.
- Indexed, palette-checked canvas: lines, ellipses, polygons, flood fill, dithering, gradients,
  symmetry, selective outlines, shade-assist, orphan-pixel cleanup.
- Sprite sources as grid JSON, rig JSON (parts, alternate drawings, part animations) or Python scripts,
  with precise error messages.
- Exports: frames, sprite sheets with Aseprite-style JSON, contact sheets, animated GIF/APNG (verified on
  write), Unity strips and atlases with a fixed cell, foot pivot and import notes.
- `check`: PASS/WARN/FAIL quality report for sources and atlases, including game style compliance.
- Animation templates (idle, walk, run, jump, attack, hurt, death; front views for walk/run), `tween`
  and `oscillate` with easing.
- Game layout under `outputs/<Game>/`: `game-new`, `game-style`, `game-palette-add`, `char-new`,
  `char-export`, `outputs-index`, plus `context` and the one-call `build` (draft and final modes).
- `import` of PNG sheets and Unity atlases back into sources, `depixelize` / `grid-detect` for fake or
  upscaled pixel art, `blueprint` proportion guides.
- Bundled PICO-8 palette (CC0); palette lookup in `SPRITEWRIGHT_PALETTES`, `./palettes`,
  `~/.spritewright/palettes` and a checkout's `palettes/`.
- Claude Code skill (`SKILL.md` + `skill/reference/`) and `spritewright install-skill`.
- Bundled example game `examples/Test_Game` and example sprites in `examples/sprites/`.
- Documentation (`docs/`), generated command reference, CI on Windows, macOS and Linux with
  Python 3.10-3.13.

[Unreleased]: https://github.com/MehmetAliAtik/spritewright/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/MehmetAliAtik/spritewright/releases/tag/v0.1.0
