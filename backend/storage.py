"""Session storage behind one interface; callers never know which backend they have.

Every store keeps one document per finished round, keyed by ``session_id``. Documents are plain
dicts holding exactly the validated SESSION_END fields (see ``SessionEnd.to_document``).
Metrics with no samples are stored as null, never zero.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Protocol

from shared.protocol import SessionEnd

STORE_KINDS = ("jsonl", "sqlite", "mongo")
_FIELDS = tuple(SessionEnd.__dataclass_fields__)
_NEWEST_FIRST = lambda document: (document["endedAt"], document["session_id"])  # noqa: E731


class StorageError(RuntimeError):
    """The operation could not be completed; for a save, the sender should retry later."""


class ResultStore(Protocol):
    def save(self, result: SessionEnd) -> bool:
        """Persist the result. Return True if newly stored, False if the session_id already existed."""

    def get(self, session_id: str) -> dict | None:
        """The stored document, or None."""

    def list_sessions(self, *, game: str | None = None, limit: int = 20) -> list[dict]:
        """Stored documents, most recently ended first, at most ``limit`` (at least 1)."""

    def count(self, *, game: str | None = None) -> int: ...

    def close(self) -> None: ...


def _check_limit(limit: int) -> None:
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive integer.")


class JsonlResultStore:
    """Append-only JSON-lines file; works with no database installed."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._documents: dict[str, dict] = {}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if self._path.exists():
                with self._path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            document = json.loads(line)
                            self._documents[document["session_id"]] = document
                        except (ValueError, KeyError, TypeError):
                            continue  # Skip a damaged line rather than refuse to start.
        except OSError as error:
            raise StorageError(f"Cannot prepare results file: {error.strerror or error}") from error

    def save(self, result: SessionEnd) -> bool:
        if result.session_id in self._documents:
            return False
        document = result.to_document()
        line = json.dumps(document, separators=(",", ":"), allow_nan=False) + "\n"
        try:
            with self._path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as error:
            raise StorageError(f"Cannot write results file: {error.strerror or error}") from error
        self._documents[result.session_id] = document
        return True

    def get(self, session_id: str) -> dict | None:
        document = self._documents.get(session_id)
        return dict(document) if document is not None else None

    def list_sessions(self, *, game: str | None = None, limit: int = 20) -> list[dict]:
        _check_limit(limit)
        matches = [d for d in self._documents.values()
                   if (game is None or d.get("game") == game) and isinstance(d.get("endedAt"), int)]
        return [dict(d) for d in sorted(matches, key=_NEWEST_FIRST, reverse=True)[:limit]]

    def count(self, *, game: str | None = None) -> int:
        return sum(1 for d in self._documents.values() if game is None or d.get("game") == game)

    def close(self) -> None:
        pass


class SqliteResultStore:
    """Single-file SQL database from the standard library; a real database that needs no server."""

    _TYPES = {"str": "TEXT", "int": "INTEGER", "float": "REAL"}

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(self._path)
            self._db.row_factory = sqlite3.Row
            columns = []
            for name, field in SessionEnd.__dataclass_fields__.items():
                base = str(field.type).split("|")[0].strip()  # "float | None" -> "float"; nulls stay allowed
                key = " PRIMARY KEY" if name == "session_id" else ""
                columns.append(f"{name} {self._TYPES[base]}{key}")
            self._db.execute(f"CREATE TABLE IF NOT EXISTS sessions ({', '.join(columns)})")
            self._db.execute("CREATE INDEX IF NOT EXISTS sessions_ended ON sessions (endedAt DESC)")
            self._db.commit()
        except (OSError, sqlite3.Error) as error:
            raise StorageError(f"Cannot open the SQLite database: {error}") from error

    def save(self, result: SessionEnd) -> bool:
        document = result.to_document()
        sql = (f"INSERT OR IGNORE INTO sessions ({', '.join(_FIELDS)}) "
               f"VALUES ({', '.join('?' for _ in _FIELDS)})")
        try:
            with self._db:
                cursor = self._db.execute(sql, [document[name] for name in _FIELDS])
        except sqlite3.Error as error:
            raise StorageError(f"SQLite write failed: {error}") from error
        return cursor.rowcount == 1

    def get(self, session_id: str) -> dict | None:
        try:
            row = self._db.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        except sqlite3.Error as error:
            raise StorageError(f"SQLite read failed: {error}") from error
        return dict(row) if row is not None else None

    def list_sessions(self, *, game: str | None = None, limit: int = 20) -> list[dict]:
        _check_limit(limit)
        where, args = ("WHERE game = ?", [game]) if game is not None else ("", [])
        try:
            rows = self._db.execute(
                f"SELECT * FROM sessions {where} ORDER BY endedAt DESC, session_id DESC LIMIT ?",
                [*args, limit]).fetchall()
        except sqlite3.Error as error:
            raise StorageError(f"SQLite read failed: {error}") from error
        return [dict(row) for row in rows]

    def count(self, *, game: str | None = None) -> int:
        where, args = ("WHERE game = ?", [game]) if game is not None else ("", [])
        try:
            return self._db.execute(f"SELECT COUNT(*) FROM sessions {where}", args).fetchone()[0]
        except sqlite3.Error as error:
            raise StorageError(f"SQLite read failed: {error}") from error

    def close(self) -> None:
        self._db.close()


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
            self._collection.create_index([("endedAt", -1)])
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

    def get(self, session_id: str) -> dict | None:
        from pymongo.errors import PyMongoError
        try:
            return self._collection.find_one({"session_id": session_id}, {"_id": 0})
        except PyMongoError as error:
            raise StorageError("MongoDB read failed.") from error

    def list_sessions(self, *, game: str | None = None, limit: int = 20) -> list[dict]:
        from pymongo.errors import PyMongoError
        _check_limit(limit)
        try:
            cursor = self._collection.find({} if game is None else {"game": game}, {"_id": 0})
            return list(cursor.sort([("endedAt", -1), ("session_id", -1)]).limit(limit))
        except PyMongoError as error:
            raise StorageError("MongoDB read failed.") from error

    def count(self, *, game: str | None = None) -> int:
        from pymongo.errors import PyMongoError
        try:
            return self._collection.count_documents({} if game is None else {"game": game})
        except PyMongoError as error:
            raise StorageError("MongoDB read failed.") from error

    def close(self) -> None:
        self._client.close()


def open_store(kind: str, *, path: Path | None = None, mongodb_uri: str = "",
               mongodb_database: str = "motionplay") -> ResultStore:
    """Build the store named by ``kind``; ``path`` is the file for jsonl and sqlite."""
    if kind == "jsonl":
        return JsonlResultStore(path or Path("data") / "results.jsonl")
    if kind == "sqlite":
        return SqliteResultStore(path or Path("data") / "motionplay.db")
    if kind == "mongo":
        return MongoResultStore(mongodb_uri, mongodb_database)
    raise StorageError(f"Unknown store {kind!r}; choose one of {', '.join(STORE_KINDS)}.")
