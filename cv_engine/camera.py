"""Own the webcam resource and translate capture failures into useful errors."""

from __future__ import annotations

import logging
from types import TracebackType

import cv2

from cv_engine.errors import CVEngineError
from cv_engine.models import VideoFrame
from shared.config import CameraSettings


LOGGER = logging.getLogger("motionplay.cv_engine.camera")


class CameraError(CVEngineError):
    """Webcam opening or frame acquisition failed."""


class Camera:
    """An explicitly opened webcam; constructing this object accesses no device."""

    def __init__(self, settings: CameraSettings) -> None:
        self.settings = settings
        self._capture: cv2.VideoCapture | None = None

    def open(self) -> None:
        """Open the configured index and request capture properties."""
        if self._capture is not None:
            raise CameraError("The webcam is already open in this controller.")
        LOGGER.info("Opening webcam index %d.", self.settings.index)
        try:
            self._capture = cv2.VideoCapture(self.settings.index)
            if not self._capture.isOpened():
                raise CameraError(
                    f"Cannot open webcam index {self.settings.index}. Connect a webcam, "
                    "check CAMERA_INDEX and camera permissions, and close other camera apps."
                )
            for property_id, requested in (
                (cv2.CAP_PROP_FRAME_WIDTH, self.settings.width),
                (cv2.CAP_PROP_FRAME_HEIGHT, self.settings.height),
                (cv2.CAP_PROP_FPS, self.settings.fps),
            ):
                if not self._capture.set(property_id, requested):
                    LOGGER.debug("Webcam declined capture property %d.", property_id)
            LOGGER.info(
                "Webcam opened; reported capture %.0fx%.0f at %.1f FPS (device report, not measured).",
                self._capture.get(cv2.CAP_PROP_FRAME_WIDTH),
                self._capture.get(cv2.CAP_PROP_FRAME_HEIGHT),
                self._capture.get(cv2.CAP_PROP_FPS),
            )
        except (CameraError, cv2.error):
            self.close()
            raise CameraError(
                f"Cannot open webcam index {self.settings.index}. Connect a webcam, "
                "check CAMERA_INDEX and camera permissions, and close other camera apps."
            ) from None

    def read(self) -> VideoFrame:
        """Read one BGR image or report an unavailable/disconnected camera."""
        if self._capture is None:
            raise CameraError("The webcam is not open.")
        try:
            success, frame = self._capture.read()
        except cv2.error:
            success, frame = False, None
        if not success or frame is None or frame.size == 0:
            raise CameraError(
                "Webcam returned no image. It may be disconnected or in use; "
                "close other camera apps and restart tracking."
            )
        return frame

    def close(self) -> None:
        """Release the capture resource; safe to call more than once."""
        if self._capture is not None:
            self._capture.release()
            self._capture = None
            LOGGER.info("Webcam released.")

    def __enter__(self) -> Camera:
        self.open()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None,
        exc: BaseException | None, traceback: TracebackType | None,
    ) -> None:
        self.close()
