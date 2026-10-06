"""Test the documentation-image tools: the demo data is valid and repeatable, and the tools write real images and a real PDF."""

from __future__ import annotations

import contextlib
import io
import re
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from tools import make_demo_assets, make_performance_charts

ROOT = Path(__file__).resolve().parents[1]
PNG = b"\x89PNG\r\n\x1a\n"


class DemoDataTests(unittest.TestCase):
    def test_rounds_are_valid_ordered_in_the_past_and_use_levels_one_to_five(self) -> None:
        rounds = make_demo_assets.demo_rounds()
        self.assertEqual(42, len(rounds))
        cutoff = make_demo_assets.NOW.timestamp() * 1000
        for result in rounds:
            self.assertLess(result.endedAt, cutoff)  # nothing "played" after the report's generated time
            self.assertIn(result.difficulty, {f"level_{n}" for n in range(1, 6)})
        ends = [r.endedAt for r in rounds]
        self.assertEqual(sorted(ends), ends)

    def test_the_data_is_repeatable_so_regenerated_images_do_not_churn(self) -> None:
        first, second = make_demo_assets.demo_rounds(), make_demo_assets.demo_rounds()
        self.assertEqual([r.difficulty for r in first], [r.difficulty for r in second])
        self.assertEqual([r.targetsCompleted for r in first], [r.targetsCompleted for r in second])
        self.assertEqual([r.endedAt for r in first], [r.endedAt for r in second])

    def test_the_story_shows_the_level_moving_both_ways(self) -> None:
        levels = [int(r.difficulty[-1]) for r in make_demo_assets.demo_rounds()]
        self.assertTrue(any(b < a for a, b in zip(levels, levels[1:])), "the level should drop at least once")
        self.assertTrue(any(b > a for a, b in zip(levels, levels[1:])), "the level should rise at least once")

    def test_the_demo_period_is_about_five_weeks(self) -> None:
        rounds = make_demo_assets.demo_rounds()
        span = timedelta(milliseconds=rounds[-1].endedAt - rounds[0].endedAt)
        self.assertGreater(span, timedelta(days=28))


class ToolOutputTests(unittest.TestCase):
    def test_report_assets_are_written_without_showing_any_window(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, make_demo_assets.main(["--out", str(out), "--no-windows"]))
            for name in ("report-summary.png", "report-trends.png", "report-rounds.png"):
                self.assertTrue((out / name).read_bytes().startswith(PNG), name)
            self.assertTrue((out / "sample-report.pdf").read_bytes().startswith(b"%PDF"))
            self.assertFalse((out / "dashboard.png").exists())  # window screenshots were skipped

    def test_performance_charts_are_written(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, make_performance_charts.main(["--out", folder]))
            for name in ("perf-camera-open.png", "perf-frame-rate.png", "perf-flicker.png"):
                self.assertTrue((Path(folder) / name).read_bytes().startswith(PNG), name)

    def test_the_committed_images_exist_and_are_real(self) -> None:
        images = ROOT / "docs" / "images"
        for name in ("dashboard.png", "login.png", "report-summary.png", "report-trends.png", "report-rounds.png",
                     "perf-camera-open.png", "perf-frame-rate.png", "perf-flicker.png"):
            with self.subTest(name):
                self.assertTrue((images / name).read_bytes().startswith(PNG))
        self.assertTrue((images / "sample-report.pdf").read_bytes().startswith(b"%PDF"))


class RecordedMeasurementTests(unittest.TestCase):
    """The charts quote the same numbers as the write-up, so the two cannot quietly disagree.

    Each value is looked for in its own table row or sentence, not just anywhere in the text, so an unrelated number
    that happens to match cannot hide a mismatch."""

    def setUp(self) -> None:
        self.text = (ROOT / "docs" / "performance.md").read_text(encoding="utf-8")

    @staticmethod
    def plain(name: str) -> str:
        return " ".join(name.split())  # chart labels contain line breaks

    def test_frame_rates_are_in_the_table(self) -> None:
        for name, value in [*make_performance_charts.FRAME_RATE_LIVE, make_performance_charts.FRAME_RATE_FINAL]:
            with self.subTest(self.plain(name)):
                self.assertRegex(self.text, re.compile(rf"^\|[^|]*\| {value:.1f} \|$", re.MULTILINE))

    def test_flicker_rates_and_sample_sizes_are_in_the_table(self) -> None:
        for name, value, sample in make_performance_charts.FLICKERS:
            with self.subTest(self.plain(name)):
                self.assertIn(f"| {value:.1f} | {sample} |", self.text)

    def test_camera_open_times_are_stated(self) -> None:
        for name, runs in make_performance_charts.CAMERA_OPEN.items():
            with self.subTest(self.plain(name)):
                if "Default" in name:
                    sentence = next(line for line in self.text.splitlines() if "four runs" in line)
                    for seconds in runs:
                        self.assertIn(f"{seconds:.1f}", sentence)
                else:
                    self.assertIn(f"{min(runs):.1f} to {max(runs):.1f} s", self.text)


if __name__ == "__main__":
    unittest.main()
