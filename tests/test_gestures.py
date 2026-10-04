"""Verify classification geometry, debouncing, loss handling, and preview integration."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from cv_engine.controller import run_tracking
from cv_engine.gesture_processor import GestureProcessor
from cv_engine.gestures import GestureDebouncer, GestureEngine, joint_angle
from cv_engine.models import ControlResult, Gesture, Landmark, TrackingResult
from cv_engine.position_processor import PositionProcessor
from shared.config import ConfigurationError, ControlSettings, GestureSettings, load_settings
from tests.gesture_fixtures import gesture_hand


class GeometryTests(unittest.TestCase):
    """Test explicit shapes and invariance under synthetic coordinate transforms."""

    def setUp(self) -> None:
        self.engine = GestureEngine()

    def test_all_five_candidates_and_reusable_predicates(self) -> None:
        predicates = {
            Gesture.OPEN_HAND: self.engine.detect_open_hand,
            Gesture.FIST: self.engine.detect_fist,
            Gesture.PINCH: self.engine.detect_pinch,
            Gesture.POINT: self.engine.detect_point,
        }
        for gesture in Gesture:
            with self.subTest(gesture=gesture):
                hand = gesture_hand(gesture)
                detection = self.engine.analyze(hand)
                self.assertTrue(detection.valid)
                self.assertEqual(detection.candidate, gesture)
                for name, predicate in predicates.items():
                    self.assertEqual(predicate(hand), name == gesture)

    def test_rotation_translation_scale_and_mirroring_preserve_candidates(self) -> None:
        for gesture in Gesture:
            for angle in (0, 90, 180, 270):
                for mirrored in (False, True):
                    with self.subTest(gesture=gesture, angle=angle, mirrored=mirrored):
                        hand = gesture_hand(gesture, angle=angle, mirrored=mirrored, scale=0.13, offset=(0.3, 0.4), label="left")
                        self.assertEqual(self.engine.classify(hand), gesture)

    def test_camera_aspect_ratio_is_applied_before_geometry(self) -> None:
        for gesture in Gesture:
            for aspect in (4 / 3, 16 / 9, 3 / 4):
                with self.subTest(gesture=gesture, aspect=aspect):
                    hand = gesture_hand(gesture, image_aspect_ratio=aspect, angle=45)
                    self.assertEqual(self.engine.classify(hand, aspect), gesture)

    def test_fist_has_priority_when_thumb_and_index_tips_touch(self) -> None:
        hand = gesture_hand(Gesture.FIST)
        points = list(hand.landmarks)
        points[4] = points[8]
        hand = replace(hand, landmarks=tuple(points))
        self.assertEqual(self.engine.classify(hand), Gesture.FIST)
        self.assertFalse(self.engine.detect_pinch(hand))

    def test_pinch_ratio_threshold_can_be_tuned(self) -> None:
        hand = gesture_hand(Gesture.PINCH)
        self.assertTrue(self.engine.detect_pinch(hand))
        strict = GestureEngine(GestureSettings(pinch_ratio=0.01))
        self.assertFalse(strict.detect_pinch(hand))

    def test_invalid_incomplete_and_degenerate_data_are_unusable_unknown(self) -> None:
        hand = gesture_hand(Gesture.OPEN_HAND)
        invalid = [replace(hand, landmarks=hand.landmarks[:20]), replace(hand, landmarks=(Landmark(0, 0, 0),) * 21)]
        for value in (float("nan"), float("inf"), 1e308):
            points = list(hand.landmarks)
            points[8] = Landmark(value, value, value)
            invalid.append(replace(hand, landmarks=tuple(points)))
        for sample in invalid:
            with self.subTest(sample=sample):
                result = self.engine.analyze(sample)
                self.assertFalse(result.valid)
                self.assertEqual(result.candidate, Gesture.UNKNOWN)

    def test_angle_math_handles_straight_right_and_zero_length_segments(self) -> None:
        self.assertAlmostEqual(joint_angle((-1, 0, 0), (0, 0, 0), (1, 0, 0)), 180)
        self.assertAlmostEqual(joint_angle((1, 0, 0), (0, 0, 0), (0, 1, 0)), 90)
        self.assertIsNone(joint_angle((0, 0, 0), (0, 0, 0), (1, 0, 0)))

    def test_invalid_aspect_ratio_is_rejected(self) -> None:
        for value in (0, -1, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.engine.classify(gesture_hand(Gesture.OPEN_HAND), value)


class DebounceTests(unittest.TestCase):
    """Confirm only consecutive sequences and emit a single change edge."""

    def test_confirmation_requires_exactly_five_frames_and_changes_once(self) -> None:
        debouncer = GestureDebouncer()
        for _ in range(4):
            result = debouncer.update(Gesture.OPEN_HAND)
            self.assertEqual(result.gesture, Gesture.UNKNOWN)
            self.assertFalse(result.changed)
        result = debouncer.update(Gesture.OPEN_HAND)
        self.assertEqual(result.gesture, Gesture.OPEN_HAND)
        self.assertTrue(result.changed)
        result = debouncer.update(Gesture.OPEN_HAND)
        self.assertFalse(result.changed)
        self.assertEqual(result.consecutive_frames, 5)

    def test_one_noisy_frame_does_not_change_confirmation(self) -> None:
        debouncer = GestureDebouncer(required_frames=3)
        for _ in range(3):
            debouncer.update(Gesture.OPEN_HAND)
        self.assertEqual(debouncer.update(Gesture.FIST).gesture, Gesture.OPEN_HAND)
        self.assertEqual(debouncer.update(Gesture.OPEN_HAND).gesture, Gesture.OPEN_HAND)
        for _ in range(2):
            self.assertEqual(debouncer.update(Gesture.FIST).gesture, Gesture.OPEN_HAND)
        result = debouncer.update(Gesture.FIST)
        self.assertEqual(result.gesture, Gesture.FIST)
        self.assertTrue(result.changed)

    def test_unknown_valid_pose_also_requires_confirmation(self) -> None:
        debouncer = GestureDebouncer(required_frames=2)
        for _ in range(2):
            debouncer.update(Gesture.POINT)
        self.assertEqual(debouncer.update(Gesture.UNKNOWN).gesture, Gesture.POINT)
        self.assertEqual(debouncer.update(Gesture.UNKNOWN).gesture, Gesture.UNKNOWN)

    def test_reset_discards_both_confirmation_and_pending_frames(self) -> None:
        debouncer = GestureDebouncer(required_frames=2)
        debouncer.update(Gesture.FIST)
        debouncer.update(Gesture.FIST)
        debouncer.reset()
        result = debouncer.update(Gesture.FIST)
        self.assertEqual(result.gesture, Gesture.UNKNOWN)
        self.assertEqual(result.consecutive_frames, 1)

    def test_alternating_candidates_never_confirm(self) -> None:
        debouncer = GestureDebouncer()
        for gesture in [Gesture.FIST, Gesture.POINT] * 10:
            self.assertEqual(debouncer.update(gesture).gesture, Gesture.UNKNOWN)

    def test_invalid_frame_counts_and_candidate_types_are_rejected(self) -> None:
        for frames in (0, -1, 61, 1.5, True):
            with self.subTest(frames=frames), self.assertRaises(ValueError):
                GestureDebouncer(frames)
        with self.assertRaises(ValueError):
            GestureDebouncer().update("FIST")


class ProcessorTests(unittest.TestCase):
    """Use the real palm processor so gesture eligibility matches control eligibility."""

    def setUp(self) -> None:
        control = ControlSettings()
        self.positions = PositionProcessor(control)
        self.gestures = GestureProcessor(GestureSettings(debounce_frames=3), control)

    def process(self, now, *hands):
        observations = TrackingResult(tuple(hands), processing_ms=1)
        controls = self.positions.update(observations, now)
        return self.gestures.update(observations, controls, now)

    def test_missing_tracking_clears_confirmation_immediately_and_restarts_count(self) -> None:
        for now in (0, 0.03, 0.06):
            result = self.process(now, gesture_hand(Gesture.OPEN_HAND))
        self.assertEqual(result.hands[0].gesture, Gesture.OPEN_HAND)
        result = self.process(0.09)
        self.assertFalse(result.hands[0].tracking)
        self.assertEqual(result.hands[0].gesture, Gesture.UNKNOWN)
        self.assertFalse(result.hands[0].changed)
        result = self.process(0.12, gesture_hand(Gesture.OPEN_HAND))
        self.assertEqual(result.hands[0].consecutive_frames, 1)
        self.assertEqual(result.hands[0].gesture, Gesture.UNKNOWN)

    def test_low_confidence_resets_pending_sequence(self) -> None:
        self.process(0, gesture_hand(Gesture.PINCH))
        self.process(0.03, gesture_hand(Gesture.PINCH))
        self.assertFalse(self.process(0.06, gesture_hand(Gesture.PINCH, confidence=0.5)).hands[0].tracking)
        result = self.process(0.09, gesture_hand(Gesture.PINCH))
        self.assertEqual(result.hands[0].consecutive_frames, 1)
        self.assertEqual(result.hands[0].gesture, Gesture.UNKNOWN)

    def test_left_and_right_sequences_do_not_share_history(self) -> None:
        for now in (0, 0.03, 0.06):
            result = self.process(now, gesture_hand(Gesture.OPEN_HAND, label="left"), gesture_hand(Gesture.FIST))
        self.assertEqual([hand.gesture for hand in result.hands], [Gesture.OPEN_HAND, Gesture.FIST])
        result = self.process(0.09, gesture_hand(Gesture.FIST))
        self.assertEqual(result.hands[0].gesture, Gesture.UNKNOWN)
        self.assertEqual(result.hands[1].gesture, Gesture.FIST)

    def test_long_gap_without_empty_frame_starts_new_sequence(self) -> None:
        for now in (0, 0.03, 0.06):
            self.process(now, gesture_hand(Gesture.POINT))
        result = self.process(1, gesture_hand(Gesture.POINT))
        self.assertEqual(result.hands[0].gesture, Gesture.UNKNOWN)
        self.assertEqual(result.hands[0].consecutive_frames, 1)

    def test_invalid_finger_geometry_resets_even_if_palm_control_is_valid(self) -> None:
        for now in (0, 0.03, 0.06):
            self.process(now, gesture_hand(Gesture.OPEN_HAND))
        hand = gesture_hand(Gesture.OPEN_HAND)
        points = list(hand.landmarks)
        points[8] = Landmark(float("nan"), 0.5, 0)
        result = self.process(0.09, replace(hand, landmarks=tuple(points)))
        self.assertFalse(result.hands[0].tracking)
        self.assertEqual(result.hands[0].gesture, Gesture.UNKNOWN)

    def test_duplicate_labels_match_the_observation_selected_for_palm_control(self) -> None:
        for now in (0, 0.03, 0.06):
            result = self.process(now, gesture_hand(Gesture.FIST, confidence=0.8), gesture_hand(Gesture.OPEN_HAND, confidence=0.95))
        self.assertEqual(len(result.hands), 1)
        self.assertEqual(result.hands[0].gesture, Gesture.OPEN_HAND)

    def test_changed_edge_is_logged_once_and_holding_does_not_repeat_it(self) -> None:
        with self.assertLogs("motionplay.cv_engine.gesture_processor", level="INFO") as logs:
            results = [self.process(index * 0.03, gesture_hand(Gesture.FIST)) for index in range(6)]
        self.assertEqual(sum(result.hands[0].changed for result in results), 1)
        self.assertEqual(len(logs.output), 1)

    def test_invalid_clock_is_rejected_without_consuming_confirmation_frame(self) -> None:
        self.process(1, gesture_hand(Gesture.FIST))
        for now in (0.9, float("nan"), float("inf")):
            with self.subTest(now=now), self.assertRaises(ValueError):
                self.gestures.update(TrackingResult((), 0), ControlResult(), now)
        result = self.process(1.03, gesture_hand(Gesture.FIST))
        self.assertEqual(result.hands[0].consecutive_frames, 2)


class ConfigurationTests(unittest.TestCase):
    """Check tunable thresholds and cross-setting angle constraints."""

    def test_defaults_overrides_and_invalid_thresholds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            self.assertEqual(load_settings(path, environ={}).gestures, GestureSettings())
            settings = load_settings(path, environ={"GESTURE_DEBOUNCE_FRAMES": "3", "GESTURE_PINCH_RATIO": "0.2"})
            self.assertEqual(settings.gestures.debounce_frames, 3)
            self.assertEqual(settings.gestures.pinch_ratio, 0.2)
            for key, value in (
                ("GESTURE_DEBOUNCE_FRAMES", "0"), ("GESTURE_DEBOUNCE_FRAMES", "1.5"),
                ("GESTURE_PINCH_RATIO", "0"), ("GESTURE_PINCH_RATIO", "1.1"),
                ("GESTURE_EXTENDED_ANGLE", "90"), ("GESTURE_EXTENDED_ANGLE", "181"),
                ("GESTURE_CURLED_ANGLE", "160"), ("GESTURE_REACH_RATIO", "1"),
                ("GESTURE_PINCH_RATIO", "nan"), ("GESTURE_CURLED_ANGLE", "inf"),
            ):
                with self.subTest(key=key, value=value), self.assertRaises(ConfigurationError):
                    load_settings(path, environ={key: value})


class IntegrationTests(unittest.TestCase):
    """Run actual classification through the controller with a fake camera/model."""

    @patch("cv_engine.preview.Preview")
    @patch("cv_engine.hand_tracker.HandTracker")
    @patch("cv_engine.camera.Camera")
    def test_preview_receives_raw_confirmed_and_unavailable_gestures(
        self, camera_factory: MagicMock, tracker_factory: MagicMock, preview_factory: MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = load_settings(Path(directory) / ".env", environ={})
        camera_factory.return_value.__enter__.return_value.read.return_value = np.zeros((480, 640, 3), dtype=np.uint8)
        observations = TrackingResult((gesture_hand(Gesture.OPEN_HAND, image_aspect_ratio=4 / 3),), 1)
        tracker_factory.return_value.__enter__.return_value.process.side_effect = [observations] * 5 + [TrackingResult((), 1)]
        preview = preview_factory.return_value.__enter__.return_value
        preview.show.side_effect = [True] * 5 + [False]
        self.assertEqual(run_tracking(settings, send_udp=False), 6)
        states = [call.args[4].hands[0] for call in preview.show.call_args_list]
        self.assertEqual(states[0].candidate, Gesture.OPEN_HAND)
        self.assertEqual(states[0].gesture, Gesture.UNKNOWN)
        self.assertEqual(states[4].gesture, Gesture.OPEN_HAND)
        self.assertEqual(states[5].gesture, Gesture.UNKNOWN)
        self.assertFalse(states[5].tracking)
        camera_factory.return_value.__exit__.assert_called_once()


if __name__ == "__main__":
    unittest.main()
