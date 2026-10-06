<#
.SYNOPSIS
  Starts the MotionPlay Python side: the result receiver and the CV engine, each in its own window.

.DESCRIPTION
  The receiver saves each finished round for a player (it asks for that player's password in its own window).
  The CV engine reads your webcam and sends hand positions to Unity.
  Then open unity\MotionPlay in Unity and press Play.

  To stop: press Q or Esc in the CV engine window (or Ctrl+C), and Ctrl+C in the receiver window.

.PARAMETER User
  The player the rounds are saved for. Create one first with:  .\.venv\Scripts\python.exe -m backend.users create <name>
.PARAMETER NoPlayer
  Save rounds without a player (they can be claimed later with python -m backend.sessions claim).
.PARAMETER Preview
  Show the camera preview window (it costs about a third of the frame rate). Default: no preview.
.PARAMETER Dashboard
  Also open the dashboard window.
.PARAMETER DryRun
  Print what would be started without starting anything.
.PARAMETER ProjectRoot
  The MotionPlay folder. Defaults to the folder above this script.
#>
[CmdletBinding()]
param(
    [string]$User,
    [switch]$NoPlayer,
    [switch]$Preview,
    [switch]$Dashboard,
    [switch]$DryRun,
    [string]$ProjectRoot
)

$ErrorActionPreference = 'Stop'
if (-not $ProjectRoot) { $ProjectRoot = Split-Path -Parent $PSScriptRoot }
$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

function Stop-WithError([string]$Message) {
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

# ---- checks ---------------------------------------------------------------------------------------
if (-not (Test-Path $VenvPython)) {
    Stop-WithError "The Python environment is not set up yet. Run scripts\setup.ps1 (or MotionPlay-Setup.cmd) first."
}
if (-not (Test-Path (Join-Path $ProjectRoot '.env'))) {
    Stop-WithError "There is no .env file. Run scripts\setup.ps1 to create it."
}

if ($User -and $NoPlayer) { Stop-WithError "Use either -User or -NoPlayer, not both." }
if (-not $User -and -not $NoPlayer) {
    if ([Environment]::UserInteractive -and -not $DryRun) {
        $User = (Read-Host "Player name (leave empty to save rounds without a player)").Trim()
        if (-not $User) { $NoPlayer = $true }
    } else {
        Stop-WithError "Say who is playing: -User <name>, or -NoPlayer."
    }
}
if ($User -and $User -notmatch '^[A-Za-z0-9._-]{3,32}$') {
    Stop-WithError "A player name is 3 to 32 letters, digits, dots, dashes, or underscores."
}

# ---- what to start ------------------------------------------------------------------------------------
$receiverArgs = '-m backend.result_receiver --store sqlite'
if ($User) { $receiverArgs += " --user $User" }
$engineArgs = '-m cv_engine.controller'
if (-not $Preview) { $engineArgs += ' --no-preview' }

$windows = @(
    [pscustomobject]@{ Title = 'MotionPlay receiver'; Arguments = $receiverArgs },
    [pscustomobject]@{ Title = 'MotionPlay CV engine'; Arguments = $engineArgs }
)
if ($Dashboard) {
    $windows += [pscustomobject]@{ Title = 'MotionPlay dashboard'; Arguments = '-m app.dashboard' }
}

function Start-InWindow($Window) {
    # Single quotes inside the command protect the folder name, which may contain spaces.
    $python = $VenvPython.Replace("'", "''")
    $command = "`$Host.UI.RawUI.WindowTitle = '$($Window.Title)'; & '$python' $($Window.Arguments)"
    Start-Process -FilePath 'powershell.exe' -WorkingDirectory $ProjectRoot `
        -ArgumentList @('-NoProfile', '-NoExit', '-Command', ('"' + $command + '"'))
}

Write-Host "MotionPlay  ($ProjectRoot)" -ForegroundColor White
if ($DryRun) { Write-Host "Dry run: nothing is started." -ForegroundColor Yellow }
foreach ($window in $windows) {
    Write-Host ("{0,-22} .venv\Scripts\python.exe {1}" -f $window.Title, $window.Arguments)
    if (-not $DryRun) { Start-InWindow $window }
}

Write-Host ""
Write-Host "Next:"
if ($User) { Write-Host "  - Type the password for '$User' in the receiver window." }
Write-Host "  - Open unity\MotionPlay in Unity, open the ReachGarden scene, and press Play."
Write-Host "  - Show your hand to the camera to start a round. [ and ] change the difficulty level between rounds."
Write-Host "  - To stop: press Q or Esc in the CV engine window, and Ctrl+C in the receiver window."
exit 0
