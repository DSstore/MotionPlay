"""Test the wire contract, pacing, socket failures, and real loopback delivery."""

from __future__ import annotations

import json
import socket
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import numpy as np

from app.udp_monitor import main as monitor_main
from cv_engine.controller import run_tracking
from cv_engine.models import (
    ControlPosition, ControlResult, Gesture, GestureResult, HandControl, HandGesture, TrackingResult,
)
from cv_engine.udp_sender import UdpError, UdpSender, hand_state
from shared.config import ConfigurationError, SenderSettings, load_settings
from shared.protocol import CVState, MAX_DATAGRAM_BYTES, Position, ProtocolError, decode_cv_state
from tests.gesture_fixtures import gesture_hand


def tracked_controls(hand: str = "right") -> ControlResult:
    """One fresh filtered position, different from its unfiltered input."""
    return ControlResult((HandControl(hand, "tracking", 0.95,
                                     ControlPosition(0.1, 0.2, 0), ControlPosition(0.55, 0.31, -0.03)),))


def confirmed_gestures(hand: str = "right") -> GestureResult:
    """A pending POINT must not replace the last confirmed OPEN_HAND on wire."""
    return GestureResult((HandGesture(hand, True, Gesture.POINT, Gesture.OPEN_HAND, 2),))


def example_state() -> CVState:
    """Deterministic metadata and a representative tracked hand."""
    return hand_state(tracked_controls(), confirmed_gestures(), "right",
                      "a1e111a1-1111-4111-8111-111111111111", 7, 123456789, True)


class ProtocolTests(unittest.TestCase):
    """Enforce all required fields, numeric bounds, and explicit lost semantics."""

    def test_round_trip_uses_filtered_position_confirmed_gesture_and_version(self) -> None:
        state = example_state()
        payload = state.to_bytes()
        self.assertLess(len(payload), MAX_DATAGRAM_BYTES)
        self.assertEqual(decode_cv_state(payload), state)
        data = json.loads(payload)
        self.assertEqual(data["type"], "CV_STATE")
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["position"], {"x": 0.55, "y": 0.31, "z": -0.03})
        self.assertEqual(data["gesture"], "OPEN_HAND")
        self.assertNotIn("landmarks", data)

    def test_missing_selected_hand_is_explicitly_lost_without_fallback(self) -> None:
        state = hand_state(tracked_controls("left"), confirmed_gestures("left"), "right",
                           str(uuid4()), 0, 100, False)
        self.assertFalse(state.tracking)
        self.assertIsNone(state.position)
        self.assertEqual(state.gesture, "UNKNOWN")
        self.assertEqual(state.confidence, 0)
        self.assertEqual(decode_cv_state(state.to_bytes()), state)

    def test_unavailable_gesture_keeps_valid_palm_but_clears_action(self) -> None:
        state = hand_state(tracked_controls(), GestureResult((HandGesture("right"),)), "right",
                           str(uuid4()), 0, 0, True)
        self.assertTrue(state.tracking)
        self.assertEqual(state.gesture, "UNKNOWN")

    def test_all_gestures_and_normalized_boundaries_are_serializable(self) -> None:
        for gesture in Gesture:
            for position in (Position(0, 1, -3), Position(1, 0, 4)):
                with self.subTest(gesture=gesture, position=position):
                    state = replace(example_state(), gesture=gesture.value, position=position)
                    self.assertEqual(decode_cv_state(state.to_bytes()), state)

    def test_invalid_required_fields_and_nonfinite_positions_are_rejected(self) -> None:
        mutations = (
            {"version": True}, {"version": 2}, {"type": "SESSION_END"},
            {"timestamp": -1}, {"timestamp": 1.2}, {"sequence": True},
            {"stream_id": "bad"}, {"hand": "both"}, {"hand": []},
            {"gesture": "WAVE"}, {"tracking": 1}, {"mirrored": "true"},
            {"confidence": -0.1}, {"confidence": float("nan")}, {"confidence": True},
            {"confidence": 10 ** 500}, {"position": None}, {"position": []},
            {"position": {"x": 1.1, "y": 0, "z": 0}},
            {"position": {"x": False, "y": 0, "z": 0}},
            {"position": {"x": 0, "y": float("inf"), "z": 0}},
            {"position": {"x": 0, "y": 0, "z": float("nan")}},
        )
        base = json.loads(example_state().to_bytes())
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ProtocolError):
                decode_cv_state(json.dumps({**base, **mutation}).encode())
        for key in base:
            with self.subTest(missing=key), self.assertRaises(ProtocolError):
                decode_cv_state(json.dumps({name: value for name, value in base.items() if name != key}).encode())

    def test_lost_packets_cannot_contain_stale_position_action_or_confidence(self) -> None:
        state = example_state()
        for mutation in ({"tracking": False}, {"tracking": False, "position": None},
                         {"tracking": False, "position": None, "gesture": "UNKNOWN"}):
            with self.subTest(mutation=mutation), self.assertRaises(ProtocolError):
                replace(state, **mutation)

    def test_invalid_encoding_duplicate_keys_size_and_json_shape(self) -> None:
        for payload in (b"", b"\xff", b"null", b"[]", b"{", b"x" * (MAX_DATAGRAM_BYTES + 1),
                        example_state().to_bytes().replace(b'"version":1', b'"version":1,"version":1')):
            with self.subTest(payload=payload[:40]), self.assertRaises(ProtocolError):
                decode_cv_state(payload)

    def test_additive_unknown_fields_are_ignored(self) -> None:
        data = json.loads(example_state().to_bytes())
        data["future_metric"] = 10
        self.assertEqual(decode_cv_state(json.dumps(data).encode()), example_state())
        for value in (float("nan"), float("inf"), float("-inf")):
            data["future_metric"] = value
            with self.subTest(value=value), self.assertRaises(ProtocolError):
                decode_cv_state(json.dumps(data).encode())


