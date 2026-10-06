# Phase 18: Installer and startup scripts

## What changed

Setting MotionPlay up and starting it used to mean typing about a dozen commands from three documents. Now there are
three scripts, each with a double-click launcher in the project folder:

| Launcher | Script | What it does |
|---|---|---|
| `MotionPlay-Setup.cmd` | `scripts\setup.ps1` | Creates the Python environment, installs the packages, creates `.env`, runs the health check. Safe to run again. |
| `MotionPlay-Start.cmd` | `scripts\start.ps1` | Opens the result receiver and the CV engine, each in its own window. |
| `MotionPlay-Test.cmd` | `scripts\test.ps1` | Runs every automated check and prints a summary. |

The launchers run PowerShell with `-ExecutionPolicy Bypass` for that one command, so they work even where scripts are
normally blocked, and they pass any options on. To run a script directly from PowerShell instead:
`.\scripts\setup.ps1`. If PowerShell refuses with an execution-policy message, use the `.cmd` launcher, or run
`powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1`.

## First-time setup

1. Install **64-bit Python 3.11** from python.org with the *py launcher* option (or run `py install 3.11`).
2. Double-click `MotionPlay-Setup.cmd`.
3. Create a player (asks for a password twice): `.\.venv\Scripts\python.exe -m backend.users create <name>`
4. Open `unity\MotionPlay` in **Unity 2022.3.62f3**. The first time, click **MotionPlay > Create Reach Garden Scene**.

The first setup took about **4 minutes** on the test machine, almost all of it pip working out which compatible versions of
MediaPipe's dependencies to use. A second run takes about 20 seconds.

### Setup options

| Option | Meaning |
|---|---|
| `-CheckOnly` | Report what is ready and what is missing, and change nothing. Exit code 1 if anything is missing. |
| `-Recreate` | Delete and rebuild `.venv` (when the environment is broken). |
| `-RunTests` | Also run the Python tests afterwards. |
| `-CertFile <path>` | Certificate bundle for pip, for antivirus or a proxy that inspects SSL (sets `PIP_CERT` for this run only). If pip fails with `CERTIFICATE_VERIFY_FAILED`, setup says so and tells you to use this. |

Setup never overwrites an existing `.env`. If `.env.example` gains new settings later, they use their defaults until you add them.

## Starting MotionPlay

Double-click `MotionPlay-Start.cmd` (it asks which player), or from PowerShell:

```powershell
.\scripts\start.ps1 -User steve
```

Two windows open: **MotionPlay receiver** (type the player's password there) and **MotionPlay CV engine**. Then press Play in
Unity and show your hand. To stop, press **Q** or **Esc** in the CV engine window and **Ctrl+C** in the receiver window.

| Option | Meaning |
|---|---|
| `-User <name>` | Save rounds for this player (3 to 32 letters, digits, dots, dashes or underscores; anything else is refused before anything starts). |
| `-NoPlayer` | Save rounds without a player. |
| `-Preview` | Show the camera preview window. It is off by default because it costs roughly a third of the frame rate. |
| `-Dashboard` | Also open the dashboard. |
| `-DryRun` | Print what would be started and start nothing. |

## Running the checks

`MotionPlay-Test.cmd` (or `.\scripts\test.ps1`) runs the Python tests, the C# harness and the Python-to-C# UDP check, then prints
a PASS/FAIL summary. `-Coverage` also measures Python coverage (after `pip install -r requirements-dev.txt`). The C# checks are
skipped, and the summary says so, if the .NET SDK is not installed.

## What was verified, and how

- A **from-scratch install** into an empty folder: venv created, every package installed, `.env` created, health check passed, and
  the whole Python test suite then passed inside that new environment.
- A second setup run changed nothing (an edited `.env` was untouched). A bad `-CertFile` failed clearly with exit code 1.
- A real **launch**: both windows opened from a folder whose name contains a space, and both programs started (camera opened via
  DirectShow in under 3 s, receiver listening).
- `MotionPlay-Test.cmd -Coverage` run the way a double-click would: every Python test (336 tests at that point), the 118 C# tests and the UDP check all passed, with 96% Python coverage.
- `tests\test_scripts.py` (13 tests, Windows only, about 30 seconds) keeps the scripts working: every script parses, the files are
  plain ASCII, unsafe player names are refused, `-CheckOnly` changes nothing, `-DryRun` starts nothing, and the launchers pass their
  options on. It already caught a launcher with a stray tab character in its path.

## What this is not

- **Not a packaged installer.** There is no MSI or single `.exe`. MotionPlay needs the Unity Editor (or a Unity build, which is not
  part of this project yet), and the Python side bundles hundreds of MB of MediaPipe and OpenCV. Scripts over a documented manual setup
  are the honest scope for a portfolio project; a PyInstaller or Inno Setup package would be a later step.
- **Windows only.** The scripts are Windows PowerShell 5.1. On Linux or macOS follow `docs\setup.md`.
- **Unity is still manual.** Installing Unity, opening the project, and pressing Play are not automated.
- **No start-with-Windows.** MotionPlay uses the webcam, so it is deliberately started by hand.
