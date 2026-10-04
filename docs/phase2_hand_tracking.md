# Phase 2: webcam and MediaPipe Hands

This guide records its original development phase. On current Phase 5 source,
the controller also sends numerical UDP states by default. Add `--no-udp` to
the commands below for local-only checks, or follow the [Phase 5 guide](phase5_udp_sender.md).

## Scope and ownership

Phase 2 implements local capture and hand detection. It does not implement palm-center mapping, coordinate clamping, smoothing, gesture detection, calibration, UDP, or Unity. These follow in their planned phases.

| Module | Responsibility |
| --- | --- |
| `cv_engine/camera.py` | Open/read/release the webcam; request dimensions and FPS. |
| `cv_engine/hand_tracker.py` | Convert BGR to RGB, run MediaPipe Hands, and detach native results into application data. |
| `cv_engine/models.py` | Define immutable hand observations, anatomical indices, and per-frame timing. |
| `cv_engine/preview.py` | Draw landmarks and labels; own an optional local preview window. |
| `cv_engine/controller.py` | Coordinate these components, log transitions, and handle user exit/errors. |
| `shared/config.py` | Validate configuration before opening hardware. |

Context managers release camera, model, and window resources on normal exit, exceptions, or Ctrl+C. If model initialization fails after the camera opens, the camera is still released. An unavailable camera or lost camera stream ends with exit code `1` and a useful message. An invalid CLI argument uses argparse's exit code `2`.

## Tracking data and mirroring

Each `TrackedHand` contains all 21 raw landmarks, a physical `left`/`right` hand label, and `handedness_confidence`. Wrist, every fingertip, and MCP joints have explicit enum names. No native MediaPipe result escapes the tracker boundary.

MediaPipe's x coordinate increases toward the right of the processed image, and y increases downward. x/y are native image-relative values, usually between zero and one; off-image predictions are preserved in this phase. z is wrist-relative model depth, not physical distance in meters. Phase 3 will add a stable palm center, normalized control coordinates, and smoothing.

By default the controller mirrors the image **before both inference and preview**, so movement feels like a mirror. MediaPipe's handedness labels assume this selfie orientation. With `CAMERA_MIRROR=false`, the tracker swaps MediaPipe's left/right labels so observations still describe the physical hand. No second mirror is applied in the preview.

`handedness_confidence` measures confidence in the left/right label. It does not measure landmark accuracy. MediaPipe's configurable detection and tracking thresholds are separate. This phase reports tracking immediately per frame; debouncing and timeout behavior belong to later phases.

## Windows 11 run instructions

From the project root, after following [setup.md](setup.md):

```powershell
.\.venv\Scripts\python.exe -m app.health_check
.\.venv\Scripts\python.exe -m cv_engine.controller
```

The local preview should open. Show one hand with your palm visible in good lighting. Green landmarks identify the right hand; blue/orange landmarks identify the left hand. Wrist, fingertips, and MCP joints use larger markers. Press **Q**, **Escape**, or the window's close button to exit. Ctrl+C in the terminal also stops the process.

For a bounded run without a window:

```powershell
.\.venv\Scripts\python.exe -m cv_engine.controller --no-preview --max-frames 300
```

This still uses the webcam. Run `.venv/bin/python -m cv_engine.controller` on Linux with an attached camera and a working desktop display. A cloud without a webcam cannot exercise live tracking; `--no-preview` does not change that.

## Configuration

Add these settings to your existing `.env`, or use the updated `.env.example` for a new installation. Defaults apply if a key is absent; process environment variables take precedence.

| Setting | Default | Meaning |
| --- | --- | --- |
| `CAMERA_INDEX` | `0` | Local camera index, 0–32. Try 1 for a second camera. |
| `CAMERA_WIDTH` | `640` | Requested width, 160–7680 pixels. |
| `CAMERA_HEIGHT` | `480` | Requested height, 120–4320 pixels. |
| `CAMERA_FPS` | `30` | Requested capture FPS, 1–120. |
| `CAMERA_MIRROR` | `true` | Mirror capture before inference and preview. |
| `TRACKING_MAX_HANDS` | `1` | Detect up to 1 or 2 hands. |
| `TRACKING_MODEL_COMPLEXITY` | `1` | Bundled model: 0 lighter, 1 full. |
| `TRACKING_DETECTION_CONFIDENCE` | `0.6` | MediaPipe palm detection threshold, 0–1. |
| `TRACKING_MIN_CONFIDENCE` | `0.6` | MediaPipe landmark tracking threshold, 0–1. |

Camera properties are requests, not guarantees. Startup logs show the device-reported settings. The preview's **Loop FPS** measures average throughput of the capture/tracking loop; it is not the camera's advertised FPS. **MediaPipe ms** measures model processing for the latest frame, excluding capture, color conversion, drawing, and display. Requesting 30 FPS does not establish that the pipeline achieves it. UDP and Unity latency cannot yet be measured.

## Local acceptance checklist

1. Start the preview and confirm a usable camera image appears.
2. Show each physical hand separately; check that all landmarks and the physical label appear correctly.
3. Move your hand left/right/up/down; check that landmarks follow it and that mirroring feels natural.
4. Hide your hand, then show it again; inspect the log for a loss/restoration transition. No-hand frames should continue normally.
5. Repeat with `CAMERA_MIRROR=false`; physical left/right labels should remain correct while the image orientation changes.
6. Exit with Q, Escape, and the close button on separate runs. Restart after each to check that the camera was released.
7. Run for about a minute and note loop FPS and MediaPipe time. Try model complexity 0 if processing is slow.

Use these observations to verify live detection before progressing to Phase 3. Avoid committing camera images or video from your checks.

## Troubleshooting and verification limits

- **Cannot open webcam:** check the index, cable, Windows Settings → Privacy & security → Camera, and enable camera access for desktop apps. Close Teams, browsers, or other apps using the camera. OpenCV cannot reliably distinguish these causes, so the message lists the likely actions.
- **No image after capture starts:** reconnect the camera and restart. Frame-acquisition failure releases resources and ends cleanly.
- **No hand detected:** improve lighting, show the whole hand, move away from the lens, and check the preview orientation. An empty detection is a normal result.
- **No desktop display:** run on your Windows desktop or use headless mode with an attached camera. The controller guards against opening a native window on Linux without a display.
- **MediaPipe initialization fails:** run the health check with the same interpreter and verify the pinned requirements. Set `LOG_LEVEL=DEBUG` to include chained native error details in the local log.
- MediaPipe may print native XNNPACK initialization and feedback-tensor warnings to stderr. They occurred during successful smoke checks; Python logging does not control those native messages.

Cloud verification passed 33 automated tests, the existing import health check, real initialization of both hand models, and five synthetic blank frames per model with no hand detections. Missing-camera, missing-display, and invalid-frame-limit checks produced the expected error messages and exit codes. Synthetic blanks check model execution and empty results; they do not validate detection on real hands, handedness on a real camera, GUI interaction, or live performance. Those local checks remain pending.
