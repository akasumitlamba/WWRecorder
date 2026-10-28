<#
.SYNOPSIS
  One-click sequential runner for WWRecorder Windows E2E Testing.

.DESCRIPTION
  Prefer this script on a real Windows desktop. It:
    1. Locates the repo root from this script path
    2. Prefers .\.venv\Scripts\python.exe when present
    3. Installs requirements-dev.txt if pytest is missing (opt-in with -InstallDeps)
    4. Runs tests/windows_e2e/run_all.py (sequential pytest + QA reports)
    5. Prints the report folder for QA

  Exit code mirrors the Python runner (0 ok, 1 test/report failure, 2 precondition).

.PARAMETER Markers
  Optional pytest -m expression, e.g. "feature_recording and not windows_gui"

.PARAMETER ReportDir
  Output directory (default: <repo>\artifacts\windows_e2e)

.PARAMETER ForceOffscreen
  Set QT_QPA_PLATFORM=offscreen even on Windows (headless agents only)

.PARAMETER InstallDeps
  Run pip install -r requirements-dev.txt before the suite

.PARAMETER CollectOnly
  Only collect tests (harness sanity)

.PARAMETER DryReport
  Only exercise the report generator with synthetic JUnit

.NOTES
  Windows-only product execution. Do not treat a Linux collect-only run as GUI E2E pass.
#>
[CmdletBinding()]
param(
    [string]$Markers = "",
    [string]$ReportDir = "",
    [switch]$ForceOffscreen,
    [switch]$InstallDeps,
    [switch]$CollectOnly,
    [switch]$DryReport
)

$ErrorActionPreference = "Stop"
$E2ERoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $E2ERoot "..\..")
Set-Location $RepoRoot

if (-not $ReportDir) {
    $ReportDir = Join-Path $RepoRoot "artifacts\windows_e2e"
}
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null

function Fail-Preflight([string]$Message) {
    $safe = [System.Net.WebUtility]::HtmlEncode($Message)
    Set-Content -Encoding UTF8 -Path (Join-Path $ReportDir 'summary.md') -Value "# Test setup failed`n`n$Message"
    Set-Content -Encoding UTF8 -Path (Join-Path $ReportDir 'summary.html') -Value "<html><body><h1>Test setup failed</h1><p>$safe</p></body></html>"
    @{ status = 'setup_failed'; message = $Message } | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $ReportDir 'summary.json')
    Write-Host $Message
    exit 2
}

$Python = $null
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $Python = $VenvPython
} else {
    $cmd = Get-Command py -ErrorAction SilentlyContinue
    if ($cmd) {
        & $cmd.Source -3.13 -m venv (Join-Path $RepoRoot '.venv')
        if ($LASTEXITCODE -eq 0) { $Python = $VenvPython }
    }
    if (-not $Python) {
        $cmd = Get-Command python -ErrorAction SilentlyContinue
        if ($cmd) {
            & $cmd.Source -m venv (Join-Path $RepoRoot '.venv')
            if ($LASTEXITCODE -eq 0) { $Python = $VenvPython }
        }
    }
}
if (-not $Python) {
    Fail-Preflight "Python not found. Install Python 3.13, then double-click RUN_TESTS.cmd."
}

Write-Host "WWRecorder Windows E2E"
Write-Host "  repo:    $RepoRoot"
Write-Host "  python:  $Python"
Write-Host "  reports: $ReportDir"

if ($InstallDeps) {
    & $Python -m pip install --no-input --disable-pip-version-check -r (Join-Path $RepoRoot "requirements-dev.txt")
    if ($LASTEXITCODE -ne 0) { Fail-Preflight "Dependency installation failed. Check network access and the console output." }
}

# Prove pytest import before launching the suite (clear failure, not silent skip-all)
& $Python -c "import pytest; print('pytest', pytest.__version__)"
if ($LASTEXITCODE -ne 0) {
    Fail-Preflight "pytest missing. Double-click RUN_TESTS.cmd to install test dependencies automatically."
}

if ($ForceOffscreen) {
    $env:WWR_E2E_FORCE_OFFSCREEN = "1"
    $env:QT_QPA_PLATFORM = "offscreen"
} else {
    # Interactive Windows desktop: do not force offscreen
    if ($env:QT_QPA_PLATFORM -eq "offscreen" -and -not $env:WWR_E2E_FORCE_OFFSCREEN) {
        Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
    }
}

$runner = Join-Path $E2ERoot "run_all.py"
$argList = @($runner, "--report-dir", $ReportDir)
if ($Markers) { $argList += @("--markers", $Markers) }
if ($CollectOnly) { $argList += "--collect-only" }
if ($DryReport) { $argList += "--dry-report" }

& $Python @argList
$code = $LASTEXITCODE

Write-Host ""
Write-Host "Reports directory: $ReportDir"
if (Test-Path (Join-Path $ReportDir "summary.md")) {
    Write-Host "Open: $(Join-Path $ReportDir 'summary.md')"
}
exit $code
