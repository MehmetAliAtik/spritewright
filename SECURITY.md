# Security policy

## Supported versions

spritewright is a young project; security fixes are made for the latest release only.

| Version | Supported |
|---|---|
| 0.1.x | yes |

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Report them privately through GitHub's private vulnerability reporting: open the repository's
**Security** tab and choose **Report a vulnerability** (this creates a draft
[security advisory](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
visible only to you and the maintainer).

Please include:

- the spritewright version (`spritewright --version`), Python version and operating system,
- the command or API call and input files needed to reproduce the problem,
- what happens and what you expected, and the impact as you see it.

You can expect an acknowledgement within a week. Once a fix is ready, it is released and the advisory is
published, crediting you unless you prefer otherwise.

## Scope notes

spritewright runs locally and makes no network requests. Two features execute code by design:

- `.py` sprite sources, `spritewright run SCRIPT.py` and `spritewright build` (which runs
  `source/make_*.py`) execute Python scripts with your user's permissions. Only run scripts you trust,
  exactly as you would with any other Python file.
- `spritewright install-skill` writes into `~/.claude/skills/spritewright/` (or the `--target` you give).

Reports about these behaviours are welcome when they happen unexpectedly (for example, code executed when
loading a `.json` file or a PNG, or files written outside the documented locations).
