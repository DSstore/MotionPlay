# Phase 7: hand-controlled Unity cursor

## What changed

The Phase 6 receiver now feeds a separate `HandCursorController`. A simple mint
disc follows the selected hand's **filtered palm position**, hides whenever
fresh tracking is unavailable, and returns on reacquisition. The disc is an
original geometric placeholder generated in memory; no artwork or new package
dependency is added. Gesture detection remains visible in diagnostics but does
not trigger gameplay in this phase.

```text
Webcam → OpenCV/MediaPipe → filtered palm + confirmed gesture
                                  ↓ UDP CV_STATE
Unity socket worker → fresh snapshot → CursorMapper → HandCursorController → disc
```

`Core/CursorMapper.cs` contains engine-independent mapping in the
`MotionPlay.Control` namespace. `Runtime/HandCursorController.cs` handles camera
placement and visibility, `CursorDisc.cs` owns its generated sprite/texture,
and `HandCursorStatusPanel.cs` shows tracking status. The receiver keeps its
existing protocol validation, sequence ordering, stream retirement, and timeout.
There is no second smoothing filter in Unity; Python's EMA already filters
coordinates. Unity displays the latest accepted position between packets.

## Mapping, bounds, and mirroring

The test camera is orthographic. Its half-height is `orthographicSize` and its
half-width is `orthographicSize × aspect`. Subtract cursor radius plus edge
margin from each to obtain the cursor-center limits. This keeps the entire disc
inside the view. Limits are recomputed each Update, including when the Game view
aspect ratio or camera size changes.

For an already mirrored packet and default mirror control:

```text
local X = (2 × normalized X − 1) × usable half-width
local Y = (1 − 2 × normalized Y) × usable half-height
```

Y is inverted once because image Y grows downward. These are camera-plane
coordinates; the controller uses the camera's right/up/forward vectors to place
the cursor in world space, so moving or rotating the camera moves the plane with
it. MediaPipe Z is ignored for this 2D control; it does not represent real depth.

**Mirror Control** selects the desired final horizontal orientation:

| Python `mirrored` | Unity Mirror Control | Unity X conversion |
|---|---|---|
| true | true | Use packet X directly |
| false | true | Use `1 − X` |
| true | false | Use `1 − X` to undo Python mirroring |
| false | false | Use packet X directly |

Keep `CAMERA_MIRROR=true` in `.env` and Mirror Control checked for natural
mirror-like movement. With both true, moving to your physical right should move
the cursor to screen right. If using an unmirrored Python preview, Unity can
still provide mirrored control; its X will then differ from the preview's X.
Physical left/right hand labels do not change during cursor mapping.

No fresh state, an explicit lost state, receiver disable/failure, or receive
timeout hides the renderer and makes `CurrentPosition` null. The cursor
GameObject stays active so its Update can restore tracking. Disabling the cursor
component also hides it. A future game should use the nullable current position
or `IsTracking`, rather than the hidden Transform's last location.

## Windows 11: exact setup and proof-of-concept check

1. Run `git pull` at the repository root. Open `unity/MotionPlay` through Unity
   Hub with the pinned **2022.3.62f3** editor. If setting up Unity for the first
   time, follow the [Phase 6 installation steps](phase6_unity_receiver.md).
2. Let scripts import and verify **Window → General → Console** has no red
   compilation errors. Close the Python UDP monitor; Unity owns its receive port.
3. Click **MotionPlay → Create Hand Cursor Test Scene**. Save an existing scene
   if prompted. This creates and saves
   `Assets/MotionPlay/Scenes/HandCursorTest.unity` with a camera, receiver,
   diagnostics, and the cursor. It does not replace `ReceiverTest.unity`.
4. Select **Hand Cursor** in Hierarchy. Its **Hand Cursor Controller** should
   reference **MotionPlay Receiver** and **Main Camera**. Default settings:
   Mirror Control on, radius **0.12**, edge margin **0.08**, plane distance **10**.
   The camera is orthographic, size **3**, at `(0, 0, -10)`. Keep the cursor at
   the root with no scaled parent so its world radius matches the mapping bounds.
5. Click **Game**, then **Play**. Before hand tracking, the cursor should be
   hidden and its status should say hand unavailable. The receiver's diagnostics
   start collapsed; click **Expand diagnostics** to inspect coordinates/gesture.
