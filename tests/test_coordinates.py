"""Verify Phase 3 math and loss handling using deterministic hand observations."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from cv_engine.coordinates import PALM_LANDMARKS, normalize_position, palm_center
from cv_engine.controller import run_tracking
from cv_engine.models import ControlPosition, Landmark, TrackedHand, TrackingResult
from cv_engine.position_processor import PositionProcessor
from cv_engine.preview import draw_overlay
from cv_engine.smoothing import PositionSmoother
from shared.config import ConfigurationError, ControlSettings, load_settings


def hand(x=0.5, y=0.5, z=-0.02, label="right", confidence=0.95) -> TrackedHand:
    """Make synthetic landmarks for math tests; this is not a detector fixture."""
    return TrackedHand(label, confidence, (Landmark(x, y, z),) * 21)


def frame(*hands: TrackedHand) -> TrackingResult:
    """Wrap a synthetic frame's observations with a placeholder processing time."""
    return TrackingResult(tuple(hands), processing_ms=1.0)


class CoordinateTests(unittest.TestCase):
    """Check anatomical selection and normalized image bounds."""

    def test_center_uses_wrist_and_finger_bases_and_ignores_fingertips(self) -> None:
        points = [Landmark(1, 1, 1)] * 21
        for index, x in zip(PALM_LANDMARKS, (0.1, 0.3, 0.5, 0.7, 0.9)):
            points[index] = Landmark(x, 0.4, -0.03)
        observed = replace(hand(), landmarks=tuple(points))
        center = palm_center(observed)
        self.assertAlmostEqual(center.x, 0.5)
        self.assertAlmostEqual(center.y, 0.4)
        self.assertAlmostEqual(center.z, -0.03)
        points[8] = Landmark(-10, 10, -1)
        self.assertEqual(palm_center(replace(observed, landmarks=tuple(points))), center)

    def test_native_coordinates_are_clamped_without_rescaling_or_flipping(self) -> None:
        self.assertEqual(normalize_position(Landmark(0.64, 0.38, -0.03)), ControlPosition(0.64, 0.38, -0.03))
        self.assertEqual(normalize_position(Landmark(-0.2, 1.2, -2)), ControlPosition(0, 1, -2))
        self.assertEqual(normalize_position(Landmark(1.2, -0.2, 2)), ControlPosition(1, 0, 2))

    def test_invalid_coordinates_and_incomplete_palms_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            palm_center(replace(hand(), landmarks=hand().landmarks[:20]))
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_position(Landmark(0.5, 0.5, value))
                with self.assertRaises(ValueError):
                    palm_center(hand(x=value))


