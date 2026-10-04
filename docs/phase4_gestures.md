# Phase 4: gesture engine

This guide records its original development phase. On current Phase 5 source,
the controller also sends numerical UDP states by default. Add `--no-udp` to
the commands below for local-only checks, or follow the [Phase 5 guide](phase5_udp_sender.md).

## Scope and architecture

Phase 4 adds reusable, original hand-geometry heuristics and debouncing. It sends no UDP messages, starts no Unity game, and stores no webcam frames. Existing palm filtering remains unchanged.

```text
Raw MediaPipe landmarks -> GestureEngine -> raw candidate
Fresh palm eligibility -> GestureProcessor -> per-hand GestureDebouncer
                         -> confirmed gesture + change edge -> local preview
```

`cv_engine/gestures.py` provides `GestureEngine`, `GestureDebouncer`, and joint-angle math. Public detector methods are `detect_open_hand`, `detect_fist`, `detect_pinch`, and `detect_point`; `classify` returns a raw `Gesture` enum. `analyze` also reports whether the geometry was usable. No camera, Unity, or networking code is required to use them.

`cv_engine/gesture_processor.py` coordinates the existing control eligibility with independent left/right gesture histories. It classifies the same raw observation selected for palm control. Geometry uses the original landmarks, never coordinates altered by clamping or smoothing.

## Geometry rules

MediaPipe X is normalized by image width, Y by height, and Z approximately uses X's scale. Convert Y to comparable units by dividing it by `image_aspect_ratio = width / height`. The controller supplies the actual captured frame dimensions. Direct classifier calls default to a square image; pass the actual ratio for webcam observations.

For each finger, inspect its two distal joint angles and compare tip-to-wrist distance with base-to-wrist distance. Straight fingers beyond the reach threshold are extended; bent fingers within it are curled. Intermediate configurations are unknown. Thumb uses its CMC/MCP/IP/tip chain; the other fingers use MCP/PIP/DIP/tip.

Palm size is the larger of wrist-to-middle-MCP distance and index-to-pinky-MCP distance. Thumb/index tip separation divided by that size gives a dimensionless pinch ratio. Thresholds therefore do not depend on a fixed pixel distance or a left/right X-axis comparison.

| Gesture | Rule |
| --- | --- |
| `FIST` | All four non-thumb fingers are curled. Thumb position does not decide this rule. |
| `PINCH` | Thumb/index tip ratio is at most the configured threshold, and the four-finger fist rule is false. |
| `POINT` | Index is extended; middle, ring, and pinky are curled. Thumb position does not decide this rule. |
| `OPEN_HAND` | All five fingers are extended. |
| `UNKNOWN` | A usable pose matches none of the rules, or the input geometry is unusable. |

Classification priority is **FIST → PINCH → POINT → OPEN_HAND → UNKNOWN**. Public detector predicates can overlap; `classify` resolves them using this priority. A fist can incidentally bring thumb/index tips together, so the fist rule wins. This deliberately limits compact pinch poses with all other fingers folded; try pinching with the other fingers relaxed/extended when checking the baseline.

Incomplete landmarks, nonfinite geometry, near-zero segments, collapsed palms, and overflowing derived values produce an unusable `UNKNOWN` detection. Intermediate but valid finger poses produce usable `UNKNOWN`, which follows normal debouncing. These are heuristics based on model coordinates, not a trained gesture model or a physical joint-angle measurement. Lighting, occlusion, viewpoint, landmark errors, and unusual finger configurations can affect recognition. Synthetic transformation tests do not establish invariance under real camera perspective or real-hand accuracy.

## Debouncing and tracking loss

Default confirmation requires five consecutive accepted frames with the same candidate. A different candidate restarts the count. While a new candidate is pending, keep the previous confirmed gesture for that fresh, valid hand. `UNKNOWN` from a valid ambiguous pose also requires confirmation.

On the first confirmed change, `HandGesture.changed` is true. Holding that gesture does not repeat the edge on later frames. The count stops at the configured confirmation length. At an achieved 30 FPS, five frames take roughly 0.17 seconds; actual delay depends on frame rate and classification stability.

