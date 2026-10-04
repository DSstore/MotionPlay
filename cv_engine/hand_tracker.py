"""Convert webcam frames into reusable hand observations using MediaPipe Hands."""

from __future__ import annotations

import logging
from time import perf_counter
from types import TracebackType
from typing import Any, Literal

import cv2
import numpy as np

from cv_engine.errors import CVEngineError
from cv_engine.models import Landmark, TrackedHand, TrackingResult, VideoFrame
from shared.config import TrackingSettings


LOGGER = logging.getLogger("motionplay.cv_engine.hand_tracker")


class TrackingError(CVEngineError):
    """MediaPipe initialization, processing, or result decoding failed."""


def decode_hands(result: Any, mirrored_input: bool) -> tuple[TrackedHand, ...]:
    """Detach native results and correct labels for unmirrored input.

    MediaPipe Hands labels assume selfie-mirrored images. Process and display
    the same mirrored frame, or swap left/right when mirroring is disabled.
    Native result types are generated dynamically, hence Any at this boundary.
    """
    native_hands = result.multi_hand_landmarks or []
    handedness = result.multi_handedness or []
    if len(native_hands) != len(handedness):
        raise TrackingError("MediaPipe returned unmatched landmarks and hand labels.")
    observations = []
    for native_hand, classification in zip(native_hands, handedness):
        if not classification.classification:
            raise TrackingError("MediaPipe returned a missing hand classification.")
        label = classification.classification[0]
        if label.label not in {"Left", "Right"} or len(native_hand.landmark) != 21:
            raise TrackingError("MediaPipe returned an unsupported hand result.")
        hand: Literal["left", "right"] = "left" if label.label == "Left" else "right"
        if not mirrored_input:
            hand = "right" if hand == "left" else "left"
        observations.append(TrackedHand(
            hand=hand,
            handedness_confidence=float(label.score),
            landmarks=tuple(Landmark(float(p.x), float(p.y), float(p.z)) for p in native_hand.landmark),
        ))
    return tuple(observations)


class HandTracker:
    """A reusable streaming tracker with explicit resource ownership."""

    def __init__(self, settings: TrackingSettings, mirrored_input: bool = True) -> None:
        self.settings = settings
        self.mirrored_input = mirrored_input
        self._engine: Any = None

    def open(self) -> None:
        """Initialize the packaged model without opening a webcam or downloading assets."""
        if self._engine is not None:
            raise TrackingError("The hand tracker is already initialized.")
        LOGGER.info("Initializing MediaPipe Hands.")
        try:
            import mediapipe as mp

            self._engine = mp.solutions.hands.Hands(
                static_image_mode=False,
                max_num_hands=self.settings.max_hands,
                model_complexity=self.settings.model_complexity,
                min_detection_confidence=self.settings.detection_confidence,
                min_tracking_confidence=self.settings.tracking_confidence,
            )
        except Exception as error:
            raise TrackingError(
                "MediaPipe Hands initialization failed. Activate the Python 3.11 environment "
                "and reinstall requirements.txt; check native-library errors in the logs."
            ) from error
        LOGGER.info("MediaPipe Hands initialized.")

    def process(self, frame: VideoFrame) -> TrackingResult:
        """Process a BGR uint8 frame; the caller decides whether to mirror it."""
        if self._engine is None:
            raise TrackingError("The hand tracker is not initialized.")
        if frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3 or frame.size == 0:
            raise TrackingError("Hand tracking requires a non-empty uint8 BGR image.")
        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            started_at = perf_counter()
            result = self._engine.process(rgb)
            processing_ms = (perf_counter() - started_at) * 1000
            observations = decode_hands(result, self.mirrored_input)
        except TrackingError:
            raise
        except Exception as error:
            raise TrackingError("MediaPipe could not process a frame; restart tracking and check the logs.") from error
        return TrackingResult(hands=observations, processing_ms=processing_ms)

    def close(self) -> None:
        """Release model resources; safe to call more than once."""
        if self._engine is not None:
            self._engine.close()
            self._engine = None
            LOGGER.info("MediaPipe Hands released.")

    def __enter__(self) -> HandTracker:
        self.open()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None,
        exc: BaseException | None, traceback: TracebackType | None,
    ) -> None:
        self.close()
