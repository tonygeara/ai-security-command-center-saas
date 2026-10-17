# Builds the Windows program and the Setup.exe installer.
#   powershell -ExecutionPolicy Bypass -File edge\installer\build.ps1
# Output: edge\installer\output\AI-Security-Command-Center-Setup-<version>.exe
$ErrorActionPreference = 'Stop'
$Installer = $PSScriptRoot
$Edge = Split-Path -Parent $Installer
$Venv = Join-Path $Edge '.venv-build'

$version = (Select-String -Path (Join-Path $Edge 'app\launcher.pyw') -Pattern "^APP_VERSION = '(.+)'").Matches[0].Groups[1].Value
if (-not $version) { throw 'APP_VERSION not found in launcher.pyw' }
Write-Host "Building AI Security Command Center $version" -ForegroundColor Cyan

if (-not (Test-Path (Join-Path $Venv 'Scripts\python.exe'))) {
    $py = (Get-Command python -ErrorAction Stop).Source
    & $py -m venv $Venv
}
$python = Join-Path $Venv 'Scripts\python.exe'
& $python -m pip install --quiet --upgrade pip
& $python -m pip install --quiet -r (Join-Path $Edge 'requirements.txt') 'pyinstaller>=6.10,<7'
if ($LASTEXITCODE) { throw 'Dependency install failed' }

# Syntax check before packaging.
& $python -m py_compile (Join-Path $Edge 'app\launcher.pyw') (Join-Path $Edge 'app\dashboard.py')
if ($LASTEXITCODE) { throw 'Python syntax check failed' }

Push-Location $Installer
try {
    & $python -m PyInstaller --clean --noconfirm --distpath dist --workpath build AI_Security_Command_Center.spec
    if ($LASTEXITCODE) { throw 'PyInstaller build failed' }
} finally { Pop-Location }

$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw 'Inno Setup 6 not found. Install it with: winget install -e --id JRSoftware.InnoSetup' }
& $iscc "/DMyAppVersion=$($version.TrimStart('V'))" (Join-Path $Installer 'installer.iss')
if ($LASTEXITCODE) { throw 'Installer build failed' }
Write-Host "Done: $(Join-Path $Installer 'output')" -ForegroundColor Green
