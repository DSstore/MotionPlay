# MotionPlay UDP protocol

Phase 5 implements **Python → Unity `CV_STATE`**. The packet monitor is a
diagnostic tool. Phase 6 implements the Unity receiver; Unity → Python result
messages below are reserved designs, not working endpoints.

## Transport

| Direction | Destination | Default port | Status |
|---|---|---|---|
| Python CV → Unity | `UDP_HOST` | `CV_TO_UNITY_PORT=5005` | Sender and receiver implemented |
| Unity → Python backend | Future Python receiver | `UNITY_TO_PYTHON_PORT=5006` | Reserved for Phase 10 |

One UDP datagram contains one UTF-8 JSON object, without a newline, length prefix,
or fragmentation at the application layer. CV packets are limited to **1,200
bytes**. The two configured ports must differ. Python sends from an OS-assigned
ephemeral source port; it does not bind the result port. Use a literal unicast
IPv4 destination. Hostnames and IPv6 are not supported in this phase, avoiding
DNS resolution in the processing loop. Default `127.0.0.1` keeps messages on the
same computer. Configuring another address sends numerical states to that host;
frames and landmarks are never included.

UDP has no delivery, ordering, duplicate suppression, or liveness guarantee.
`sendto` success means the local OS accepted a packet, not that Unity received
it. Logs say **delivery unconfirmed**. There is no connection handshake or
application acknowledgment in Phase 5. A receiver must validate each packet,
keep only its latest accepted state, and clear control after a receive timeout.
Use **0.5 seconds** as the initial receiver timeout, measured on the receiver's
monotonic clock; clearing `tracking=false` takes effect immediately on receipt.
Python's filtering timeout cannot protect a receiver when Python stops sending.

## Implemented CV_STATE, version 1

```json
{
  "type": "CV_STATE",
  "version": 1,
  "stream_id": "a1e111a1-1111-4111-8111-111111111111",
  "sequence": 7,
  "timestamp": 1770000000123,
  "hand": "right",
  "tracking": true,
  "position": { "x": 0.55, "y": 0.31, "z": -0.03 },
  "gesture": "OPEN_HAND",
  "confidence": 0.95,
  "mirrored": true
}
```

| Field | Type | Contract |
|---|---|---|
| `type` | string | Exactly `CV_STATE` |
| `version` | integer | Exactly `1`; booleans are invalid |
| `stream_id` | string | Canonical UUID generated for a sender run |
| `sequence` | integer | 0..2^63−1, starting at zero, increasing per send attempt |
| `timestamp` | integer | 0..2^63−1, Unix UTC milliseconds at serialization |
| `hand` | string | Physical `left` or `right`, selected by `CONTROL_HAND` |
| `tracking` | boolean | Fresh accepted palm available for this selected hand |
| `position` | object or null | Filtered palm: finite x/y in [0,1], finite z |
| `gesture` | string | Debounced `OPEN_HAND`, `FIST`, `PINCH`, `POINT`, or `UNKNOWN` |
| `confidence` | number | Finite [0,1] handedness classification confidence |
| `mirrored` | boolean | Whether Python mirrored the input before inference |

All fields are required. X increases to the image right, Y increases downward.
Z is wrist-relative MediaPipe model depth, not meters. Confidence is confidence
in the left/right label, not landmark accuracy. Native landmarks and raw gesture
candidates are excluded. A usable palm with unusable gesture geometry still
sends `tracking=true`, its position, and `gesture=UNKNOWN`.

With `mirrored=true`, Python has already mirrored the coordinates; Unity should
not mirror X again. Unity will convert Y downward to its own coordinate system.
With `mirrored=false`, a future configurable Unity mapping may invert X for
mirror-like control. Labels always refer to the physical hand.

Only the selected hand controls this stream. There is no automatic fallback to
the other hand, even when both are tracked. Separate filter/gesture states remain
available locally. Missing/low-confidence selected hands send:

```json
{
  "type": "CV_STATE",
  "version": 1,
  "stream_id": "a1e111a1-1111-4111-8111-111111111111",
  "sequence": 8,
  "timestamp": 1770000000157,
  "hand": "right",
  "tracking": false,
  "position": null,
  "gesture": "UNKNOWN",
  "confidence": 0.0,
  "mirrored": true
}
```

Untracked packets must use null position, UNKNOWN gesture, and zero confidence.
They are also sent before the first detection. No stale coordinates are reused.

### Pacing, shutdown, and receiver responsibilities

