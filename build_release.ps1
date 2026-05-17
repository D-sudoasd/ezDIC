param(
    [string]$Version = "0.1.3"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $Root ".venv-build"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$DistDir = Join-Path $Root "dist\ezDIC_Windows_x64"
$ReleaseRoot = Join-Path $Root "release"
$ReleaseDir = Join-Path $ReleaseRoot "ezDIC_Windows_x64"
$ZipPath = Join-Path $ReleaseRoot "ezDIC_Windows_x64_v$Version.zip"

Set-Location $Root

if (!(Test-Path $VenvPython)) {
    py -3.11 -m venv $VenvDir
}

& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r (Join-Path $Root "requirements-build.txt")

& $VenvPython -m pytest -q
& $VenvPython -m py_compile (Join-Path $Root "dic_virtual_extensometer_gui_v7_multi_roi_range.py")

if (Test-Path (Join-Path $Root "build")) {
    Remove-Item -LiteralPath (Join-Path $Root "build") -Recurse -Force
}
if (Test-Path (Join-Path $Root "dist")) {
    Remove-Item -LiteralPath (Join-Path $Root "dist") -Recurse -Force
}

& $VenvPython -m PyInstaller (Join-Path $Root "ezDIC.spec") --clean --noconfirm

if (!(Test-Path $DistDir)) {
    throw "PyInstaller output was not found: $DistDir"
}

if (Test-Path $ReleaseDir) {
    Remove-Item -LiteralPath $ReleaseDir -Recurse -Force
}
New-Item -ItemType Directory -Path $ReleaseRoot -Force | Out-Null
Copy-Item -LiteralPath $DistDir -Destination $ReleaseDir -Recurse -Force

$ReadmeFile = Get-ChildItem -LiteralPath $Root -Filter "README_*.txt" | Select-Object -First 1
if ($null -eq $ReadmeFile) {
    throw "README_*.txt was not found in $Root"
}
Copy-Item -LiteralPath $ReadmeFile.FullName -Destination $ReleaseDir -Force
Copy-Item -LiteralPath (Join-Path $Root "VERSION.txt") -Destination $ReleaseDir -Force
Copy-Item -LiteralPath (Join-Path $Root "NOTICE_Attribution_and_Usage.txt") -Destination $ReleaseDir -Force

if (Test-Path $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}
Compress-Archive -Path $ReleaseDir -DestinationPath $ZipPath -Force

Write-Host "Release folder: $ReleaseDir"
Write-Host "Release zip: $ZipPath"
