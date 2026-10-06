# Phase 3: palm coordinates and smoothing

This guide records its original development phase. On current Phase 5 source,
the controller also sends numerical UDP states by default. Add `--no-udp` to
the commands below for local-only checks, or follow the [Phase 5 guide](phase5_udp_sender.md).

## Pipeline and responsibilities

```text
MediaPipe hand observations
    -> handedness-confidence threshold
    -> average wrist and four finger MCP joints
    -> clamp image-relative X/Y to [0, 1]
    -> per-hand EMA with an XY dead zone
    -> fresh control position or an explicit loss state
    -> local preview
```

`coordinates.py` owns palm-center math and normalization. `smoothing.py` provides an independent `PositionSmoother` class. `position_processor.py` owns confidence checks, one filter per physical hand label, and timeout history. The controller passes immutable `ControlResult` data to the preview. MediaPipe's raw landmarks remain untouched and available for the gesture phase.

This phase implements no gestures, UDP, Unity, calibration mapping, or database features. Velocity calculation is optional and deferred.

## Coordinate conventions

The palm center is the arithmetic mean of landmark indices **0, 5, 9, 13, 17**: wrist and index/middle/ring/pinky MCP joints. Fingertip movement does not directly change this estimate. It is an image-space control point, not a medical measurement or a geometric reconstruction of the palm.

MediaPipe already supplies image-relative coordinates. X increases rightward; Y increases downward. Normalize by clamping X/Y to zero through one, without dividing by camera dimensions a second time. Preserve finite wrist-relative Z, which can be negative and is not meters. Mirroring happens once in the capture controller, before inference; the coordinate processor does not mirror again.

Incomplete or nonfinite palm observations are rejected. The raw preview skips malformed landmark arrays instead of attempting to draw them. A raw hand detection can appear while control is unavailable because its handedness confidence was rejected.

## Smoothing behavior

For each accepted hand, start the filter at its first position. Further positions use:

```text
filtered = alpha * input + (1 - alpha) * previous_filtered
```

Left and right hands have separate histories. Reordering MediaPipe observations does not mix their positions. If duplicate observations carry the same label, the highest-confidence observation is considered once.

The dead zone is an XY Euclidean radius around the previous filtered output. Inside that radius, hold the full previous position, including Z. Compare input against the filtered output so gradual physical motion can eventually leave the radius. A zero radius disables this hold behavior, including for depth-only motion. EMA with alpha `1` and dead zone `0` passes coordinates through immediately.

Lower alpha reduces jitter and adds lag. A larger dead zone holds more small movement and can leave a small offset from a stationary input. This is a frame-based EMA: its response depends on achieved FPS. Do not call its output evidence of medical improvement or claim a measured camera frame rate from this algorithm.

## Confidence and loss states

MediaPipe Hands exposes a confidence score for **left/right classification**. `CONTROL_MIN_HANDEDNESS_CONFIDENCE` gates that score; it does not represent landmark positional accuracy. MediaPipe's detection/tracking thresholds remain separate settings from Phase 2.

An accepted observation produces status `tracking` with fresh unfiltered and smoothed palm positions. Missing, invalid, or low-confidence observations expose `position=None` immediately. History handling is:

| State | Position exposed | Filter history |
| --- | --- | --- |
| `tracking` | Fresh bounded position | Updated by accepted input |
| `temporarily_lost` | None | Retained until timeout |
| `lost` | None | Cleared at timeout |
| Never observed/accepted | No hand entry | No history |

Time is measured using the monotonic processing clock, not wall-clock timestamps. Only accepted observations refresh `last_seen`. At a gap **greater than or equal to** the timeout, clear history. This also applies to a long processing pause where the next frame already contains a hand. A short interruption resumes the old filter; reacquisition after timeout seeds a new position without blending from the old location.

The preview hides control markers immediately on loss. Logs record transitions and timeout resets without storing landmarks. A timeout reset is logged once per expiration. Reset behavior is tied to processed frames; this synchronous CV pipeline cannot update its status while blocked inside a camera read. Camera-read failures still end with the existing cleanup/error handling.

## Configuration and Windows tuning

Add these keys to an existing `.env`; defaults apply when absent:

```dotenv
SMOOTHING_ALPHA=0.35
SMOOTHING_DEAD_ZONE=0.008
CONTROL_MIN_HANDEDNESS_CONFIDENCE=0.75
CONTROL_TRACKING_TIMEOUT=0.5
CONTROL_CONTINUITY_SECONDS=0.3
CONTROL_CONTINUITY_RADIUS=0.25
```