The sender uses monotonic deadlines and a configurable cadence
(`UDP_SEND_FPS=30`). At most one fresh packet is attempted per due processing
frame. Excess frames are skipped, missed slots are discarded, and states are
never queued or replayed. The cadence stays anchored to avoid halving throughput
when a webcam runs just above 30 FPS. Actual throughput depends on webcam and
model processing speed; this is a target cadence, not a per-packet minimum
spacing guarantee. There is no background heartbeat while camera/inference
blocks. A clean exit attempts one final lost state, bypassing pacing once;
delivery is not guaranteed, so the receiver timeout is essential.

Use `sequence` to ignore duplicate/older packets in an active `stream_id`.
Missing numbers can mean OS send errors or network loss. Skipped processing
frames do not consume sequence numbers. A new run has a new stream ID and starts
at zero. The Phase 6 receiver adopts a new stream ID after the prior stream has
timed out and retires the old ID, so late packets from a retired run cannot
reactivate it. Retirement is bounded at 128 IDs per listener lifetime;
disable/re-enable to reset after that limit. This is state streaming,
not gesture event delivery; a held gesture appears repeatedly. Games must decide
whether an action uses a gesture edge or a continuously held state.

Wall-clock timestamps can jump and clocks on different computers can differ.
Use sequence numbers for ordering, and local monotonic time for receive timeout.
Timestamps alone do not measure UDP or Unity update latency. Those measurements
will need clock-aware instrumentation in later phases.

`shared.protocol.decode_cv_state` rejects oversized packets, invalid UTF-8/JSON,
duplicate keys, missing fields, unsupported versions/types, invalid enums,
booleans in numeric fields, nonfinite coordinates, and inconsistent lost states.
Unknown extra fields are ignored to allow additive extensions. A breaking change
requires a new protocol version. UDP JSON is unauthenticated; the local monitor
binds only to loopback.

## Phase 6 receiver implementation

`unity/MotionPlay/Assets/MotionPlay/Core` validates CV packets on a socket worker, keeps only the latest state, ignores duplicate/older sequence numbers without refreshing the deadline, and retires timed-out streams when a new one takes over. It binds exclusively to **127.0.0.1**. Unity's main-thread `UdpReceiver.Update` observes fresh immutable snapshots; timeout produces a null current state. The main-thread diagnostic panel renders numerical states, with no cursor movement yet. The parser caps nesting at 16 levels and rejects comments, unquoted keys, single quotes, and nonfinite numbers. See the [Unity setup guide](phase6_unity_receiver.md).

## Reserved Unity → Python messages

The following describes the intended fields for Phase 10. They are not encoded,
decoded, sent, or persisted by Phase 5. Final schemas, validation, and result
delivery/idempotency behavior will be finalized alongside session implementation.
Use the same `type`, `version`, `stream_id`, `sequence`, and UTC-millisecond
`timestamp` envelope, plus a session UUID and game identifier. Unity's stream ID
and sequence belong to its own sender, independently of the CV stream.

| Type | Purpose | Planned payload fields |
|---|---|---|
| `GAME_STATE` | Game lifecycle/status | `session_id`, `game`, `state` (ready/calibrating/playing/paused/complete) |
| `SESSION_UPDATE` | Cumulative metrics snapshot | `session_id`, `game`, `score`, `targetsAttempted`, `targetsCompleted`, `averageReactionTime`, `accuracy` |
| `SESSION_END` | Final session summary | Update fields plus `startedAt`, `endedAt`, `duration`, `hand`, `difficulty`, `averageMovementTime`, `averageHoldStability`, `currentStreak`, `bestStreak`, `pathEfficiency` |

Example **reserved** update:

```json
{
  "type": "SESSION_UPDATE",
  "version": 1,
  "stream_id": "b2e222b2-2222-4222-8222-222222222222",
  "sequence": 12,
  "timestamp": 1770000001000,
  "session_id": "c3e333c3-3333-4333-8333-333333333333",
  "game": "reach_garden",
  "score": 8,
  "targetsAttempted": 10,
  "targetsCompleted": 8,
  "averageReactionTime": 1.42,
  "accuracy": 0.80
}
```

Durations/reaction/movement time will use seconds; started/ended timestamps use
UTC milliseconds. Accuracy and stability will use [0,1]. Metrics with no samples
should be null rather than fabricated zero. Exact definitions will be established
in Phase 9. These are gameplay metrics, with no medical interpretation.
Cumulative updates and session IDs permit deduplication, but UDP alone cannot
guarantee final-result persistence. Phase 10 must resolve result delivery before
database integration; a single SESSION_END send will not count as reliable storage.
