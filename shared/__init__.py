"""Configuration, logging, and wire protocol shared by MotionPlay components."""

import logging as _logging

# Without this, a library user (or a test) that never configured logging would get warnings and errors
# printed to the console by Python's last-resort handler. Entry points replace it via shared.logger.
_logging.getLogger("motionplay").addHandler(_logging.NullHandler())
