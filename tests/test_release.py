"""Tests: release hygiene - --version, help text for every command, English-only sources, no personal
paths, nothing written into the package, skill install from installed package data.

Run standalone:  python tests/test_release.py
Also executed by tests/smoke_test.py (shared counters).
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import spritewright as ps  # noqa: E402
from spritewright import cli as ps_cli  # noqa: E402
from spritewright import paths as ps_paths  # noqa: E402
from spritewright import skill as ps_skill  # noqa: E402

TURKISH = re.compile("[" + "".join(map(chr, (0x11F, 0xFC, 0x15F, 0x131, 0xF6, 0xE7, 0x11E, 0xDC, 0x15E, 0x130, 0xD6, 0xC7))) + "]")
# personal strings that must never appear in the repository (assembled so this file does not contain them)
PERSONAL = ["C:" + "\\" + "Users", "D:" + "\\" + "Proje" + "ler", "Ham" + "mer",
            "alimehmet" + "atik"]
TEXT_SUFFIXES = {".py", ".md", ".json", ".toml", ".txt", ".ps1", ".hex", ".cfg", ".yml", ".yaml"}
# Files exempt from the English / personal-path scans below (none: every document is covered).
PENDING_DOCS = set()
# Public documentation whose `spritewright <command> ...` examples must use real commands and flags.
PUBLIC_DOCS = ["README.md", "CONTRIBUTING.md", "docs/style-guide-format.md", "docs/sprite-grid-format.md",
               "docs/animation-templates.md"]
DEMO_ASSETS = ["docs/assets/test_hero_atlas.png", "docs/assets/test_hero_walk.gif", "docs/assets/test_hero_idle.gif"]


def doc_command_lines(text):
    """`spritewright <cmd> ...` invocations: lines of fenced code blocks and inline code spans."""
    out, fenced = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            m = re.match(r"^\s*spritewright ([a-z][a-z-]*)(.*)$", line)
            if m:
                out.append((m.group(1), m.group(2).split("#")[0]))
        else:
            for m in re.finditer(r"`spritewright ([a-z][a-z-]*)([^`]*)`", line):
                out.append((m.group(1), m.group(2)))
    return out

def repo_files():
    """Files of the repository (tracked + new, not ignored), relative POSIX paths; None without git."""
    try:
        r = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=str(ROOT),
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return sorted({ln.strip() for ln in r.stdout.splitlines() if ln.strip() and (ROOT / ln.strip()).is_file()})


def _frontmatter_end(text):
    m = re.match(r"^---\r?\n.*?\r?\n---\r?\n", text, re.S)
    return m.end() if m else 0


def _subparsers():
    p = ps_cli.build_parser()
    sub = next(a for a in p._actions if a.__class__.__name__ == "_SubParsersAction")
    helps = {a.dest: a.help for a in sub._choices_actions}
    return p, sub, helps


def run(check, cli, tmp):
    # ---- --version / --help
    out = cli("--version", contains=f"spritewright {ps.__version__}")
    check("release: version is 0.1.0", ps.__version__ == "0.1.0" and out.strip() == "spritewright 0.1.0", out)
    p, sub, helps = _subparsers()
    empty = sorted(c for c in sub.choices if not (helps.get(c) or "").strip())
    check("release: every subcommand has a one-line help", not empty, str(empty))
    no_desc = sorted(c for c, sp in sub.choices.items() if not (sp.description or "").strip())
    check("release: every subcommand -h has a description", not no_desc, str(no_desc))
    out = cli("--help")
    missing = sorted(c for c in sub.choices if not re.search(rf"^\s+{re.escape(c)}\s", out, re.M))
    check("release: --help lists every command", not missing and "--version" in out, str(missing))
    out = cli("install-skill", "--help", contains="--uninstall")
    check("release: subcommand --help works", "--dry-run" in out and "--target" in out, out[-300:])

    # ---- English only, no personal paths (repository files)
    files = repo_files()
    if files is None:
        check("release: repository file scan (git not available - skipped)", True)
    else:
        turkish, personal = [], []
        for rel in files:
            path = ROOT / rel
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            # the public repository URL legitimately contains the GitHub owner name
            scan = re.sub(r"github\.com/[\w-]+/spritewright", "", text, flags=re.I)
            for s in PERSONAL:
                if s.lower() in scan.lower() and rel not in PENDING_DOCS:
                    personal.append(f"{rel}: {s}")
            if path.suffix.lower() in (".py", ".md", ".json") and rel not in PENDING_DOCS:
                body = text[_frontmatter_end(text):] if rel == "SKILL.md" else text
                for i, line in enumerate(body.splitlines(), 1):
                    if TURKISH.search(line):
                        turkish.append(f"{rel}:{i}")
        check("release: no Turkish characters outside the SKILL.md trigger phrases", not turkish, str(turkish[:20]))
        check("release: no personal paths / names in the repository", not personal, str(personal[:20]))
        removed = [f for f in files if f.endswith(".hex") and Path(f).stem.lower() in
                   ("sweetie-16", "endesga-32", "endesga-64", "resurrect-64", "aap-64")]
        check("release: only pico-8 is bundled", not removed and "spritewright/palettes/pico-8.hex" in files,
              str(removed))

    # ---- runtime never writes into the package; defaults are cwd-relative
    pkg = ps_paths.PACKAGE_DIR
    extra = sorted(d.name for d in pkg.iterdir() if d.is_dir()
                   and d.name not in ("palettes", "templates", "__pycache__", "_skill"))
    check("release: no runtime folders inside the package", not extra, str(extra))
    saved = {k: os.environ.pop(k, None) for k in ("SPRITEWRIGHT_OUTPUTS", "SPRITEWRIGHT_OUTPUT",
                                                   "SPRITEWRIGHT_PROJECTS", "PIXELSTUDIO_OUTPUTS",
                                                   "PIXELSTUDIO_OUTPUT")}
    try:
        cwd = Path.cwd()
        check("release: default roots are ./outputs, ./output, ./projects",
              ps_paths.outputs_root() == cwd / "outputs" and ps_paths.scratch_root() == cwd / "output"
              and ps_paths.projects_root() == cwd / "projects")
        os.environ["PIXELSTUDIO_OUTPUTS"] = str(tmp / "legacy")
        check("release: legacy PIXELSTUDIO_OUTPUTS still accepted", ps_paths.outputs_root() == tmp / "legacy")
        os.environ["SPRITEWRIGHT_OUTPUTS"] = str(tmp / "new")
        check("release: SPRITEWRIGHT_OUTPUTS wins over the legacy name", ps_paths.outputs_root() == tmp / "new")
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
    check("release: bundled palette dir is inside the package and last in the search order",
          ps_paths.palette_dirs()[-1].resolve() == ps_paths.BUNDLED_PALETTES.resolve()
          and (ps_paths.BUNDLED_PALETTES / "pico-8.hex").is_file())

    # ---- skill install from installed package data (spritewright/_skill/, as in the wheel)
    fake_pkg = tmp / "fake_site" / "spritewright"
    src_skill, src_ref = ps_skill.skill_sources()
    (fake_pkg / "_skill").mkdir(parents=True, exist_ok=True)
    shutil.copy(src_skill, fake_pkg / "_skill" / "SKILL.md")
    shutil.copytree(src_ref, fake_pkg / "_skill" / "reference", dirs_exist_ok=True)
    old = ps_skill.PACKAGE_DIR, ps_skill.ROOT
    ps_skill.PACKAGE_DIR, ps_skill.ROOT = fake_pkg, fake_pkg.parent
    try:
        srcs = ps_skill.skill_sources()
        cmd = ps_skill.default_command()
        lines = ps_skill.install(target=tmp / "skills_pkg")
    finally:
        ps_skill.PACKAGE_DIR, ps_skill.ROOT = old
    got = (tmp / "skills_pkg" / "spritewright" / "SKILL.md")
    text = got.read_text(encoding="utf-8") if got.is_file() else ""
    check("release: install-skill reads the package copy (_skill/) when installed",
          srcs[0] == fake_pkg / "_skill" / "SKILL.md" and "spritewright" in cmd and "spritewright.py" not in cmd
          and f"`{cmd} <cmd>`" in text and len(list((got.parent / "reference").glob("*.md"))) >= 6, str(lines))

    # ---- public docs: generated command reference is current, examples use real commands / flags
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import gen_command_docs
        current = (ROOT / "docs" / "commands.md").read_text(encoding="utf-8")
        check("release: docs/commands.md is up to date (python tools/gen_command_docs.py)",
              current == gen_command_docs.generate())
    finally:
        sys.path.remove(str(ROOT / "tools"))
    flags = {c: {f for a in sp._actions for f in a.option_strings} for c, sp in sub.choices.items()}
    bad = []
    for rel in PUBLIC_DOCS:
        path = ROOT / rel
        if not path.is_file():
            bad.append(f"{rel}: missing")
            continue
        for c, rest in doc_command_lines(path.read_text(encoding="utf-8")):
            if c not in sub.choices:
                bad.append(f"{rel}: unknown command {c}")
                continue
            for fl in re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]*|-[a-zA-Z])(?![\w-])", rest):
                if fl not in flags[c]:
                    bad.append(f"{rel}: {c} has no option {fl}")
    check("release: documented spritewright commands and options exist", not bad, str(bad[:20]))
    sizes = [(ROOT / f).stat().st_size if (ROOT / f).is_file() else None for f in DEMO_ASSETS]
    check("release: README demo assets exist, total < 1 MB",
          None not in sizes and sum(sizes) < 1024 * 1024
          and all(f in (ROOT / "README.md").read_text(encoding="utf-8") for f in DEMO_ASSETS), str(sizes))


if __name__ == "__main__":
    FAILS, N = [], [0]
    TMP = Path(tempfile.mkdtemp(prefix="spritewright_release_"))
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    def check(name, cond, detail=""):
        N[0] += 1
        print(f"[{'ok ' if cond else 'FAIL'}] {name}" + ("" if cond else f"  ({str(detail)[:600]})"))
        if not cond:
            FAILS.append(name)

    def cli(*args, expect=0, contains=None):
        r = subprocess.run([sys.executable, str(ROOT / "spritewright.py"), *map(str, args)],
                           capture_output=True, text=True, cwd=str(ROOT), encoding="utf-8", errors="replace")
        out = r.stdout + r.stderr
        check("cli: " + " ".join(map(str, args))[:90],
              r.returncode == expect and (contains is None or contains in out), out[-600:])
        return out

    run(check, cli, TMP)
    print(f"\n{N[0] - len(FAILS)}/{N[0]} passed")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if FAILS else 0)