class SenderTests(unittest.TestCase):
    """Deterministic monotonic pacing and recoverable socket-error behavior."""

    def setUp(self) -> None:
        self.factory_patch = patch("cv_engine.udp_sender.socket.socket")
        self.factory = self.factory_patch.start()
        self.addCleanup(self.factory_patch.stop)
        self.sock = self.factory.return_value
        self.sock.sendto.side_effect = lambda payload, destination: len(payload)
        self.sender = UdpSender("127.0.0.1", 5005, SenderSettings(), True).open()
        self.addCleanup(self.sender.close)

    def send(self, now: float) -> bool:
        """Submit representative fresh controls."""
        return self.sender.send(tracked_controls(), confirmed_gestures(), now)

    def test_first_send_immediate_then_rate_limit_without_sleep_or_queue(self) -> None:
        outcomes = [self.send(index / 120) for index in range(120)]
        self.assertTrue(outcomes[0])
        self.assertEqual(sum(outcomes), 30)
        self.assertEqual(self.sender.skipped, 90)
        packets = [decode_cv_state(call.args[0]) for call in self.sock.sendto.call_args_list]
        self.assertEqual([item.sequence for item in packets], list(range(30)))
        self.assertEqual(len({item.stream_id for item in packets}), 1)
        self.sock.setblocking.assert_called_once_with(False)

    def test_new_state_after_skips_is_sent_without_replaying_previous_position(self) -> None:
        self.send(0)
        self.assertFalse(self.sender.send(ControlResult(), GestureResult(), 0.01))
        self.assertTrue(self.sender.send(ControlResult(), GestureResult(), 0.04))
        packet = decode_cv_state(self.sock.sendto.call_args.args[0])
        self.assertFalse(packet.tracking)
        self.assertIsNone(packet.position)
        self.assertEqual(packet.sequence, 1)

    def test_slow_frames_do_not_trigger_catch_up_bursts(self) -> None:
        self.send(0)
        self.send(2)
        self.assertFalse(self.send(2))
        self.assertEqual(self.sender.sent, 2)

    def test_near_30_fps_camera_does_not_halve_send_rate(self) -> None:
        outcomes = [self.send(index / 30.1) for index in range(302)]
        self.assertGreaterEqual(sum(outcomes), 300)
        self.assertLessEqual(sum(outcomes), 301)

    def test_failures_are_paced_logged_sparingly_and_recover_with_sequence_gap(self) -> None:
        self.sock.sendto.side_effect = BlockingIOError("send buffer full")
        with self.assertLogs("motionplay.cv_engine.udp_sender", level="WARNING") as logs:
            for now in (0, 0.04, 0.08, 5.1):
                self.assertFalse(self.send(now))
        self.assertEqual(len(logs.output), 2)
        self.assertEqual(self.sender.failed, 4)
        self.sock.sendto.side_effect = lambda payload, destination: len(payload)
        with self.assertLogs("motionplay.cv_engine.udp_sender", level="INFO") as logs:
            self.assertTrue(self.send(5.2))
        self.assertIn("resumed", logs.output[0])
        self.assertEqual(decode_cv_state(self.sock.sendto.call_args.args[0]).sequence, 4)

    def test_terminal_lost_packet_bypasses_rate_once_and_close_is_idempotent(self) -> None:
        self.send(0)
        self.sender.close()
        self.sender.close()
        self.assertEqual(self.sock.sendto.call_count, 2)
        self.assertFalse(decode_cv_state(self.sock.sendto.call_args.args[0]).tracking)
        self.sock.close.assert_called_once()
        with self.assertRaises(UdpError):
            self.send(1)

    def test_final_send_failure_still_closes_socket(self) -> None:
        self.sock.sendto.side_effect = OSError("unavailable")
        with self.assertLogs("motionplay.cv_engine.udp_sender", level="WARNING"):
            self.sender.close()
        self.sock.close.assert_called_once()

    def test_invalid_clock_is_rejected(self) -> None:
        self.send(1)
        for now in (0.9, float("nan"), float("inf")):
            with self.subTest(now=now), self.assertRaises(ValueError):
                self.send(now)

    def test_initialization_failure_closes_partially_open_socket(self) -> None:
        self.sender.close()
        self.sock.reset_mock()
        self.sock.setblocking.side_effect = OSError("not allowed")
        with self.assertRaisesRegex(UdpError, "--no-udp"):
            UdpSender("127.0.0.1", 5005, SenderSettings(), True).open()
        self.sock.close.assert_called_once()

    def test_new_runs_have_distinct_stream_ids(self) -> None:
        other = UdpSender("127.0.0.1", 5005, SenderSettings(), False)
        self.assertNotEqual(self.sender.stream_id, other.stream_id)


