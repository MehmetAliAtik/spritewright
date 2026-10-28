"""Install the spritewright Claude Code skill from a source checkout (thin wrapper).

Same as `spritewright install-skill` (pip / pipx / uv installs) or `python spritewright.py install-skill`.
Copies SKILL.md + skill/reference/*.md to ~/.claude/skills/spritewright/ and writes the command that
runs this checkout ("<this python>" "<this folder>/spritewright.py") into SKILL.md.

    python install_skill.py               install (or update)
    python install_skill.py --dry-run     show what would be written, change nothing
    python install_skill.py --uninstall   remove the installed skill (and its folders if empty)
    --target DIR      skills root (default ~/.claude/skills); files go to DIR/spritewright/
    --command CMD     command written into the skill (default: see spritewright/skill.py)
    --tool-path DIR   checkout to point the skill at (with --python: '"PY" "DIR/spritewright.py"')
    --python EXE      interpreter written into the skill (default: the one running this script)
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from spritewright.skill import install  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description="Install the spritewright Claude Code skill")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    ap.add_argument("--uninstall", action="store_true", help="remove the installed skill")
    ap.add_argument("--target", help="skills root (default: ~/.claude/skills)")
    ap.add_argument("--command", help="command line the skill uses to call the tool")
    ap.add_argument("--tool-path", help="checkout folder written into the skill command")
    ap.add_argument("--python", help="python interpreter written into the skill command")
    a = ap.parse_args(argv)
    cmd = a.command
    if cmd is None and (a.tool_path or a.python):
        tool = Path(a.tool_path) if a.tool_path else HERE
        cmd = f'"{a.python or sys.executable}" "{tool / "spritewright.py"}"'
    try:
        lines = install(target=a.target, dry_run=a.dry_run, uninstall=a.uninstall, command=cmd)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