Missing hands, rejected handedness confidence, or unusable finger geometry immediately clear both pending and confirmed gesture state. The output becomes unavailable with gesture `UNKNOWN`, count `0`, and `changed=False`. Returning hands must build a new sequence. A gap at least as long as `CONTROL_TRACKING_TIMEOUT` also clears history even when no empty frame was processed during the gap. A short missing frame resets gesture confirmation even though the separate position filter may retain its history.

Logs record confirmed gesture changes once, without storing landmarks. This phase creates data for later game control; it does not trigger game actions or measure clinical effects.

## Configuration

These defaults apply if an existing `.env` has no new keys:

```dotenv
GESTURE_DEBOUNCE_FRAMES=5
GESTURE_PINCH_RATIO=0.3
GESTURE_EXTENDED_ANGLE=160
GESTURE_CURLED_ANGLE=105
GESTURE_REACH_RATIO=1.2
```

| Setting | Valid range | Purpose |
| --- | --- | --- |
| `GESTURE_DEBOUNCE_FRAMES` | Integer 1–60 | Consecutive frames required to confirm a change |
| `GESTURE_PINCH_RATIO` | Greater than 0, at most 1 | Maximum thumb/index tip separation relative to palm size |
| `GESTURE_EXTENDED_ANGLE` | At most 180, above curled angle | Minimum joint angle for extension |
| `GESTURE_CURLED_ANGLE` | Greater than 0, below extended angle | Maximum bent joint angle for curl |
| `GESTURE_REACH_RATIO` | Finite, greater than 1 | Tip/base wrist-distance boundary |

Existing `CONTROL_MIN_HANDEDNESS_CONFIDENCE` gates eligibility, and `CONTROL_TRACKING_TIMEOUT` handles long gaps. These do not provide gesture confidence probabilities. Invalid settings produce a named configuration error before accessing the webcam. No dependencies were added.

## Windows acceptance checks

From the MotionPlay directory:

```powershell
.\.venv\Scripts\python.exe -m cv_engine.controller
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

1. Show an open palm with all fingers extended and hold it. Raw and confirmed labels should become `OPEN_HAND`.
2. Curl the four fingers into a fist and hold. Confirm `FIST`.
3. Touch thumb and index tips while keeping the other fingers relaxed/extended. Confirm `PINCH`.
4. Extend index and curl middle, ring, and pinky. Confirm `POINT`.
5. Show a mixed pose with two fingers extended. Observe `UNKNOWN` if it matches none of the other rules.
6. Change poses quickly. The raw candidate can change before the confirmed label; a noisy single frame should not confirm a change.
7. Hide the hand, then restore it. Confirm immediate unavailable/`UNKNOWN` output and a new confirmation sequence.
8. Repeat with the other physical hand and `CAMERA_MIRROR=false`. For two-hand checking, set `TRACKING_MAX_HANDS=2`; histories should remain independent.

Keep the entire hand visible in good lighting. Tune one parameter at a time. If pinch requires excessive precision, increase its ratio slightly; if recognition changes too quickly, raise the confirmation frame count. Keep curl angle below extension angle. Restore defaults after comparison.

## Verification and limits

The automated suite passes **81 tests**, including **24 new gesture tests**. Original synthetic fixtures exercise all five labels, reusable predicates, scale/translation/mirroring/image-plane rotation, image aspect correction, fist/pinch priority, tunable thresholds, unusable geometry, exact confirmation counts, one-frame noise, unknown transitions, reset behavior, separate hand histories, confidence rejection, long gaps, duplicate observation selection, one-time change edges, and controller/preview integration.

The import health check passed. Five blank frames also passed through a real MediaPipe model, palm processor, gesture processor, and in-memory preview with no false gesture outputs or input-image mutation. An invalid gesture configuration returned exit code `1` before webcam access. These integration checks exercise software execution rather than live recognition.

The synthetic fixtures are math inputs, not webcam detections or recorded human hands. Live gesture recognition and timing still require local Windows checks; the managed cloud has no webcam or desktop display. MotionPlay remains an educational portfolio project, not a medical device.
