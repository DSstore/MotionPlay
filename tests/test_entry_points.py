"""Test the command-line entry points: result receiver, health check, and CV controller.

These cover argument handling, exit codes, and error messages. The real receiver is run on a loopback port;
the controller's heavy parts (camera, MediaPipe) are replaced, and logging is kept away from the real log file.
"""

from __future__ import annotations

import contextlib
import io
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import health_check
from backend import result_receiver
from backend.auth import AuthError
from backend.storage import SqliteResultStore, StorageError
from cv_engine import controller
from shared.config import ConfigurationError
from shared.protocol import decode_session_end
from tests.test_results import make_result


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def run_main(main, argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class ReceiverMainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db = Path(self.folder.name) / "m.db"
        self.port = free_port()

    def args(self, *extra: str) -> list[str]:
        return ["--store", "sqlite", "--file", str(self.db), "--port", str(self.port), *extra]

    def deliver(self, result, extra: tuple[str, ...] = ()) -> tuple[int, str, str, bytes]:
        """Run main() in a thread and send one result to it, retrying until the port is open."""
        outcome: dict = {}
        thread = threading.Thread(target=lambda: outcome.update(
            zip(("code", "out", "err"), run_main(result_receiver.main, self.args("--max-results", "1",
                                                                              "--timeout", "10", *extra)))))
        thread.start()
        reply = b""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.settimeout(0.3)
            for _ in range(40):
                try:
                    client.sendto(result.to_bytes(), ("127.0.0.1", self.port))
                    reply, _ = client.recvfrom(2048)
                    break
                except (socket.timeout, ConnectionResetError):
                    time.sleep(0.1)
        thread.join(timeout=10)
        self.assertFalse(thread.is_alive(), "main() did not return")
        return outcome["code"], outcome["out"], outcome["err"], reply

    def test_saves_a_round_without_a_player_and_exits_cleanly(self) -> None:
        result = make_result()
        code, out, _err, reply = self.deliver(result)
        self.assertEqual(0, code)
        self.assertIn("No --user given", out)
        self.assertIn(b"stored", reply)
        store = SqliteResultStore(self.db)
        self.addCleanup(store.close)
        saved = store.get(result.session_id)
        self.assertIsNotNone(saved)
        self.assertIsNone(saved["user_id"])

    def test_saves_the_round_for_the_logged_in_player(self) -> None:
        result = make_result()
        player = SimpleNamespace(username="sam", user_id="user-1")
        with patch("backend.result_receiver.log_in", return_value=player) as log_in:
            code, out, _err, _reply = self.deliver(result, ("--user", "sam"))
        self.assertEqual(0, code)
        self.assertIn("Saving rounds for sam", out)
        self.assertEqual("sam", log_in.call_args.args[0])
        store = SqliteResultStore(self.db)
        self.addCleanup(store.close)
        self.assertEqual("user-1", store.get(result.session_id)["user_id"])

    def test_idle_timeout_is_reported_as_failure(self) -> None:
        code, _out, err = run_main(result_receiver.main, self.args("--timeout", "0.6"))
        self.assertEqual(1, code)
        self.assertIn("idle timeout", err)

    def test_port_outside_the_allowed_range_is_refused(self) -> None:
        for port in ("80", "70000"):
            with self.subTest(port=port):
                code, _out, err = run_main(result_receiver.main, ["--store", "sqlite", "--file", str(self.db),
                                                                  "--port", port])
                self.assertEqual(1, code)
                self.assertIn("1024 to 65535", err)

    def test_a_failed_login_stops_before_listening(self) -> None:
        with patch("backend.result_receiver.log_in", side_effect=AuthError("Wrong username or password.")):
            code, _out, err = run_main(result_receiver.main, self.args("--user", "sam"))
        self.assertEqual(1, code)
        self.assertIn("Login failed", err)
        self.assertIn("Wrong username or password", err)

    def test_a_port_already_in_use_is_a_clear_error(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as holder:
            holder.bind(("127.0.0.1", self.port))
            code, _out, err = run_main(result_receiver.main, self.args("--timeout", "1"))
        self.assertEqual(1, code)
        self.assertIn("Result receiver error", err)

    def test_a_storage_failure_is_a_clear_error(self) -> None:
        with patch("backend.result_receiver.store_from_args", side_effect=StorageError("disk full")):
            code, _out, err = run_main(result_receiver.main, self.args())
        self.assertEqual(1, code)
        self.assertIn("disk full", err)

    def test_ctrl_c_stops_quietly_and_closes_the_store(self) -> None:
        store = MagicMock()
        with patch("backend.result_receiver.store_from_args", return_value=store), \
                patch("backend.result_receiver.serve", side_effect=KeyboardInterrupt):
            code, out, _err = run_main(result_receiver.main, self.args())
        self.assertEqual(0, code)
        self.assertIn("Result receiver stopped", out)
        store.close.assert_called_once()

    def test_the_store_is_closed_after_an_error_too(self) -> None:
        store = MagicMock()
        with patch("backend.result_receiver.store_from_args", return_value=store), \
                patch("backend.result_receiver.serve", side_effect=OSError("boom")):
            code, _out, _err = run_main(result_receiver.main, self.args())
        self.assertEqual(1, code)
        store.close.assert_called_once()

    def test_a_delivered_result_decodes_as_sent(self) -> None:
        result = make_result()
        self.assertEqual(result, decode_session_end(result.to_bytes()))


class HealthCheckTests(unittest.TestCase):
    """main() with the logger replaced so it does not write to the real log file."""

    def run_check(self, **patches):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch("shared.logger.configure_logging", return_value=MagicMock()))
        for target, value in patches.items():
            stack.enter_context(patch(target.replace("__", "."), **value))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = health_check.main()
        return code, out.getvalue()

    def test_passes_on_this_environment(self) -> None:
        code, out = self.run_check()
        self.assertEqual(0, code, out)
        self.assertIn("READY", out)
        self.assertNotIn("FAIL", out)

    def test_a_wrong_python_version_fails(self) -> None:
        code, out = self.run_check(app__health_check__REQUIRED_PYTHON={"new": (2, 7)})
        self.assertEqual(1, code)
        self.assertIn("FAIL Python", out)
        self.assertIn("FAILED: 1 check(s)", out)

    def test_a_dependency_that_will_not_import_fails_by_name(self) -> None:
        real = health_check.importlib.import_module

        def broken(name, *args):
            if name == "cv2":
                raise ImportError("DLL load failed")
            return real(name, *args)

        code, out = self.run_check(app__health_check__importlib__import_module={"side_effect": broken})
        self.assertEqual(1, code)
        self.assertIn("FAIL OpenCV: ImportError: DLL load failed", out)
        self.assertEqual(1, sum(line.startswith("FAIL ") for line in out.splitlines()))

    def test_a_configuration_error_fails(self) -> None:
        code, out = self.run_check(shared__config__load_settings={"side_effect": ConfigurationError("bad .env")})
        self.assertEqual(1, code)
        self.assertIn("FAIL configuration/logging: ConfigurationError: bad .env", out)

    def test_package_version_falls_back_when_not_installed(self) -> None:
        self.assertEqual("version unavailable", health_check._package_version(("no-such-distribution-xyz",)))
        self.assertNotEqual("version unavailable", health_check._package_version(("no-such-xyz", "numpy")))


class ControllerMainTests(unittest.TestCase):
    def run_cli(self, argv: list[str], run=None, settings_error=None):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch("cv_engine.controller.configure_logging"))
        stack.enter_context(patch("cv_engine.controller.load_settings",
                                  side_effect=settings_error, return_value=MagicMock()))
        runner = stack.enter_context(patch("cv_engine.controller.run_tracking", **(run or {"return_value": 0})))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = controller.main(argv)
        return code, err.getvalue(), runner

    def test_success_passes_the_command_line_options_through(self) -> None:
        code, _err, runner = self.run_cli(["--no-preview", "--no-udp", "--max-frames", "7"])
        self.assertEqual(0, code)
        self.assertEqual({"show_preview": False, "max_frames": 7, "send_udp": False}, runner.call_args.kwargs)

    def test_defaults_show_the_preview_and_send_udp(self) -> None:
        _code, _err, runner = self.run_cli([])
        self.assertEqual({"show_preview": True, "max_frames": None, "send_udp": True}, runner.call_args.kwargs)

    def test_a_configuration_error_stops_before_anything_starts(self) -> None:
        code, err, runner = self.run_cli([], settings_error=ConfigurationError("CAMERA_INDEX is bad"))
        self.assertEqual(1, code)
        self.assertIn("CAMERA_INDEX is bad", err)
        runner.assert_not_called()

    def test_each_failure_kind_exits_with_status_1(self) -> None:
        from cv_engine.errors import CVEngineError

        for error in (CVEngineError("camera gone"), ImportError("dll"), OSError("native"), RuntimeError("surprise")):
            with self.subTest(error=type(error).__name__), self.assertLogs("motionplay.cv_engine.controller"):
                code, _err, _runner = self.run_cli([], run={"side_effect": error})
                self.assertEqual(1, code)

    def test_ctrl_c_is_a_clean_stop(self) -> None:
        with self.assertLogs("motionplay.cv_engine.controller", level="INFO") as logs:
            code, _err, _runner = self.run_cli([], run={"side_effect": KeyboardInterrupt})
        self.assertEqual(0, code)
        self.assertTrue(any("stopped by user" in line for line in logs.output))

    def test_a_bad_frame_limit_is_rejected_by_the_parser(self) -> None:
        for value in ("0", "-3", "many"):
            with self.subTest(value=value), contextlib.redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit) as raised:
                controller.main(["--max-frames", value])
            self.assertEqual(2, raised.exception.code)

    def test_run_tracking_refuses_a_non_positive_frame_limit(self) -> None:
        for limit in (0, -1):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                controller.run_tracking(MagicMock(), max_frames=limit)


if __name__ == "__main__":
    unittest.main()
