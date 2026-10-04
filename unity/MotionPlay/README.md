# MotionPlay Unity project — Phase 6

Open **this folder** (`unity/MotionPlay`) in Unity Hub with **2022.3.62f3**.
Wait for package restoration, then click
**MotionPlay → Create Receiver Test Scene → Play**.
Start Python from the repository root:

```powershell
.\.venv\Scripts\python.exe -m cv_engine.controller
```

The Game view displays numerical CV states. Cursor movement begins in Phase 7.
Close the Python packet monitor before playing: it uses the same UDP port.

Follow the complete [Windows setup and acceptance guide](../../docs/phase6_unity_receiver.md)
and [UDP protocol](../../docs/udp_protocol.md). Run the core tests from
**Window → General → Test Runner → EditMode → Run All**.

The cloud has compiled and tested the engine-independent C# core and real Python
UDP delivery. Unity Editor/Windows/live webcam verification remains pending.
This is an educational portfolio project, not a medical device.
