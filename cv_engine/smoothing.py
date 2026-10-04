"""A reusable exponential moving average with a normalized XY dead zone."""

from __future__ import annotations

import math

from cv_engine.models import ControlPosition


class PositionSmoother:
    """Filter one hand independently; first observations seed the filter immediately."""

    def __init__(self, alpha: float = 0.35, dead_zone: float = 0.008) -> None:
        if not math.isfinite(alpha) or not 0 < alpha <= 1:
            raise ValueError("Smoothing alpha must be finite and in (0, 1].")
        if not math.isfinite(dead_zone) or not 0 <= dead_zone <= 1:
            raise ValueError("Dead zone must be finite and in [0, 1].")
        self.alpha = alpha
        self.dead_zone = dead_zone
        self._position: ControlPosition | None = None

    def update(self, new: ControlPosition) -> ControlPosition:
        """Apply EMA unless XY stays within the radius of the previous output.

        Compare the input against the output, not against the previous input:
        gradual movement can accumulate enough distance to leave the dead zone.
        While inside it, the entire previous position (including z) is held.
        """
        if not all(math.isfinite(value) for value in (new.x, new.y, new.z)):
            raise ValueError("Smoothing input must be finite.")
        if not 0 <= new.x <= 1 or not 0 <= new.y <= 1:
            raise ValueError("Smoothing input x/y must be normalized to [0, 1].")
        previous = self._position
        if previous is None:
            self._position = new
        elif self.dead_zone == 0 or math.hypot(new.x - previous.x, new.y - previous.y) > self.dead_zone:
            alpha = self.alpha
            self._position = ControlPosition(
                x=alpha * new.x + (1 - alpha) * previous.x,
                y=alpha * new.y + (1 - alpha) * previous.y,
                z=alpha * new.z + (1 - alpha) * previous.z,
            )
        return self._position

    def reset(self) -> None:
        """Discard history so the next observation seeds a new position."""
        self._position = None
