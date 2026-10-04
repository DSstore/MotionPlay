"""Apply confidence/loss eligibility to independent per-hand gesture histories."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Literal

from cv_engine.gestures import GestureDebouncer, GestureEngine
from cv_engine.models import ControlResult, GestureResult, HandGesture, TrackingResult
from shared.config import ControlSettings, GestureSettings


LOGGER = logging.getLogger("motionplay.cv_engine.gesture_processor")
HandLabel = Literal["left", "right"]


@dataclass
class _GestureState:
    debouncer: GestureDebouncer
    last_seen: float | None = None


class GestureProcessor:
    """Classify only fresh control-eligible hands and debounce each physical label."""

    def __init__(self, settings: GestureSettings, control_settings: ControlSettings) -> None:
        self.engine = GestureEngine(settings)
        self.settings = settings
        self.tracking_timeout = control_settings.tracking_timeout
        self._states: dict[HandLabel, _GestureState] = {}
        self._previous_update: float | None = None

    def update(
        self, observations: TrackingResult, controls: ControlResult, now: float,
        image_aspect_ratio: float = 1.0,
    ) -> GestureResult:
        """Reset immediately on missing/rejected/invalid data; confirm fresh sequences."""
        if not math.isfinite(now) or now < 0 or (self._previous_update is not None and now < self._previous_update):
            raise ValueError("Gesture processing requires nondecreasing finite timestamps.")
        if not math.isfinite(image_aspect_ratio) or image_aspect_ratio <= 0:
            raise ValueError("Image aspect ratio must be finite and positive (width / height).")
        self._previous_update = now
        eligible = {hand.hand: hand for hand in controls.hands if hand.tracking}
        labels = sorted(set(self._states) | {hand.hand for hand in controls.hands})
        outputs = []
        for label in labels:
            if label not in self._states:
                self._states[label] = _GestureState(GestureDebouncer(self.settings.debounce_frames))
            state = self._states[label]
            control = eligible.get(label)
            # Match the same highest-confidence observation selected by the
            # position processor, including its first-observation tie behavior.
            hand = next((hand for hand in observations.hands if control is not None
                         and hand.hand == label and hand.handedness_confidence == control.handedness_confidence), None)
            if hand is None:
                state.debouncer.reset()
                state.last_seen = None
                outputs.append(HandGesture(label))
                continue
            if state.last_seen is not None and now - state.last_seen >= self.tracking_timeout:
                state.debouncer.reset()
            detection = self.engine.analyze(hand, image_aspect_ratio)
            if not detection.valid:
                state.debouncer.reset()
                state.last_seen = None
                outputs.append(HandGesture(label))
                continue
            state.last_seen = now
            confirmed = state.debouncer.update(detection.candidate)
            outputs.append(HandGesture(
                hand=label, tracking=True, candidate=detection.candidate,
                gesture=confirmed.gesture, consecutive_frames=confirmed.consecutive_frames,
                changed=confirmed.changed,
            ))
            if confirmed.changed:
                LOGGER.info("%s gesture confirmed: %s.", label.capitalize(), confirmed.gesture.value)
        return GestureResult(tuple(outputs))
