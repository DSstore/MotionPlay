"""Load validated configuration without starting application services."""

from __future__ import annotations

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
class Settings:
    """Validated application settings; connection URIs stay out of repr()."""

    log_level: str
    log_dir: Path
    udp_host: str
    cv_to_unity_port: int
    unity_to_python_port: int
    mongodb_uri: str = field(repr=False)
    mongodb_database: str


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
    )
