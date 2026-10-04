"""Exercise Phase 2 using synthetic images, native-result doubles, and fake devices."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from cv_engine.camera import Camera, CameraError
from cv_engine.controller import main, run_tracking
from cv_engine.hand_tracker import HandTracker, TrackingError, decode_hands
from cv_engine.models import HandLandmark, TrackingResult
from cv_engine.preview import Preview, PreviewError, draw_overlay
from shared.config import CameraSettings, ConfigurationError, TrackingSettings, load_settings


def native_result(label: str = "Right") -> SimpleNamespace:
    """Represent the shape of a MediaPipe result; these are not realistic hand poses."""
    points = [SimpleNamespace(x=i / 20, y=0.5, z=-i / 100) for i in range(21)]
    return SimpleNamespace(
        multi_hand_landmarks=[SimpleNamespace(landmark=points)],
        multi_handedness=[SimpleNamespace(classification=[SimpleNamespace(label=label, score=0.94)])],
    )


def no_hand_result() -> SimpleNamespace:
    """Represent a native result with no hand detections."""
    return SimpleNamespace(multi_hand_landmarks=None, multi_handedness=None)


class CVConfigurationTests(unittest.TestCase):
    """Reject incorrect camera and tracker values before opening resources."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env_path = Path(self.directory.name) / ".env"

    def test_defaults_target_one_mirrored_hand_and_30_fps(self) -> None:
        settings = load_settings(self.env_path, environ={})
        self.assertEqual(settings.camera, CameraSettings())
        self.assertEqual(settings.tracking, TrackingSettings())

    def test_environment_overrides_capture_and_tracking(self) -> None:
        settings = load_settings(self.env_path, environ={
            "CAMERA_INDEX": "2", "CAMERA_MIRROR": "false",
            "CAMERA_FPS": "24", "TRACKING_MAX_HANDS": "2",
            "TRACKING_DETECTION_CONFIDENCE": "0.75",
        })
        self.assertEqual(settings.camera.index, 2)
        self.assertFalse(settings.camera.mirror)
        self.assertEqual(settings.camera.fps, 24)
        self.assertEqual(settings.tracking.max_hands, 2)
        self.assertEqual(settings.tracking.detection_confidence, 0.75)

    def test_invalid_camera_and_model_options(self) -> None:
        cases = {
            "CAMERA_INDEX": "-1", "CAMERA_WIDTH": "0", "CAMERA_HEIGHT": "bad",
            "CAMERA_FPS": "0", "CAMERA_MIRROR": "maybe",
            "TRACKING_MAX_HANDS": "3", "TRACKING_MODEL_COMPLEXITY": "2",
        }
        for key, value in cases.items():
            with self.subTest(key=key), self.assertRaises(ConfigurationError):
                load_settings(self.env_path, environ={key: value})

    def test_nonfinite_and_out_of_range_thresholds(self) -> None:
        for key in ("TRACKING_DETECTION_CONFIDENCE", "TRACKING_MIN_CONFIDENCE"):
            for value in ("nan", "inf", "-0.1", "1.1", "", "bad"):
                with self.subTest(key=key, value=value), self.assertRaises(ConfigurationError):
                    load_settings(self.env_path, environ={key: value})


class CameraTests(unittest.TestCase):
    """Verify failures and device release without a real webcam."""

    @patch("cv_engine.camera.cv2.VideoCapture")
    def test_unavailable_camera_reports_actions_and_releases(self, factory: MagicMock) -> None:
        capture = factory.return_value
        capture.isOpened.return_value = False
        with self.assertRaisesRegex(CameraError, "camera permissions"):
            Camera(CameraSettings()).open()
        capture.release.assert_called_once()

    @patch("cv_engine.camera.cv2.VideoCapture")
    def test_capture_resource_is_released_after_failure_in_context(self, factory: MagicMock) -> None:
        capture = factory.return_value
        capture.isOpened.return_value = True
        capture.get.return_value = 30.0
        capture.read.return_value = (True, np.zeros((4, 6, 3), dtype=np.uint8))
        with self.assertRaisesRegex(RuntimeError, "test failure"):
            with Camera(CameraSettings(index=2)) as camera:
                self.assertEqual(camera.read().shape, (4, 6, 3))
                raise RuntimeError("test failure")
        factory.assert_called_once_with(2)
        capture.release.assert_called_once()
        camera.close()
        capture.release.assert_called_once()

    @patch("cv_engine.camera.cv2.VideoCapture")
    def test_empty_or_failed_frame_is_reported(self, factory: MagicMock) -> None:
        capture = factory.return_value
        capture.isOpened.return_value = True
        capture.get.return_value = 30.0
        with Camera(CameraSettings()) as camera:
            for response in ((False, None), (True, None), (True, np.empty((0, 0, 3), dtype=np.uint8))):
                capture.read.return_value = response
                with self.subTest(response=response[0]), self.assertRaisesRegex(CameraError, "returned no image"):
                    camera.read()
        capture.release.assert_called_once()

    def test_read_before_opening_is_rejected(self) -> None:
        with self.assertRaisesRegex(CameraError, "not open"):
            Camera(CameraSettings()).read()


