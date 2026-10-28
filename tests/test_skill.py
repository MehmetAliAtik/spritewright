"""Tests: SKILL.md (Claude Code skill) + skill/reference/*.md + install_skill.py.

Run standalone:  python tests/test_skill.py
Also executed by tests/smoke_test.py (shared counters).
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from spritewright import cli as ps_cli  # noqa: E402
from spritewright import skill as ps_skill  # noqa: E402

SKILL = ROOT / "SKILL.md"
REFDIR = ROOT / "skill" / "reference"
COMMANDS_MD = REFDIR / "commands.md"
REF_FILES = ("commands.md", "api.md", "animation.md", "anatomy.md", "troubleshooting.md", "style-system.md")
INSTALLER = ROOT / "install_skill.py"
PLACEHOLDER = "`spritewright <cmd>`"


def _frontmatter(text):
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
    if not m:
        return None
    fm, key = {}, None
    for line in m.group(1).splitlines():
        km = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if km:
            key = km.group(1)
            fm[key] = km.group(2).strip()
        elif key and line.startswith((" ", "\t")):
            fm[key] = (fm[key] + " " + line.strip()).strip()
    for k, v in fm.items():
        if v in (">-", ">", "|", "|-"):
            fm[k] = ""
    return {k: v.replace(">- ", "", 1) if v.startswith(">- ") else v for k, v in fm.items()}


def _parser_commands():
    p = ps_cli.build_parser()
    sub = next(a for a in p._actions if a.__class__.__name__ == "_SubParsersAction")
    return set(sub.choices)


def _reference_commands(text):
    """Commands documented as list items: '- `cmd ...`' (commands.md) or '- `PS cmd ...`' (SKILL.md), plus
    further '`[PS ]cmd ...`' items after '/', '.' or ',' on the same line."""
    cmds = set()
    for line in text.splitlines():
        m = re.match(r"^- `(?:PS )?([a-z][a-z-]*)", line)
        if m:
            cmds.add(m.group(1))
            for extra in re.findall(r"(?:/|\.|,)\s+`(?:PS )?([a-z][a-z-]*)[ `]", line):
                cmds.add(extra)
    return cmds


def _mentioned_commands(text):
    """Every `PS <cmd>` invocation."""
    return set(re.findall(r"\bPS ([a-z][a-z-]+)", text)) - {"cmd"}


def run(check, cli, tmp):
    text = SKILL.read_text(encoding="utf-8")
    fm = _frontmatter(text)
    check("skill: frontmatter present", fm is not None)
    fm = fm or {}
    check("skill: name is spritewright", fm.get("name") == "spritewright", str(fm.get("name")))
    desc = fm.get("description", "")
    check("skill: description long enough + triggers (EN + TR)", len(desc) > 200 and all(
        w in desc.lower() for w in ("pixel art", "sprite sheet", "unity", "gif", "animasyon", "piksel")), desc[:200])
    check("skill: description <= 1024 chars", len(desc) <= 1024, str(len(desc)))
    n_lines = text.count("\n")
    check("skill: SKILL.md <= 60 lines", n_lines <= 60, str(n_lines))
    check("skill: command placeholder present, no absolute paths", PLACEHOLDER in text
          and not re.search(r"[A-Za-z]:[\\/]|/home/|/Users/", text))
    check("skill: flow + rules present", all(w in text for w in ("PS context", "PS build", "--draft",
                                                                 "explicit request", "reference/")))
    check("skill: reference files exist", all((REFDIR / f).is_file() for f in REF_FILES),
          str([f for f in REF_FILES if not (REFDIR / f).is_file()]))

    parser_cmds = _parser_commands()
    cmd_text = COMMANDS_MD.read_text(encoding="utf-8") if COMMANDS_MD.is_file() else ""
    in_cmds = _reference_commands(cmd_text)
    ref = _reference_commands(text) | in_cmds
    check("skill: every parser command documented (SKILL.md or commands.md)", parser_cmds <= ref,
          str(sorted(parser_cmds - ref)))
    check("skill: every documented command exists", ref <= parser_cmds, str(sorted(ref - parser_cmds)))
    check("skill: commands.md lists every command", parser_cmds <= in_cmds, str(sorted(parser_cmds - in_cmds)))
    used = set()
    for f in [SKILL] + [REFDIR / x for x in REF_FILES if (REFDIR / x).is_file()]:
        used |= _mentioned_commands(f.read_text(encoding="utf-8"))
    check("skill: every 'PS <cmd>' exists (all files)", used and used <= parser_cmds, str(sorted(used - parser_cmds)))

    # ---- installer: --target temp dir, --tool-path substitution, --dry-run, --uninstall
    def inst(*args):
        r = subprocess.run([sys.executable, str(INSTALLER), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        return r.returncode, r.stdout + r.stderr

    target = tmp / "skills_root"
    dest = target / "spritewright" / "SKILL.md"
    refd = target / "spritewright" / "reference"
    rc, out = inst("--target", target, "--dry-run")
    check("installer: dry-run writes nothing", rc == 0 and not dest.exists() and not refd.exists()
          and "[dry-run]" in out and str(dest) in out, out)
    rc, out = inst("--target", target)
    got = dest.read_text(encoding="utf-8") if dest.exists() else ""
    expect_cmd = ps_skill.default_command()  # checkout: "<python>" "<repo>/spritewright.py"
    check("installer: writes SKILL.md with the command of this installation", rc == 0 and got.startswith("---")
          and f"`{expect_cmd} <cmd>`" in got and PLACEHOLDER not in got
          and (str(ROOT / "spritewright.py") in got) == (Path(ps_skill.ROOT) == ROOT), out)
    check("installer: copies reference files", all((refd / f).is_file() for f in REF_FILES)
          and (refd / "commands.md").read_text(encoding="utf-8") == COMMANDS_MD.read_text(encoding="utf-8"), out)
    moved = "X:/Moved Repo/spritewright"
    rc, out = inst("--target", target, "--tool-path", moved, "--python", "X:/Py/python.exe")
    got = dest.read_text(encoding="utf-8") if dest.exists() else ""
    check("installer: --tool-path/--python written into the command", rc == 0 and "X:/Py/python.exe" in got
          and "Moved Repo" in got and str(ROOT) not in got and "update" in out, out)
    rc, out = inst("--target", target, "--command", "spritewright")
    got = dest.read_text(encoding="utf-8") if dest.exists() else ""
    check("installer: --command spritewright", rc == 0 and "`spritewright <cmd>`" in got and str(ROOT) not in got, out)
    out = cli("install-skill", "--target", tmp / "skills_cli", "--dry-run", contains="[dry-run]")
    check("cli install-skill --dry-run writes nothing", not (tmp / "skills_cli").exists(), out)
    cli("install-skill", "--target", tmp / "skills_cli", contains="skill installed")
    check("cli install-skill writes skill + reference", (tmp / "skills_cli" / "spritewright" / "SKILL.md").is_file()
          and len(list((tmp / "skills_cli" / "spritewright" / "reference").glob("*.md"))) == len(REF_FILES))
    cli("install-skill", "--target", tmp / "skills_cli", "--uninstall", contains="removed")
    check("cli install-skill --uninstall removes it", not (tmp / "skills_cli" / "spritewright").exists())
    rc, out = inst("--target", target, "--uninstall", "--dry-run")
    check("installer: uninstall dry-run keeps files", rc == 0 and dest.exists() and refd.is_dir(), out)
    rc, out = inst("--target", target, "--uninstall")
    check("installer: uninstall removes files + folders", rc == 0 and not dest.exists() and not refd.exists()
          and not dest.parent.exists(), out)
    rc, out = inst("--target", target, "--uninstall")
    check("installer: uninstall when absent is a no-op", rc == 0 and "nothing to remove" in out, out)


if __name__ == "__main__":
    FAILS, N = [], [0]
    TMP = Path(tempfile.mkdtemp(prefix="spritewright_skill_"))
    sys.stdout.reconfigure(errors="replace")

    def check(name, cond, detail=""):
        N[0] += 1
        print(f"[{'ok ' if cond else 'FAIL'}] {name}" + ("" if cond else f"  ({detail})"))
        if not cond:
            FAILS.append(name)

    def cli(*args, expect=0, contains=None):
        r = subprocess.run([sys.executable, str(ROOT / "spritewright.py"), *map(str, args)],
                           capture_output=True, text=True, cwd=str(ROOT), encoding="utf-8", errors="replace")
        out = r.stdout + r.stderr
        check("cli: " + " ".join(map(str, args))[:90],
              r.returncode == expect and (contains is None or contains in out), out[-400:])
        return out

    run(check, cli, TMP)
    print(f"\n{N[0] - len(FAILS)}/{N[0]} passed")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if FAILS else 0)
