# Phase 1 setup

## Windows 11

Install 64-bit Python 3.11 from python.org with the Python launcher enabled. Check it in PowerShell:

```powershell
py -3.11 --version
```

Open PowerShell in the MotionPlay project directory:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m app.health_check
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Copy the example only when creating your configuration; preserve an existing `.env`.
Optional activation: `.\.venv\Scripts\Activate.ps1`. Explicit Python paths above work without activation or changing execution policy.

## Linux or cloud

With Python 3.11 installed, run from the project root:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
.venv/bin/python -m app.health_check
.venv/bin/python -m unittest discover -s tests -v
```

Optional developer alternative with `uv`:

```bash
uv python install 3.11
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

`uv` is a setup convenience, not an application dependency. The managed cloud uses Linux; its virtual environment cannot be copied to Windows. Recreate `.venv` on your own machine.

## Troubleshooting

| Failure | Action |
| --- | --- |
| Python check reports 3.12 or another version | Create `.venv` with Python 3.11 and invoke its interpreter explicitly. |
| Import reports `ModuleNotFoundError` | Install requirements using the same interpreter used for the health check. |
| Native import fails on Windows | Confirm 64-bit Python and install the current Microsoft Visual C++ x64 Redistributable if a DLL is missing. |
| OpenCV/PyQt6 import reports `libGL.so.1` on Linux | Install the distribution's OpenGL runtime; Debian/Ubuntu commonly provide it as `libgl1`. |
| A Qt window later fails in a cloud environment | Desktop interaction requires a display and Qt platform libraries. Phase 1 checks imports only and launches no GUI. |
| Configuration check fails | Check the named setting in `.env` and environment overrides; ports must differ and be integers from 1024 to 65535. |
| Logging fails | Ensure `LOG_DIR` is writable. Relative paths are resolved from the project root. |
| PyMongo imports successfully | This verifies the driver only. MongoDB availability/authentication will be tested in the database phase. |

No camera, Unity, MongoDB server, or credentials are required for Phase 1. Successful imports do not establish that tracking or desktop gameplay works.

## Verified Phase 1 baseline

The managed Linux workspace was verified with Python 3.11.16:

- All eight dependency imports and configuration/logging passed the health check.
- All nine foundation tests passed.
- The dependency checker found no conflicts across the 33 installed packages.
- An invalid UDP port produced a helpful configuration error and exit code `1`.
- The pinned direct dependencies resolved to binary wheels for Windows x64/Python 3.11. This verifies package availability, not execution on Windows.

The Windows instructions still require testing on the user's machine. No webcam capture, MediaPipe tracking session, GUI window, MongoDB connection, or Unity gameplay was tested in Phase 1.
