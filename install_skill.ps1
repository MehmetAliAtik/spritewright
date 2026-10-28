# Wrapper: installs the spritewright Claude Code skill. Arguments are passed through
# (e.g. .\install_skill.ps1 --dry-run   |   .\install_skill.ps1 --uninstall)
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = "py" }
& $py "$PSScriptRoot\install_skill.py" @args
exit $LASTEXITCODE
