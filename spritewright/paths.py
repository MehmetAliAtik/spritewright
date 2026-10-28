"""Where spritewright reads and writes files.

Nothing is ever written inside the installed package. Defaults are relative to the current working
directory; every root can be overridden with an environment variable (the old PIXELSTUDIO_* names are
still accepted as a fallback):

    outputs/   game projects (game-new, char-new, char-export, build)   SPRITEWRIGHT_OUTPUTS or --root
    output/    scratch output of single-sprite commands (render, gif)   SPRITEWRIGHT_OUTPUT
    projects/  loose sprite projects (new, import --project)            SPRITEWRIGHT_PROJECTS

Palette search order for a palette *name* (first match wins; a path to a .hex/.json always works):

    1. every folder in SPRITEWRIGHT_PALETTES (os.pathsep-separated)
    2. ./palettes                  (current working directory)
    3. ~/.spritewright/palettes
    4. <repo>/palettes             (only when running from a source checkout)
    5. the palettes bundled with the package (pico-8)

Paths stored on disk are relative to the file that stores them (POSIX separators), so output folders
can be moved, shared or committed without leaking absolute paths / user names. Readers resolve a
relative stored path against the storing file's folder; absolute stored paths (older files) still work.
"""
import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
# Repository root in a source checkout (site-packages when installed). Read-only: only used to make
# `import spritewright` work for drawing scripts and to find a checkout's palettes/ and examples/.
ROOT = PACKAGE_DIR.parent
BUNDLED_PALETTES = PACKAGE_DIR / "palettes"


def env(name):
    """SPRITEWRIGHT_<name>, else the legacy PIXELSTUDIO_<name>, else None."""
    return os.environ.get(f"SPRITEWRIGHT_{name}") or os.environ.get(f"PIXELSTUDIO_{name}") or None


def outputs_root(root=None):
    """Game projects root: root argument, env SPRITEWRIGHT_OUTPUTS, else ./outputs."""
    if root:
        return Path(root)
    e = env("OUTPUTS")
    return Path(e) if e else Path.cwd() / "outputs"


def scratch_root():
    """Scratch output root of single-sprite commands: env SPRITEWRIGHT_OUTPUT, else ./output."""
    e = env("OUTPUT")
    return Path(e) if e else Path.cwd() / "output"


def projects_root():
    """Loose sprite projects: env SPRITEWRIGHT_PROJECTS, else ./projects."""
    e = env("PROJECTS")
    return Path(e) if e else Path.cwd() / "projects"


def examples_root():
    """examples/ of a source checkout (may not exist when installed)."""
    return ROOT / "examples"


def palette_dirs():
    """Palette folders in search order (see module doc); only existing folders are returned."""
    dirs = []
    e = env("PALETTES")
    if e:
        dirs += [Path(p) for p in e.split(os.pathsep) if p]
    dirs += [Path.cwd() / "palettes", Path.home() / ".spritewright" / "palettes", ROOT / "palettes",
             BUNDLED_PALETTES]
    out, seen = [], set()
    for d in dirs:
        try:
            key = d.resolve()
        except OSError:
            continue
        if key in seen or not d.is_dir():
            continue
        seen.add(key)
        out.append(d)
    return out


def rel_to(path, base_dir):
    """`path` relative to `base_dir` with '/' separators. Empty/None -> ''. Falls back to the absolute
    path only when no relative path exists (e.g. a different Windows drive)."""
    if not path:
        return ""
    try:
        return os.path.relpath(Path(path).resolve(), Path(base_dir).resolve()).replace("\\", "/")
    except ValueError:
        return str(path)


def resolve_from(path, base_dir):
    """Inverse of rel_to: a stored path (relative to `base_dir`, or absolute) -> absolute Path."""
    if not path:
        return None
    p = Path(path)
    return p if p.is_absolute() else (Path(base_dir) / p).resolve()
