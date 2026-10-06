# Phase 17: Expanded logging and error handling

## What changed

Before this phase only the CV engine and the health check wrote to the rotating log file. The result
receiver (which stores your rounds), the dashboard, the report command and the account tools did not, and an
unexpected error could end a program with nothing recorded. Now every command that does real work logs to
`logs/motionplay.log` (2 MiB per file, three backups), and unexpected errors are recorded with their traceback.

| Area | Change |
|---|---|
| Start-up | `shared.logger.start_logging(settings, component)` sets up logging, records uncaught errors, and writes one start-up line: component, process id, Python version, log level, log file. It never includes credentials or the MongoDB connection string. |
| Uncaught errors | Errors that escape the main thread or a worker thread are logged at CRITICAL with a traceback; the normal console message still appears. Ctrl+C and normal exits are not logged as crashes. |
| Result receiver | Now logs to the file too. Each result line says what it was: `stored (reach_garden, level_4, 7 of 8 watered)`. A rejected datagram logs its size and the reason, never its content, and at most 5 per minute (the rest are counted and summarised) so a noisy sender cannot flood the log. An unexpected error while storing is logged with its traceback and answered with an `error` acknowledgement, so the receiver keeps running and Unity retries. |
| Accounts | Account created, login, wrong password (with attempt number), lockout, refused login while locked, and password change. Passwords are never logged. A login for a name that does not exist logs only "no such account": the typed name is left out because it may be a password typed into the wrong box. |
| CV engine | Logs how long the webcam took to open (a warning above 5 s, which also says Ctrl+C is not handled until it finishes) and how long MediaPipe took to start. A settings line records the camera, model, control hand and continuity values. The run ends with a summary: frames, seconds, average FPS, times the hand was lost, label corrections. |
| Dashboard | Logs report exports (saved or not) and failed refreshes. An unexpected error shows a message box with the log path instead of Qt silently aborting the program. |
| Report and accounts commands | Log to the file only, so their normal output stays clean. |
| Console | `configure_logging(settings, console=False)` keeps log lines out of the terminal. The engine and receiver (long-running) still print them. |
| Library use | `motionplay` loggers have a null handler, so importing a module without configuring logging stays silent. |

## Reading the log

```powershell
Get-Content logs\motionplay.log -Tail 40
Select-String -Path logs\motionplay.log -Pattern "WARNING|ERROR|CRITICAL"
```

Useful lines:

- `MotionPlay CV engine starting (...)`: the start of each run.
- `Opening the webcam took 29.0 s`: a slow camera start, usually from another app or the driver.
- `Tracking finished after N frame(s) in S s (average F FPS); hand lost L time(s); C label correction(s)`.
- `Result <id> stored (...)`: confirms Unity's rounds arrived, and at which level.
- `Uncaught ...`: a bug. Include the lines around it in a report.

Set `LOG_LEVEL=DEBUG` in `.env` for more detail (for example each label correction).

## Tests

`tests/test_logging_errors.py` has 24 tests: log setup, the start-up line (including that credentials never appear), uncaught
errors in both threads, no duplicate records when installed twice, every account event and that passwords and unknown
names stay out, the receiver's outcomes and flood limit and surviving store errors, the engine's settings and summary lines,
the slow-camera warning, and the dashboard's error dialog. Test runs write their logs to a temporary folder, never to `logs/`.

Run it: `.\.venv\Scripts\python.exe -m unittest tests.test_logging_errors`.

## Not changed

- **Camera glitches are still fatal.** One failed frame read ends the engine. Tolerating a few failed reads in a row would help
  with transient USB hiccups, but needs hardware testing, so it is left for later.
- **Unity logs stay in Unity.** The Editor log is where Unity-side messages go; Python only sees what Unity sends.
- **Logs are plain text.** There is no structured (JSON) logging or remote collection.
