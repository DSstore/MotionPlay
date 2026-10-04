"""Load validated configuration without starting application services."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class ConfigurationError(ValueError):
    """A configuration setting is missing or invalid."""


@dataclass(frozen=True)
class CameraSettings:
    """Requested capture settings; a device may negotiate different dimensions/FPS."""

    index: int = 0
    width: int = 640
    height: int = 480
    fps: int = 30
    mirror: bool = True


@dataclass(frozen=True)
class TrackingSettings:
    """MediaPipe detection/tracking thresholds, not handedness confidence gates."""

    max_hands: int = 1
    model_complexity: int = 1
    detection_confidence: float = 0.6
    tracking_confidence: float = 0.6


@dataclass(frozen=True)
class Settings:
    """Validated application settings; connection URIs stay out of repr()."""

    log_level: str
    log_dir: Path
    udp_host: str
    cv_to_unity_port: int
    unity_to_python_port: int
    mongodb_uri: str = field(repr=False)
    mongodb_database: str
    camera: CameraSettings = field(default_factory=CameraSettings)
    tracking: TrackingSettings = field(default_factory=TrackingSettings)


def _value(values: Mapping[str, str | None], name: str, default: str) -> str:
    """Read a non-empty setting without exposing its value in errors."""
    value = values.get(name, default)
    if value is None or not value.strip():
        raise ConfigurationError(f"{name} must not be empty.")
    return value.strip()


def _port(values: Mapping[str, str | None], name: str, default: str) -> int:
    """Validate an unprivileged UDP port."""
    try:
        port = int(_value(values, name, default))
    except ValueError:
        raise ConfigurationError(f"{name} must be an integer from 1024 to 65535.") from None
    if not 1024 <= port <= 65535:
        raise ConfigurationError(f"{name} must be an integer from 1024 to 65535.")
    return port


def _integer(
    values: Mapping[str, str | None], name: str, default: int, low: int, high: int
) -> int:
    """Read a bounded integer setting without exposing its supplied value."""
    try:
        result = int(_value(values, name, str(default)))
    except ValueError:
        raise ConfigurationError(f"{name} must be an integer from {low} to {high}.") from None
    if not low <= result <= high:
        raise ConfigurationError(f"{name} must be an integer from {low} to {high}.")
    return result


def _confidence(values: Mapping[str, str | None], name: str, default: float) -> float:
    """Reject nonfinite and out-of-range MediaPipe probability thresholds."""
    try:
        result = float(_value(values, name, str(default)))
    except ValueError:
        raise ConfigurationError(f"{name} must be a finite number from 0.0 to 1.0.") from None
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise ConfigurationError(f"{name} must be a finite number from 0.0 to 1.0.")
    return result


def _boolean(values: Mapping[str, str | None], name: str, default: bool) -> bool:
    """Read explicit true/false values, accepting 1/0 for environment overrides."""
    value = _value(values, name, str(default)).lower()
    if value not in {"true", "false", "1", "0"}:
        raise ConfigurationError(f"{name} must be true, false, 1, or 0.")
    return value in {"true", "1"}


def load_settings(
    env_file: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Settings:
    """Load defaults, then .env, then environment overrides without mutating os.environ.

    Paths are relative to the project root, regardless of the working directory.
    Passing an explicit environment mapping allows deterministic tests. Variable
    interpolation is disabled so credentials containing '$' remain literal.
    """
    path = env_file if env_file is not None else PROJECT_ROOT / ".env"
    try:
        values: dict[str, str | None] = dict(dotenv_values(path, interpolate=False))
    except (OSError, UnicodeError):
        raise ConfigurationError("Cannot read the .env file; check its access and UTF-8 encoding.") from None
    values.update(os.environ if environ is None else environ)

    log_level = _value(values, "LOG_LEVEL", "INFO").upper()
    if log_level not in LOG_LEVELS:
        raise ConfigurationError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL.")
    log_dir = Path(_value(values, "LOG_DIR", "logs")).expanduser()
    if not log_dir.is_absolute():
        log_dir = PROJECT_ROOT / log_dir

    cv_port = _port(values, "CV_TO_UNITY_PORT", "5005")
    result_port = _port(values, "UNITY_TO_PYTHON_PORT", "5006")
    if cv_port == result_port:
        raise ConfigurationError("CV_TO_UNITY_PORT and UNITY_TO_PYTHON_PORT must differ.")

    mongodb_uri = _value(values, "MONGODB_URI", "mongodb://127.0.0.1:27017")
    if not mongodb_uri.startswith(("mongodb://", "mongodb+srv://")):
        raise ConfigurationError("MONGODB_URI must use mongodb:// or mongodb+srv://.")

    return Settings(
        log_level=log_level,
        log_dir=log_dir.resolve(),
        udp_host=_value(values, "UDP_HOST", "127.0.0.1"),
        cv_to_unity_port=cv_port,
        unity_to_python_port=result_port,
        mongodb_uri=mongodb_uri,
        mongodb_database=_value(values, "MONGODB_DATABASE", "motionplay"),
        camera=CameraSettings(
            index=_integer(values, "CAMERA_INDEX", 0, 0, 32),
            width=_integer(values, "CAMERA_WIDTH", 640, 160, 7680),
            height=_integer(values, "CAMERA_HEIGHT", 480, 120, 4320),
            fps=_integer(values, "CAMERA_FPS", 30, 1, 120),
            mirror=_boolean(values, "CAMERA_MIRROR", True),
        ),
        tracking=TrackingSettings(
            max_hands=_integer(values, "TRACKING_MAX_HANDS", 1, 1, 2),
            model_complexity=_integer(values, "TRACKING_MODEL_COMPLEXITY", 1, 0, 1),
            detection_confidence=_confidence(values, "TRACKING_DETECTION_CONFIDENCE", 0.6),
            tracking_confidence=_confidence(values, "TRACKING_MIN_CONFIDENCE", 0.6),
        ),
    )
