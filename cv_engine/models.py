"""Application-owned hand data independent of MediaPipe protobuf objects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
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
    preserved unchanged; the separate control pipeline normalizes/smooths its
    palm-center output. z is not meters.
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


@dataclass(frozen=True)
class ControlPosition:
    """Palm control coordinates: x/y in 0..1, z in wrist-relative model units."""

    x: float
    y: float
    z: float


@dataclass(frozen=True)
class HandControl:
    """One hand's fresh control output or an explicit unavailable state.

    Lost states never expose a stale position. raw_position is the clamped,
    unfiltered palm center; the original landmarks remain in TrackingResult.
    """

    hand: Literal["left", "right"]
    status: Literal["tracking", "temporarily_lost", "lost"]
    handedness_confidence: float = 0.0
    raw_position: ControlPosition | None = None
    position: ControlPosition | None = None

    @property
    def tracking(self) -> bool:
        """Whether a fresh, accepted position is available."""
        return self.status == "tracking" and self.position is not None


@dataclass(frozen=True)
class ControlResult:
    """Independent states for observed hands; empty until the first accepted hand."""

    hands: tuple[HandControl, ...] = ()

    @property
    def tracking(self) -> bool:
        """Whether at least one hand has a fresh control position."""
        return any(hand.tracking for hand in self.hands)


class Gesture(StrEnum):
    """Original MotionPlay protocol-ready gesture names."""

    OPEN_HAND = "OPEN_HAND"
    FIST = "FIST"
    PINCH = "PINCH"
    POINT = "POINT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class GestureDetection:
    """A raw candidate and whether its landmark geometry was usable."""

    candidate: Gesture = Gesture.UNKNOWN
    valid: bool = False


@dataclass(frozen=True)
class HandGesture:
    """One hand's gesture state; unavailable hands never retain an action."""

    hand: Literal["left", "right"]
    tracking: bool = False
    candidate: Gesture = Gesture.UNKNOWN
    gesture: Gesture = Gesture.UNKNOWN
    consecutive_frames: int = 0
    changed: bool = False


@dataclass(frozen=True)
class GestureResult:
    """Independent gesture results for the observed physical hand labels."""

    hands: tuple[HandGesture, ...] = ()
