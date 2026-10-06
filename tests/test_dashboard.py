"""Test dashboard numbers (no Qt) and the login and dashboard windows (Qt offscreen, no display needed)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QDialog

from app import dashboard_model as model
from app.dashboard import DashboardWindow, LoginDialog
from backend.auth import UserStore
from backend.storage import SqliteResultStore
from tests.test_results import make_result

APP = QApplication.instance() or QApplication([])


def document(**changes) -> dict:
    return {**make_result(**changes).to_document(), "user_id": None}


class ModelTests(unittest.TestCase):
    def test_empty_summary_has_no_values(self) -> None:
        summary = model.summarize([])
        self.assertEqual(0, summary.rounds)
        self.assertIsNone(summary.accuracy)
        self.assertIsNone(summary.average_reaction)
        self.assertIsNone(summary.last_played)
        self.assertEqual(0, summary.best_streak)

    def test_summary_totals_and_averages(self) -> None:
        a = document(targetsAttempted=8, targetsCompleted=6, score=6, bestStreak=4, currentStreak=1,
                     averageReactionTime=0.4, duration=60.0, endedAt=1770000100000)
        b = document(targetsAttempted=8, targetsCompleted=2, score=2, bestStreak=2, currentStreak=0,
                     averageReactionTime=0.8, duration=30.0, endedAt=1770000200000)
        summary = model.summarize([a, b])
        self.assertEqual(2, summary.rounds)
        self.assertAlmostEqual(0.5, summary.accuracy)  # 8 of 16 flowers overall, not the mean of round rates
        self.assertEqual(4, summary.best_streak)
        self.assertAlmostEqual(0.6, summary.average_reaction)
        self.assertEqual(90.0, summary.total_seconds)
        self.assertEqual(1770000200000, summary.last_played)

    def test_rounds_without_a_value_do_not_count_as_zero(self) -> None:
        empty = document(score=0, targetsCompleted=0, currentStreak=0, bestStreak=0, accuracy=None,
                         averageReactionTime=None, averageMovementTime=None, averageHoldStability=None,
                         pathEfficiency=None)
        played = document(averageReactionTime=0.5, averageHoldStability=0.8)
        summary = model.summarize([empty, played])
        self.assertAlmostEqual(0.5, summary.average_reaction)
        self.assertAlmostEqual(0.8, summary.average_stability)
        self.assertEqual(["-"] * 4, model.table_row(empty)[4:8])

    def test_trend_is_oldest_first_and_keeps_gaps(self) -> None:
        late = document(endedAt=1770000300000, accuracy=0.9, averageReactionTime=0.3)
        early = document(endedAt=1770000100000, accuracy=None, averageReactionTime=None)
        result = model.trend([late, early])
        self.assertEqual([None, 0.9], result.accuracy)
        self.assertEqual([None, 0.3], result.reaction)

    def test_formatting(self) -> None:
        self.assertEqual("75%", model.percent(0.75))
        self.assertEqual("-", model.percent(None))
        self.assertEqual("0.42 s", model.seconds(0.42))
        self.assertEqual("45 s", model.duration(45.2))
        self.assertEqual("3 min 05 s", model.duration(185))
        self.assertEqual("-", model.duration(None))
        self.assertRegex(model.when(1770000000000), r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        self.assertEqual("-", model.when(None))
        row = model.table_row(document())
        self.assertEqual(len(model.TABLE_HEADERS), len(row))
        self.assertEqual("6/8", row[3])


class LevelTests(unittest.TestCase):
    def test_level_labels(self) -> None:
        self.assertEqual(4, model.level_of({"difficulty": "level_4"}))
        self.assertEqual(3, model.level_of({"difficulty": "default"}))  # saved before adaptive difficulty
        for bad in ("level_0", "level_6", "level_", "level_-1", "Level_3", "level_3x", "hard", "", None, 3):
            self.assertIsNone(model.level_of({"difficulty": bad}), bad)
        self.assertIsNone(model.level_of({}))
        self.assertEqual("-", model.level_text({"difficulty": "hard"}))

    def test_table_shows_the_level(self) -> None:
        row = model.table_row(document(difficulty="level_5"))
        self.assertEqual("Level", model.TABLE_HEADERS[2])
        self.assertEqual("5", row[2])

    def test_mixed_levels(self) -> None:
        docs = [document(difficulty="level_2"), document(difficulty="level_2")]
        self.assertFalse(model.mixed_levels(docs))
        self.assertTrue(model.mixed_levels(docs + [document(difficulty="level_3")]))
        self.assertFalse(model.mixed_levels(docs + [document(difficulty="mystery")]))
        self.assertTrue(model.mixed_levels(docs + [document()]))  # "default" counts as level 3
        self.assertFalse(model.mixed_levels([]))


class WindowTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "m.db"
        self.users = UserStore(self.path, rounds=4)
        self.addCleanup(self.users.close)
        self.store = SqliteResultStore(self.path)
        self.addCleanup(self.store.close)
        self.alice = self.users.create_user("alice", "alice-password")
        self.bob = self.users.create_user("bob", "bob-password-1")


class LoginDialogTests(WindowTestCase):
    def fill(self, dialog: LoginDialog, username: str, password: str, repeat: str | None = None) -> None:
        dialog.username_edit.setText(username)
        dialog.password_edit.setText(password)
        if repeat is not None:
            dialog.repeat_edit.setText(repeat)

    def test_correct_password_accepts_and_returns_the_user(self) -> None:
        dialog = LoginDialog(self.users)
        self.fill(dialog, "alice", "alice-password")
        dialog.primary_button.click()
        self.assertEqual(QDialog.DialogCode.Accepted, dialog.result())
        self.assertEqual(self.alice, dialog.user)
        self.assertEqual("", dialog.password_edit.text(), "the password is cleared after use")

    def test_wrong_password_shows_a_generic_message_and_stays_open(self) -> None:
        dialog = LoginDialog(self.users)
        self.fill(dialog, "alice", "not-the-password")
        dialog.primary_button.click()
        self.assertIsNone(dialog.user)
        self.assertNotEqual(QDialog.DialogCode.Accepted, dialog.result())
        self.assertEqual("Error: Invalid username or password.", dialog.error_label.text())
        self.assertEqual("", dialog.password_edit.text())

    def test_password_field_hides_what_is_typed(self) -> None:
        dialog = LoginDialog(self.users)
        from PyQt6.QtWidgets import QLineEdit
        self.assertEqual(QLineEdit.EchoMode.Password, dialog.password_edit.echoMode())
        self.assertEqual(QLineEdit.EchoMode.Password, dialog.repeat_edit.echoMode())

    def test_creating_an_account_logs_in(self) -> None:
        dialog = LoginDialog(self.users)
        dialog.mode_button.click()
        self.assertFalse(dialog.repeat_edit.isHidden())
        self.fill(dialog, "carol", "carol-password", "carol-password")
        dialog.primary_button.click()
        self.assertEqual("carol", dialog.user.username)
        self.assertIsNotNone(self.users.get_by_username("carol"))

    def test_create_errors_are_shown_and_nothing_is_created(self) -> None:
        dialog = LoginDialog(self.users)
        dialog.mode_button.click()
        self.fill(dialog, "carol", "carol-password", "different-one")
        dialog.primary_button.click()
        self.assertIn("do not match", dialog.error_label.text())
        self.fill(dialog, "carol", "short", "short")
        dialog.primary_button.click()
        self.assertIn("at least 8", dialog.error_label.text())
        self.fill(dialog, "ALICE", "another-password", "another-password")
        dialog.primary_button.click()
        self.assertIn("already taken", dialog.error_label.text())
        self.assertIsNone(self.users.get_by_username("carol"))
        self.assertIsNone(dialog.user)

    def test_lockout_message_is_shown(self) -> None:
        dialog = LoginDialog(self.users)
        for _ in range(5):
            self.fill(dialog, "alice", "wrong-password")
            dialog.primary_button.click()
        self.fill(dialog, "alice", "alice-password")
        dialog.primary_button.click()
        self.assertIn("Too many failed attempts", dialog.error_label.text())
        self.assertIsNone(dialog.user)

    def test_mode_toggle_restores_the_login_form(self) -> None:
        dialog = LoginDialog(self.users)
        dialog.mode_button.click()
        dialog.mode_button.click()
        self.assertTrue(dialog.repeat_edit.isHidden())
        self.assertEqual("Log in", dialog.primary_button.text())


class DashboardWindowTests(WindowTestCase):
    def window(self, user) -> DashboardWindow:
        window = DashboardWindow(self.store, user, refresh_ms=0)
        self.addCleanup(window.close)
        return window

    def test_empty_state_for_a_player_with_no_rounds(self) -> None:
        window = self.window(self.alice)
        self.assertEqual(1, window.pages.currentIndex())
        self.assertIn("No rounds yet for alice", window.empty_label.text())
        self.assertEqual("0", window.cards["Rounds"].text())
        self.assertEqual("-", window.cards["Accuracy"].text())
        self.assertEqual("-", window.cards["Reaction"].text())

    def test_shows_only_the_players_own_rounds(self) -> None:
        mine = make_result(endedAt=1770000300000, targetsCompleted=8, targetsAttempted=8, score=8,
                           currentStreak=8, bestStreak=8, accuracy=1.0, averageReactionTime=0.5)
        theirs = make_result(endedAt=1770000200000)
        self.store.save(mine, self.alice.user_id)
        self.store.save(theirs, self.bob.user_id)
        window = self.window(self.alice)
        self.assertEqual(0, window.pages.currentIndex())
        self.assertEqual(1, window.table.rowCount())
        self.assertEqual("8/8", window.table.item(0, 3).text())
        self.assertEqual("1", window.cards["Rounds"].text())
        self.assertEqual("100%", window.cards["Accuracy"].text())
        self.assertEqual("8", window.cards["Best streak"].text())
        self.assertEqual("0.50 s", window.cards["Reaction"].text())
        self.assertEqual(1, self.window(self.bob).table.rowCount())

    def test_unassigned_rounds_belong_to_nobody(self) -> None:
        self.store.save(make_result())
        self.assertEqual(0, self.window(self.alice).table.rowCount())

    def test_rounds_are_listed_newest_first_with_dashes_for_missing_metrics(self) -> None:
        old = make_result(endedAt=1770000100000, score=0, targetsCompleted=0, currentStreak=0, bestStreak=0,
                          accuracy=None, averageReactionTime=None, averageMovementTime=None,
                          averageHoldStability=None, pathEfficiency=None)
        new = make_result(endedAt=1770000900000)
        self.store.save(old, self.alice.user_id)
        self.store.save(new, self.alice.user_id)
        window = self.window(self.alice)
        self.assertEqual(2, window.table.rowCount())
        self.assertEqual("6/8", window.table.item(0, 3).text())
        self.assertEqual("0/8", window.table.item(1, 3).text())
        self.assertEqual(["-", "-", "-", "-"], [window.table.item(1, c).text() for c in range(4, 8)])
        self.assertEqual(2, len(window.figure.axes))

    def test_refresh_picks_up_a_new_round(self) -> None:
        window = self.window(self.alice)
        self.assertEqual(0, window.table.rowCount())
        self.store.save(make_result(), self.alice.user_id)
        window.refresh_button.click()
        self.assertEqual(1, window.table.rowCount())
        self.assertEqual(0, window.pages.currentIndex())
        self.assertIn("1 round(s)", window.status_label.text())

    def test_log_out_flags_the_window_and_closes_it(self) -> None:
        window = self.window(self.alice)
        window.show()
        window.logout_button.click()
        self.assertTrue(window.logged_out)
        self.assertFalse(window.isVisible())

    def test_a_storage_failure_is_reported_not_raised(self) -> None:
        window = self.window(self.alice)
        self.store.close()
        window.refresh()
        self.assertIn("Could not read rounds", window.status_label.text())


if __name__ == "__main__":
    unittest.main()
