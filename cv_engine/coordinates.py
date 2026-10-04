"""Compute a palm center and bounded control coordinates without camera access."""

from __future__ import annotations

import math
from statistics import fmean

from cv_engine.models import ControlPosition, HandLandmark, Landmark, TrackedHand


PALM_LANDMARKS = (
    HandLandmark.WRIST, HandLandmark.INDEX_MCP, HandLandmark.MIDDLE_MCP,
    HandLandmark.RING_MCP, HandLandmark.PINKY_MCP,
)


def palm_center(hand: TrackedHand) -> Landmark:
    """Average wrist and four finger-base joints so fingertip flexion has no direct effect."""
    if len(hand.landmarks) != 21:
        raise ValueError("Palm-center calculation requires all 21 hand landmarks.")
    points = [hand.landmarks[index] for index in PALM_LANDMARKS]
    if not all(math.isfinite(value) for point in points for value in (point.x, point.y, point.z)):
        raise ValueError("Palm landmarks must contain finite coordinates.")
    return Landmark(
        x=fmean(point.x for point in points),
        y=fmean(point.y for point in points),
        z=fmean(point.z for point in points),
    )


def normalize_position(position: Landmark) -> ControlPosition:
    """Clamp native image-relative x/y; preserve finite z without scaling or mirroring.

    MediaPipe already reports x/y relative to image dimensions. Dividing these
    values by camera width/height again would be incorrect. Calibration mapping
    belongs to its own later stage.
    """
    if not all(math.isfinite(value) for value in (position.x, position.y, position.z)):
        raise ValueError("Control coordinates must be finite.")
    return ControlPosition(
        x=min(1.0, max(0.0, position.x)),
        y=min(1.0, max(0.0, position.y)),
        z=position.z,
    )
