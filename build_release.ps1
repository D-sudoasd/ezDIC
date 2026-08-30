param(
    [string]$Version = "0.1.4",
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
$MainScriptName = "dic_virtual_extensometer_gui_v7_multi_roi_range.py"

# These files are both copied to the portable package and listed as root-level
# datas in ezDIC.spec. Keep this single manifest in sync with the spec. Build
# this filename from code points so Windows PowerShell 5.1 can read this UTF-8
# script even when the file has no BOM.
$ReadmeBundleFile = "README_" + [char]0x4F7F + [char]0x7528 + [char]0x8BF4 + [char]0x660E + ".txt"
$BundleFiles = @(
    $ReadmeBundleFile,
    "VERSION.txt",
    "NOTICE_Attribution_and_Usage.txt",
    "LICENSE.txt",
    "CITATION.cff"
)
$SmokeRequested = $SmokeTest -or $env:EZDIC_BUILD_SMOKE_TEST

Set-Location $Root

function Invoke-NativeChecked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [string[]]$CommandParts
    )

    if ($CommandParts.Count -lt 1) {
        throw "$Label has no executable."
    }

    $exe = $CommandParts[0]
    $args = @()
    if ($CommandParts.Count -gt 1) {
        $args = $CommandParts[1..($CommandParts.Count - 1)]
    }

    try {
        & $exe @args
    }
    catch {
        throw "$Label could not start: $($_.Exception.Message)"
    }

    if ($null -eq $LASTEXITCODE) {
        $LASTEXITCODE = 0
    }
    $exitCode = [int]$LASTEXITCODE
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $($exitCode): $($CommandParts -join ' ')"
    }
}

function Test-PythonCommand {
    param(
        [string[]]$CommandParts
    )

    if ($CommandParts.Count -lt 1) {
        return $false
    }

    try {
        Invoke-NativeChecked -Label "Python probe" -CommandParts ($CommandParts + @("--version"))
        return $true
    }
    catch {
        return $false
    }
}

function Invoke-PythonCommand {
    param(
        [string[]]$CommandParts,
        [string[]]$Arguments,
        [string]$Label = "Python command"
    )

    $fullCommand = @($CommandParts) + @($Arguments)
    Invoke-NativeChecked -Label $Label -CommandParts $fullCommand
}

