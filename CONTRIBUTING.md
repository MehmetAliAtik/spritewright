# Contributing to spritewright

Thanks for your interest! Bug reports, ideas, documentation fixes and pull requests are all welcome.
Please follow the [Code of Conduct](CODE_OF_CONDUCT.md). Security problems go through
[SECURITY.md](SECURITY.md), not public issues.

## Development setup

You need Python 3.10-3.13 and git.

```sh
git clone https://github.com/MehmetAliAtik/spritewright.git
cd spritewright
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -e .
spritewright --version
```

`pip install -e .` installs the package in editable mode, so changes to `spritewright/` take effect
immediately. You can also run everything without installing: `python spritewright.py <command>`.

## Running the tests

```sh
python tests/smoke_test.py          # all suites (about a minute); exit code 0 = everything passed
python tests/smoke_test.py --keep   # keep the temporary output folder for inspection
python tests/test_build.py          # a single suite on its own (each tests/test_*.py file works this way)
```

The tests write only to temporary folders. They must pass on Windows, macOS and Linux: CI runs them on
all three with Python 3.10 to 3.13, and also builds the wheel and runs the installed `spritewright`.
Keep tests portable: build paths with `pathlib`, compare relative paths with `/` (`as_posix()`), open
text files with `encoding="utf-8"`, and do not rely on a case-insensitive file system.

## Code style

- Python 3.10+, standard library plus Pillow and NumPy only. A new runtime dependency needs a very good
  reason; discuss it in an issue first.
- Follow the existing style: PEP 8, 4-space indentation, lines up to about 120 characters, docstrings on
  public functions.
- English only in code, comments, messages and documentation.
- No absolute paths, user names or machine-specific details in code, tests, examples or generated files
  (`tests/test_release.py` checks this).
- Default command output stays short (one line, `--verbose` for more): the tool is driven by AI agents
  and every line costs tokens.
- Error messages say exactly what is wrong and where (frame, row, column, file).
- Nothing is ever written inside the installed package; defaults are relative to the current directory.

## Pull requests

1. Open an issue first for larger changes, so we can agree on the approach.
2. Keep each pull request focused on one change; update the documentation and `CHANGELOG.md`
   (under "Unreleased") in the same pull request.
3. Add or update tests; `python tests/smoke_test.py` must pass.
4. Fill in the pull request template. By contributing you agree that your contribution is licensed
   under the [MIT License](LICENSE).

## Adding a new command

A command touches four places, which must stay in sync (the tests enforce most of it):

1. **CLI** - add a `cmd_<name>(args)` function and register it in `build_parser()` in
   `spritewright/cli.py` with `add(name, fn, help, ...)`. The help text is one line; every argument gets a
   `help=` string. Put the real work in a module function so it is usable from Python as well.
2. **Docs** - regenerate the command reference with `python tools/gen_command_docs.py` (never edit
   `docs/commands.md` by hand) and mention the command in `README.md` if users need to know about it.
3. **Skill** - add a list item for the command to `skill/reference/commands.md` (and to `SKILL.md` only if
   the agent needs it in its main flow; `SKILL.md` must stay at most 60 lines).
4. **Tests** - call the command at least once in `tests/smoke_test.py` or the matching `tests/test_*.py`.

`tests/test_skill.py` fails when a parser command is missing from the skill reference (or the reference
names a command that does not exist); `tests/test_release.py` fails when `docs/commands.md` is stale or a
documentation example uses an unknown command or option.

## Adding a palette

spritewright bundles only palettes whose license explicitly allows redistribution (currently PICO-8,
released under CC0). Before proposing a new bundled palette:

- Link to a statement by the palette's author that it is free to redistribute (for example CC0 or a
  permissive license). "Found on the internet" or an unclear license is not enough; such palettes stay
  downloadable by users instead (see [palettes/README.md](palettes/README.md)).
- Add `spritewright/palettes/<name>.hex` (one `RRGGBB` per line), an entry with the license in
  `THIRD_PARTY_NOTICES.md` and a line in `palettes/README.md`.
- Update the "only pico-8 is bundled" check in `tests/test_release.py`.

Adding a palette for your own use needs no change to the project: drop `<name>.hex` into `./palettes`,
`~/.spritewright/palettes` or a folder listed in `SPRITEWRIGHT_PALETTES`.

## Updating the example and the demo images

`examples/Test_Game` is regenerated with the tool itself (copy it to an outputs root, run
`spritewright build Test_Game Test_Hero --root <that root>`, copy it back without the `_archive/`
folders). After changing it, refresh the README images with `python tools/make_demo_assets.py`
(the total of `docs/assets/` must stay below 1 MB).

## Releasing (maintainers)

1. Update the version in `spritewright/__init__.py` and `pyproject.toml`, and move the "Unreleased"
   entries in `CHANGELOG.md` under the new version with the date.
2. Make sure CI is green, then tag the release (`vX.Y.Z`) and create a GitHub release.
