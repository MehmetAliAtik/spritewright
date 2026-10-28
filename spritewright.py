"""Run spritewright from a source checkout without installing it.

    python spritewright.py <command> ...      (same as the installed `spritewright` command; see -h)

`import spritewright` still resolves to the spritewright/ package next to this file (a package
directory takes precedence over a module of the same name).
"""
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
if (_here / "spritewright" / "__init__.py").is_file():
    if str(_here) not in sys.path:
        sys.path.insert(0, str(_here))
else:  # copied without the package: use the installed one instead of importing this file
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != _here]

if __name__ == "__main__":
    from spritewright.cli import main
    sys.exit(main())
