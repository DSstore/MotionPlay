"""Test configuration boundaries and logging using only temporary local files."""

from __future__ import annotations

import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shared.config import PROJECT_ROOT, ConfigurationError, load_settings
from shared.logger import configure_logging


class ConfigurationTests(unittest.TestCase):
    """Validate settings without depending on developer configuration."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env_file = Path(self.temp.name) / ".env"

    def test_missing_env_uses_local_defaults(self) -> None:
        settings = load_settings(self.env_file, environ={})
        self.assertEqual(settings.cv_to_unity_port, 5005)
        self.assertEqual(settings.unity_to_python_port, 5006)
        self.assertEqual(settings.log_dir, PROJECT_ROOT / "logs")
        self.assertEqual(settings.mongodb_database, "motionplay")

    def test_environment_overrides_file_without_global_mutation(self) -> None:
        self.env_file.write_text("CV_TO_UNITY_PORT=6100\nLOG_LEVEL=debug\n", encoding="utf-8")
        with patch.dict(os.environ, {"CV_TO_UNITY_PORT": "6200"}, clear=True):
            before = dict(os.environ)
            settings = load_settings(self.env_file)
            self.assertEqual(settings.cv_to_unity_port, 6200)
            self.assertEqual(settings.log_level, "DEBUG")
            self.assertEqual(dict(os.environ), before)

    def test_invalid_ports_rejected(self) -> None:
        for value in ("", "abc", "1.5", "1023", "65536"):
            with self.subTest(value=value), self.assertRaises(ConfigurationError):
                load_settings(self.env_file, environ={"CV_TO_UNITY_PORT": value})

    def test_equal_ports_rejected(self) -> None:
        with self.assertRaises(ConfigurationError):
            load_settings(self.env_file, environ={"UNITY_TO_PYTHON_PORT": "5005"})

    def test_invalid_log_level_rejected(self) -> None:
        with self.assertRaises(ConfigurationError):
            load_settings(self.env_file, environ={"LOG_LEVEL": "LOUD"})

    def test_credentials_remain_literal_and_are_hidden_from_repr(self) -> None:
        secret = "mongodb://player:private${PASSWORD}@localhost:27017"
        self.env_file.write_text(f"MONGODB_URI='{secret}'\n", encoding="utf-8")
        settings = load_settings(self.env_file, environ={})
        self.assertEqual(settings.mongodb_uri, secret)
        self.assertNotIn("private", repr(settings))

    def test_invalid_uri_error_does_not_expose_value(self) -> None:
        with self.assertRaises(ConfigurationError) as error:
            load_settings(self.env_file, environ={"MONGODB_URI": "https://private-password"})
        self.assertNotIn("private-password", str(error.exception))

    def test_empty_settings_rejected(self) -> None:
        for key in ("UDP_HOST", "MONGODB_URI", "MONGODB_DATABASE", "LOG_DIR"):
            with self.subTest(key=key), self.assertRaises(ConfigurationError):
                load_settings(self.env_file, environ={key: " "})


class LoggingTests(unittest.TestCase):
    """Check file output and repeated setup without leaking handlers."""

    def test_repeated_setup_writes_one_entry_and_preserves_root_logger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root_handlers = logging.getLogger().handlers[:]
            settings = load_settings(
                Path(directory) / ".env", environ={"LOG_DIR": directory}
            )
            logger = configure_logging(settings)
            try:
                logger = configure_logging(settings)
                self.assertEqual(len(logger.handlers), 2)
                logger.info("foundation-test-entry")
                for handler in logger.handlers:
                    handler.flush()
                text = (Path(directory) / "motionplay.log").read_text(encoding="utf-8")
                self.assertEqual(text.count("foundation-test-entry"), 1)
                self.assertEqual(logging.getLogger().handlers, root_handlers)
            finally:
                for handler in logger.handlers[:]:
                    logger.removeHandler(handler)
                    handler.close()


if __name__ == "__main__":
    unittest.main()
