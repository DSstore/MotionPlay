"""Process raw hand observations without coupling filters to cameras or gameplay."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Literal

from cv_engine.coordinates import normalize_position, palm_center
from cv_engine.models import ControlResult, HandControl, TrackedHand, TrackingResult
from cv_engine.smoothing import PositionSmoother
from shared.config import ControlSettings


LOGGER = logging.getLogger("motionplay.cv_engine.position_processor")
HandLabel = Literal["left", "right"]


@dataclass
class _HandState:
    """Private filter state; never reused between physical hand labels."""

    smoother: PositionSmoother
    last_seen: float | None = None


class PositionProcessor:
    """Gate observations, normalize palms, and maintain separate left/right filters.

    Missing/rejected hands immediately become unavailable. Filter history survives
    only short interruptions; an elapsed timeout resets it even if the next frame
    already contains a hand. Call update for every processed frame, including empty
    detections, using a monotonic timestamp in seconds.
    """

    def __init__(self, settings: ControlSettings) -> None:
        self.settings = settings
        self._states: dict[HandLabel, _HandState] = {}
        self._previous_update: float | None = None

    def _accepted_hands(self, result: TrackingResult) -> dict[HandLabel, TrackedHand]:
        """Choose at most one observation per label, prioritizing confidence."""
        accepted: dict[HandLabel, TrackedHand] = {}
        for hand in result.hands:
            confidence = hand.handedness_confidence
            if hand.hand not in {"left", "right"}:
                continue
            if not math.isfinite(confidence):
                continue
            # Continuity vouches for a hand that sits where a tracked hand just was, so the label's low
            # confidence (or the flipped label) is not held against it.
            if not hand.label_corrected and not self.settings.min_handedness_confidence <= confidence <= 1:
                continue
            previous = accepted.get(hand.hand)
            if previous is None or confidence > previous.handedness_confidence:
                accepted[hand.hand] = hand
        return accepted

    def update(self, result: TrackingResult, now: float) -> ControlResult:
        """Return fresh positions or explicit loss states without leaking stale data."""
        if not math.isfinite(now) or now < 0 or (self._previous_update is not None and now < self._previous_update):
            raise ValueError("Position processing requires nondecreasing finite timestamps.")
        self._previous_update = now
        for label, state in self._states.items():
            if state.last_seen is not None and now - state.last_seen >= self.settings.tracking_timeout:
                state.smoother.reset()
                state.last_seen = None
                LOGGER.info("%s hand tracking timed out; smoothing reset.", label.capitalize())

        outputs: dict[HandLabel, HandControl] = {}
        for label, hand in self._accepted_hands(result).items():
            try:
                raw = normalize_position(palm_center(hand))
            except ValueError:
                LOGGER.debug("Rejected invalid %s palm coordinates.", label)
                continue
            if label not in self._states:
                self._states[label] = _HandState(PositionSmoother(
                    alpha=self.settings.smoothing_alpha, dead_zone=self.settings.dead_zone,
                ))
            state = self._states[label]
            position = state.smoother.update(raw)
            state.last_seen = now
            outputs[label] = HandControl(label, "tracking", hand.handedness_confidence, raw, position)

        for label, state in self._states.items():
            if label not in outputs:
                status = "lost" if state.last_seen is None else "temporarily_lost"
                outputs[label] = HandControl(label, status)
        return ControlResult(tuple(outputs[label] for label in sorted(outputs)))
