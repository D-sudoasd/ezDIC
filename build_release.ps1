param(
    [string]$Version = "0.1.3",
    [switch]$SmokeTest
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

function Test-PythonCommand {
    param(
        [string[]]$CommandParts
    )

    if ($CommandParts.Count -lt 1) {
        return $false
    }

    $exe = $CommandParts[0]
    $args = @()
    if ($CommandParts.Count -gt 1) {
        $args = $CommandParts[1..($CommandParts.Count - 1)]
    }

    try {
        & $exe @args --version *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

function Invoke-PythonCommand {
    param(
        [string[]]$CommandParts,
        [string[]]$Arguments
    )

    $exe = $CommandParts[0]
    $baseArgs = @()
    if ($CommandParts.Count -gt 1) {
        $baseArgs = $CommandParts[1..($CommandParts.Count - 1)]
    }

    & $exe @baseArgs @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed: $($CommandParts -join ' ') $($Arguments -join ' ')"
    }
}

function Test-VenvPython {
    param(
        [string]$PythonPath
    )

    if (!(Test-Path $PythonPath)) {
        return $false
    }
    if (-not (Test-PythonCommand -CommandParts @($PythonPath))) {
        return $false
    }

    try {
        & $PythonPath -m pip --version *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

function Get-BasePythonCommand {
    $candidates = @(
        ,@("py", "-3.11")
        ,@("py", "-3")
        ,@("python")
    )

    foreach ($candidate in $candidates) {
        if (Test-PythonCommand -CommandParts $candidate) {
            return $candidate
        }
    }

    throw "Python was not found. Install Python 3.11+ or ensure python is on PATH."
}

if (Test-Path $VenvPython) {
    if (-not (Test-VenvPython -PythonPath $VenvPython)) {
        Write-Warning "Existing build virtual environment is not usable. Recreating .venv-build..."
        Remove-Item -LiteralPath $VenvDir -Recurse -Force
    }
}

if (!(Test-Path $VenvPython)) {
    $BasePython = Get-BasePythonCommand
    try {
        Invoke-PythonCommand -CommandParts $BasePython -Arguments @("-m", "venv", $VenvDir)
    }
    catch {
        if (Test-VenvPython -PythonPath $VenvPython) {
            Write-Warning "Virtual environment creation returned an error, but .venv-build Python and pip are usable. Continuing..."
        }
        else {
            throw
        }
    }
}

if (-not (Test-VenvPython -PythonPath $VenvPython)) {
    throw "Created .venv-build, but its Python or pip is not usable: $VenvPython"
}

if ($SmokeTest -or $env:EZDIC_BUILD_SMOKE_TEST) {
    Write-Host "ezDIC build smoke test"
    Write-Host "Project: $Root"
    Write-Host "Python: $VenvPython"
    & $VenvPython --version
    exit 0
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
