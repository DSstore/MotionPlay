"""Result storage behind one small interface; the receiver never knows which backend it has."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

from shared.protocol import SessionEnd


class StorageError(RuntimeError):
    """The result could not be durably stored; the sender should retry later."""


class ResultStore(Protocol):
    def save(self, result: SessionEnd) -> bool:
        """Persist the result. Return True if newly stored, False if the session_id already existed."""

    def close(self) -> None: ...


class JsonlResultStore:
    """Append-only JSON-lines file; works with no database installed."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._ids: set[str] = set()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if self._path.exists():
                with self._path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            self._ids.add(json.loads(line)["session_id"])
                        except (ValueError, KeyError, TypeError):
                            continue  # Skip a damaged line rather than refuse to start.
        except OSError as error:
            raise StorageError(f"Cannot prepare results file: {error.strerror or error}") from error

    def save(self, result: SessionEnd) -> bool:
        if result.session_id in self._ids:
            return False
        line = json.dumps(result.to_document(), separators=(",", ":"), allow_nan=False) + "\n"
        try:
            with self._path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as error:
            raise StorageError(f"Cannot write results file: {error.strerror or error}") from error
        self._ids.add(result.session_id)
        return True

    def close(self) -> None:
        pass


class MongoResultStore:
    """MongoDB store; a unique index on session_id makes repeated deliveries harmless."""

    COLLECTION = "sessions"

    def __init__(self, uri: str, database: str, *, client=None) -> None:
        try:
            if client is None:
                from pymongo import MongoClient
                client = MongoClient(uri, serverSelectionTimeoutMS=3000)
                client.admin.command("ping")
            self._client = client
            self._collection = client[database][self.COLLECTION]
            self._collection.create_index("session_id", unique=True)
        except Exception as error:  # pymongo raises several unrelated connection errors
            raise StorageError("Cannot reach MongoDB; check MONGODB_URI and that the server is running.") from error

    def save(self, result: SessionEnd) -> bool:
        from pymongo.errors import DuplicateKeyError, PyMongoError
        try:
            self._collection.insert_one(result.to_document())
        except DuplicateKeyError:
            return False
        except PyMongoError as error:
            raise StorageError("MongoDB write failed.") from error
        return True

    def close(self) -> None:
        self._client.close()