function Test-VenvPython {
    param(
        [string]$PythonPath
    )

    if (!(Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        return $false
    }
    if (-not (Test-PythonCommand -CommandParts @($PythonPath))) {
        return $false
    }

    try {
        Invoke-PythonCommand -CommandParts @($PythonPath) -Arguments @("-m", "pip", "--version") -Label "Build-environment pip probe"
        return $true
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

function Ensure-BuildVenv {
    if (Test-Path -LiteralPath $VenvPython) {
        if (-not (Test-VenvPython -PythonPath $VenvPython)) {
            Write-Warning "Existing build virtual environment is not usable. Recreating .venv-build..."
            Remove-Item -LiteralPath $VenvDir -Recurse -Force
        }
    }

    if (!(Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        $BasePython = Get-BasePythonCommand
        try {
            Invoke-PythonCommand -CommandParts $BasePython -Arguments @("-m", "venv", $VenvDir) -Label "Build virtual-environment creation"
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
}

function Read-RequiredText {
    param([string]$Path)

    if (!(Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required release file is missing: $Path"
    }
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8
}

function Test-ReleaseContracts {
    if ($Version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+$') {
        throw "-Version must be a semantic version such as 0.1.4; received '$Version'."
    }

    $versionPath = Join-Path $Root "VERSION.txt"
    $versionText = Read-RequiredText $versionPath
    if ($versionText -notmatch '(?m)^\s*ezDIC\s+v([0-9]+\.[0-9]+\.[0-9]+)\s*$') {
        throw "VERSION.txt must start with 'ezDIC v<version>'."
    }
    $versionFileValue = $Matches[1]

    $mainPath = Join-Path $Root $MainScriptName
    $mainText = Read-RequiredText $mainPath
    if ($mainText -notmatch '(?m)^\s*APP_VERSION\s*=\s*["'']([^"'']+)["'']') {
        throw "$MainScriptName does not define a readable APP_VERSION."
    }
    $appVersionValue = $Matches[1]

    if ($Version -ne $versionFileValue -or $Version -ne $appVersionValue) {
        throw "Version mismatch: -Version=$Version, VERSION.txt=$versionFileValue, APP_VERSION=$appVersionValue."
    }

    $citationPath = Join-Path $Root "CITATION.cff"
    $citationText = Read-RequiredText $citationPath
    if ($citationText -notmatch '(?m)^\s*version:\s*([0-9]+\.[0-9]+\.[0-9]+)\s*$') {
        throw "CITATION.cff does not define a readable version."
    }
    $citationVersion = $Matches[1]
    if ($citationVersion -ne $Version) {
        throw "CITATION.cff version $citationVersion does not match $Version."
    }
    if ($citationText -notmatch '(?m)^\s*date-released:\s*2026-08-30\s*$') {
        throw "CITATION.cff date-released must be 2026-08-30 for this build."
    }

    $zenodoPath = Join-Path $Root ".zenodo.json"
    $zenodoText = Read-RequiredText $zenodoPath
    try {
        $zenodo = $zenodoText | ConvertFrom-Json
    }
    catch {
        throw ".zenodo.json is not valid JSON: $($_.Exception.Message)"
    }
    if ([string]$zenodo.version -ne $Version) {
        throw ".zenodo.json version $($zenodo.version) does not match $Version."
    }
    if ([string]$zenodo.publication_date -ne "2026-08-30") {
        throw ".zenodo.json publication_date must be 2026-08-30."
    }

    $specPath = Join-Path $Root "ezDIC.spec"
    $specText = Read-RequiredText $specPath
    if ($specText -notmatch "name='ezDIC'") {
        throw "ezDIC.spec does not define the ezDIC executable."
    }
    if ($specText -notmatch 'console=False') {
        throw "ezDIC.spec must build a windowed executable (console=False)."
    }

    $specDataNames = @(
        [regex]::Matches($specText, '\("([^"]+)",\s*"\."\)') |
            ForEach-Object { $_.Groups[1].Value }
    )
    foreach ($bundleFile in $BundleFiles) {
        if ($specDataNames -notcontains $bundleFile) {
            throw "ezDIC.spec is missing bundle data entry: $bundleFile"
        }
        [void](Read-RequiredText (Join-Path $Root $bundleFile))
    }
    $unexpectedSpecData = @($specDataNames | Where-Object { $_ -notin $BundleFiles })
    if ($unexpectedSpecData.Count -gt 0) {
        throw "ezDIC.spec has data entries outside the portable manifest: $($unexpectedSpecData -join ', ')"
    }

    $requirementsPath = Join-Path $Root "requirements.txt"
    $requirementsText = Read-RequiredText $requirementsPath
    if ($requirementsText -match '(?im)^\s*originpro\s*(?:[<>=!~].*)?$') {
        throw "requirements.txt must not include optional originpro; use requirements-origin.txt."
    }
    $originRequirementsPath = Join-Path $Root "requirements-origin.txt"
    $originRequirementsText = Read-RequiredText $originRequirementsPath
    if ($originRequirementsText -notmatch '(?im)^\s*originpro\s*(?:[<>=!~].*)?$') {
        throw "requirements-origin.txt must declare originpro."
    }
    $buildRequirementsPath = Join-Path $Root "requirements-build.txt"
    $buildRequirementsText = Read-RequiredText $buildRequirementsPath
    if ($buildRequirementsText -notmatch '(?im)^\s*-r\s+requirements\.txt\s*$') {
        throw "requirements-build.txt must include requirements.txt."
    }
    if ($buildRequirementsText -notmatch '(?im)^\s*-r\s+requirements-origin\.txt\s*$') {
        throw "requirements-build.txt must include requirements-origin.txt for release builds."
    }

    Write-Host "Release contract: version $Version; release date 2026-08-30; bundle manifest verified."
}

if ($SmokeRequested) {
    # Keep the smoke path useful for a minimal copied build script: it checks
    # the build environment and, when release files are present, also checks
    # the release metadata/manifest. The full build always requires metadata.
    Ensure-BuildVenv
    Invoke-PythonCommand -CommandParts @($VenvPython) -Arguments @("--version") -Label "Smoke-test Python"
    Invoke-PythonCommand -CommandParts @($VenvPython) -Arguments @("-m", "pip", "--version") -Label "Smoke-test pip"

    $contractInputNames = @(
        $MainScriptName,
        ".zenodo.json",
        "CITATION.cff",
        "requirements.txt",
        "requirements-origin.txt",
        "requirements-build.txt",
        "ezDIC.spec"
    ) + $BundleFiles
    $presentContractInputs = @(
        $contractInputNames | Where-Object { Test-Path -LiteralPath (Join-Path $Root $_) -PathType Leaf }
    )
    if ($presentContractInputs.Count -gt 0) {
        Test-ReleaseContracts
        Write-Host "Release metadata and portable-file manifest checks passed."
    }
    else {
        Write-Host "Minimal smoke fixture detected; release metadata checks deferred to a full build."
    }

    Write-Host "ezDIC build smoke test"
    Write-Host "Project: $Root"
    Write-Host "Build-environment Python and pip checks passed."
    exit 0
}

Test-ReleaseContracts
Ensure-BuildVenv

Invoke-PythonCommand -CommandParts @($VenvPython) -Arguments @("-m", "pip", "install", "--upgrade", "pip") -Label "pip upgrade"
Invoke-PythonCommand -CommandParts @($VenvPython) -Arguments @("-m", "pip", "install", "-r", (Join-Path $Root "requirements-build.txt")) -Label "build requirements installation"
Invoke-PythonCommand -CommandParts @($VenvPython) -Arguments @("-m", "pytest", "-q") -Label "pytest"
Invoke-PythonCommand -CommandParts @($VenvPython) -Arguments @("-m", "py_compile", (Join-Path $Root $MainScriptName)) -Label "py_compile"

if (Test-Path -LiteralPath (Join-Path $Root "build")) {
    Remove-Item -LiteralPath (Join-Path $Root "build") -Recurse -Force
}
if (Test-Path -LiteralPath (Join-Path $Root "dist")) {
    Remove-Item -LiteralPath (Join-Path $Root "dist") -Recurse -Force
}

Invoke-PythonCommand -CommandParts @($VenvPython) -Arguments @("-m", "PyInstaller", (Join-Path $Root "ezDIC.spec"), "--clean", "--noconfirm") -Label "PyInstaller"

if (!(Test-Path -LiteralPath $DistDir -PathType Container)) {
    throw "PyInstaller output was not found: $DistDir"
}

if (Test-Path -LiteralPath $ReleaseDir) {
    Remove-Item -LiteralPath $ReleaseDir -Recurse -Force
}
New-Item -ItemType Directory -Path $ReleaseRoot -Force | Out-Null
Copy-Item -LiteralPath $DistDir -Destination $ReleaseDir -Recurse -Force

foreach ($bundleFile in $BundleFiles) {
    $source = Join-Path $Root $bundleFile
    $destination = Join-Path $ReleaseDir $bundleFile
    Copy-Item -LiteralPath $source -Destination $destination -Force
}

foreach ($bundleFile in $BundleFiles) {
    $packagedFile = Join-Path $ReleaseDir $bundleFile
    if (!(Test-Path -LiteralPath $packagedFile -PathType Leaf)) {
        throw "Portable package is missing required file: $bundleFile"
    }
}

if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}
Compress-Archive -Path $ReleaseDir -DestinationPath $ZipPath -Force
if (!(Test-Path -LiteralPath $ZipPath -PathType Leaf)) {
    throw "Release zip was not created: $ZipPath"
}

Write-Host "Release folder: $ReleaseDir"
Write-Host "Release zip: $ZipPath"