class HandDecodingTests(unittest.TestCase):
    """Preserve native coordinates and correctly associate handedness labels."""

    def test_all_21_landmarks_and_physical_right_label_are_preserved(self) -> None:
        hands = decode_hands(native_result(), mirrored_input=True)
        self.assertEqual(len(hands), 1)
        self.assertEqual(hands[0].hand, "right")
        self.assertEqual(hands[0].handedness_confidence, 0.94)
        self.assertEqual(len(hands[0].landmarks), 21)
        self.assertEqual(hands[0].landmarks[HandLandmark.INDEX_TIP].x, 0.4)
        self.assertEqual(hands[0].landmarks[HandLandmark.PINKY_TIP].z, -0.2)

    def test_unmirrored_labels_are_swapped(self) -> None:
        self.assertEqual(decode_hands(native_result("Right"), False)[0].hand, "left")
        self.assertEqual(decode_hands(native_result("Left"), False)[0].hand, "right")

    def test_out_of_frame_coordinates_remain_raw(self) -> None:
        result = native_result()
        result.multi_hand_landmarks[0].landmark[0].x = -0.05
        result.multi_hand_landmarks[0].landmark[0].y = 1.02
        point = decode_hands(result, True)[0].landmarks[HandLandmark.WRIST]
        self.assertEqual((point.x, point.y), (-0.05, 1.02))

    def test_no_detection_becomes_empty_result(self) -> None:
        hands = decode_hands(no_hand_result(), True)
        self.assertEqual(hands, ())
        self.assertFalse(TrackingResult(hands, processing_ms=2.0).tracking)

    def test_invalid_landmark_count_or_labels_are_rejected(self) -> None:
        missing_landmark = native_result()
        missing_landmark.multi_hand_landmarks[0].landmark.pop()
        missing_label = native_result()
        missing_label.multi_handedness = []
        empty_classification = native_result()
        empty_classification.multi_handedness[0].classification = []
        for result in (missing_landmark, missing_label, empty_classification, native_result("Unknown")):
            with self.subTest(result=result), self.assertRaises(TrackingError):
                decode_hands(result, True)

    def test_two_hands_keep_their_matching_landmarks_and_labels(self) -> None:
        result = native_result("Left")
        second = native_result("Right")
        second.multi_hand_landmarks[0].landmark[0].x = 0.8
        result.multi_hand_landmarks += second.multi_hand_landmarks
        result.multi_handedness += second.multi_handedness
        hands = decode_hands(result, True)
        self.assertEqual([hand.hand for hand in hands], ["left", "right"])
        self.assertEqual(hands[1].landmarks[HandLandmark.WRIST].x, 0.8)


class TrackerTests(unittest.TestCase):
    """Check color conversion, model configuration, and cleanup using a fake engine."""

    @patch("mediapipe.solutions.hands.Hands")
    def test_process_converts_bgr_to_readonly_rgb_and_preserves_input(self, factory: MagicMock) -> None:
        engine = factory.return_value
        engine.process.return_value = native_result()
        frame = np.full((2, 3, 3), [10, 20, 30], dtype=np.uint8)
        original = frame.copy()
        with HandTracker(TrackingSettings()) as tracker:
            result = tracker.process(frame)
        received = engine.process.call_args.args[0]
        np.testing.assert_array_equal(received[0, 0], [30, 20, 10])
        np.testing.assert_array_equal(frame, original)
        self.assertFalse(received.flags.writeable)
        self.assertTrue(result.tracking)
        self.assertGreaterEqual(result.processing_ms, 0)
        factory.assert_called_once_with(
            static_image_mode=False, max_num_hands=1, model_complexity=1,
            min_detection_confidence=0.6, min_tracking_confidence=0.6,
        )
        engine.close.assert_called_once()

    @patch("mediapipe.solutions.hands.Hands", side_effect=RuntimeError("test native failure"))
    def test_initialization_failure_explains_environment_fix(self, factory: MagicMock) -> None:
        with self.assertRaisesRegex(TrackingError, "Python 3.11"):
            HandTracker(TrackingSettings()).open()

    @patch("mediapipe.solutions.hands.Hands")
    def test_processing_failure_releases_the_engine(self, factory: MagicMock) -> None:
        engine = factory.return_value
        engine.process.side_effect = RuntimeError("test processing failure")
        with self.assertRaisesRegex(TrackingError, "could not process"):
            with HandTracker(TrackingSettings()) as tracker:
                tracker.process(np.zeros((2, 2, 3), dtype=np.uint8))
        engine.close.assert_called_once()
        tracker.close()
        engine.close.assert_called_once()

    @patch("mediapipe.solutions.hands.Hands")
    def test_invalid_frames_are_rejected_before_inference(self, factory: MagicMock) -> None:
        with HandTracker(TrackingSettings()) as tracker:
            for frame in (
                np.zeros((2, 2), dtype=np.uint8),
                np.zeros((2, 2, 3), dtype=np.float32),
                np.zeros((0, 2, 3), dtype=np.uint8),
            ):
                with self.subTest(shape=frame.shape), self.assertRaisesRegex(TrackingError, "BGR image"):
                    tracker.process(frame)
        factory.return_value.process.assert_not_called()

    def test_processing_before_initialization_is_rejected(self) -> None:
        with self.assertRaisesRegex(TrackingError, "not initialized"):
            HandTracker(TrackingSettings()).process(np.zeros((2, 2, 3), dtype=np.uint8))