class SmoothingTests(unittest.TestCase):
    """Check the EMA response, dead-zone geometry, reset, and invalid input."""

    def test_first_sample_seeds_and_following_sample_obeys_ema(self) -> None:
        smoother = PositionSmoother(alpha=0.25, dead_zone=0)
        first = ControlPosition(0.2, 0.4, -0.02)
        self.assertEqual(smoother.update(first), first)
        result = smoother.update(ControlPosition(0.8, 0.6, -0.06))
        self.assertAlmostEqual(result.x, 0.35)
        self.assertAlmostEqual(result.y, 0.45)
        self.assertAlmostEqual(result.z, -0.03)

    def test_alpha_one_and_zero_dead_zone_pass_through_including_depth(self) -> None:
        smoother = PositionSmoother(alpha=1, dead_zone=0)
        smoother.update(ControlPosition(0.5, 0.5, 0))
        depth_change = ControlPosition(0.5, 0.5, -0.1)
        self.assertEqual(smoother.update(depth_change), depth_change)

    def test_dead_zone_holds_output_until_accumulated_movement_crosses_radius(self) -> None:
        smoother = PositionSmoother(alpha=1, dead_zone=0.01)
        initial = ControlPosition(0, 0, 0)
        smoother.update(initial)
        for x in (0.002, 0.004, 0.006, 0.008, 0.01):
            self.assertEqual(smoother.update(ControlPosition(x, 0, -0.1)), initial)
        outside = ControlPosition(0.012, 0, -0.1)
        self.assertEqual(smoother.update(outside), outside)

    def test_dead_zone_uses_euclidean_xy_distance(self) -> None:
        smoother = PositionSmoother(alpha=1, dead_zone=0.01)
        smoother.update(ControlPosition(0, 0, 0))
        diagonal = ControlPosition(0.008, 0.008, 0)
        self.assertEqual(smoother.update(diagonal), diagonal)

    def test_reset_removes_old_position(self) -> None:
        smoother = PositionSmoother(alpha=0.1)
        smoother.update(ControlPosition(0.1, 0.1, 0))
        smoother.reset()
        new = ControlPosition(0.9, 0.9, 0)
        self.assertEqual(smoother.update(new), new)

    def test_defaults_reduce_stationary_alternating_jitter(self) -> None:
        smoother = PositionSmoother()
        raw = [0.5 + (0.01 if index % 2 else -0.01) for index in range(100)]
        filtered = [smoother.update(ControlPosition(x, 0.5, 0)).x for x in raw]
        # Ignore startup: the steady filtered signal must have less than half
        # the input variation while remaining close to the stationary center.
        self.assertLess(float(np.std(filtered[20:])), float(np.std(raw[20:])) / 2)
        self.assertLess(abs(float(np.mean(filtered[20:])) - 0.5), 0.005)

    def test_invalid_settings_and_samples_do_not_poison_existing_filter(self) -> None:
        for options in ({"alpha": 0}, {"alpha": 1.1}, {"alpha": float("nan")}, {"dead_zone": -0.1}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                PositionSmoother(**options)
        smoother = PositionSmoother(alpha=0.5, dead_zone=0)
        smoother.update(ControlPosition(0.2, 0.2, 0))
        for position in (ControlPosition(2, 0.2, 0), ControlPosition(0.2, 0.2, float("nan"))):
            with self.subTest(position=position), self.assertRaises(ValueError):
                smoother.update(position)
        self.assertAlmostEqual(smoother.update(ControlPosition(0.8, 0.2, 0)).x, 0.5)


class ProcessorTests(unittest.TestCase):
    """Verify separate hand history, confidence rejection, and monotonic timeouts."""

    def setUp(self) -> None:
        self.processor = PositionProcessor(ControlSettings(smoothing_alpha=0.5, dead_zone=0, tracking_timeout=0.5))

    def test_no_observations_produces_no_control(self) -> None:
        result = self.processor.update(frame(), 0)
        self.assertFalse(result.tracking)
        self.assertEqual(result.hands, ())

    def test_palm_control_is_bounded_and_original_landmarks_are_preserved(self) -> None:
        observed = hand(x=-0.2, y=1.2)
        control = self.processor.update(frame(observed), 0).hands[0]
        self.assertTrue(control.tracking)
        self.assertEqual(control.position, ControlPosition(0, 1, -0.02))
        self.assertEqual(observed.landmarks[0], Landmark(-0.2, 1.2, -0.02))

    def test_missing_hand_immediately_exposes_no_stale_position(self) -> None:
        self.processor.update(frame(hand()), 0)
        result = self.processor.update(frame(), 0.1)
        self.assertFalse(result.tracking)
        self.assertEqual(result.hands[0].status, "temporarily_lost")
        self.assertIsNone(result.hands[0].position)
        self.assertIsNone(result.hands[0].raw_position)

    def test_timeout_changes_state_and_logs_reset_once(self) -> None:
        self.processor.update(frame(hand()), 0)
        with self.assertLogs("motionplay.cv_engine.position_processor", level="INFO") as logs:
            result = self.processor.update(frame(), 0.5)
            self.processor.update(frame(), 1)
        self.assertEqual(result.hands[0].status, "lost")
        self.assertEqual(len(logs.output), 1)
        self.assertIn("smoothing reset", logs.output[0])

    def test_short_gap_preserves_filter_and_long_gap_seeds_fresh(self) -> None:
        self.processor.update(frame(hand(x=0.2)), 0)
        self.processor.update(frame(), 0.1)
        result = self.processor.update(frame(hand(x=0.8)), 0.2)
        self.assertAlmostEqual(result.hands[0].position.x, 0.5)
        result = self.processor.update(frame(hand(x=0.9)), 1)
        self.assertAlmostEqual(result.hands[0].position.x, 0.9)

    def test_left_and_right_filters_are_independent_when_input_order_changes(self) -> None:
        self.processor.update(frame(hand(x=0.1, label="left"), hand(x=0.9)), 0)
        result = self.processor.update(frame(hand(x=0.7), hand(x=0.3, label="left")), 0.1)
        outputs = {control.hand: control for control in result.hands}
        self.assertAlmostEqual(outputs["left"].position.x, 0.2)
        self.assertAlmostEqual(outputs["right"].position.x, 0.8)
        result = self.processor.update(frame(hand(x=0.7)), 0.2)
        self.assertEqual(result.hands[0].status, "temporarily_lost")
        self.assertTrue(result.hands[1].tracking)

    def test_rejected_confidence_does_not_refresh_timeout_or_filter(self) -> None:
        self.processor.update(frame(hand(x=0.2)), 0)
        for timestamp in (0.1, 0.2, 0.3):
            result = self.processor.update(frame(hand(x=0.8, confidence=0.5)), timestamp)
            self.assertFalse(result.tracking)
        result = self.processor.update(frame(hand(x=0.8)), 0.6)
        self.assertAlmostEqual(result.hands[0].position.x, 0.8)

    def test_confidence_boundary_is_accepted_and_invalid_confidence_is_rejected(self) -> None:
        self.assertTrue(self.processor.update(frame(hand(confidence=0.75)), 0).tracking)
        for value in (0.749, -0.1, 1.1, float("nan"), float("inf")):
            with self.subTest(confidence=value):
                self.assertFalse(self.processor.update(frame(hand(confidence=value)), 0.1).tracking)

    def test_duplicate_labels_use_the_most_confident_observation_once(self) -> None:
        result = self.processor.update(frame(hand(x=0.2, confidence=0.8), hand(x=0.8, confidence=0.9)), 0)
        self.assertEqual(len(result.hands), 1)
        self.assertAlmostEqual(result.hands[0].position.x, 0.8)

    def test_invalid_palm_is_unavailable_and_does_not_poison_history(self) -> None:
        self.processor.update(frame(hand(x=0.2)), 0)
        result = self.processor.update(frame(hand(x=float("nan"))), 0.1)
        self.assertFalse(result.tracking)
        result = self.processor.update(frame(hand(x=0.8)), 0.2)
        self.assertAlmostEqual(result.hands[0].position.x, 0.5)

    def test_non_monotonic_or_nonfinite_time_is_rejected_without_state_change(self) -> None:
        self.processor.update(frame(hand(x=0.2)), 1)
        for now in (0.9, -1, float("nan"), float("inf")):
            with self.subTest(now=now), self.assertRaises(ValueError):
                self.processor.update(frame(hand(x=0.8)), now)
        result = self.processor.update(frame(hand(x=0.8)), 1.1)
        self.assertAlmostEqual(result.hands[0].position.x, 0.5)


class ConfigurationTests(unittest.TestCase):
    """Validate Phase 3 environment options before camera startup."""

    def test_defaults_overrides_and_invalid_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            self.assertEqual(load_settings(path, environ={}).control, ControlSettings())
            settings = load_settings(path, environ={"SMOOTHING_ALPHA": "1", "SMOOTHING_DEAD_ZONE": "0", "CONTROL_TRACKING_TIMEOUT": "2"})
            self.assertEqual(settings.control.smoothing_alpha, 1)
            self.assertEqual(settings.control.dead_zone, 0)
            self.assertEqual(settings.control.tracking_timeout, 2)
            for key, value in (
                ("SMOOTHING_ALPHA", "0"), ("SMOOTHING_ALPHA", "nan"),
                ("SMOOTHING_DEAD_ZONE", "-0.1"), ("SMOOTHING_DEAD_ZONE", "1.1"),
                ("CONTROL_MIN_HANDEDNESS_CONFIDENCE", "inf"),
                ("CONTROL_TRACKING_TIMEOUT", "0"), ("CONTROL_TRACKING_TIMEOUT", "bad"),
            ):
                with self.subTest(key=key, value=value), self.assertRaises(ConfigurationError):
                    load_settings(path, environ={key: value})


class IntegrationTests(unittest.TestCase):
    """Exercise the controller and preview with filtered and missing observations."""

    @patch("cv_engine.preview.cv2.drawMarker")
    def test_preview_draws_smoothed_marker_and_hides_it_during_loss(self, marker: MagicMock) -> None:
        processor = PositionProcessor(ControlSettings(smoothing_alpha=0.5, dead_zone=0))
        processor.update(frame(hand(x=0.2, y=0.4)), 0)
        observation = frame(hand(x=0.8, y=0.4))
        controls = processor.update(observation, 0.1)
        image = np.zeros((100, 200, 3), dtype=np.uint8)
        draw_overlay(image, observation, 30, controls)
        self.assertEqual(marker.call_args.args[1], (100, 40))
        self.assertFalse(np.any(image))
        marker.reset_mock()
        draw_overlay(image, frame(), 30, processor.update(frame(), 0.2))
        marker.assert_not_called()
        # Invalid raw landmarks are also safe to display as unavailable.
        draw_overlay(image, frame(hand(x=float("nan"))), 30, controls=None)

    @patch("cv_engine.preview.Preview")
    @patch("cv_engine.hand_tracker.HandTracker")
    @patch("cv_engine.camera.Camera")
    def test_controller_passes_filtered_output_to_preview_and_releases_resources(
        self, camera_factory: MagicMock, tracker_factory: MagicMock, preview_factory: MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = load_settings(Path(directory) / ".env", environ={})
        camera_factory.return_value.__enter__.return_value.read.return_value = np.zeros((4, 6, 3), dtype=np.uint8)
        tracker_factory.return_value.__enter__.return_value.process.side_effect = [frame(hand(x=0.5)), frame()]
        preview = preview_factory.return_value.__enter__.return_value
        preview.show.side_effect = [True, False]
        self.assertEqual(run_tracking(settings), 2)
        self.assertTrue(preview.show.call_args_list[0].args[3].tracking)
        self.assertFalse(preview.show.call_args_list[1].args[3].tracking)
        camera_factory.return_value.__exit__.assert_called_once()
        tracker_factory.return_value.__exit__.assert_called_once()
        preview_factory.return_value.__exit__.assert_called_once()


if __name__ == "__main__":
    unittest.main()
