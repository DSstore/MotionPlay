<#
.SYNOPSIS
  Runs all MotionPlay automated checks and prints a summary. Needs no webcam, Unity, or database server.

.DESCRIPTION
  - Python unit tests (always)
  - C# test harness for the code Unity runs (if the .NET SDK is installed)
  - Python-to-C# UDP check (if the .NET SDK is installed)

.PARAMETER Coverage
  Measure Python line and branch coverage (needs:  .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt).
.PARAMETER ProjectRoot
  The MotionPlay folder. Defaults to the folder above this script.
#>
[CmdletBinding()]
param(
    [switch]$Coverage,
    [string]$ProjectRoot
)

$ErrorActionPreference = 'Stop'
if (-not $ProjectRoot) { $ProjectRoot = Split-Path -Parent $PSScriptRoot }
$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path $VenvPython)) {
    Write-Host "ERROR: The Python environment is not set up. Run scripts\setup.ps1 first." -ForegroundColor Red
    exit 1
}

$results = New-Object System.Collections.ArrayList
function Add-Result([string]$Name, [string]$Status, [string]$Detail) {
    [void]$results.Add([pscustomobject]@{ Check = $Name; Status = $Status; Detail = $Detail })
}

function Invoke-Native {
    # Run a command with live output; return its exit code and the last lines it printed.
    param([string]$File, [string[]]$Arguments)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $lines = @(& $File @Arguments 2>&1 | ForEach-Object { "$_" })
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previous }
    return [pscustomobject]@{ Code = $code; Lines = $lines }
}

Push-Location $ProjectRoot
try {
    # ---- Python tests ---------------------------------------------------------------------------------
    Write-Host "== Python tests" -ForegroundColor Cyan
    if ($Coverage) {
        $probe = Invoke-Native $VenvPython @('-m', 'coverage', '--version')
        if ($probe.Code -ne 0) {
            Write-Host "coverage is not installed. Run:  .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt" -ForegroundColor Yellow
            Add-Result 'Python tests' 'SKIPPED' 'coverage is not installed'
        } else {
            $run = Invoke-Native $VenvPython @('-m', 'coverage', 'run', '--branch', '--source=app,backend,cv_engine,shared', '-m', 'unittest', 'discover', '-s', 'tests')
            $run.Lines | Select-Object -Last 4 | Out-Host
            $report = Invoke-Native $VenvPython @('-m', 'coverage', 'report', '--skip-empty')
            $total = ($report.Lines | Where-Object { $_ -match '^TOTAL' } | Select-Object -First 1)
            $ran = ($run.Lines | Where-Object { $_ -match '^Ran \d+ tests' } | Select-Object -First 1)
            Add-Result 'Python tests' $(if ($run.Code -eq 0) { 'PASS' } else { 'FAIL' }) ("$ran; " + ($total -replace '\s+', ' '))
        }
    } else {
        $run = Invoke-Native $VenvPython @('-m', 'unittest', 'discover', '-s', 'tests')
        $run.Lines | Select-Object -Last 4 | Out-Host
        $ran = ($run.Lines | Where-Object { $_ -match '^Ran \d+ tests' } | Select-Object -First 1)
        Add-Result 'Python tests' $(if ($run.Code -eq 0) { 'PASS' } else { 'FAIL' }) "$ran"
    }

    # ---- C# harness and UDP check ----------------------------------------------------------------------
    $harness = Join-Path $ProjectRoot 'tests\csharp\MotionPlay.ReceiverHarness.csproj'
    if (-not (Get-Command dotnet -ErrorAction SilentlyContinue) -or -not (Test-Path $harness)) {
        Write-Host "== C# checks skipped: the .NET SDK is not installed." -ForegroundColor Yellow
        Add-Result 'C# tests' 'SKIPPED' 'dotnet not found'
        Add-Result 'Python-to-C# UDP check' 'SKIPPED' 'dotnet not found'
    } else {
        Write-Host "== C# tests" -ForegroundColor Cyan
        $csharp = Invoke-Native 'dotnet' @('run', '--project', $harness, '--', '--noresult')
        $count = ($csharp.Lines | Where-Object { $_ -match 'Test Count:' } | Select-Object -First 1)
        Write-Host ("  " + "$count".Trim())
        Add-Result 'C# tests' $(if ($csharp.Code -eq 0) { 'PASS' } else { 'FAIL' }) "$count".Trim()

        Write-Host "== Python-to-C# UDP check" -ForegroundColor Cyan
        $udp = Invoke-Native $VenvPython @('-m', 'tests.check_python_unity_udp')
        $udp.Lines | Select-Object -Last 3 | Out-Host
        Add-Result 'Python-to-C# UDP check' $(if ($udp.Code -eq 0) { 'PASS' } else { 'FAIL' }) ''
    }
} finally { Pop-Location }

Write-Host ""
Write-Host "== Summary" -ForegroundColor Cyan
foreach ($row in $results) {
    $color = switch ($row.Status) { 'PASS' { 'Green' } 'FAIL' { 'Red' } default { 'Yellow' } }
    Write-Host ("{0,-8} {1,-26} {2}" -f $row.Status, $row.Check, $row.Detail) -ForegroundColor $color
}
Write-Host ""
Write-Host "Not covered by these checks: the Unity Editor, the live webcam, and a real MongoDB server (see the checklists in docs\)."
if (@($results | Where-Object { $_.Status -eq 'FAIL' }).Count -gt 0) { exit 1 }
exit 0
