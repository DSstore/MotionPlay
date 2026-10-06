"""Keep a hand's identity steady across frames where MediaPipe's left/right label flickers.

MediaPipe classifies each frame's hand as left or right on its own, so a single hand being moved
can briefly come back as the other hand, or with a confidence below the control gate. With one
control hand that makes the cursor disappear for a frame or two. This stage corrects only the clear
cases: a detection that sits where a hand was tracked a moment ago keeps that hand's label.

It never creates identity from nothing: a hand with no recent tracked history is left exactly as
MediaPipe reported it, and a hand that appears somewhere else is not matched to an old track.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, replace
from typing import Literal

from cv_engine.coordinates import normalize_position, palm_center
from cv_engine.models import TrackedHand, TrackingResult
from shared.config import ControlSettings


LOGGER = logging.getLogger("motionplay.cv_engine.continuity")
HandLabel = Literal["left", "right"]


@dataclass
class _Track:
    x: float
    y: float
    seen_at: float


class LabelContinuity:
    """Correct brief label flips and low-confidence frames for hands that were just tracked.

    Call ``apply`` once per processed frame, before the position and gesture processors, with a
    monotonic timestamp in seconds. Corrected hands are marked ``label_corrected`` and keep
    MediaPipe's original ``handedness_confidence``.
    """

    def __init__(self, settings: ControlSettings) -> None:
        self.settings = settings
        self._tracks: dict[HandLabel, _Track] = {}
        self._previous: float | None = None
        #: Hands whose label or confidence was overridden so far (a diagnostic counter).
        self.corrections = 0

    @property
    def enabled(self) -> bool:
        return self.settings.continuity_seconds > 0

    def apply(self, result: TrackingResult, now: float) -> TrackingResult:
        """Return ``result`` with continuity corrections applied (the same object if none)."""
        if not math.isfinite(now) or now < 0 or (self._previous is not None and now < self._previous):
            raise ValueError("Label continuity requires nondecreasing finite timestamps.")
        self._previous = now
        if not self.enabled:
            return result

        window = self.settings.continuity_seconds
        fresh = {label: track for label, track in self._tracks.items() if now - track.seen_at < window}
        taken: set[HandLabel] = {hand.hand for hand in result.hands}
        corrected: list[TrackedHand] = []
        palms: list[tuple[float, float] | None] = []
        changed = False
        for hand in result.hands:
            try:
                palm = normalize_position(palm_center(hand))
            except ValueError:
                corrected.append(hand)
                palms.append(None)
                continue
            position = (palm.x, palm.y)
            palms.append(position)
            new = hand
            own = fresh.get(hand.hand)
            if own is not None:
                # Same label, still where that hand was: trust the position over a low confidence.
                if self._near(own, position) and not self._passes_gate(hand):
                    new = replace(hand, label_corrected=True)
            else:
                # This label has no recent track. If the other label does, and this detection sits on it
                # (and that label is not also present this frame), it is almost surely the same hand flipped.
                other = self._flipped_from(fresh, taken, hand.hand, position)
                if other is not None:
                    taken.add(other)
                    new = replace(hand, hand=other, label_corrected=True)
            if new is not hand:
                changed = True
                self.corrections += 1
                LOGGER.debug("Label continuity: %s -> %s (confidence %.2f).", hand.hand, new.hand,
                             hand.handedness_confidence)
            corrected.append(new)

        for hand, position in zip(corrected, palms):
            if position is not None and (hand.label_corrected or self._passes_gate(hand)):
                self._tracks[hand.hand] = _Track(position[0], position[1], now)
        if not changed:
            return result
        return TrackingResult(hands=tuple(corrected), processing_ms=result.processing_ms)

    def _passes_gate(self, hand: TrackedHand) -> bool:
        confidence = hand.handedness_confidence
        return math.isfinite(confidence) and self.settings.min_handedness_confidence <= confidence <= 1

    def _near(self, track: _Track, position: tuple[float, float]) -> bool:
        return math.hypot(position[0] - track.x, position[1] - track.y) <= self.settings.continuity_radius

    def _flipped_from(
        self, fresh: dict[HandLabel, _Track], taken: set[HandLabel], label: HandLabel,
        position: tuple[float, float],
    ) -> HandLabel | None:
        best: tuple[float, HandLabel] | None = None
        for other, track in fresh.items():
            if other == label or other in taken or not self._near(track, position):
                continue
            distance = math.hypot(position[0] - track.x, position[1] - track.y)
            if best is None or distance < best[0]:
                best = (distance, other)
        return None if best is None else best[1]
