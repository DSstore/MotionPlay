"""Test camera backend selection: DirectShow by default on Windows, fallbacks, and the CAMERA_BACKEND setting."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2

from cv_engine.camera import Camera, CameraError, backend_flag
from shared.config import CameraSettings, ConfigurationError, load_settings


def capture(opened: bool = True, backend: str = "DSHOW") -> MagicMock:
    cap = MagicMock()
    cap.isOpened.return_value = opened
    cap.get.return_value = 30.0
    cap.getBackendName.return_value = backend
    return cap


class BackendFlagTests(unittest.TestCase):
    def test_auto_means_directshow_on_windows_and_the_opencv_default_elsewhere(self) -> None:
        self.assertEqual(cv2.CAP_DSHOW, backend_flag("auto", "win32"))
        self.assertIsNone(backend_flag("auto", "linux"))
        self.assertIsNone(backend_flag("auto", "darwin"))

    def test_explicit_choices_do_not_depend_on_the_platform(self) -> None:
        for platform in ("win32", "linux"):
            self.assertEqual(cv2.CAP_DSHOW, backend_flag("dshow", platform))
            self.assertEqual(cv2.CAP_MSMF, backend_flag("msmf", platform))
            self.assertIsNone(backend_flag("default", platform))


class OpenTests(unittest.TestCase):
    @patch("cv_engine.camera.sys.platform", "win32")
    @patch("cv_engine.camera.cv2.VideoCapture")
    def test_windows_auto_opens_with_directshow(self, factory: MagicMock) -> None:
        factory.return_value = capture()
        with Camera(CameraSettings(index=1)):
            pass
        factory.assert_called_once_with(1, cv2.CAP_DSHOW)

    @patch("cv_engine.camera.sys.platform", "linux")
    @patch("cv_engine.camera.cv2.VideoCapture")
    def test_other_platforms_use_the_opencv_default(self, factory: MagicMock) -> None:
        factory.return_value = capture(backend="V4L2")
        with Camera(CameraSettings(index=1)):
            pass
        factory.assert_called_once_with(1)

    @patch("cv_engine.camera.sys.platform", "win32")
    @patch("cv_engine.camera.cv2.VideoCapture")
    def test_auto_falls_back_to_the_default_backend_when_directshow_cannot_open(self, factory: MagicMock) -> None:
        failed, working = capture(opened=False), capture(backend="MSMF")
        factory.side_effect = [failed, working]
        with self.assertLogs("motionplay.cv_engine.camera", level="INFO") as logs:
            with Camera(CameraSettings()) as camera:
                self.assertIs(working, camera._capture)
        self.assertEqual([((0, cv2.CAP_DSHOW),), ((0,),)], [call[0:1] for call in factory.call_args_list])
        failed.release.assert_called_once()  # the failed attempt is released, not leaked
        text = "\n".join(logs.output)
        self.assertIn("DirectShow could not open webcam 0", text)
        self.assertIn("via MSMF", text)

    @patch("cv_engine.camera.cv2.VideoCapture")
    def test_an_explicit_backend_is_respected_and_does_not_fall_back(self, factory: MagicMock) -> None:
        factory.return_value = capture(opened=False)
        with self.assertRaisesRegex(CameraError, "Cannot open webcam"):
            Camera(CameraSettings(backend="msmf")).open()
        factory.assert_called_once_with(0, cv2.CAP_MSMF)

    @patch("cv_engine.camera.sys.platform", "win32")
    @patch("cv_engine.camera.cv2.VideoCapture")
    def test_when_every_backend_fails_the_error_says_what_to_do(self, factory: MagicMock) -> None:
        factory.side_effect = [capture(opened=False), capture(opened=False)]
        with self.assertRaisesRegex(CameraError, "close other camera apps"):
            Camera(CameraSettings()).open()
        self.assertEqual(2, factory.call_count)

    @patch("cv_engine.camera.cv2.VideoCapture")
    def test_the_backend_that_was_used_is_logged(self, factory: MagicMock) -> None:
        factory.return_value = capture(backend="DSHOW")
        with self.assertLogs("motionplay.cv_engine.camera", level="INFO") as logs:
            Camera(CameraSettings(backend="dshow")).open()
        self.assertIn("Webcam opened via DSHOW", "\n".join(logs.output))


class PropertyTests(unittest.TestCase):
    """Setting a capture property can take over a second on DirectShow, so values already in place are left alone."""

    @patch("cv_engine.camera.cv2.VideoCapture")
    def test_properties_the_camera_already_reports_are_not_set_again(self, factory: MagicMock) -> None:
        cap = capture()
        reported = {cv2.CAP_PROP_FRAME_WIDTH: 640.0, cv2.CAP_PROP_FRAME_HEIGHT: 480.0, cv2.CAP_PROP_FPS: 0.0}
        cap.get.side_effect = lambda prop: reported.get(prop, 0.0)
        factory.return_value = cap
        Camera(CameraSettings(backend="dshow")).open()
        # Size matches, so only the frame rate (which this camera reports as 0: unknown) is set.
        self.assertEqual([((cv2.CAP_PROP_FPS, 30),)], [call[0:1] for call in cap.set.call_args_list])

    @patch("cv_engine.camera.cv2.VideoCapture")
    def test_properties_that_differ_are_set(self, factory: MagicMock) -> None:
        cap = capture()
        cap.get.side_effect = lambda prop: 10.0
        factory.return_value = cap
        Camera(CameraSettings(width=800, height=600, fps=24, backend="dshow")).open()
        self.assertEqual({cv2.CAP_PROP_FRAME_WIDTH: 800, cv2.CAP_PROP_FRAME_HEIGHT: 600, cv2.CAP_PROP_FPS: 24},
                         {c.args[0]: c.args[1] for c in cap.set.call_args_list})

    @patch("cv_engine.camera.cv2.VideoCapture")
    def test_a_declined_property_is_not_fatal(self, factory: MagicMock) -> None:
        cap = capture()
        cap.get.side_effect = lambda prop: 0.0
        cap.set.return_value = False
        factory.return_value = cap
        with Camera(CameraSettings(backend="dshow")):
            pass  # opens anyway; the device may negotiate other values


class SettingTests(unittest.TestCase):
    def load(self, **environ):
        with tempfile.TemporaryDirectory() as directory:
            return load_settings(Path(directory) / ".env", environ=environ)

    def test_default_is_auto_and_values_are_case_insensitive(self) -> None:
        self.assertEqual("auto", self.load().camera.backend)
        for value in ("DShow", "MSMF", "default", "AUTO"):
            self.assertEqual(value.lower(), self.load(CAMERA_BACKEND=value).camera.backend)

    def test_unknown_values_are_refused_before_the_camera_opens(self) -> None:
        for value in ("directshow", "v4l2", "", "1"):
            with self.subTest(value=value), self.assertRaisesRegex(ConfigurationError, "CAMERA_BACKEND"):
                self.load(CAMERA_BACKEND=value)
        with self.assertRaises(ConfigurationError):
            CameraSettings(backend="nope")


if __name__ == "__main__":
    unittest.main()
