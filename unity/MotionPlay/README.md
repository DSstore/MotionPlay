# MotionPlay Unity project — Phase 7

Open **this folder** (`unity/MotionPlay`) in Unity Hub with **2022.3.62f3**.
Wait for package restoration, then click
**MotionPlay → Create Hand Cursor Test Scene → Play**.
Start Python from the repository root:

```powershell
.\.venv\Scripts\python.exe -m cv_engine.controller
```

The Game view displays a simple disc controlled by the filtered palm position. It hides on tracking loss or receive timeout. Expand diagnostics to inspect numerical states. The separate Phase 6 scene remains available through **MotionPlay → Create Receiver Test Scene**.
Close the Python packet monitor before playing: it uses the same UDP port.

Follow the complete [Windows setup and acceptance guide](../../docs/phase7_hand_cursor.md)
and [UDP protocol](../../docs/udp_protocol.md). Run the core tests from
**Window → General → Test Runner → EditMode → Run All**. The **PlayMode** tab also includes a hardware-free cursor lifecycle test, which still needs local execution.

The cloud has compiled and tested the engine-independent C# core and real Python
UDP delivery. Unity Editor/Windows/live webcam verification remains pending.
This is an educational portfolio project, not a medical device.
