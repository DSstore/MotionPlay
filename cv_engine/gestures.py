"""Reusable landmark-geometry gesture classification and frame debouncing."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from cv_engine.models import Gesture, GestureDetection, TrackedHand
from shared.config import GestureSettings


Point = tuple[float, float, float]
FingerState = Literal["extended", "curled", "unknown"]
FINGER_CHAINS = ((1, 2, 3, 4), (5, 6, 7, 8), (9, 10, 11, 12), (13, 14, 15, 16), (17, 18, 19, 20))


def joint_angle(a: Point, joint: Point, b: Point) -> float | None:
    """Return degrees, or None for nonfinite/degenerate joint segments."""
    if not all(math.isfinite(value) for point in (a, joint, b) for value in point):
        return None
    left = tuple(value - origin for value, origin in zip(a, joint))
    right = tuple(value - origin for value, origin in zip(b, joint))
    denominator = math.hypot(*left) * math.hypot(*right)
    if not math.isfinite(denominator) or denominator <= 1e-12:
        return None
    cosine = sum(x * y for x, y in zip(left, right)) / denominator
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


@dataclass(frozen=True)
class _Features:
    """Geometry features computed once for a classification."""

    fingers: tuple[FingerState, ...]
    pinch_ratio: float


class GestureEngine:
    """Heuristic classification independent of cameras, handedness, and games.

    The classifier uses original raw landmarks, not clamped or smoothed control
    coordinates. Thresholds are tunable heuristics, not learned confidence scores.
    """

    def __init__(self, settings: GestureSettings | None = None) -> None:
        self.settings = settings if settings is not None else GestureSettings()

    def _features(self, hand: TrackedHand, image_aspect_ratio: float) -> _Features | None:
        """Put x/y/z on comparable model units, then inspect finger bends and reach."""
        if not math.isfinite(image_aspect_ratio) or image_aspect_ratio <= 0:
            raise ValueError("Image aspect ratio must be finite and positive (width / height).")
        if len(hand.landmarks) != 21 or not all(
            math.isfinite(value) for p in hand.landmarks for value in (p.x, p.y, p.z)
        ):
            return None
        # MediaPipe z approximately uses x's scale; y is normalized by height.
        points = [(p.x, p.y / image_aspect_ratio, p.z) for p in hand.landmarks]
        palm_size = max(math.dist(points[0], points[9]), math.dist(points[5], points[17]))
        if not math.isfinite(palm_size) or palm_size <= 1e-9:
            return None
        states: list[FingerState] = []
        for base, proximal, distal, tip in FINGER_CHAINS:
            first = joint_angle(points[base], points[proximal], points[distal])
            second = joint_angle(points[proximal], points[distal], points[tip])
            base_reach = math.dist(points[0], points[base])
            if first is None or second is None or base_reach <= 1e-9:
                return None
            tip_reach = math.dist(points[0], points[tip])
            boundary = base_reach * self.settings.reach_ratio
            if not math.isfinite(tip_reach) or not math.isfinite(boundary):
                return None
            if min(first, second) >= self.settings.extended_angle and tip_reach > boundary:
                states.append("extended")
            elif min(first, second) <= self.settings.curled_angle and tip_reach <= boundary:
                states.append("curled")
            else:
                states.append("unknown")
        pinch_ratio = math.dist(points[4], points[8]) / palm_size
        if not math.isfinite(pinch_ratio):
            return None
        return _Features(tuple(states), pinch_ratio)

    @staticmethod
    def _is_fist(features: _Features) -> bool:
        return all(state == "curled" for state in features.fingers[1:])

    def _is_pinch(self, features: _Features) -> bool:
        # A closed fist can also bring these tips close; give its folded fingers
        # priority rather than calling that incidental proximity a pinch.
        return features.pinch_ratio <= self.settings.pinch_ratio and not self._is_fist(features)

    @staticmethod
    def _is_point(features: _Features) -> bool:
        return features.fingers[1] == "extended" and all(state == "curled" for state in features.fingers[2:])

    @staticmethod
    def _is_open_hand(features: _Features) -> bool:
        return all(state == "extended" for state in features.fingers)

    def analyze(self, hand: TrackedHand, image_aspect_ratio: float = 1.0) -> GestureDetection:
        """Classify once; distinguish ambiguous valid poses from unusable geometry."""
        features = self._features(hand, image_aspect_ratio)
        if features is None:
            return GestureDetection()
        for gesture, matches in (
            (Gesture.FIST, self._is_fist(features)),
            (Gesture.PINCH, self._is_pinch(features)),
            (Gesture.POINT, self._is_point(features)),
            (Gesture.OPEN_HAND, self._is_open_hand(features)),
        ):
            if matches:
                return GestureDetection(gesture, valid=True)
        return GestureDetection(Gesture.UNKNOWN, valid=True)

    def classify(self, hand: TrackedHand, image_aspect_ratio: float = 1.0) -> Gesture:
        """Return only the raw gesture name, without temporal confirmation."""
        return self.analyze(hand, image_aspect_ratio).candidate

    def detect_fist(self, hand: TrackedHand, image_aspect_ratio: float = 1.0) -> bool:
        """Whether all four non-thumb fingers satisfy the folded-finger heuristic."""
        features = self._features(hand, image_aspect_ratio)
        return features is not None and self._is_fist(features)

    def detect_pinch(self, hand: TrackedHand, image_aspect_ratio: float = 1.0) -> bool:
        """Whether thumb/index proximity is a pinch rather than a folded fist."""
        features = self._features(hand, image_aspect_ratio)
        return features is not None and self._is_pinch(features)

    def detect_open_hand(self, hand: TrackedHand, image_aspect_ratio: float = 1.0) -> bool:
        """Whether all five fingers satisfy the extension heuristic."""
        features = self._features(hand, image_aspect_ratio)
        return features is not None and self._is_open_hand(features)

    def detect_point(self, hand: TrackedHand, image_aspect_ratio: float = 1.0) -> bool:
        """Whether index is extended while middle, ring, and pinky are folded."""
        features = self._features(hand, image_aspect_ratio)
        return features is not None and self._is_point(features)


@dataclass(frozen=True)
class DebouncedGesture:
    """Confirmation result; changed is an edge, not a repeated per-frame action."""

    gesture: Gesture
    consecutive_frames: int
    changed: bool


class GestureDebouncer:
    """Require repeated identical candidates before changing a confirmed gesture."""

    def __init__(self, required_frames: int = 5) -> None:
        if type(required_frames) is not int or not 1 <= required_frames <= 60:
            raise ValueError("Gesture debounce frames must be an integer from 1 to 60.")
        self.required_frames = required_frames
        self.reset()

    def reset(self) -> None:
        """Clear both confirmed and pending state after lost or unusable tracking."""
        self._candidate = Gesture.UNKNOWN
        self._confirmed = Gesture.UNKNOWN
        self._count = 0

    def update(self, candidate: Gesture) -> DebouncedGesture:
        """Count consecutive candidates; retain the last confirmation while pending."""
        if not isinstance(candidate, Gesture):
            raise ValueError("Gesture candidate must be a Gesture enum value.")
        if candidate != self._candidate:
            self._candidate = candidate
            self._count = 0
        self._count = min(self.required_frames, self._count + 1)
        changed = self._count == self.required_frames and candidate != self._confirmed
        if changed:
            self._confirmed = candidate
        return DebouncedGesture(self._confirmed, self._count, changed)
