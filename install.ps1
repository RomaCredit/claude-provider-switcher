param(
    [ValidatePattern('^v[0-9]+\.[0-9]+\.[0-9]+$')]
    [string]$Version = 'v0.1.3',
    [string]$InstallDirectory,
    [switch]$NoPipx
)
$ErrorActionPreference = 'Stop'
$archive = "https://github.com/RomaCredit/claude-provider-switcher/archive/refs/tags/$Version.zip"
if (-not $NoPipx -and -not $InstallDirectory -and (Get-Command pipx -ErrorAction SilentlyContinue)) {
    & pipx install --force $archive
    if ($LASTEXITCODE -ne 0) { throw 'pipx installation failed.' }
    Write-Output 'Run: ccs --version. Use pipx ensurepath if the command is not found.'
    return
}
$pythonCommand = if (Get-Command python -ErrorAction SilentlyContinue) { 'python' } else { 'py' }
$versionArgs = if ($pythonCommand -eq 'py') { @('-3') } else { @() }
& $pythonCommand @versionArgs -c 'import sys; sys.exit(sys.version_info < (3,10))'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.10 or newer is required.' }
$environmentDir = if ($InstallDirectory) { [System.IO.Path]::GetFullPath($InstallDirectory) } else {
    Join-Path $env:LOCALAPPDATA 'claude-provider-switcher\venv'
}
& $pythonCommand @versionArgs -m venv $environmentDir
if ($LASTEXITCODE -ne 0) { throw 'Cannot create isolated Python environment.' }
$pythonPath = Join-Path $environmentDir 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw 'Python did not create the expected virtual environment. Check your Python installation.'
}
& $pythonPath -m pip install --upgrade $archive
if ($LASTEXITCODE -ne 0) { throw 'Package installation failed.' }
$commandDir = Join-Path $environmentDir 'Scripts'
Write-Output "Installed: $commandDir\ccs.exe"
Write-Output "Add $commandDir to your user PATH, then run ccs --version."
