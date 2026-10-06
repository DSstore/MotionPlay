"""Poll the console for a stop key, so a headless run can be ended without relying on Ctrl+C."""

from __future__ import annotations

from types import ModuleType

STOP_KEYS = frozenset({"q", "Q", "\x1b"})  # Q or Escape


def stop_requested(console: ModuleType | None = None) -> bool:
    """True if Q or Escape was pressed in the console since the last call.

    Reads and discards every pending key so keystrokes do not pile up. Works only on Windows (msvcrt)
    and only while the console window has focus; elsewhere it always returns False and Ctrl+C remains
    the way to stop. ``console`` is the msvcrt module, injectable for tests.
    """
    if console is None:
        try:
            import msvcrt as console
        except ImportError:
            return False
    stop = False
    try:
        while console.kbhit():
            key = console.getwch()
            if key in ("\x00", "\xe0"):  # first half of a function/arrow key: skip its second half
                console.getwch()
            elif key in STOP_KEYS:
                stop = True
    except OSError:
        return False  # no real console attached (for example, input redirected)
    return stop
