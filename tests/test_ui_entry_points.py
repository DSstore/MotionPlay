"""Test the dashboard's save dialog, run loop and command line, and the OpenCV preview window's behavior.

Qt runs offscreen; OpenCV window calls are replaced, so no display or camera is needed.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
from PyQt6.QtWidgets import QApplication, QDialog

from app import dashboard
from app.dashboard import DashboardWindow, LoginDialog
from backend.auth import UserStore
from backend.storage import SqliteResultStore, StorageError
from cv_engine import preview
from cv_engine.models import (ControlPosition, ControlResult, Gesture, GestureResult, HandControl,
                              HandGesture, Landmark, TrackedHand, TrackingResult)
from shared.config import ConfigurationError
from tests.test_results import make_result

APP = QApplication.instance() or QApplication([])


class DashboardFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "m.db"
        self.users = UserStore(self.path, rounds=4)
        self.addCleanup(self.users.close)
        self.store = SqliteResultStore(self.path)
        self.addCleanup(self.store.close)
        self.alice = self.users.create_user("alice", "alice-password")

    def window(self) -> DashboardWindow:
        window = DashboardWindow(self.store, self.alice, refresh_ms=0)
        self.addCleanup(window.close)
        return window


class DashboardExportDialogTests(DashboardFixture):
    def test_a_chosen_file_is_exported(self) -> None:
        self.store.save(make_result(), self.alice.user_id)
        window = self.window()
        target = Path(self.folder.name) / "out.pdf"
        with patch("app.dashboard.DEFAULT_REPORT_DIR", Path(self.folder.name) / "reports"), \
                patch("app.dashboard.QFileDialog.getSaveFileName", return_value=(str(target), "PDF files (*.pdf)")) as ask:
            window._choose_and_export()
        self.assertTrue(target.read_bytes().startswith(b"%PDF"))
        self.assertIn("Report saved", window.status_label.text())
        self.assertTrue((Path(self.folder.name) / "reports").is_dir())  # the suggested folder is created
        self.assertIn("alice", ask.call_args.args[2])  # the suggested name mentions the player

    def test_cancelling_the_dialog_writes_nothing(self) -> None:
        window = self.window()
        with patch("app.dashboard.DEFAULT_REPORT_DIR", Path(self.folder.name) / "reports"), \
                patch("app.dashboard.QFileDialog.getSaveFileName", return_value=("", "")), \
                patch.object(window, "export_report") as export:
            window._choose_and_export()
        export.assert_not_called()

    def test_a_player_with_no_rounds_gets_a_message_not_a_file(self) -> None:
        window = self.window()
        target = Path(self.folder.name) / "none.pdf"
        self.assertFalse(window.export_report(target))
        self.assertIn("Report not saved", window.status_label.text())
        self.assertFalse(target.exists())

    def test_a_storage_failure_while_exporting_is_reported(self) -> None:
        window = self.window()
        self.store.close()
        self.assertFalse(window.export_report(Path(self.folder.name) / "x.pdf"))
        self.assertIn("Report not saved", window.status_label.text())


class LoginStorageErrorTests(DashboardFixture):
    def test_a_storage_error_while_creating_an_account_is_shown(self) -> None:
        dialog = LoginDialog(self.users)
        dialog.mode_button.click()
        dialog.username_edit.setText("carol")
        dialog.password_edit.setText("carol-password")
        dialog.repeat_edit.setText("carol-password")
        with patch.object(self.users, "create_user", side_effect=StorageError("database is locked")):
            dialog.primary_button.click()
        self.assertIn("database is locked", dialog.error_label.text())
        self.assertIsNone(dialog.user)
        self.assertNotEqual(QDialog.DialogCode.Accepted, dialog.result())


class DashboardTimerTests(DashboardFixture):
    def test_the_refresh_timer_runs_only_when_asked_and_stops_on_close(self) -> None:
        manual = self.window()
        self.assertFalse(manual.timer.isActive())
        timed = DashboardWindow(self.store, self.alice, refresh_ms=5000)
        self.addCleanup(timed.close)
        self.assertTrue(timed.timer.isActive())
        timed.close()
        self.assertFalse(timed.timer.isActive())


class DashboardRunTests(unittest.TestCase):
    def test_quitting_the_login_returns_zero_without_a_window(self) -> None:
        with patch("app.dashboard.LoginDialog") as dialog_class, patch("app.dashboard.DashboardWindow") as window_class:
            dialog_class.return_value.exec.return_value = QDialog.DialogCode.Rejected
            self.assertEqual(0, dashboard.run(MagicMock(), MagicMock(), MagicMock()))
        window_class.assert_not_called()

    def test_log_out_returns_to_the_login_and_quit_ends_the_loop(self) -> None:
        user = MagicMock()
        first, second = MagicMock(logged_out=True), MagicMock(logged_out=False)
        app = MagicMock()
        with patch("app.dashboard.LoginDialog") as dialog_class, \
                patch("app.dashboard.DashboardWindow", side_effect=[first, second]) as window_class:
            dialog_class.return_value.exec.return_value = QDialog.DialogCode.Accepted
            dialog_class.return_value.user = user
            self.assertEqual(0, dashboard.run(MagicMock(), MagicMock(), app))
        self.assertEqual(2, window_class.call_count)  # logged in twice: once after logging out
        self.assertEqual(2, app.exec.call_count)
        first.show.assert_called_once()

    def test_an_accepted_dialog_without_a_user_ends_the_loop(self) -> None:
        with patch("app.dashboard.LoginDialog") as dialog_class:
            dialog_class.return_value.exec.return_value = QDialog.DialogCode.Accepted
            dialog_class.return_value.user = None
            self.assertEqual(0, dashboard.run(MagicMock(), MagicMock(), MagicMock()))


class DashboardMainTests(unittest.TestCase):
    def run_main(self, argv, **patches):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        mocks = {name: stack.enter_context(patch(f"app.dashboard.{name}", **options))
                 for name, options in patches.items()}
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = dashboard.main(argv)
        return code, err.getvalue(), mocks

    def test_opens_the_store_and_accounts_runs_and_closes_both(self) -> None:
        store, users = MagicMock(), MagicMock()
        code, _err, mocks = self.run_main(
            [], load_settings={"return_value": MagicMock()}, store_from_args={"return_value": store},
            open_users={"return_value": users}, run={"return_value": 0})
        self.assertEqual(0, code)
        self.assertEqual("sqlite", mocks["store_from_args"].call_args.args[0])  # the dashboard defaults to SQLite
        store.close.assert_called_once()
        users.close.assert_called_once()

    def test_errors_are_reported_and_resources_still_closed(self) -> None:
        store = MagicMock()
        for error in (ConfigurationError("bad .env"), StorageError("disk full"), OSError("no such file")):
            with self.subTest(error=type(error).__name__):
                store.reset_mock()
                code, err, _mocks = self.run_main(
                    [], load_settings={"return_value": MagicMock()}, store_from_args={"return_value": store},
                    open_users={"side_effect": error}, run={"return_value": 0})
                self.assertEqual(1, code)
                self.assertIn("Dashboard error", err)
                store.close.assert_called_once()


def blank(width=64, height=48) -> np.ndarray:
    return np.zeros((height, width, 3), dtype=np.uint8)


def hand(label="right", confidence=0.9) -> TrackedHand:
    return TrackedHand(label, confidence, tuple(Landmark(0.5, 0.5, 0.0) for _ in range(21)))


class OverlayTextTests(unittest.TestCase):
    """draw_overlay is exercised through the text it would print, captured from cv2.putText."""

    def rows(self, result, controls=None, gestures=None) -> list[str]:
        with patch("cv_engine.preview.cv2.putText") as put:
            preview.draw_overlay(blank(), result, 30.0, controls, gestures)
        return [call.args[1] for call in put.call_args_list][::2]  # each row is drawn twice (outline, fill)

    def test_status_line_for_no_hand_and_for_a_labelled_hand(self) -> None:
        self.assertIn("No hand detected", self.rows(TrackingResult((), 5.0))[0])
        self.assertIn("right (label 0.90)", self.rows(TrackingResult((hand(),), 5.0))[0])

    def test_no_accepted_hand_and_lost_states_are_explained(self) -> None:
        empty = ControlResult(())
        self.assertIn("Control: no accepted hand", self.rows(TrackingResult((), 5.0), empty))
        lost = ControlResult((HandControl("right", "temporarily_lost"),))
        self.assertIn("right control: temporarily lost", self.rows(TrackingResult((), 5.0), lost))

    def test_a_tracked_hand_shows_its_coordinates_and_markers(self) -> None:
        tracked = ControlResult((HandControl("right", "tracking", 0.9, ControlPosition(0.4, 0.5, 0),
                                             ControlPosition(0.41, 0.5, 0)),))
        with patch("cv_engine.preview.cv2.drawMarker") as marker:
            rows = self.rows(TrackingResult((hand(),), 5.0), tracked)
        self.assertIn("right control: x=0.410 y=0.500", rows)
        marker.assert_called_once()

    def test_gesture_rows_cover_tracked_and_unavailable_hands(self) -> None:
        gestures = GestureResult((
            HandGesture("right", True, Gesture.FIST, Gesture.FIST, 5, False),
            HandGesture("left"),
        ))
        rows = self.rows(TrackingResult((hand(),), 5.0), None, gestures)
        self.assertTrue(any(r.startswith("right gesture: FIST") for r in rows))
        self.assertIn("left gesture: UNKNOWN (tracking unavailable)", rows)

    def test_the_captured_frame_is_never_modified_and_bad_landmarks_are_skipped(self) -> None:
        frame = blank()
        broken = TrackedHand("right", 0.9, (Landmark(float("nan"), 0, 0),) * 21)
        short = TrackedHand("left", 0.9, (Landmark(0.5, 0.5, 0),) * 3)
        canvas = preview.draw_overlay(frame, TrackingResult((broken, short), 1.0), 10.0)
        self.assertFalse(frame.any())
        self.assertIsNot(canvas, frame)


class PreviewWindowTests(unittest.TestCase):
    def test_a_missing_display_is_a_clear_error_on_linux(self) -> None:
        with patch("cv_engine.preview.sys.platform", "linux"), patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(preview.PreviewError) as raised:
                preview.Preview().__enter__()
        self.assertIn("--no-preview", str(raised.exception))

    def test_a_window_that_cannot_open_is_a_clear_error(self) -> None:
        with patch("cv_engine.preview.sys.platform", "win32"), \
                patch("cv_engine.preview.cv2.namedWindow", side_effect=cv2.error("no gui")):
            with self.assertRaises(preview.PreviewError):
                preview.Preview().__enter__()

    def shown(self, key: int, visible: float = 1.0) -> bool:
        window = preview.Preview()
        with patch("cv_engine.preview.cv2.imshow"), patch("cv_engine.preview.cv2.waitKey", return_value=key), \
                patch("cv_engine.preview.cv2.getWindowProperty", return_value=visible):
            return window.show(blank(), TrackingResult((), 1.0), 30.0)

    def test_q_and_escape_ask_for_a_stop(self) -> None:
        for key in (ord("q"), ord("Q"), 27):
            with self.subTest(key=key):
                self.assertFalse(self.shown(key))

    def test_other_keys_keep_running_while_the_window_is_visible(self) -> None:
        self.assertTrue(self.shown(255))  # no key pressed (waitKey reports 255 after masking)
        self.assertTrue(self.shown(ord("a")))

    def test_closing_the_window_asks_for_a_stop(self) -> None:
        self.assertFalse(self.shown(255, visible=0.0))

    def test_a_rendering_failure_is_a_preview_error(self) -> None:
        window = preview.Preview()
        with patch("cv_engine.preview.cv2.imshow", side_effect=cv2.error("gone")):
            with self.assertRaises(preview.PreviewError):
                window.show(blank(), TrackingResult((), 1.0), 30.0)

    def test_close_destroys_only_an_opened_window_and_survives_a_native_error(self) -> None:
        window = preview.Preview()
        with patch("cv_engine.preview.cv2.destroyWindow") as destroy:
            window.close()
            destroy.assert_not_called()  # never opened
        window._opened = True
        with patch("cv_engine.preview.cv2.destroyWindow", side_effect=cv2.error("already closed")):
            window.close()  # must not raise
        self.assertFalse(window._opened)


if __name__ == "__main__":
    unittest.main()