class ConfigurationTests(unittest.TestCase):
    """Load send settings before opening devices/sockets."""

    def test_defaults_overrides_and_invalid_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            self.assertEqual(load_settings(path, environ={}).sender, SenderSettings())
            settings = load_settings(path, environ={"CONTROL_HAND": "LEFT", "UDP_SEND_FPS": "20"})
            self.assertEqual(settings.sender, SenderSettings(20, "left"))
            for key, value in (
                ("CONTROL_HAND", "both"), ("UDP_SEND_FPS", "0"), ("UDP_SEND_FPS", "121"),
                ("UDP_SEND_FPS", "nan"), ("UDP_HOST", "localhost"), ("UDP_HOST", "::1"),
                ("UDP_HOST", "0.0.0.0"), ("UDP_HOST", "224.0.0.1"), ("UDP_HOST", "255.255.255.255"),
            ):
                with self.subTest(key=key, value=value), self.assertRaises(ConfigurationError):
                    load_settings(path, environ={key: value})


class LoopbackTests(unittest.TestCase):
    """Use real OS UDP sockets with an ephemeral port; no webcam needed."""

    def test_real_loopback_receives_tracked_lost_and_terminal_packets(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind(("127.0.0.1", 0))
            receiver.settimeout(2)
            with UdpSender("127.0.0.1", receiver.getsockname()[1], SenderSettings(), True) as sender:
                self.assertTrue(sender.send(tracked_controls(), confirmed_gestures(), 0))
                self.assertTrue(decode_cv_state(receiver.recv(1201)).tracking)
                self.assertTrue(sender.send(ControlResult(), GestureResult(), 0.04))
                self.assertFalse(decode_cv_state(receiver.recv(1201)).tracking)
            terminal = decode_cv_state(receiver.recv(1201))
            self.assertEqual(terminal.sequence, 2)
            self.assertFalse(terminal.tracking)

    @patch("cv_engine.controller.perf_counter", side_effect=[0, 0, 0.04, 0.08, 0.12, 0.16, 0.20])
    @patch("cv_engine.hand_tracker.HandTracker")
    @patch("cv_engine.camera.Camera")
    def test_controller_transmits_confirmed_gesture_and_clears_loss(
        self, camera_factory: MagicMock, tracker_factory: MagicMock, clock: MagicMock,
    ) -> None:
        camera_factory.return_value.__enter__.return_value.read.return_value = np.zeros((480, 640, 3), np.uint8)
        hand = gesture_hand(Gesture.OPEN_HAND, image_aspect_ratio=4 / 3)
        observations = TrackingResult((hand,), 1)
        tracker_factory.return_value.__enter__.return_value.process.side_effect = [observations] * 5 + [TrackingResult((), 1)]
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind(("127.0.0.1", 0))
            receiver.settimeout(2)
            with tempfile.TemporaryDirectory() as directory:
                settings = load_settings(Path(directory) / ".env", environ={
                    "CV_TO_UNITY_PORT": str(receiver.getsockname()[1]), "UNITY_TO_PYTHON_PORT": "1024",
                })
            self.assertEqual(run_tracking(settings, show_preview=False, max_frames=6), 6)
            packets = [decode_cv_state(receiver.recv(1201)) for _ in range(7)]
        self.assertEqual(packets[0].gesture, "UNKNOWN")
        self.assertEqual(packets[4].gesture, "OPEN_HAND")
        self.assertFalse(packets[5].tracking)
        self.assertFalse(packets[6].tracking)
        self.assertEqual([packet.sequence for packet in packets], list(range(7)))
        camera_factory.return_value.__exit__.assert_called_once()
        tracker_factory.return_value.__exit__.assert_called_once()


class MonitorTests(unittest.TestCase):
    """Check diagnostic CLI validation, output, and bind failures."""

    @patch("app.udp_monitor.load_settings")
    @patch("app.udp_monitor.socket.socket")
    @patch("builtins.print")
    def test_monitor_rejects_bad_packet_then_prints_valid_one(
        self, output: MagicMock, socket_factory: MagicMock, load: MagicMock,
    ) -> None:
        load.return_value.cv_to_unity_port = 5005
        receiver = socket_factory.return_value.__enter__.return_value
        receiver.recvfrom.side_effect = [(b"invalid", ("127.0.0.1", 1234)), (example_state().to_bytes(), ("127.0.0.1", 1234))]
        self.assertEqual(monitor_main(["--max-packets", "1"]), 0)
        receiver.bind.assert_called_once_with(("127.0.0.1", 5005))
        self.assertIn(example_state().to_bytes().decode(), [call.args[0] for call in output.call_args_list])

    @patch("app.udp_monitor.load_settings")
    @patch("app.udp_monitor.socket.socket")
    @patch("builtins.print")
    def test_monitor_bind_error_and_idle_timeout_return_one(
        self, output: MagicMock, socket_factory: MagicMock, load: MagicMock,
    ) -> None:
        load.return_value.cv_to_unity_port = 5005
        receiver = socket_factory.return_value.__enter__.return_value
        receiver.bind.side_effect = OSError("port in use")
        self.assertEqual(monitor_main([]), 1)
        receiver.bind.side_effect = None
        receiver.recvfrom.side_effect = socket.timeout()
        self.assertEqual(monitor_main([]), 1)


if __name__ == "__main__":
    unittest.main()
