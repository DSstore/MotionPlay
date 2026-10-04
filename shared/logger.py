"""Configure console logging and bounded local log files."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from shared.config import Settings


def configure_logging(settings: Settings) -> logging.Logger:
    """Configure the MotionPlay logger; repeated setup does not duplicate handlers.

    The application logger owns its handlers, leaving host/root logging alone.
    Child loggers should use names such as 'motionplay.cv_engine'. Never log
    credentials, configuration objects, or webcam frames.
    """
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        settings.log_dir / "motionplay.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    console_handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    logger = logging.getLogger("motionplay")
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(settings.log_level)
    logger.propagate = False
    for handler in (file_handler, console_handler):
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger
