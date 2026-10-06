"""Test Phase 17: log setup, uncaught-error recording, account/result/startup log events, and the error dialog."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import contextlib
import io
import logging
import platform
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
from PyQt6.QtWidgets import QApplication

from app import dashboard
from backend.auth import AccountLocked, InvalidCredentials, UserStore
from backend.result_receiver import ResultReceiver
from backend.storage import SqliteResultStore, StorageError
from cv_engine.camera import SLOW_OPEN_SECONDS, Camera
from cv_engine.controller import run_tracking
from shared import logger as motionplay_logging
from shared.config import load_settings
from tests.test_coordinates import frame, hand
from tests.test_results import make_result

ROOT = Path(__file__).resolve().parents[1]
APP = QApplication.instance() or QApplication([])


def close_handlers(logger: logging.Logger) -> None:
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    logger.addHandler(logging.NullHandler())


class LoggingTestCase(unittest.TestCase):
    """Give each test its own log folder and put global state (handlers, hooks) back afterwards."""

    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.saved_hooks = (sys.excepthook, threading.excepthook)
        self.addCleanup(self.restore_hooks)
        self.addCleanup(close_handlers, logging.getLogger("motionplay"))
        self.settings = load_settings(Path(self.folder.name) / ".env", environ={"LOG_DIR": self.folder.name})

    def restore_hooks(self) -> None:
        motionplay_logging.remove_excepthooks()
        sys.excepthook, threading.excepthook = self.saved_hooks

    def log_text(self) -> str:
        for handler in logging.getLogger("motionplay").handlers:
            handler.flush()
        path = Path(self.folder.name) / "motionplay.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""


class SetupTests(LoggingTestCase):
    def test_console_can_be_left_out(self) -> None:
        both = motionplay_logging.configure_logging(self.settings)
        self.assertEqual(2, len(both.handlers))
        quiet = motionplay_logging.configure_logging(self.settings, console=False)
        self.assertEqual(1, len(quiet.handlers))
        self.assertIsInstance(quiet.handlers[0], logging.FileHandler)

    def test_start_up_line_names_the_run_and_never_leaks_credentials(self) -> None:
        settings = load_settings(Path(self.folder.name) / ".env", environ={
            "LOG_DIR": self.folder.name, "MONGODB_URI": "mongodb://dbuser:s3cretpass@db.example:27017"})
        motionplay_logging.start_logging(settings, "test component", console=False)
        text = self.log_text()
        self.assertIn("MotionPlay test component starting", text)
        self.assertIn(f"pid {os.getpid()}", text)
        self.assertIn(f"Python {platform.python_version()}", text)
        self.assertIn("motionplay.log", text)
        self.assertNotIn("s3cretpass", text)
        self.assertNotIn("dbuser", text)

    def test_unconfigured_use_is_silent(self) -> None:
        code = ("import shared, logging; logging.getLogger('motionplay.demo').warning('should stay quiet'); "
                "logging.getLogger('motionplay.demo').error('and this')")
        done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual("", done.stderr)
        self.assertEqual("", done.stdout)


class ExceptionHookTests(LoggingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.passed_on: list = []
        sys.excepthook = lambda *info: self.passed_on.append(info)       # stands in for the usual hook
        threading.excepthook = lambda args: self.passed_on.append(args)
        motionplay_logging.start_logging(self.settings, "hook test", console=False)

    def test_an_uncaught_error_is_logged_with_its_traceback_and_still_passed_on(self) -> None:
        try:
            raise ValueError("boom in the main thread")
        except ValueError:
            sys.excepthook(*sys.exc_info())
        text = self.log_text()
        self.assertIn("CRITICAL", text)
        self.assertIn("Uncaught ValueError: boom in the main thread", text)
        self.assertIn("Traceback (most recent call last)", text)
        self.assertEqual(1, len(self.passed_on))

    def test_ctrl_c_and_exit_are_not_logged_as_crashes(self) -> None:
        sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
        sys.excepthook(SystemExit, SystemExit(0), None)
        self.assertNotIn("CRITICAL", self.log_text())
        self.assertEqual(2, len(self.passed_on))

    def test_an_error_in_another_thread_is_logged_with_the_thread_name(self) -> None:
        def explode() -> None:
            raise RuntimeError("boom in a worker")

        worker = threading.Thread(target=explode, name="worker-7")
        worker.start()
        worker.join()
        text = self.log_text()
        self.assertIn("Uncaught RuntimeError in thread worker-7: boom in a worker", text)

    def test_installing_twice_logs_each_error_once(self) -> None:
        motionplay_logging.start_logging(self.settings, "hook test again", console=False)
        try:
            raise KeyError("only once")
        except KeyError:
            sys.excepthook(*sys.exc_info())
        self.assertEqual(1, self.log_text().count("Uncaught KeyError"))
        self.assertEqual(1, len(self.passed_on))

    def test_removing_the_hooks_restores_the_originals(self) -> None:
        before = (sys.excepthook, threading.excepthook)
        self.assertIsNot(sys.excepthook, self.saved_hooks[0])
        motionplay_logging.remove_excepthooks()
        self.assertIsNot(sys.excepthook, before[0])
        self.assertTrue(callable(sys.excepthook) and callable(threading.excepthook))


class AccountLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.now = [1000.0]
        self.users = UserStore(Path(self.folder.name) / "u.db", rounds=4, clock=lambda: self.now[0],
                               max_attempts=2, lockout_seconds=60)
        self.addCleanup(self.users.close)

    def test_creating_and_logging_in_are_recorded(self) -> None:
        with self.assertLogs("motionplay.backend.auth", level="INFO") as logs:
            self.users.create_user("alice", "alice-password")
            self.users.authenticate("alice", "alice-password")
        text = "\n".join(logs.output)
        self.assertIn("Player account created: alice", text)
        self.assertIn("Login: alice", text)
        self.assertNotIn("alice-password", text)

    def test_wrong_passwords_and_the_lockout_are_recorded_without_the_password(self) -> None:
        self.users.create_user("alice", "alice-password")
        with self.assertLogs("motionplay.backend.auth", level="WARNING") as logs:
            with self.assertRaises(InvalidCredentials):
                self.users.authenticate("alice", "guess-number-one")
            with self.assertRaises(InvalidCredentials):
                self.users.authenticate("alice", "guess-number-two")
            with self.assertRaises(AccountLocked):
                self.users.authenticate("alice", "alice-password")
        text = "\n".join(logs.output)
        self.assertIn("Login failed for alice: wrong password (attempt 1 of 2)", text)
        self.assertIn("account locked for 60 s", text)
        self.assertIn("Login refused: alice is locked", text)
        self.assertNotIn("guess-number", text)

    def test_an_unknown_name_is_not_written_to_the_log(self) -> None:
        with self.assertLogs("motionplay.backend.auth", level="WARNING") as logs:
            with self.assertRaises(InvalidCredentials):
                self.users.authenticate("hunter2-typed-in-the-wrong-box", "x")
        text = "\n".join(logs.output)
        self.assertIn("no such account", text)
        self.assertNotIn("hunter2", text)

    def test_a_password_change_is_recorded(self) -> None:
        self.users.create_user("alice", "alice-password")
        with self.assertLogs("motionplay.backend.auth", level="INFO") as logs:
            self.users.change_password("alice", "alice-password", "a-new-password")
        self.assertIn("Password changed for alice", "\n".join(logs.output))


class ReceiverLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = SqliteResultStore(Path(self.folder.name) / "m.db")
        self.addCleanup(self.store.close)

    def test_a_stored_result_logs_what_it_was(self) -> None:
        with self.assertLogs("motionplay.backend.result_receiver", level="INFO") as logs:
            ResultReceiver(self.store).handle(make_result(difficulty="level_4").to_bytes())
        text = "\n".join(logs.output)
        self.assertIn("stored (reach_garden, level_4, 6 of 8 watered)", text)

    def test_a_rejected_datagram_logs_the_size_and_reason_but_not_its_content(self) -> None:
        payload = b'{"secret": "do-not-log-me"}'
        with self.assertLogs("motionplay.backend.result_receiver", level="WARNING") as logs:
            ResultReceiver(self.store).handle(payload)
        text = "\n".join(logs.output)
        self.assertIn(f"Rejected an invalid SESSION_END datagram ({len(payload)} bytes)", text)
        self.assertNotIn("do-not-log-me", text)

    def test_a_flood_of_bad_datagrams_cannot_flood_the_log(self) -> None:
        now = [0.0]
        receiver = ResultReceiver(self.store, clock=lambda: now[0])
        with self.assertLogs("motionplay.backend.result_receiver", level="WARNING") as logs:
            for _ in range(200):
                receiver.handle(b"junk")
            self.assertEqual(5, len(logs.output))  # only the first few in this minute are written
            now[0] = 61.0
            receiver.handle(b"junk")  # a new minute: the earlier flood is summarised, then logging resumes
        text = "\n".join(logs.output)
        self.assertIn("195 more invalid datagram(s) in the last minute were not logged one by one", text)
        self.assertEqual(7, len(logs.output))

    def test_a_quiet_receiver_logs_every_bad_datagram_it_gets(self) -> None:
        receiver = ResultReceiver(self.store, clock=lambda: 0.0)
        with self.assertLogs("motionplay.backend.result_receiver", level="WARNING") as logs:
            for _ in range(5):
                receiver.handle(b"junk")
        self.assertEqual(5, len(logs.output))

    def test_an_unexpected_store_error_is_logged_and_the_receiver_keeps_working(self) -> None:
        flaky = MagicMock()
        flaky.save.side_effect = [RuntimeError("driver exploded"), True]
        receiver = ResultReceiver(flaky)
        with self.assertLogs("motionplay.backend.result_receiver", level="ERROR") as logs:
            first = receiver.handle(make_result().to_bytes())
        self.assertIn(b"error", first)
        self.assertIn("unexpected error", "\n".join(logs.output))
        self.assertIn("driver exploded", "\n".join(logs.output))  # the traceback is in the log record
        second = receiver.handle(make_result().to_bytes())
        self.assertIn(b"stored", second)

    def test_a_known_storage_error_is_still_an_error_ack(self) -> None:
        failing = MagicMock()
        failing.save.side_effect = StorageError("disk full")
        with self.assertLogs("motionplay.backend.result_receiver", level="ERROR"):
            reply = ResultReceiver(failing).handle(make_result().to_bytes())
        self.assertIn(b"error", reply)


class EngineLogTests(unittest.TestCase):
    def run_loop(self, frames: int):
        with tempfile.TemporaryDirectory() as directory:
            settings = load_settings(Path(directory) / ".env", environ={})
        with patch("cv_engine.hand_tracker.HandTracker") as tracker_factory, patch("cv_engine.camera.Camera") as camera_factory:
            camera_factory.return_value.__enter__.return_value.read.return_value = np.zeros((4, 6, 3), dtype=np.uint8)
            tracker_factory.return_value.__enter__.return_value.process.side_effect = (
                [frame(hand()), frame(hand()), frame(), frame(hand())][:frames])
            with self.assertLogs("motionplay.cv_engine.controller", level="INFO") as logs:
                run_tracking(settings, show_preview=False, max_frames=frames, send_udp=False)
        return "\n".join(logs.output)

    def test_the_run_logs_its_settings_and_a_summary(self) -> None:
        text = self.run_loop(4)
        self.assertIn("Settings: camera 0 requested 640x480", text)
        self.assertIn("control hand right", text)
        self.assertIn("Tracking finished after 4 frame(s) in", text)
        self.assertIn("hand lost 1 time(s)", text)
        self.assertIn("0 label correction(s)", text)

    def test_the_summary_counts_a_lost_hand_each_time_it_is_lost(self) -> None:
        self.assertIn("hand lost 0 time(s)", self.run_loop(2))


class SlowCameraTests(unittest.TestCase):
    def open_with_clock(self, elapsed: float):
        with tempfile.TemporaryDirectory() as directory:
            settings = load_settings(Path(directory) / ".env", environ={})
        capture = MagicMock()
        capture.isOpened.return_value = True
        capture.get.return_value = 30.0
        ticks = iter([100.0, 100.0 + elapsed, 200.0, 300.0])
        with patch("cv_engine.camera.cv2.VideoCapture", return_value=capture), \
                patch("cv_engine.camera.time.perf_counter", side_effect=lambda: next(ticks)), \
                self.assertLogs("motionplay.cv_engine.camera", level="INFO") as logs:
            Camera(settings.camera).open()
        return logs.records

    def test_a_normal_start_is_info_and_a_slow_start_is_a_warning_that_explains_itself(self) -> None:
        fast = self.open_with_clock(1.2)
        self.assertEqual("INFO", fast[-1].levelname)
        self.assertIn("took 1.2 s", fast[-1].getMessage())
        slow = self.open_with_clock(SLOW_OPEN_SECONDS + 15)
        self.assertEqual("WARNING", slow[-1].levelname)
        self.assertIn("took 20.0 s", slow[-1].getMessage())
        self.assertIn("Ctrl+C", slow[-1].getMessage())


class ErrorDialogTests(LoggingTestCase):
    def test_an_unexpected_error_shows_a_message_box_after_the_usual_handling(self) -> None:
        seen = []
        sys.excepthook = lambda *info: seen.append(info)
        dashboard.install_error_dialog(Path("logs") / "motionplay.log")
        with patch("app.dashboard.QMessageBox.critical") as box:
            sys.excepthook(ValueError, ValueError("the cause"), None)
        self.assertEqual(1, len(seen))  # the earlier hook (which logs) ran first
        title, text = box.call_args.args[1:3]
        self.assertEqual("MotionPlay", title)
        self.assertIn("the cause", text)
        self.assertIn("motionplay.log", text)

    def test_ctrl_c_shows_no_dialog_and_a_failing_dialog_never_raises(self) -> None:
        sys.excepthook = lambda *info: None
        dashboard.install_error_dialog(Path("logs") / "motionplay.log")
        with patch("app.dashboard.QMessageBox.critical") as box:
            sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
        box.assert_not_called()
        with patch("app.dashboard.QMessageBox.critical", side_effect=RuntimeError("no display")):
            sys.excepthook(ValueError, ValueError("x"), None)  # must not raise


class EntryPointLoggingTests(unittest.TestCase):
    def test_the_receiver_logs_to_the_file_not_only_the_console(self) -> None:
        from backend import result_receiver

        with patch("backend.result_receiver.start_logging") as start, \
                patch("backend.result_receiver.serve", return_value=0), \
                patch("backend.result_receiver.store_from_args", return_value=MagicMock()):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, result_receiver.main(["--port", "40123"]))
        self.assertEqual("result receiver", start.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
