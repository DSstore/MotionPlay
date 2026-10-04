# Phase 5: Python UDP sender

## What changed

The existing capture → tracking → palm/gesture pipeline now feeds a separate
`UdpSender`. `shared/protocol.py` owns the validated wire model and JSON encoding;
`cv_engine/udp_sender.py` adapts filtered output and owns one nonblocking socket.
The controller only coordinates these components. No Unity project, gameplay,
result receiver, database, or new dependency is added.

Each packet contains the configured physical hand's smoothed palm position,
confirmed gesture, handedness confidence, mirror flag, and ordering metadata.
No camera image or 21-point landmark array is transmitted. `CONTROL_HAND=right`
is the default; set `left` if needed. The sender never switches hands automatically.
It sends a lost state while the selected hand is absent, including before first
detection. Invalid gesture geometry can leave palm control active with UNKNOWN.

The default target cadence is 30 Hz, limited by real frame-processing speed.
Pacing skips frames and expired slots; it does not sleep or queue stale states.
Startup failures are actionable errors; runtime socket errors log at most once
per five seconds while capture continues, with a recovery message if OS sends
resume. Totals track OS-accepted sends, failed attempts, and skipped frames.
They do not count packets actually received. A final lost packet is attempted
on clean exit or processing failure, and socket closure is idempotent.

## Windows 11 acceptance check

From the project directory, update source/dependencies as needed:

```powershell
git pull
.\.venv\Scripts\python.exe -m app.health_check
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

If `.env` already exists, add the new keys manually; do not overwrite your local
settings with the example. Ensure:

```dotenv
UDP_HOST=127.0.0.1
CV_TO_UNITY_PORT=5005
UNITY_TO_PYTHON_PORT=5006
UDP_SEND_FPS=30
CONTROL_HAND=right
```

Open **two PowerShell terminals** in the project directory. In the first, start
the local diagnostic listener:

```powershell
.\.venv\Scripts\python.exe -m app.udp_monitor --timeout 120
```

In the second, start the webcam pipeline:

```powershell
.\.venv\Scripts\python.exe -m cv_engine.controller
```

1. With no hand visible, verify packets show `tracking=false`, null position,
   UNKNOWN, and zero confidence. Sequence should increase.
2. Show your selected hand. Verify `tracking=true` and bounded X/Y. Move it and
   compare the packet coordinates with the preview's magenta filtered marker.
3. Hold OPEN_HAND/FIST/PINCH/POINT. Confirm the packet gesture agrees with the
   preview's **confirmed** label, after the configured consecutive-frame delay.
4. Hide the selected hand. The next due fresh packet should clear the position
   and gesture; it must not keep transmitting the last position.
5. Show only the other hand. Packets should remain untracked. To use that hand,
   change `CONTROL_HAND` and restart. Set `TRACKING_MAX_HANDS=2` to test both
   simultaneously; the preview may show both but only one is sent.
6. Press Q/Escape in the preview. Watch for the best-effort final lost packet.
   Stop the monitor with Ctrl+C. Restarting the engine should produce a new
   `stream_id` with sequence zero.

The monitor prints numerical states but does not record them to a file. Do not
run it on port 5005 concurrently with a future Unity receiver; one process owns
the receive port. It always listens on 127.0.0.1, so it will not monitor a remote
`UDP_HOST`. `--max-packets 10` can stop after ten valid messages. Idle timeout
returns exit code 1 with setup advice.

To retain the earlier local-only preview:

```powershell
.\.venv\Scripts\python.exe -m cv_engine.controller --no-udp
```

For a webcam without a desktop preview, `--no-preview --max-frames 300` works as
before and now sends UDP unless `--no-udp` is also specified.

## Troubleshooting and validation limits

- No packets: start the monitor first, check the engine is processing frames,
  confirm matching ports and loopback address, and check firewall rules. UDP
  sends may succeed even with no receiver. No automatic receiver check exists.
- Port already in use: close the other listener or choose a new CV port in both
  processes. The result port must remain different.
- Packets are always untracked: check `CONTROL_HAND`, preview handedness, camera
  visibility, and the handedness confidence threshold.
- Slow sends: compare loop FPS/model processing time in logs; the sender cannot
  exceed fresh camera/model output. Console printing can itself slow monitoring.
- Invalid configuration: errors identify the setting before camera access.
  Use numeric IPv4 `127.0.0.1`, not `localhost`, for this implementation.

Cloud checks cover 104 automated tests, including 23 new Phase 5 tests. They
exercise strict serialization/validation, selected-hand mapping, 30 Hz cadence,
near-30-FPS scheduling, send errors, loss/terminal states, a controller with fake
camera/model and real UDP sockets, and the diagnostic CLI. Real MediaPipe blank
frames and real local UDP delivery are also smoke-tested. No live webcam,
Windows socket behavior, Unity receive/update latency, or real 30 FPS webcam
performance has been verified here. Follow this checklist locally before claiming
hardware validation. See the [wire contract](udp_protocol.md) for receiver
ordering, mirroring, timeout, and future-message responsibilities.
