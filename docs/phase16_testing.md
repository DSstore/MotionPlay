# Phase 16: Broader automated testing

## What changed

Phase 16 measured where the tests were thin, then filled the biggest gaps. Python line-and-branch
coverage went from **89% to 96%**, and the suite from 240 to **285** tests (all hardware-free).

| Module | Before | After | What was added |
|---|---|---|---|
| `app/health_check.py` | 0% | 96% | Pass path, wrong Python, a dependency that fails to import, config error, version fallback |
| `backend/result_receiver.py` | 62% | 94% | The `main()` command line against a real loopback port: save with and without a player, idle timeout, bad port, failed login, port in use, storage failure, Ctrl+C, store always closed |
| `cv_engine/controller.py` | 79% | 92% | `main()` exit codes for every failure kind, option pass-through, bad `--max-frames` |
| `cv_engine/preview.py` | 66% | 97% | Overlay text for every state, Q/Esc/close handling, window errors, safe close |
| `app/dashboard.py` | 83% | 99% | Save-report dialog (chosen, cancelled, empty, storage failure), account-creation storage error, refresh timer, log-in/log-out loop, `main()` |

New files: `tests/test_entry_points.py`, `tests/test_ui_entry_points.py`. Tests that use
Qt run offscreen, OpenCV window calls are replaced, and nothing writes to your real `logs/` or `data/`.

To check the new tests really detect faults, five deliberate breaks were made in the source and each was caught
(a quit key removed, a cancelled dialog treated as a choice, a login error message dropped, the UDP flag inverted,
failed health checks not counted). The breaks were reverted.

## Run the tests and measure coverage

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
dotnet run --project tests/csharp/MotionPlay.ReceiverHarness.csproj -- --noresult
```

Coverage needs a dev tool. If pip fails with `CERTIFICATE_VERIFY_FAILED` (antivirus SSL inspection), set `PIP_CERT` to your antivirus's certificate file first:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m coverage run --branch --source=app,backend,cv_engine,shared -m unittest discover -s tests
.\.venv\Scripts\python.exe -m coverage report --skip-empty -m
```

## What is still not covered

- **Under 90%:** `app/udp_monitor.py` (83%), `backend/users.py` (87%): small command-line and error branches.
  `backend/auth.py`, `cv_engine/camera.py` and a few storage lines are 90 to 94%: mostly defensive handlers for
  database and device errors that are hard to trigger on purpose.
- **Not automated at all:** the Unity controller scenes and HUD (they need the Unity Editor), the live webcam, a real MongoDB
  server, and real-display rendering. These stay on the manual checklists in each phase document.
- **No continuous integration yet.** Tests run locally. A GitHub Actions workflow is a sensible next step.

## Documentation checks (added in Phase 19)

`tests/test_docs.py` (7 tests) keeps the documents honest: every relative link and heading anchor in the README and `docs/` must resolve, every Mermaid block must be
a recognisable diagram, every phase guide must be linked from the README, and `docs/configuration.md` must list exactly the settings in `.env.example` with the defaults the
code actually uses (and document every key the loader reads). Mermaid syntax itself is validated with the Mermaid parser when a diagram changes, not in the test run.
