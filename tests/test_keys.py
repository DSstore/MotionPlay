"""Test the console stop key and its use by the headless (no preview) engine loop."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from cv_engine.controller import run_tracking
from cv_engine.keys import stop_requested
from shared.config import load_settings
from tests.test_coordinates import frame, hand


class FakeConsole:
    """Stands in for msvcrt: a queue of pending key presses."""

    def __init__(self, *keys: str, fail: bool = False) -> None:
        self.keys = list(keys)
        self.fail = fail

    def kbhit(self) -> bool:
        if self.fail:
            raise OSError("no console")
        return bool(self.keys)

    def getwch(self) -> str:
        return self.keys.pop(0)


class StopKeyTests(unittest.TestCase):
    def test_q_in_either_case_and_escape_stop(self) -> None:
        for key in ("q", "Q", "\x1b"):
            with self.subTest(key=key):
                self.assertTrue(stop_requested(FakeConsole(key)))

    def test_other_keys_and_no_keys_do_not_stop(self) -> None:
        self.assertFalse(stop_requested(FakeConsole()))
        self.assertFalse(stop_requested(FakeConsole("a", " ", "\r", "Z")))

    def test_every_pending_key_is_read_and_discarded(self) -> None:
        console = FakeConsole("a", "q", "b")
        self.assertTrue(stop_requested(console))
        self.assertEqual([], console.keys)
        self.assertFalse(stop_requested(console))  # nothing left over to trigger a second stop

    def test_the_second_half_of_a_function_key_is_not_a_stop_key(self) -> None:
        # An arrow or function key arrives as a prefix plus a code that can equal a letter.
        self.assertFalse(stop_requested(FakeConsole("\xe0", "q")))
        self.assertFalse(stop_requested(FakeConsole("\x00", "Q")))
        self.assertTrue(stop_requested(FakeConsole("\xe0", "H", "q")))

    def test_a_missing_console_never_stops_or_raises(self) -> None:
        self.assertFalse(stop_requested(FakeConsole("q", fail=True)))

    def test_platforms_without_msvcrt_return_false(self) -> None:
        with patch.dict(sys.modules, {"msvcrt": None}):
            self.assertFalse(stop_requested())


class ControllerStopTests(unittest.TestCase):
    def run_loop(self, preview: bool, stops: list[bool], frames: int):
        with tempfile.TemporaryDirectory() as directory:
            settings = load_settings(Path(directory) / ".env", environ={})
        patches = (patch("cv_engine.preview.Preview"), patch("cv_engine.hand_tracker.HandTracker"),
                   patch("cv_engine.camera.Camera"), patch("cv_engine.keys.stop_requested", side_effect=stops))
        preview_factory, tracker_factory, camera_factory, keys = (p.start() for p in patches)
        for p in patches:
            self.addCleanup(p.stop)
        camera_factory.return_value.__enter__.return_value.read.return_value = np.zeros((4, 6, 3), dtype=np.uint8)
        tracker_factory.return_value.__enter__.return_value.process.side_effect = [frame(hand())] * frames
        preview_factory.return_value.__enter__.return_value.show.return_value = True
        return run_tracking(settings, show_preview=preview, max_frames=frames, send_udp=False), keys

    def test_headless_loop_stops_on_the_key_and_says_how(self) -> None:
        with self.assertLogs("motionplay.cv_engine.controller", level="INFO") as logs:
            processed, keys = self.run_loop(preview=False, stops=[False, False, True], frames=10)
        self.assertEqual(3, processed)  # stopped on the third check, well before max_frames
        self.assertEqual(3, keys.call_count)
        text = "\n".join(logs.output)
        self.assertIn("press Q or Esc", text)
        self.assertIn("Stop key pressed", text)

    def test_headless_loop_runs_to_its_limit_without_the_key(self) -> None:
        processed, keys = self.run_loop(preview=False, stops=[False] * 4, frames=4)
        self.assertEqual(4, processed)

    def test_the_console_is_not_polled_when_a_preview_window_owns_the_keyboard(self) -> None:
        processed, keys = self.run_loop(preview=True, stops=[], frames=3)
        self.assertEqual(3, processed)
        keys.assert_not_called()


if __name__ == "__main__":
    unittest.main()