6. From PowerShell at the repository root:

   ```powershell
   .\.venv\Scripts\python.exe -m cv_engine.controller
   ```

7. Show your configured hand (right by default). The disc should appear. Move
   slowly left/right and up/down, then hold still. Verify directions feel natural
   and the disc follows Python's magenta filtered palm marker with tolerable
   jitter and delay. The Python gesture may be UNKNOWN without hiding a usable
   palm cursor.
8. Move toward all four webcam edges. Verify the disc remains fully inside the
   Game view. Change the Game view aspect ratio while playing and check bounds
   update. A narrow view may need a smaller radius/margin; an invalid view hides
   the cursor and logs configuration advice once per distinct error.
9. Hide the selected hand, or show only the other hand. The next lost packet
   must hide the disc. Return the selected hand and verify it reappears. Change
   `CONTROL_HAND=left` and restart Python to test the other hand.
10. Exit Python normally, then test abrupt closure. Unity must hide the cursor
    after an explicit lost packet or, without that packet, after the configured
    receive timeout. Restart Python; its new stream is adopted after the previous
    stream's timeout.
11. While playing, toggle **Udp Receiver** off/on. The cursor must hide and
    recover. Toggle **Hand Cursor Controller** off/on and verify the same.
    Stop and restart Play Mode to check socket release and recreated visuals.
12. Repeat the direction check with `CAMERA_MIRROR=false`, keeping Unity Mirror
    Control checked, then restore your preferred settings. Unity should provide
    the same final movement orientation. Toggling Mirror Control in Inspector
    intentionally reverses horizontal orientation.

Collapse diagnostics during movement checks if the box obscures the disc.
No mouse, keyboard movement, or physical controller drives the cursor.

To wire an existing orthographic scene manually: create a root **Hand Cursor**,
add **Sprite Renderer**, **Cursor Disc**, **Hand Cursor Controller**, and
optionally **Hand Cursor Status Panel**. In the controller Inspector, drag in
the existing **Udp Receiver** GameObject and gameplay **Camera**. Use the menu
scene as the primary acceptance setup so the configuration is reproducible.

## Tests and validation limits

In Unity, open **Window → General → Test Runner**:

- **EditMode → Run All** runs the core receiver and cursor mapping tests.
- **PlayMode → Run All** runs `CursorFollowsUdpHidesOnLossTimeoutAndDisable`.
  This sends synthetic packets to a real temporary loopback port, checks cursor
  position and sprite bounds, and checks loss, timeout, and component disable.
  No webcam is required. It restores the process variables it temporarily uses.

The Play Mode test is supplied but **has not run in the cloud**. It needs Unity's
actual lifecycle, graphics objects, and Test Runner.

Optional standalone checks with the .NET 8 SDK:

```powershell
dotnet run --project tests/csharp/MotionPlay.ReceiverHarness.csproj -- --noresult
.\.venv\Scripts\python.exe -m tests.check_python_unity_udp
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Cloud validation passed **72 compiled C# cases** (21 new mapping cases),
**104 Python tests**, the dependency health check, and real Python → C# UDP
checks extended to assert mapped cursor coordinates and null output on loss.
Mapping cases cover center/corners, all mirror combinations, bounds, aspect and
camera-size changes, invalid dimensions, unknown gestures, expired/lost states,
and reacquisition. The standalone harness links the same Core and EditMode
source; it does not execute Unity scripts or fake Unity graphics.

Unity compilation/import, sprite rendering, camera transforms, native Play Mode
tests, Windows socket behavior, live hand tracking, and measured end-to-end
delay still need local verification. A target of 30 FPS is not a measured claim.
The cloud checks establish the protocol-to-mapping software path, not the full
webcam-to-visible-cursor milestone.

## Before Reach Garden

Record your editor version, webcam, actual loop FPS, and the outcomes of direction,
jitter, tracking loss, timeout, edge bounds, and restart checks. You may add a
local demo GIF/video to the portfolio later; MotionPlay itself still records no
webcam video. **Verify this proof of concept works reliably before starting
Phase 8 gameplay**, as required by the development plan. Calibration, session
metrics, adaptive difficulty, and medical interpretation are not part of Phase 7.
MotionPlay is an educational portfolio project, not a medical device.
