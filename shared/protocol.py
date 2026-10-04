"""Versioned JSON wire models; no CV, UI, database, or socket dependencies."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from uuid import UUID


PROTOCOL_VERSION = 1
MAX_DATAGRAM_BYTES = 1200
MAX_WIRE_INTEGER = 2**63 - 1
GESTURES = frozenset({"OPEN_HAND", "FIST", "PINCH", "POINT", "UNKNOWN"})


class ProtocolError(ValueError):
    """A packet violates the supported wire contract."""


def _number(value: object, low: float | None = None, high: float | None = None) -> bool:
    """Reject booleans, nonfinite values, and coordinates outside their range."""
    if type(value) not in (int, float):
        return False
    try:
        finite = math.isfinite(value)
    except OverflowError:
        return False
    return (
        finite
        and (low is None or value >= low) and (high is None or value <= high)
    )


@dataclass(frozen=True)
class Position:
    """Filtered palm coordinates; z is relative model depth, not meters."""

    x: float
    y: float
    z: float


@dataclass(frozen=True)
class CVState:
    """One selected hand's current state, never a queued frame or gesture event."""

    stream_id: str
    sequence: int
    timestamp: int
    hand: str
    tracking: bool
    position: Position | None
    gesture: str
    confidence: float
    mirrored: bool

    def __post_init__(self) -> None:
        try:
            valid_id = isinstance(self.stream_id, str) and str(UUID(self.stream_id)) == self.stream_id
        except ValueError:
            valid_id = False
        if not valid_id:
            raise ProtocolError("stream_id must be a canonical UUID string.")
        if any(type(value) is not int or not 0 <= value <= MAX_WIRE_INTEGER
               for value in (self.sequence, self.timestamp)):
            raise ProtocolError("sequence and timestamp must be nonnegative signed-64-bit integers.")
        if (not isinstance(self.hand, str) or self.hand not in {"left", "right"}
                or not isinstance(self.gesture, str) or self.gesture not in GESTURES):
            raise ProtocolError("Unsupported hand or gesture.")
        if type(self.tracking) is not bool or type(self.mirrored) is not bool:
            raise ProtocolError("tracking and mirrored must be booleans.")
        if not _number(self.confidence, 0, 1):
            raise ProtocolError("confidence must be finite and in [0, 1].")
        if self.tracking:
            if not isinstance(self.position, Position):
                raise ProtocolError("A tracked hand requires a position.")
            if not (_number(self.position.x, 0, 1) and _number(self.position.y, 0, 1)
                    and _number(self.position.z)):
                raise ProtocolError("Position requires finite z and x/y in [0, 1].")
        elif self.position is not None or self.gesture != "UNKNOWN" or self.confidence != 0:
            raise ProtocolError("Lost tracking requires null position, UNKNOWN gesture, and zero confidence.")

    def to_bytes(self) -> bytes:
        """Serialize one complete UTF-8 JSON object with finite numeric values."""
        data = {"type": "CV_STATE", "version": PROTOCOL_VERSION, **asdict(self)}
        payload = json.dumps(data, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(payload) > MAX_DATAGRAM_BYTES:
            raise ProtocolError("CV_STATE exceeds the datagram size limit.")
        return payload


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON keys rather than silently accepting the last one."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("Duplicate JSON key.")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    """JSON forbids NaN/Infinity, including in unrecognized extension fields."""
    raise ProtocolError("Nonfinite JSON constant.")


def decode_cv_state(payload: bytes) -> CVState:
    """Validate a diagnostic packet; optional extra keys allow additive evolution."""
    if not payload or len(payload) > MAX_DATAGRAM_BYTES:
        raise ProtocolError("Empty or oversized datagram.")
    try:
        data = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
        if not isinstance(data, dict) or data.get("type") != "CV_STATE":
            raise ProtocolError("Expected a CV_STATE object.")
        if type(data.get("version")) is not int or data["version"] != PROTOCOL_VERSION:
            raise ProtocolError("Unsupported protocol version.")
        position = data["position"]
        if position is not None:
            if not isinstance(position, dict):
                raise ProtocolError("position must be an object or null.")
            position = Position(position["x"], position["y"], position["z"])
        return CVState(
            stream_id=data["stream_id"], sequence=data["sequence"], timestamp=data["timestamp"],
            hand=data["hand"], tracking=data["tracking"], position=position,
            gesture=data["gesture"], confidence=data["confidence"], mirrored=data["mirrored"],
        )
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError, RecursionError) as error:
        raise ProtocolError("Invalid CV_STATE packet; see docs/udp_protocol.md.") from error
