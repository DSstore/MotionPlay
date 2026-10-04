"""User-facing failures from the local computer vision pipeline."""


class CVEngineError(RuntimeError):
    """A camera, tracking, or preview operation could not complete."""