| Setting | Valid range | Meaning |
| --- | --- | --- |
| `SMOOTHING_ALPHA` | Greater than 0, at most 1 | EMA response per accepted frame |
| `SMOOTHING_DEAD_ZONE` | 0 through 1 | Normalized XY hold radius; 0 disables it |
| `CONTROL_MIN_HANDEDNESS_CONFIDENCE` | 0 through 1 | Minimum left/right classification confidence |
| `CONTROL_TRACKING_TIMEOUT` | Finite positive seconds | Maximum gap before clearing filter history |
| `CONTROL_CONTINUITY_SECONDS` | 0 through 1 | A hand detected where a tracked hand was this recently keeps that hand's label; 0 turns label continuity off |
| `CONTROL_CONTINUITY_RADIUS` | Greater than 0, at most 1 | Largest palm movement between frames (normalized image distance) still treated as the same hand |

From the MotionPlay folder on Windows:

```powershell
.\.venv\Scripts\python.exe -m cv_engine.controller
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The **white circle** shows the bounded, unfiltered palm center. The **magenta cross** shows the filtered position. Skeleton landmarks keep their existing left/right colors.

1. Hold your palm still and compare movement of the circle and cross.
2. Move slowly left/right/up/down and check that the cross follows, with X/Y within zero through one.
3. Curl or extend your fingers while keeping the palm still; observe that palm control uses the wrist and finger bases rather than fingertips.
4. Hide the hand briefly and restore it before the timeout. The cross should disappear while unavailable, then resume smoothing.
5. Hide it for longer than the timeout. Show it at a different location; the cross should start there instead of moving from its old position.
6. Set `TRACKING_MAX_HANDS=2`, show both hands, and confirm their controls move independently.
7. Compare `SMOOTHING_ALPHA=1` and `SMOOTHING_DEAD_ZONE=0` with the defaults. Restore defaults after checking.
8. Try `CAMERA_MIRROR=false`; physical handedness should remain correct and there should be no additional coordinate flip.

If movement feels too slow, raise alpha slightly. If small movement is ignored, reduce the dead-zone radius. Tune one setting at a time. Existing webcam troubleshooting remains in [the Phase 2 guide](phase2_hand_tracking.md).

## Verification and limits

All 57 automated tests passed, including 24 new tests for palm-joint selection, coordinate bounds, finite-value rejection, known EMA response, reduction of synthetic stationary jitter, radial/gradual dead-zone movement, separate hand filters, confidence gating, timeout boundary, reacquisition after long/short gaps, non-monotonic clocks, and controller/preview integration. Tests use deterministic synthetic observations and fake devices.

The import health check passed. A real MediaPipe model also processed five blank synthetic frames through the position processor and in-memory preview without creating control positions or modifying the input image. An invalid smoothing alpha produced a named configuration error and exit code `1` before webcam access. These checks exercise software integration rather than live tracking.

Live webcam movement, perceived jitter/lag, window interaction, and achieved camera FPS still require checking on the Windows machine. The managed cloud has no webcam or desktop display. No live hand-detection or clinical validation is claimed.

## Label continuity

MediaPipe labels each frame's hand as left or right on its own, so one hand being moved can briefly come back as the other hand or with a confidence under `CONTROL_MIN_HANDEDNESS_CONFIDENCE`. With a single control hand that makes the cursor disappear for a frame or two, which in a game pauses timers and drains dwell progress.

`cv_engine/continuity.py` corrects only the clear cases, before the position and gesture processors run:

- **Flipped label:** a detection whose label has no recent track, sitting within `CONTROL_CONTINUITY_RADIUS` of the other label's track from the last `CONTROL_CONTINUITY_SECONDS`, takes that label (unless the other label is also detected this frame).
- **Low confidence:** a detection with a recently tracked label, still within the radius, is accepted despite a confidence below the gate.
- **Never invented:** a hand with no recent tracked history, or one that appears far from the old track, is left exactly as MediaPipe reported it. A weak frame never starts or extends a track.
- Corrected hands are marked `label_corrected`; `handedness_confidence` keeps MediaPipe's original value. The 5-second log line reports the number of corrections so far.

If a genuine hand swap ever looks wrong in play, set `CONTROL_CONTINUITY_SECONDS=0` to turn it off.

Measured offline on two 20-second recordings with the hand in view, 93% and 96% of frames were usable for the right-hand control; the fix could raise that toward 100% where the mislabeled frames stayed near the tracked hand. That is an upper bound from labels only (positions were not recorded), so confirm with a live run.
