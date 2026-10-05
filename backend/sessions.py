"""Inspect and migrate stored sessions: list recent rounds, or copy one store into another."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from backend.result_receiver import add_store_arguments, store_from_args
from backend.storage import ResultStore, StorageError
from shared.config import PROJECT_ROOT, ConfigurationError, load_settings
from shared.protocol import ProtocolError, decode_session_end


def _percent(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.0f}%"


def _seconds(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}s"


def format_row(document: dict) -> str:
    """One readable line; missing metrics show as '-', never as zero."""
    ended = datetime.fromtimestamp(document["endedAt"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return (f"{ended}  {document['game']:<13} {document['hand']:<5} "
            f"{document['targetsCompleted']}/{document['targetsAttempted']} watered  "
            f"acc {_percent(document['accuracy']):>4}  react {_seconds(document['averageReactionTime']):>7}  "
            f"stab {_percent(document['averageHoldStability']):>4}  eff {_percent(document['pathEfficiency']):>4}  "
            f"{document['session_id']}")


def import_jsonl(path: Path, store: ResultStore) -> tuple[int, int, int]:
    """Copy a JSONL results file into a store. Returns (added, already_present, invalid)."""
    added = present = invalid = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                result = decode_session_end(json.dumps({"type": "SESSION_END", "version": 1, **data}).encode("utf-8"))
            except (ValueError, ProtocolError):
                invalid += 1
                continue
            if store.save(result):
                added += 1
            else:
                present += 1
    return added, present, invalid


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MotionPlay stored sessions")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="Show the most recent rounds")
    add_store_arguments(listing)
    listing.add_argument("--game", help="Only this game, e.g. reach_garden")
    listing.add_argument("--limit", type=int, default=10, help="How many rounds to show (default: 10)")
    copy = commands.add_parser("import", help="Copy a JSONL results file into the chosen store")
    add_store_arguments(copy)
    copy.add_argument("source", type=Path, help="JSONL file to read, e.g. data/results.jsonl")
    args = parser.parse_args(argv)

    store: ResultStore | None = None
    try:
        settings = load_settings()
        store = store_from_args(args.store, args.file, settings)
        if args.command == "list":
            if args.limit < 1:
                raise ConfigurationError("--limit must be at least 1.")
            total = store.count(game=args.game)
            print(f"{total} session(s) stored; showing the newest {min(total, args.limit)}.")
            for document in store.list_sessions(game=args.game, limit=args.limit):
                print(format_row(document))
        else:
            source = args.source if args.source.is_absolute() else PROJECT_ROOT / args.source
            added, present, invalid = import_jsonl(source, store)
            print(f"Imported {added} new, {present} already present, {invalid} invalid line(s).")
    except (ConfigurationError, StorageError, OSError) as error:
        print(f"Sessions error: {error}", file=sys.stderr)
        return 1
    finally:
        if store is not None:
            store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
