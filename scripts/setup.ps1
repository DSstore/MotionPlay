<#
.SYNOPSIS
  Sets up MotionPlay's Python environment on Windows. Safe to run again.

.DESCRIPTION
  1. Finds 64-bit Python 3.11 through the py launcher.
  2. Creates .venv (or keeps a working one) and installs requirements.txt.
  3. Creates .env from .env.example if you do not have one (an existing .env is never changed).
  4. Runs the health check.

  -CheckOnly reports what is ready and what is not, and changes nothing.

.PARAMETER CheckOnly
  Report the state of the setup without creating or installing anything. Exit code 1 if anything is missing.
.PARAMETER Recreate
  Delete and rebuild .venv. Use this if the environment is broken.
.PARAMETER RunTests
  Also run the Python test suite after setup (about a minute).
.PARAMETER CertFile
  Certificate bundle for pip, for networks or antivirus that inspect SSL (sets PIP_CERT for this run only).
.PARAMETER ProjectRoot
  The MotionPlay folder. Defaults to the folder above this script.
#>
[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [switch]$Recreate,
    [switch]$RunTests,
    [string]$CertFile,
    [string]$ProjectRoot
)

$ErrorActionPreference = 'Stop'
if (-not $ProjectRoot) { $ProjectRoot = Split-Path -Parent $PSScriptRoot }
$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$VenvDir = Join-Path $ProjectRoot '.venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
$script:Problems = 0

function Write-Pass([string]$Text) { Write-Host "PASS  $Text" -ForegroundColor Green }
function Write-Fail([string]$Text) { Write-Host "FAIL  $Text" -ForegroundColor Red; $script:Problems++ }
function Write-Note([string]$Text) { Write-Host "      $Text" -ForegroundColor DarkGray }
function Write-Step([string]$Text) { Write-Host ""; Write-Host "== $Text" -ForegroundColor Cyan }

# Run a native command and return its output lines; the exit code is left in $LASTEXITCODE.
function Invoke-Quiet {
    param([string]$File, [string[]]$Arguments)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { return @(& $File @Arguments 2>$null) } finally { $ErrorActionPreference = $previous }
}

function Get-PythonInfo {
    # Returns "3.11.9 64" for the py launcher's Python 3.11, or $null when it is not installed.
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) { return $null }
    $output = Invoke-Quiet 'py' @('-3.11', '-c', "import struct, sys; print(sys.version.split()[0], struct.calcsize('P') * 8)")
    if ($LASTEXITCODE -ne 0 -or -not $output) { return $null }
    return ($output | Select-Object -First 1).ToString().Trim()
}

function Get-VenvVersion {
    if (-not (Test-Path $VenvPython)) { return $null }
    $output = Invoke-Quiet $VenvPython @('-c', "import sys; print('%d.%d' % sys.version_info[:2])")
    if ($LASTEXITCODE -ne 0 -or -not $output) { return $null }
    return ($output | Select-Object -First 1).ToString().Trim()
}

Write-Host "MotionPlay setup  ($ProjectRoot)" -ForegroundColor White
if ($CheckOnly) { Write-Host "Check only: nothing will be changed." -ForegroundColor Yellow }

# ---- 1. Python 3.11 -------------------------------------------------------------------------------
Write-Step "Python 3.11 (64-bit)"
$python = Get-PythonInfo
if (-not $python) {
    Write-Fail "Python 3.11 was not found through the py launcher."
    Write-Note "Install 64-bit Python 3.11 from python.org with the py launcher option, or run:  py install 3.11"
} elseif ($python -notmatch ' 64$') {
    Write-Fail "Python $python is 32-bit. MotionPlay needs 64-bit Python 3.11."
} else {
    Write-Pass "Python $($python -replace ' 64$', '') (64-bit)"
}

# ---- 2. Virtual environment and packages ------------------------------------------------------------
Write-Step "Virtual environment (.venv)"
$venvVersion = Get-VenvVersion
if ($venvVersion -eq '3.11' -and -not $Recreate) {
    Write-Pass ".venv exists and uses Python 3.11"
} elseif ($CheckOnly) {
    if ($venvVersion) { Write-Fail ".venv uses Python $venvVersion, not 3.11. Run setup.ps1 -Recreate." }
    else { Write-Fail ".venv does not exist. Run setup.ps1." }
} elseif ($script:Problems -gt 0) {
    Write-Note "Skipped: fix the Python problem above first."
} else {
    if (Test-Path $VenvDir) {
        Write-Host "Removing the old .venv ..."
        Remove-Item -Recurse -Force $VenvDir
    }
    Write-Host "Creating .venv with Python 3.11 ..."
    & py -3.11 -m venv $VenvDir
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPython)) { Write-Fail "Could not create .venv."; }
    else { Write-Pass ".venv created" }
}

