"""Optional real Python → C# socket check using the same core compiled for Unity.

First build tests/csharp/MotionPlay.ReceiverHarness.csproj with the .NET 8 SDK.
Run from the repository root: python -m tests.check_python_unity_udp --dotnet dotnet
This does not launch Unity, a camera, or a graphical window.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
from pathlib import Path

from cv_engine.gesture_processor import GestureProcessor
from cv_engine.models import ControlResult, Gesture, GestureResult, TrackingResult
from cv_engine.position_processor import PositionProcessor
from cv_engine.udp_sender import UdpSender, hand_state
from shared.config import ControlSettings, GestureSettings, SenderSettings
from tests.gesture_fixtures import gesture_hand


ROOT = Path(__file__).resolve().parents[1]


def start_probe(dotnet: str, assembly: Path) -> tuple[subprocess.Popen[str], int]:
    """Wait for the C# listener's READY marker before sending any packets."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen([dotnet, str(assembly), "--probe", str(port)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert process.stdout is not None
    if process.stdout.readline().strip() != "READY":
        process.kill()
        _output, errors = process.communicate()
        raise RuntimeError(f"C# listener did not start: {errors}")
    return process, port


def stop_probe(process: subprocess.Popen[str]) -> None:
    """Release the subprocess even if an assertion fails."""
    if process.poll() is None:
        process.kill()
    process.communicate()


def check_pipeline(dotnet: str, assembly: Path) -> None:
    """Synthetic landmarks through real Python processors and sender to real C#."""
    control_settings = ControlSettings()
    positions = PositionProcessor(control_settings)
    gestures = GestureProcessor(GestureSettings(), control_settings)
    observation = TrackingResult((gesture_hand(Gesture.OPEN_HAND),), 1)
    for index in range(5):
        controls = positions.update(observation, index / 30)
        confirmed = gestures.update(observation, controls, index / 30)
    assert confirmed.hands[0].gesture == Gesture.OPEN_HAND
    process, port = start_probe(dotnet, assembly)
    assert process.stdout is not None
    try:
        # Malformed input must not terminate the real receiver.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as malformed_sender:
            malformed_sender.sendto(b"invalid-json", ("127.0.0.1", port))
        with UdpSender("127.0.0.1", port, SenderSettings(), True) as sender:
            sent = sender.send(controls, confirmed, 0)
            assert sent
            tracked = json.loads(process.stdout.readline())
            expected = hand_state(controls, confirmed, "right", sender.stream_id, 0, 0, True)
            assert tracked["tracking"] is True and tracked["gesture"] == "OPEN_HAND"
            assert tracked["stream_id"] == sender.stream_id and tracked["sequence"] == 0
            assert expected.position is not None
            assert tracked["position"] == {"x": expected.position.x, "y": expected.position.y, "z": expected.position.z}
            assert tracked["invalid"] == 1
            sent = sender.send(ControlResult(), GestureResult(), 0.04)
            assert sent
            lost = json.loads(process.stdout.readline())
            assert lost["tracking"] is False and lost["position"] is None and lost["gesture"] == "UNKNOWN"
        tail, errors = process.communicate(timeout=12)
        assert process.returncode == 0, errors
        assert "TIMEOUT" in tail
        print("PASS Python landmarks → palm/gestures → UDP → C# tracked/lost states; invalid packet rejected")
    finally:
        stop_probe(process)


def check_silence_timeout(dotnet: str, assembly: Path) -> None:
    """Closing a raw sender sends no terminal packet; C# must clear by timeout."""
    process, port = start_probe(dotnet, assembly)
    assert process.stdout is not None
    try:
        from tests.test_udp import example_state

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.sendto(example_state().to_bytes(), ("127.0.0.1", port))
        tracked = json.loads(process.stdout.readline())
        assert tracked["tracking"] is True
        assert process.stdout.readline().strip() == "TIMEOUT"
        _output, errors = process.communicate(timeout=12)
        assert process.returncode == 0, errors
        print("PASS C# clears Python control after silence without a shutdown packet")
    finally:
        stop_probe(process)


def main() -> int:
    """Run optional integration checks without changing the Python dependency set."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dotnet", default="dotnet", help="Path to .NET executable")
    parser.add_argument("--assembly", type=Path, default=ROOT / "tests/csharp/bin/Debug/net8.0/MotionPlay.ReceiverHarness.dll")
    args = parser.parse_args()
    if not args.assembly.is_file():
        parser.error("Build the C# harness first; see docs/phase6_unity_receiver.md.")
    check_pipeline(args.dotnet, args.assembly)
    check_silence_timeout(args.dotnet, args.assembly)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
