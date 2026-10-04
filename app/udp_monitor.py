"""Local diagnostic CV_STATE monitor; does not implement a game/result receiver."""

from __future__ import annotations

import argparse
import socket
import sys

from shared.config import ConfigurationError, load_settings
from shared.protocol import MAX_DATAGRAM_BYTES, ProtocolError, decode_cv_state


def _positive_integer(value: str) -> int:
    """Validate the optional packet limit and idle timeout."""
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive integer") from None
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def main(argv: list[str] | None = None) -> int:
    """Listen on loopback only; print numerical packets, never save recordings."""
    parser = argparse.ArgumentParser(description="MotionPlay local UDP packet monitor (run before the webcam)")
    parser.add_argument("--port", type=_positive_integer, help="Override CV_TO_UNITY_PORT")
    parser.add_argument("--max-packets", type=_positive_integer, help="Exit after this many valid packets")
    parser.add_argument("--timeout", type=_positive_integer, default=15, help="Idle timeout in seconds (default: 15)")
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
        port = args.port if args.port is not None else settings.cv_to_unity_port
        if not 1024 <= port <= 65535:
            raise ConfigurationError("Monitor port must be from 1024 to 65535.")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind(("127.0.0.1", port))
            receiver.settimeout(args.timeout)
            print(f"Listening on 127.0.0.1:{port}; idle timeout {args.timeout}s. Press Ctrl+C to stop.", flush=True)
            count = 0
            while args.max_packets is None or count < args.max_packets:
                payload, _source = receiver.recvfrom(MAX_DATAGRAM_BYTES + 1)
                try:
                    state = decode_cv_state(payload)
                except ProtocolError:
                    print("Ignored invalid CV_STATE datagram.", file=sys.stderr)
                    continue
                print(state.to_bytes().decode("utf-8"), flush=True)
                count += 1
    except socket.timeout:
        print("No packet arrived before the idle timeout. Start the CV engine, check its port, or increase --timeout.", file=sys.stderr)
        return 1
    except (ConfigurationError, OSError) as error:
        print(f"UDP monitor error: {error}. Close any other receiver on this port and check .env.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Monitor stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