class PreviewTests(unittest.TestCase):
    """Render in memory and verify display guarding without opening a window."""

    def test_rendering_keeps_raw_frame_unchanged(self) -> None:
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        result = TrackingResult(decode_hands(native_result(), True), processing_ms=10)
        output = draw_overlay(frame, result, loop_fps=30)
        self.assertEqual(output.shape, frame.shape)
        self.assertFalse(np.shares_memory(frame, output))
        self.assertTrue(np.any(output))
        self.assertFalse(np.any(frame))

    @patch("cv_engine.preview.sys.platform", "linux")
    @patch.dict("os.environ", {}, clear=True)
    @patch("cv_engine.preview.cv2.namedWindow")
    def test_no_display_is_reported_before_native_window_creation(self, create_window: MagicMock) -> None:
        with self.assertRaisesRegex(PreviewError, "--no-preview"):
            with Preview():
                pass
        create_window.assert_not_called()


class ControllerTests(unittest.TestCase):
    """Exercise tracking transitions and resource ownership with fake devices."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = load_settings(Path(self.directory.name) / ".env", environ={})

    @patch("cv_engine.preview.Preview")
    @patch("cv_engine.hand_tracker.HandTracker")
    @patch("cv_engine.camera.Camera")
    def test_headless_loop_mirrors_frames_logs_transitions_and_closes_resources(
        self, camera_factory: MagicMock, tracker_factory: MagicMock, preview_factory: MagicMock,
    ) -> None:
        camera = camera_factory.return_value.__enter__.return_value
        tracker = tracker_factory.return_value.__enter__.return_value
        frame = np.zeros((2, 3, 3), dtype=np.uint8)
        frame[:, 0] = [10, 20, 30]
        camera.read.return_value = frame
        tracker.process.side_effect = [
            TrackingResult(decode_hands(native_result(), True), 1),
            TrackingResult((), 1), TrackingResult((), 1),
        ]
        with self.assertLogs("motionplay.cv_engine.controller", level="INFO") as logs:
            self.assertEqual(run_tracking(self.settings, show_preview=False, max_frames=3), 3)
        messages = "\n".join(logs.output)
        self.assertEqual(messages.count("Hand tracking restored"), 1)
        self.assertEqual(messages.count("Hand tracking lost"), 1)
        np.testing.assert_array_equal(tracker.process.call_args_list[0].args[0], frame[:, ::-1])
        preview_factory.assert_not_called()
        camera_factory.return_value.__exit__.assert_called_once()
        tracker_factory.return_value.__exit__.assert_called_once()

    @patch("cv_engine.hand_tracker.HandTracker")
    @patch("cv_engine.camera.Camera")
    def test_tracker_startup_failure_still_closes_camera(
        self, camera_factory: MagicMock, tracker_factory: MagicMock,
    ) -> None:
        tracker_factory.return_value.__enter__.side_effect = TrackingError("test startup failure")
        with self.assertRaises(TrackingError):
            run_tracking(self.settings, show_preview=False, max_frames=1)
        camera_factory.return_value.__exit__.assert_called_once()

    @patch("cv_engine.controller.configure_logging")
    @patch("cv_engine.controller.load_settings")
    @patch("cv_engine.controller.run_tracking", side_effect=CameraError("Webcam unavailable"))
    def test_cli_camera_failure_returns_one(
        self, run: MagicMock, load: MagicMock, configure: MagicMock,
    ) -> None:
        load.return_value = self.settings
        with self.assertLogs("motionplay.cv_engine.controller", level="ERROR"):
            self.assertEqual(main(["--no-preview", "--max-frames", "1"]), 1)


if __name__ == "__main__":
    unittest.main()
