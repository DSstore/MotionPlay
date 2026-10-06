"""Hardware-independent tests for implemented MotionPlay components."""

import atexit
import os
import shutil
import tempfile

# Entry points under test configure file logging from the environment. Send it to a throwaway folder so
# running the tests never writes to the real logs/ directory.
if "LOG_DIR" not in os.environ:
    _LOG_DIR = tempfile.mkdtemp(prefix="motionplay-test-logs-")
    os.environ["LOG_DIR"] = _LOG_DIR
    atexit.register(shutil.rmtree, _LOG_DIR, ignore_errors=True)
