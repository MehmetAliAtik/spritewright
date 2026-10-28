"""Install / uninstall the spritewright Claude Code skill.

The skill is SKILL.md + reference/*.md. They are read from the installed package
(spritewright/_skill/, put there by the wheel build) or, in a source checkout, from SKILL.md and
skill/reference/ at the repository root. They are copied to <skills root>/spritewright/ (default
~/.claude/skills/spritewright/). The line defining `PS <cmd>` in SKILL.md is rewritten to the command
that runs this installation of the tool:

    * --command given                      -> that command
    * running from a source checkout       -> "<python>" "<repo>/spritewright.py"
    * installed with pip / pipx / uv       -> spritewright   (or "<python>" -m spritewright when the
                                              entry point is not on PATH)
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from .paths import PACKAGE_DIR, ROOT

SKILL_NAME = "spritewright"
PLACEHOLDER = "`spritewright <cmd>`"  # the command as written in the repository copy of SKILL.md


def skill_sources():
    """-> (SKILL.md path, reference dir) from the installed package, else the source checkout."""
    for skill, ref in ((PACKAGE_DIR / "_skill" / "SKILL.md", PACKAGE_DIR / "_skill" / "reference"),
                       (ROOT / "SKILL.md", ROOT / "skill" / "reference")):
        if skill.is_file():
            return skill, ref
    raise FileNotFoundError("SKILL.md not found in the package (_skill/) or the source checkout")


def default_command():
    """Command line (without <cmd>) that runs this installation of the tool."""
    script = ROOT / "spritewright.py"
    if script.is_file() and (ROOT / "spritewright" / "cli.py").is_file():
        return f'"{sys.executable}" "{script}"'
    exe = shutil.which("spritewright")
    if exe:
        return "spritewright"
    return f'"{sys.executable}" -m spritewright'


def render(text, command):
    """Rewrite the `PS <cmd>` definition of SKILL.md to `command <cmd>`."""
    if PLACEHOLDER not in text:
        raise ValueError(f"SKILL.md does not contain the command placeholder {PLACEHOLDER}")
    return text.replace(PLACEHOLDER, f"`{command} <cmd>`", 1)


def install(target=None, dry_run=False, uninstall=False, command=None):
    """Install (or update / remove) the skill. target = skills root (default ~/.claude/skills); files go
    to <target>/spritewright/. Returns the printed lines (the last one is the summary)."""
    root = Path(target).expanduser() if target else Path.home() / ".claude" / "skills"
    dest_dir = root / SKILL_NAME
    dest = dest_dir / "SKILL.md"
    ref_dir = dest_dir / "reference"
    tag = "[dry-run] " if dry_run else ""
    out = []
    if uninstall:
        refs = sorted(ref_dir.glob("*.md")) if ref_dir.is_dir() else []
        if not dest.exists() and not refs:
            return [f"{tag}nothing to remove: {dest} does not exist"]
        for p in ([dest] if dest.exists() else []) + refs:
            out.append(f"{tag}remove {p}")
            if not dry_run:
                p.unlink()
        if not dry_run:
            for d in (ref_dir, dest_dir):
                try:
                    d.rmdir()
                    out.append(f"removed empty folder {d}")
                except OSError:
                    if d.exists():
                        out.append(f"kept folder {d} (not empty)")
        out.append(f"{tag}skill removed from {dest_dir}")
        return out
    src, src_ref = skill_sources()
    cmd = command or default_command()
    text = render(src.read_text(encoding="utf-8"), cmd)
    refs = sorted(src_ref.glob("*.md")) if src_ref.is_dir() else []
    action = "update" if dest.exists() else "create"
    out += [f"{tag}{action} {dest}", f"{tag}  command   : {cmd} <cmd>",
            f"{tag}  size      : {len(text.encode('utf-8'))} bytes, {text.count(chr(10))} lines",
            f"{tag}  reference : {len(refs)} file(s) -> {ref_dir} ({', '.join(p.name for p in refs)})"]
    if not dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        if refs:
            ref_dir.mkdir(parents=True, exist_ok=True)
            for p in refs:
                (ref_dir / p.name).write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    out.append(f"{tag}skill {'installed' if action == 'create' else 'updated'}: {dest} (command: {cmd}). "
               "Start a new Claude Code session to load it.")
    return out
