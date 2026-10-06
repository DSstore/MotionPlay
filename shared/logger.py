"""Configure console logging and bounded local log files."""

from __future__ import annotations

import logging
import os
import platform
import sys
import threading
from logging.handlers import RotatingFileHandler

from shared.config import Settings


def configure_logging(settings: Settings, *, console: bool = True) -> logging.Logger:
    """Configure the MotionPlay logger; repeated setup does not duplicate handlers.

    ``console=False`` keeps log lines out of the terminal (for commands whose normal output is the result).

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
    for handler in (file_handler, console_handler) if console else (file_handler,):
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


_hook_state: dict = {}


def install_excepthooks(logger: logging.Logger) -> None:
    """Record uncaught exceptions (main thread and other threads) in the log, with their traceback.

    The original hooks still run afterwards, so the usual message still reaches the console. Safe to call
    more than once: later calls only change which logger receives the records.
    """
    _hook_state["logger"] = logger
    if "sys" in _hook_state:
        return
    _hook_state["sys"], _hook_state["threading"] = sys.excepthook, threading.excepthook

    def log_uncaught(exc_type, exc, traceback) -> None:
        if not issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            _hook_state["logger"].critical("Uncaught %s: %s", exc_type.__name__, exc, exc_info=(exc_type, exc, traceback))
        _hook_state["sys"](exc_type, exc, traceback)

    def log_uncaught_in_thread(args: threading.ExceptHookArgs) -> None:
        if not issubclass(args.exc_type, SystemExit):
            name = args.thread.name if args.thread is not None else "unknown"
            _hook_state["logger"].critical("Uncaught %s in thread %s: %s", args.exc_type.__name__, name,
                                           args.exc_value, exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        _hook_state["threading"](args)

    sys.excepthook = log_uncaught
    threading.excepthook = log_uncaught_in_thread


def remove_excepthooks() -> None:
    """Restore the hooks that were in place before ``install_excepthooks`` (used by tests)."""
    if "sys" in _hook_state:
        sys.excepthook, threading.excepthook = _hook_state.pop("sys"), _hook_state.pop("threading")
    _hook_state.clear()


def start_logging(settings: Settings, component: str, *, console: bool = True) -> logging.Logger:
    """Set up file and console logging for a command, log uncaught errors, and write a start-up line.

    The start-up line names the component, process, Python version, log level and log file, which is
    what a bug report needs. It never includes credentials or connection strings.
    """
    logger = configure_logging(settings, console=console)
    install_excepthooks(logger)
    logger.info("MotionPlay %s starting (pid %d, Python %s, log level %s, log file %s).", component, os.getpid(),
                platform.python_version(), settings.log_level, settings.log_dir / "motionplay.log")
    return logger
