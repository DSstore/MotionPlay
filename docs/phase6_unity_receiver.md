# Phase 6: Unity UDP receiver

This guide describes the Phase 6 receiver-only scene and its original validation.
Phase 7 adds a separate cursor scene; see the [hand cursor guide](phase7_hand_cursor.md).
The receiver scene remains available for independent checks.

## Scope and structure

Phase 6 adds an original, minimal Unity project at `unity/MotionPlay`. It receives
version-1 CV packets and displays numerical diagnostics. **There is no moving
cursor or gameplay yet.** Phase 7 maps these validated states to a cursor in a separate scene.

```text
unity/MotionPlay/
  Assets/MotionPlay/
    Core/               Immutable data, packet codec, state buffer, configuration, socket worker
    Runtime/            UdpReceiver and ReceiverDebugPanel Unity components
    Editor/             Menu action to create the receiver test scene
    Scenes/             ReceiverTest.unity is generated locally through Unity's scene APIs
    Tests/EditMode/     Core NUnit tests, also run by the standalone harness
  Packages/manifest.json
  ProjectSettings/ProjectVersion.txt
tests/csharp/           Optional .NET harness linking the same core/test source
```

Script/folder/assembly-definition `.meta` files are tracked with stable GUIDs.
Unity generates remaining project settings and its package lock on first open.
Library, Temp, build artifacts, and editor user settings stay out of Git. No
Unity-generated cache, executable, artwork, or third-party source is committed.

## Architecture and behavior

- `CvStateCodec` validates UTF-8, packet size, required fields, version, enums,
  types, finite coordinates, and lost-state semantics. Duplicate keys and
  concatenated objects are rejected. The Unity-official
  `com.unity.nuget.newtonsoft-json` package **3.2.1** supplies Json.NET **13.0.2**;
  it avoids JsonUtility's silent defaults for missing fields. Numeric sequence
  and timestamp fields are limited to nonnegative signed 64-bit values in both
  Python and C#. Unknown extra fields are ignored. Parsing depth is capped at 16.
- `UdpStateListener` binds **127.0.0.1 only**, with an exclusive UDP socket and a
  background receive thread. It never calls Unity APIs. It decodes packets and
  passes immutable values to `CvStateBuffer`. Oversized/malformed input is
  counted and discarded; reception continues.
- `CvStateBuffer` holds one latest state under a lock. Duplicate/older sequences,
  invalid packets, and packets from rejected streams do not refresh the receive
  deadline. `tracking=false` clears control immediately on receipt. At the
  configured timeout boundary, `Snapshot.State` becomes null, so a future cursor
  cannot accidentally reuse its old position.
- A fresh stream owns reception. A new stream ID is adopted after the current
  one has been silent for `UNITY_RECEIVE_TIMEOUT` seconds. The previous ID is
  retired and cannot reactivate, even with a higher sequence. This can delay
  recognition of a restarted Python sender by about 0.5 seconds. Run one sender
  at a time. Up to 128 IDs can be retired per listener lifetime; after that,
  disable/re-enable the component to reset it. Retired IDs are never evicted to
  let stale packets take control.
- `UdpReceiver` owns the socket worker through Unity enable/disable/quit events.
  Its `Update` reads a fresh snapshot before ordinary default-order gameplay
  updates (`DefaultExecutionOrder(-100)`). Only this component logs to Unity.
  Startup failures show configuration/port advice without aborting Play Mode.
  Disabling or stopping Play closes the socket and joins the worker with a
  one-second bound; stopping is idempotent.
- `ReceiverDebugPanel` shows accepted/invalid/rejected counts, stream/sequence,
  hand, tracking, confirmed gesture, mirror flag, position, and timeout status.
  The displayed **worker → Update delay** measures time from accepting the
  latest packet to observing it in an Update; it excludes network transit and
  rendering and is not end-to-end latency.

Reception runs while Unity is in the background so using Python's preview does
not pause it. Unity does not mirror, scale, or move anything in this phase. See
[UDP protocol](udp_protocol.md) for coordinates and future cursor mapping.

## Windows 11: exact Unity setup

1. In PowerShell at the repository root, run `git pull`, then the existing Python
   health check. Close the Phase 5 packet monitor; it owns the same receive port.
2. Install **Unity Hub** from Unity's official website if needed. Sign in and
   activate an appropriate Unity license. In Hub, install **Unity 2022.3.62f3**
   (the pinned project version, available through Unity's download archive).
   Another 2022.3 LTS patch may work, but any upgrade still needs local validation.
   No Android/iOS modules are required; Visual Studio is optional for editing.
3. In **Unity Hub → Projects → Add → Add project from disk**, select the
   repository's **`unity/MotionPlay`** folder. Do not select the repository root
   and do not create a second project inside it. Open with the installed editor.
4. Wait for Unity to import scripts and restore packages. This first import
   needs network access. Open **Window → General → Console** and verify there
   are no red compile errors. In **Window → Package Manager**, verify Newtonsoft
   Json 3.2.1 and Test Framework 1.1.33 are installed. These are already declared
   in the manifest; do not install a second Newtonsoft DLL.
5. Click **MotionPlay → Create Receiver Test Scene** in the top menu. Save any
   existing scene if prompted. The action creates a camera and a
   **MotionPlay Receiver** GameObject with **Udp Receiver** and
   **Receiver Debug Panel**, then saves
   `Assets/MotionPlay/Scenes/ReceiverTest.unity`.
6. Click the **Game** tab, then **Play** at the top of Unity. The diagnostic box
   should say **Listening on 127.0.0.1:5005** and **Waiting for first valid packet**.
   Nothing should move yet.
7. In PowerShell at the repository root, run:

   ```powershell
   .\.venv\Scripts\python.exe -m cv_engine.controller
   ```

8. Show your configured hand (right by default). In Unity's Game tab, check the
   accepted count increases, `tracking=True`, X/Y remain in [0,1], and the gesture
   agrees with Python's confirmed label. Hide the hand: tracking must clear and
   the panel must show no active position.
9. Exit Python with Q/Escape. The final lost packet may arrive; after the receive
   timeout the Unity panel should show **Receive timeout — tracking unavailable**.
   Also test forced Python closure to verify the timeout without a clean shutdown.
10. Restart Python. A new stream ID should be adopted after the prior stream's
    timeout. Stop Unity Play Mode, then Play again: the socket must rebind cleanly.
    In Play Mode, toggling the receiver component's checkbox in Inspector should
    stop and restart reception without leaving the port occupied.

If the menu action is unavailable after compilation, the manual equivalent is:
**File → New Scene → Basic (Built-in) → Create**; then
**GameObject → Create Empty**, rename it **MotionPlay Receiver**, and in Inspector
use **Add Component → Udp Receiver** and **Add Component → Receiver Debug Panel**.
Save as `Assets/MotionPlay/Scenes/ReceiverTest.unity`. Use the menu action as the
primary method so the scene is reproducible.

## Configuration and troubleshooting

In the Editor, the receiver loads the repository-root `.env` regardless of the
working directory. The supported receiver settings are:

```dotenv
CV_TO_UNITY_PORT=5005
UNITY_TO_PYTHON_PORT=5006
UNITY_RECEIVE_TIMEOUT=0.5
```

Defaults → selected `.env` values → process environment. Numeric values may be
quoted and include trailing comments; no interpolation or credential processing
occurs. These settings load when the component is enabled: exit/re-enter Play or
toggle the component after editing. Python still needs `UDP_HOST=127.0.0.1`.

**Env File Override** in the component Inspector can select an external file.
Alternatively set `MOTIONPLAY_ENV_FILE` before launching Unity. An explicitly
selected missing file is an error. Player builds use defaults/process variables
unless given an external file; do not copy the credential-containing repository
`.env` into Assets or a player build. Builds and packaging are later phases.
The result port is checked for a conflict but is not opened in this phase.

| Symptom | Action |
|---|---|
| Receiver unavailable / address already in use | Stop the Python monitor, another Unity instance, or any listener on port 5005; toggle the component to retry. |
| Waiting forever | Check Python is running without `--no-udp`, matching ports, localhost destination, and firewall permissions. |
| Always untracked | Check `CONTROL_HAND`, preview labels, hand visibility, and confidence threshold. |
| Red Console compile/package errors | Confirm 2022.3 LTS, allow package restore, and remove conflicting manually installed Newtonsoft DLLs. |
| No menu entry | Fix Console compile errors first, then wait for script reload. |
| Component disabled unexpectedly / invalid config | Inspect the named numeric setting; sender/result ports must differ. Re-enable after correcting it. |
| Many rejected packets | Run one Python sender; duplicates, old sequences, and fresh competing stream IDs are deliberately ignored. |

## Tests and honest verification status

Run **Window → General → Test Runner → EditMode → Run All** in Unity. Core tests
use synthetic packets and OS loopback sockets, so no webcam is required. That
Unity Test Runner execution and the scene/MonoBehaviour lifecycle need local
verification; Unity is not installed in the managed cloud.

An optional **.NET 8 SDK** harness compiles the exact same `Core/*.cs` and NUnit
test source independently of Unity. It is a developer check, not an application
runtime requirement. From the repository root on Windows:

```powershell
dotnet run --project tests/csharp/MotionPlay.ReceiverHarness.csproj -- --noresult
.\.venv\Scripts\python.exe -m tests.check_python_unity_udp
```

The first command restores pinned development packages on its first run. The
second runs two real Python → C# UDP checks and needs the compiled harness.
The standalone assembly links source files; it contains no copied implementation
or substitute Unity engine. Its Json.NET 13.0.2 version matches Unity's package.

Cloud validation passed:

- 104 existing Python tests and the Python 3.11 dependency health check.
- 51 compiled C# test cases: schema/type validation, lost states, duplicate/order
  rejection, timeout boundary, retired streams, config precedence/errors, real
  UDP reception, duplicate Start/Stop, occupied ports, and stop/rebind.
- Python synthetic landmarks → actual palm/gesture processors → actual Python
  UDP sender → actual C# listener: matching coordinates and gesture, malformed
  packet rejection, lost state, and timeout.
- Abrupt sender silence: C# cleared control without any terminal packet.

These results do not verify Unity Editor import/compilation, Game view rendering,
Play Mode lifecycle, Windows-specific socket behavior, live webcam gesture
accuracy, or end-to-end latency. Complete the Windows checklist before calling
Phase 6 locally validated. MotionPlay is an educational portfolio project, not
a medical device. Follow the Phase 7 guide for the separate cursor milestone.
