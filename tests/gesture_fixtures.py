"""Original synthetic hand layouts for testing geometry, not detector accuracy."""

from __future__ import annotations

import math

from cv_engine.models import Gesture, Landmark, TrackedHand


def gesture_hand(
    gesture: Gesture, label: str = "right", confidence: float = 0.95,
    scale: float = 0.2, angle: float = 0, mirrored: bool = False,
    offset: tuple[float, float] = (0.5, 0.2), image_aspect_ratio: float = 1,
) -> TrackedHand:
    """Create explicit straight/bent chains, then transform the entire hand."""
    points = [(0.0, 0.0)] * 21
    points[1:5] = [(-0.25, 0.25), (-0.4, 0.4), (-0.55, 0.55), (-0.7, 0.7)]
    bases = ((-0.3, 0.65), (0.0, 0.75), (0.3, 0.7), (0.6, 0.6))
    for finger, (x, y) in enumerate(bases):
        folded = gesture == Gesture.FIST or (gesture == Gesture.POINT and finger > 0)
        folded = folded or (gesture == Gesture.UNKNOWN and finger > 1)
        if folded:
            chain = [(x, y), (x, y + 0.25), (x + 0.1, y + 0.25), (x + 0.1, y - 0.1)]
        else:
            chain = [(x, y), (x, y + 0.3), (x, y + 0.6), (x, y + 0.85)]
        start = 5 + finger * 4
        points[start:start + 4] = chain
    if gesture == Gesture.PINCH:
        points[4] = (0.0, 1.0)
        points[8] = (0.05, 1.0)
    radians = math.radians(angle)
    landmarks = []
    for x, y in points:
        if mirrored:
            x = -x
        rotated_x = x * math.cos(radians) - y * math.sin(radians)
        rotated_y = x * math.sin(radians) + y * math.cos(radians)
        landmarks.append(Landmark(
            x=offset[0] + rotated_x * scale,
            y=(offset[1] + rotated_y * scale) * image_aspect_ratio,
            z=0.0,
        ))
    return TrackedHand(label, confidence, tuple(landmarks))
