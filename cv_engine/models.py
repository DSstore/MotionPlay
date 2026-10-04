"""Application-owned hand data independent of MediaPipe protobuf objects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Literal

import numpy as np
from numpy.typing import NDArray


VideoFrame = NDArray[np.uint8]


class HandLandmark(IntEnum):
    """Standard anatomical indices for MediaPipe's 21 hand landmarks."""

    WRIST = 0
    THUMB_CMC = 1
    THUMB_MCP = 2
    THUMB_IP = 3
    THUMB_TIP = 4
    INDEX_MCP = 5
    INDEX_PIP = 6
    INDEX_DIP = 7
    INDEX_TIP = 8
    MIDDLE_MCP = 9
    MIDDLE_PIP = 10
    MIDDLE_DIP = 11
    MIDDLE_TIP = 12
    RING_MCP = 13
    RING_PIP = 14
    RING_DIP = 15
    RING_TIP = 16
    PINKY_MCP = 17
    PINKY_PIP = 18
    PINKY_DIP = 19
    PINKY_TIP = 20


@dataclass(frozen=True)
class Landmark:
    """Raw MediaPipe coordinates: x rightward, y downward, z relative to wrist.

    Native x/y values are usually 0..1 but may leave the image bounds. They are
    deliberately not clamped, calibrated, or smoothed in Phase 2. z is not meters.
    """

    x: float
    y: float
    z: float


@dataclass(frozen=True)
class TrackedHand:
    """All landmarks and the physical hand label for a single detection.

    Handedness confidence describes left/right classification, not landmark
    position accuracy or a medical measurement.
    """

    hand: Literal["left", "right"]
    handedness_confidence: float
    landmarks: tuple[Landmark, ...]


@dataclass(frozen=True)
class TrackingResult:
    """One processed frame; an empty tuple means no hand was detected."""

    hands: tuple[TrackedHand, ...]
    processing_ms: float

    @property
    def tracking(self) -> bool:
        """Whether this frame contains at least one hand."""
        return bool(self.hands)
