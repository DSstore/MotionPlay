"""Verify Phase 1 prerequisites without accessing cameras, GUI, or databases."""

from __future__ import annotations

import importlib
import sys
from importlib.metadata import PackageNotFoundError, version


REQUIRED_PYTHON = (3, 11)
DEPENDENCIES = (
    ("OpenCV", "cv2", ("opencv-contrib-python", "opencv-python")),
    ("MediaPipe", "mediapipe", ("mediapipe",)),
    ("PyQt6 widgets", "PyQt6.QtWidgets", ("PyQt6",)),
    ("PyMongo", "pymongo", ("pymongo",)),
    ("NumPy", "numpy", ("numpy",)),
    ("python-dotenv", "dotenv", ("python-dotenv",)),
    ("bcrypt", "bcrypt", ("bcrypt",)),
    ("Matplotlib", "matplotlib", ("matplotlib",)),
)


def _package_version(distributions: tuple[str, ...]) -> str:
    """Return the installed version for the first matching distribution."""
    for distribution in distributions:
        try:
            return version(distribution)
        except PackageNotFoundError:
            continue
    return "version unavailable"


def main() -> int:
    """Report each prerequisite and return a nonzero status on any failure."""
    print("MotionPlay Phase 1 health check")
    python_ok = sys.version_info[:2] == REQUIRED_PYTHON
    print(f"{'PASS' if python_ok else 'FAIL'} Python {sys.version.split()[0]} (requires 3.11.x)")
    failures = int(not python_ok)
    for label, module_name, distributions in DEPENDENCIES:
        try:
            importlib.import_module(module_name)
        except Exception as error:
            # Native-library failures can occur even when a package is installed.
            print(f"FAIL {label}: {type(error).__name__}: {error}")
            failures += 1
        else:
            print(f"PASS {label} {_package_version(distributions)}")

    try:
        from shared.config import load_settings
        from shared.logger import configure_logging

        settings = load_settings()
        logger = configure_logging(settings)
    except Exception as error:
        print(f"FAIL configuration/logging: {type(error).__name__}: {error}")
        failures += 1
    else:
        logger.info("Health check completed with %d failed check(s).", failures)
        print("PASS configuration and logging")

    if failures:
        print(f"FAILED: {failures} check(s). Activate Python 3.11 and install requirements.txt.")
        print("For missing native libraries or configuration errors, see docs/setup.md.")
        return 1
    print("READY: Phase 1 prerequisites passed. Camera, GUI, MongoDB, and Unity were not exercised.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
