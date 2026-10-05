"""Receives SESSION_END results from Unity, stores them once, and acknowledges each one."""

from __future__ import annotations

import argparse
import logging
import socket
import sys
from pathlib import Path

from backend.storage import JsonlResultStore, MongoResultStore, ResultStore, StorageError
from shared.config import PROJECT_ROOT, ConfigurationError, load_settings
from shared.protocol import (MAX_DATAGRAM_BYTES, ProtocolError, decode_session_end,
                             encode_result_ack, peek_session_id)

LOGGER = logging.getLogger("motionplay.backend.result_receiver")


class ResultReceiver:
    """Socket-free core: bytes in, optional acknowledgement bytes out."""

    def __init__(self, store: ResultStore) -> None:
        self._store = store

    def handle(self, payload: bytes) -> bytes | None:
        try:
            result = decode_session_end(payload)
        except ProtocolError:
            LOGGER.warning("Rejected an invalid SESSION_END datagram.")
            session_id = peek_session_id(payload)
            return encode_result_ack(session_id, "rejected") if session_id else None
        try:
            created = self._store.save(result)
        except StorageError as error:
            LOGGER.error("Result %s not stored: %s", result.session_id, error)
            return encode_result_ack(result.session_id, "error")
        LOGGER.info("Result %s %s.", result.session_id, "stored" if created else "was already stored")
        return encode_result_ack(result.session_id, "stored" if created else "duplicate")


def serve(receiver: ResultReceiver, port: int, *, max_results: int | None = None,
          idle_timeout: float | None = None) -> int:
    """Listen on loopback only. Returns how many datagrams were answered."""
    answered = 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", port))
        sock.settimeout(idle_timeout)
        print(f"Listening for results on 127.0.0.1:{port}. Press Ctrl+C to stop.", flush=True)
        while max_results is None or answered < max_results:
            payload, source = sock.recvfrom(MAX_DATAGRAM_BYTES + 1)
            reply = receiver.handle(payload)
            if reply is not None:
                sock.sendto(reply, source)
                answered += 1
    return answered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MotionPlay Unity result receiver")
    parser.add_argument("--store", choices=("jsonl", "mongo"), default="jsonl",
                        help="Where to save results (default: jsonl, no database needed)")
    parser.add_argument("--file", type=Path, default=Path("data") / "results.jsonl",
                        help="JSONL path, relative to the project root (default: data/results.jsonl)")
    parser.add_argument("--port", type=int, help="Override UNITY_TO_PYTHON_PORT")
    parser.add_argument("--max-results", type=int, help="Exit after answering this many datagrams")
    parser.add_argument("--timeout", type=float, help="Exit after this many idle seconds")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    store: ResultStore | None = None
    try:
        settings = load_settings()
        port = args.port if args.port is not None else settings.unity_to_python_port
        if not 1024 <= port <= 65535:
            raise ConfigurationError("Result port must be from 1024 to 65535.")
        if args.store == "mongo":
            store = MongoResultStore(settings.mongodb_uri, settings.mongodb_database)
        else:
            path = args.file if args.file.is_absolute() else PROJECT_ROOT / args.file
            store = JsonlResultStore(path)
        serve(ResultReceiver(store), port, max_results=args.max_results, idle_timeout=args.timeout)
    except socket.timeout:
        print("No result arrived before the idle timeout.", file=sys.stderr)
        return 1
    except (ConfigurationError, StorageError, OSError) as error:
        print(f"Result receiver error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Result receiver stopped.")
    finally:
        if store is not None:
            store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
