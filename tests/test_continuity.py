"""Test hand-label continuity: which flickers it fixes, and the cases it must leave alone."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from cv_engine.continuity import LabelContinuity
from cv_engine.gesture_processor import GestureProcessor
from cv_engine.models import Gesture, Landmark, TrackedHand, TrackingResult
from cv_engine.position_processor import PositionProcessor
from shared.config import ConfigurationError, ControlSettings, GestureSettings, load_settings
from tests.gesture_fixtures import gesture_hand


def hand(x=0.5, y=0.5, label="right", confidence=0.95) -> TrackedHand:
    return TrackedHand(label, confidence, (Landmark(x, y, -0.02),) * 21)


def frame(*hands: TrackedHand) -> TrackingResult:
    return TrackingResult(tuple(hands), processing_ms=1.0)


class ContinuityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = ControlSettings(smoothing_alpha=1, dead_zone=0)
        self.continuity = LabelContinuity(self.settings)

    def tracked_right_at(self, x=0.5, y=0.5, now=0.0) -> None:
        """Establish a recently tracked right hand."""
        result = self.continuity.apply(frame(hand(x, y)), now)
        self.assertFalse(result.hands[0].label_corrected)

    def test_flipped_label_near_the_tracked_hand_is_corrected(self) -> None:
        self.tracked_right_at()
        result = self.continuity.apply(frame(hand(0.52, 0.5, label="left", confidence=0.97)), 0.05)
        self.assertEqual("right", result.hands[0].hand)
        self.assertTrue(result.hands[0].label_corrected)
        self.assertEqual(0.97, result.hands[0].handedness_confidence)  # the original value is kept
        self.assertEqual(1, self.continuity.corrections)

    def test_low_confidence_near_the_tracked_hand_is_rescued(self) -> None:
        self.tracked_right_at()
        result = self.continuity.apply(frame(hand(0.51, 0.5, confidence=0.4)), 0.05)
        self.assertEqual("right", result.hands[0].hand)
        self.assertTrue(result.hands[0].label_corrected)
        self.assertEqual(0.4, result.hands[0].handedness_confidence)

    def test_flipped_and_low_confidence_together_is_corrected(self) -> None:
        self.tracked_right_at()
        result = self.continuity.apply(frame(hand(0.5, 0.5, label="left", confidence=0.3)), 0.05)
        self.assertEqual("right", result.hands[0].hand)
        self.assertTrue(result.hands[0].label_corrected)

    def test_clean_frames_pass_through_unchanged(self) -> None:
        self.tracked_right_at()
        observed = frame(hand(0.55, 0.5))
        self.assertIs(observed, self.continuity.apply(observed, 0.05))
        self.assertEqual(0, self.continuity.corrections)

    def test_nothing_is_invented_without_recent_history(self) -> None:
        # First sight of a left-labelled hand stays left; first sight of a weak hand stays weak.
        first = frame(hand(label="left", confidence=0.95))
        self.assertIs(first, self.continuity.apply(first, 0.0))
        fresh = LabelContinuity(self.settings)
        weak = frame(hand(confidence=0.3))
        self.assertIs(weak, fresh.apply(weak, 0.0))
        self.assertEqual(0, fresh.corrections)

    def test_a_weak_frame_does_not_start_or_extend_a_track(self) -> None:
        weak_only = LabelContinuity(self.settings)
        weak_only.apply(frame(hand(confidence=0.3)), 0.0)
        flipped = frame(hand(label="left"))
        self.assertIs(flipped, weak_only.apply(flipped, 0.05))  # the weak frame was never accepted

    def test_a_hand_far_from_the_old_track_is_left_alone(self) -> None:
        self.tracked_right_at(0.2, 0.2)
        far = frame(hand(0.8, 0.8, label="left"))
        self.assertIs(far, self.continuity.apply(far, 0.05))
        weak_far = frame(hand(0.8, 0.8, confidence=0.3))
        self.assertIs(weak_far, self.continuity.apply(weak_far, 0.06))

    def test_an_old_track_expires(self) -> None:
        self.tracked_right_at(now=0.0)
        late = frame(hand(label="left"))
        self.assertIs(late, self.continuity.apply(late, 0.3))  # window is 0.3 s, exclusive

    def test_corrections_keep_the_track_alive_for_the_next_frame(self) -> None:
        self.tracked_right_at(now=0.0)
        self.assertTrue(self.continuity.apply(frame(hand(label="left")), 0.2).hands[0].label_corrected)
        self.assertTrue(self.continuity.apply(frame(hand(label="left")), 0.4).hands[0].label_corrected)

    def test_a_genuine_second_hand_keeps_its_label(self) -> None:
        self.tracked_right_at(0.3, 0.5)
        both = frame(hand(0.3, 0.5), hand(0.7, 0.5, label="left"))
        self.assertIs(both, self.continuity.apply(both, 0.05))
        # Once the left hand has a track of its own, a left detection next to it stays left.
        again = frame(hand(0.3, 0.5), hand(0.72, 0.5, label="left"))
        self.assertIs(again, self.continuity.apply(again, 0.1))

    def test_two_flipped_detections_cannot_both_claim_one_label(self) -> None:
        self.tracked_right_at(0.5, 0.5)
        result = self.continuity.apply(frame(hand(0.5, 0.5, label="left"), hand(0.55, 0.5, label="left")), 0.05)
        self.assertEqual(["right", "left"], [h.hand for h in result.hands])

    def test_disabled_returns_the_same_frame(self) -> None:
        off = LabelContinuity(ControlSettings(continuity_seconds=0))
        self.assertFalse(off.enabled)
        off.apply(frame(hand()), 0.0)
        flipped = frame(hand(label="left"))
        self.assertIs(flipped, off.apply(flipped, 0.05))

    def test_invalid_landmarks_and_bad_clocks_are_handled(self) -> None:
        self.tracked_right_at()
        broken = frame(hand(x=float("nan"), label="left"))
        self.assertIs(broken, self.continuity.apply(broken, 0.05))
        for now in (0.01, -1, float("nan"), float("inf")):
            with self.subTest(now=now), self.assertRaises(ValueError):
                self.continuity.apply(frame(hand()), now)

    def test_empty_frames_are_fine(self) -> None:
        empty = frame()
        self.assertIs(empty, self.continuity.apply(empty, 0.0))


class PipelineTests(unittest.TestCase):
    """The corrected frame must actually keep the cursor and gestures alive downstream."""

    def setUp(self) -> None:
        self.control = ControlSettings(smoothing_alpha=1, dead_zone=0)
        self.continuity = LabelContinuity(self.control)
        self.positions = PositionProcessor(self.control)
        self.gestures = GestureProcessor(GestureSettings(debounce_frames=2), self.control)

    def run_frame(self, now, *hands, correct=True):
        observed = frame(*hands)
        if correct:
            observed = self.continuity.apply(observed, now)
        controls = self.positions.update(observed, now)
        return controls, self.gestures.update(observed, controls, now)

    def right(self, controls):
        return next(h for h in controls.hands if h.hand == "right")

    def test_a_flip_no_longer_drops_the_right_hand(self) -> None:
        self.run_frame(0.00, hand(0.4, 0.4))
        controls, _ = self.run_frame(0.03, hand(0.41, 0.4, label="left", confidence=0.96))
        self.assertTrue(self.right(controls).tracking)
        self.assertAlmostEqual(0.41, self.right(controls).position.x)
        self.assertFalse(any(h.tracking for h in controls.hands if h.hand == "left"))

    def test_the_same_flip_drops_the_hand_without_continuity(self) -> None:
        self.run_frame(0.00, hand(0.4, 0.4), correct=False)
        controls, _ = self.run_frame(0.03, hand(0.41, 0.4, label="left", confidence=0.96), correct=False)
        self.assertFalse(self.right(controls).tracking)

    def test_low_confidence_frame_is_kept_with_continuity_and_dropped_without(self) -> None:
        self.run_frame(0.00, hand(0.4, 0.4))
        controls, _ = self.run_frame(0.03, hand(0.41, 0.4, confidence=0.3))
        self.assertTrue(self.right(controls).tracking)
        plain = PositionProcessor(self.control)
        plain.update(frame(hand(0.4, 0.4)), 0.0)
        self.assertFalse(plain.update(frame(hand(0.41, 0.4, confidence=0.3)), 0.03).hands[0].tracking)

    def test_a_confirmed_gesture_survives_a_flipped_frame(self) -> None:
        for now in (0.00, 0.03):
            _, gestures = self.run_frame(now, gesture_hand(Gesture.FIST))
        self.assertEqual(Gesture.FIST, gestures.hands[0].gesture)
        _, gestures = self.run_frame(0.06, replace(gesture_hand(Gesture.FIST), hand="left"))
        right = next(h for h in gestures.hands if h.hand == "right")
        self.assertTrue(right.tracking)
        self.assertEqual(Gesture.FIST, right.gesture)
        self.assertFalse(right.changed)  # still the same confirmed gesture, not a fresh confirmation


class SettingsTests(unittest.TestCase):
    def test_defaults_overrides_and_invalid_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            defaults = load_settings(path, environ={}).control
            self.assertEqual(0.3, defaults.continuity_seconds)
            self.assertEqual(0.25, defaults.continuity_radius)
            custom = load_settings(path, environ={"CONTROL_CONTINUITY_SECONDS": "0",
                                                  "CONTROL_CONTINUITY_RADIUS": "0.4"}).control
            self.assertEqual(0, custom.continuity_seconds)
            self.assertEqual(0.4, custom.continuity_radius)
            for key, value in (("CONTROL_CONTINUITY_SECONDS", "-0.1"), ("CONTROL_CONTINUITY_SECONDS", "2"),
                               ("CONTROL_CONTINUITY_SECONDS", "nan"), ("CONTROL_CONTINUITY_RADIUS", "0"),
                               ("CONTROL_CONTINUITY_RADIUS", "1.5"), ("CONTROL_CONTINUITY_RADIUS", "bad")):
                with self.subTest(key=key, value=value), self.assertRaises(ConfigurationError):
                    load_settings(path, environ={key: value})


if __name__ == "__main__":
    unittest.main()