if (-not $CheckOnly -and $script:Problems -eq 0) {
    Write-Step "Python packages"
    if ($CertFile) {
        if (-not (Test-Path $CertFile)) { Write-Fail "CertFile not found: $CertFile" }
        else { $env:PIP_CERT = (Resolve-Path $CertFile).Path; Write-Note "pip will use the certificate file you gave." }
    }
    if ($script:Problems -eq 0) {
        $requirements = Join-Path $ProjectRoot 'requirements.txt'
        $log = Join-Path ([System.IO.Path]::GetTempPath()) 'motionplay-pip.log'
        Write-Host "Installing requirements.txt (the first time this downloads several hundred MB) ..."
        $previous = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        & $VenvPython -m pip install --upgrade pip 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath $log | Out-Host
        & $VenvPython -m pip install -r $requirements 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath $log -Append | Out-Host
        $pipExit = $LASTEXITCODE
        $ErrorActionPreference = $previous
        if ($pipExit -eq 0) {
            Write-Pass "Packages installed"
        } else {
            Write-Fail "pip could not install the packages."
            if ((Get-Content $log -Raw) -match 'CERTIFICATE_VERIFY_FAILED|SSLError') {
                Write-Note "This looks like SSL inspection by antivirus or a proxy. Re-run with your certificate file:"
                Write-Note "  setup.ps1 -CertFile 'C:\path\to\certificate.pem'"
            } else {
                Write-Note "The full pip output is in $log"
            }
        }
    }
}

# ---- 3. Configuration file --------------------------------------------------------------------------
Write-Step "Configuration (.env)"
$envFile = Join-Path $ProjectRoot '.env'
$envExample = Join-Path $ProjectRoot '.env.example'
if (Test-Path $envFile) {
    Write-Pass ".env exists (left unchanged)"
} elseif ($CheckOnly) {
    Write-Fail ".env does not exist. Run setup.ps1 to create it from .env.example."
} elseif (Test-Path $envExample) {
    Copy-Item $envExample $envFile
    Write-Pass ".env created from .env.example"
} else {
    Write-Fail ".env.example is missing, so .env could not be created."
}

# ---- 4. Health check --------------------------------------------------------------------------------
Write-Step "Health check"
if (-not (Test-Path $VenvPython) -or (Get-VenvVersion) -ne '3.11') {
    Write-Note "Skipped: there is no working .venv yet."
} else {
    Push-Location $ProjectRoot
    try {
        $previous = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        & $VenvPython -m app.health_check 2>&1 | ForEach-Object { "$_" } | Out-Host
        $healthExit = $LASTEXITCODE
        $ErrorActionPreference = $previous
    } finally { Pop-Location }
    if ($healthExit -eq 0) { Write-Pass "Health check passed" } else { Write-Fail "Health check failed (see above)." }
}

if ($RunTests -and -not $CheckOnly -and $script:Problems -eq 0) {
    Write-Step "Tests"
    Push-Location $ProjectRoot
    try {
        $previous = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        & $VenvPython -m unittest discover -s tests 2>&1 | ForEach-Object { "$_" } | Select-Object -Last 4 | Out-Host
        $testExit = $LASTEXITCODE
        $ErrorActionPreference = $previous
    } finally { Pop-Location }
    if ($testExit -eq 0) { Write-Pass "Tests passed" } else { Write-Fail "Some tests failed." }
}

Write-Host ""
if ($script:Problems -gt 0) {
    Write-Host "Setup is NOT complete: $($script:Problems) problem(s) above." -ForegroundColor Red
    exit 1
}
if ($CheckOnly) {
    Write-Host "Everything is ready." -ForegroundColor Green
} else {
    Write-Host "Setup complete." -ForegroundColor Green
    Write-Host "Next:"
    Write-Host "  1. Create a player:   .\.venv\Scripts\python.exe -m backend.users create <name>"
    Write-Host "  2. Open unity\MotionPlay in Unity 2022.3.62f3 (first time: MotionPlay > Create Reach Garden Scene)."
    Write-Host "  3. Start everything:  .\scripts\start.ps1 -User <name>   (or double-click MotionPlay-Start.cmd)"
}
exit 0
