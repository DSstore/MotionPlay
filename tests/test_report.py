"""Test the progress comparison, the report pages, PDF writing, the command, and the dashboard export."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import contextlib
import io
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from app import report
from app.dashboard import DashboardWindow
from backend.auth import UserStore
from backend.storage import SqliteResultStore
from tests.test_results import make_result

APP = QApplication.instance() or QApplication([])
NOW = datetime(2026, 10, 6, 12, 0)
HOUR_MS = 3_600_000


def document(index: int = 0, **changes) -> dict:
    base = {"endedAt": 1770000000000 + index * HOUR_MS, "startedAt": 1770000000000 + index * HOUR_MS - 40000}
    return {**make_result(**{**base, **changes}).to_document(), "user_id": "u"}


def rounds(count: int, **changes) -> list[dict]:
    return [document(i, **changes) for i in range(count)]


def page_text(figure) -> str:
    """Every piece of text on a page: free text plus table cells."""
    parts = [t.get_text() for t in figure.texts]
    for axis in figure.axes:
        parts += [cell.get_text().get_text() for table in axis.tables for cell in table.get_celld().values()]
    return "\n".join(parts)


class CompareTests(unittest.TestCase):
    def test_too_few_rounds_gives_no_comparison(self) -> None:
        self.assertIsNone(report.compare(rounds(3)))
        self.assertIsNotNone(report.compare(rounds(4)))

    def test_improvement_and_decline_are_judged_by_direction(self) -> None:
        early = [document(i, targetsCompleted=3, score=3, accuracy=0.375, averageReactionTime=0.9,
                          averageHoldStability=0.9, pathEfficiency=0.9, currentStreak=1, bestStreak=2)
                 for i in range(2)]
        late = [document(i + 2, targetsCompleted=7, score=7, accuracy=0.875, averageReactionTime=0.5,
                         averageHoldStability=0.6, pathEfficiency=0.9, currentStreak=1, bestStreak=2)
                for i in range(2)]
        by_label = {c.label: c for c in report.compare(early + late)}
        self.assertEqual("improved", by_label["Accuracy"].verdict)
        self.assertEqual("+50 pts", by_label["Accuracy"].change)
        self.assertEqual("improved", by_label["Reaction time"].verdict, "a lower reaction time is better")
        self.assertEqual("-0.40 s", by_label["Reaction time"].change)
        self.assertEqual("declined", by_label["Hold stability"].verdict)
        self.assertEqual("about the same", by_label["Path efficiency"].verdict)

    def test_small_differences_count_as_the_same(self) -> None:
        early = rounds(2, averageReactionTime=0.50)
        late = [document(i + 2, averageReactionTime=0.52) for i in range(2)]
        self.assertEqual("about the same", {c.label: c for c in report.compare(early + late)}["Reaction time"].verdict)

    def test_missing_values_are_not_treated_as_zero(self) -> None:
        none = dict(averageReactionTime=None, averageMovementTime=None, averageHoldStability=None,
                    pathEfficiency=None, targetsCompleted=0, score=0, accuracy=0.0, currentStreak=0, bestStreak=0)
        early = rounds(2, **none)
        late = [document(i + 2) for i in range(2)]
        by_label = {c.label: c for c in report.compare(early + late)}
        self.assertEqual("not enough data", by_label["Reaction time"].verdict)
        self.assertEqual("-", by_label["Reaction time"].earlier)
        self.assertEqual("improved", by_label["Accuracy"].verdict)

    def test_uses_time_order_not_input_order(self) -> None:
        early = rounds(2, targetsCompleted=1, score=1, accuracy=0.125, currentStreak=1, bestStreak=1)
        late = [document(i + 2, targetsCompleted=8, score=8, accuracy=1.0, currentStreak=8, bestStreak=8)
                for i in range(2)]
        shuffled = [late[1], early[0], late[0], early[1]]
        self.assertEqual("improved", {c.label: c for c in report.compare(shuffled)}["Accuracy"].verdict)


class BuildTests(unittest.TestCase):
    def test_no_rounds_is_an_error(self) -> None:
        with self.assertRaises(report.ReportError):
            report.build_report([], "steve", NOW)

    def test_pages_for_a_normal_report(self) -> None:
        pages = report.build_report(rounds(10), "steve", NOW, "Last 30 day(s)")
        self.assertEqual(3, len(pages))  # summary, charts, one table page
        first = page_text(pages[0])
        for expected in ("MotionPlay progress report", "Player: steve", "Last 30 day(s)", "Rounds played", "10",
                         "not a medical device", "Earlier", "Accuracy"):
            self.assertIn(expected, first)
        self.assertEqual(4, len(pages[1].axes))
        self.assertIn("page 3 of 3", page_text(pages[2]))

    def test_few_rounds_say_there_is_not_enough_to_compare(self) -> None:
        text = page_text(report.build_report(rounds(2), "steve", NOW)[0])
        self.assertIn("Not enough rounds to compare yet", text)
        self.assertNotIn("improved", text)

    def test_many_rounds_continue_on_more_table_pages(self) -> None:
        pages = report.build_report(rounds(report.ROWS_PER_PAGE * 2 + 1), "steve", NOW)
        self.assertEqual(2 + 3, len(pages))
        self.assertIn("Rounds 1 to 28 of 57", page_text(pages[2]))
        self.assertIn("Rounds 57 to 57 of 57", page_text(pages[4]))

    def test_rounds_without_values_show_dashes_not_zero_and_leave_chart_gaps(self) -> None:
        empty = document(0, targetsCompleted=0, score=0, accuracy=0.0, currentStreak=0, bestStreak=0,
                         averageReactionTime=None, averageMovementTime=None, averageHoldStability=None,
                         pathEfficiency=None)
        pages = report.build_report([empty, document(1)], "steve", NOW)
        self.assertIn("-", page_text(pages[2]))
        reaction_line = pages[1].axes[1].lines[0].get_ydata()
        self.assertNotEqual(reaction_line[0], reaction_line[0], "the missing value is a NaN gap, not 0")


class PdfTests(unittest.TestCase):
    def test_writes_a_real_pdf_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "nested" / "r.pdf"
            report.write_pdf(report.build_report(rounds(6), "steve", NOW), path)
            self.assertTrue(path.read_bytes().startswith(b"%PDF-"))
            self.assertGreater(path.stat().st_size, 5000)
            self.assertEqual(["r.pdf"], [p.name for p in path.parent.iterdir()], "no temporary file left behind")

    def test_unwritable_target_is_a_report_error(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(report.ReportError):
                report.write_pdf(report.build_report(rounds(2), "steve", NOW), Path(folder))  # A directory

    def test_period_filter_and_filename(self) -> None:
        docs = rounds(5)
        cutoff = datetime.fromtimestamp((docs[3]["endedAt"] - 1) / 1000)
        self.assertEqual(2, len(report.filter_period(docs, cutoff)))
        self.assertEqual(5, len(report.filter_period(docs, None)))
        self.assertEqual("MotionPlay-progress-steve-20261006-1200.pdf", report.default_filename("steve", NOW))


class ReportCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db = Path(self.folder.name) / "m.db"
        users = UserStore(self.db, rounds=4)
        self.alice = users.create_user("alice", "alice-password")
        self.bob = users.create_user("bob", "bob-password-1")
        users.close()
        store = SqliteResultStore(self.db)
        self.now = datetime.now()
        stamp = int(self.now.timestamp() * 1000)
        for i in range(5):
            store.save(make_result(endedAt=stamp - i * HOUR_MS, startedAt=stamp - i * HOUR_MS - 40000),
                       self.alice.user_id)
        store.save(make_result(endedAt=stamp - 90 * 24 * HOUR_MS, startedAt=stamp - 90 * 24 * HOUR_MS - 4000),
                   self.alice.user_id)
        store.close()
        self.out = Path(self.folder.name) / "report.pdf"

    def run_cli(self, *argv: str, password: str = "alice-password", user: str = "alice") -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        base = ["--user", user, "--store", "sqlite", "--file", str(self.db), "--users-db", str(self.db),
                "--out", str(self.out)]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = report.main([*base, *argv], prompt=lambda _t: password, now=self.now, rounds=4)
        return code, out.getvalue(), err.getvalue()

    def test_makes_a_report_for_the_logged_in_player(self) -> None:
        code, out, _ = self.run_cli()
        self.assertEqual(0, code)
        self.assertIn("(6 round(s))", out)
        self.assertTrue(self.out.read_bytes().startswith(b"%PDF-"))

    def test_days_window_limits_the_rounds(self) -> None:
        code, out, _ = self.run_cli("--days", "30")
        self.assertEqual(0, code)
        self.assertIn("(5 round(s))", out)

    def test_wrong_password_makes_no_file(self) -> None:
        code, _, err = self.run_cli(password="wrong-password")
        self.assertEqual(1, code)
        self.assertIn("Invalid username or password", err)
        self.assertFalse(self.out.exists())

    def test_a_player_with_no_rounds_gets_a_clear_error(self) -> None:
        code, _, err = self.run_cli(user="bob", password="bob-password-1")
        self.assertEqual(1, code)
        self.assertIn("nothing to report", err)
        self.assertFalse(self.out.exists())

    def test_bad_period_arguments_fail_cleanly(self) -> None:
        self.assertEqual(1, self.run_cli("--days", "0")[0])
        self.assertEqual(1, self.run_cli("--since", "yesterday")[0])
        self.assertFalse(self.out.exists())


class DashboardExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        db = Path(self.folder.name) / "m.db"
        self.users = UserStore(db, rounds=4)
        self.addCleanup(self.users.close)
        self.store = SqliteResultStore(db)
        self.addCleanup(self.store.close)
        self.user = self.users.create_user("alice", "alice-password")

    def window(self) -> DashboardWindow:
        window = DashboardWindow(self.store, self.user, refresh_ms=0)
        self.addCleanup(window.close)
        return window

    def test_export_writes_a_pdf_and_says_so(self) -> None:
        for i in range(5):
            self.store.save(make_result(endedAt=1770000000000 + i * HOUR_MS), self.user.user_id)
        window = self.window()
        path = Path(self.folder.name) / "out.pdf"
        self.assertTrue(window.export_report(path))
        self.assertTrue(path.read_bytes().startswith(b"%PDF-"))
        self.assertIn("Report saved", window.status_label.text())

    def test_export_without_rounds_reports_why_and_writes_nothing(self) -> None:
        window = self.window()
        path = Path(self.folder.name) / "out.pdf"
        self.assertFalse(window.export_report(path))
        self.assertIn("nothing to report", window.status_label.text())
        self.assertFalse(path.exists())

    def test_export_only_includes_this_players_rounds(self) -> None:
        other = self.users.create_user("bob", "bob-password-1")
        self.store.save(make_result(), other.user_id)
        window = self.window()
        self.assertFalse(window.export_report(Path(self.folder.name) / "out.pdf"))

    def test_export_button_exists(self) -> None:
        self.assertEqual("Export report...", self.window().export_button.text())


if __name__ == "__main__":
    unittest.main()
