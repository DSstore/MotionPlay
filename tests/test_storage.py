"""Run one behavior contract against every store, then test the session CLI and migration."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from backend import sessions
from backend.storage import (JsonlResultStore, MongoResultStore, SqliteResultStore, StorageError, open_store)
from tests.test_results import make_result


class FakeCursor:
    def __init__(self, documents: list[dict]) -> None:
        self._documents = documents

    def sort(self, keys: list[tuple[str, int]]) -> "FakeCursor":
        for key, direction in reversed(keys):
            self._documents.sort(key=lambda d: d[key], reverse=direction < 0)
        return self

    def limit(self, count: int) -> "FakeCursor":
        self._documents = self._documents[:count]
        return self

    def __iter__(self):
        return iter(self._documents)


class FakeCollection:
    """The slice of pymongo's collection API the store uses, kept in memory."""

    def __init__(self) -> None:
        self.documents: list[dict] = []
        self.unique: list[str] = []

    def create_index(self, keys, unique: bool = False) -> None:
        if unique:
            self.unique.append(keys)

    def insert_one(self, document: dict) -> None:
        from pymongo.errors import DuplicateKeyError
        for key in self.unique:
            if any(existing[key] == document[key] for existing in self.documents):
                raise DuplicateKeyError("duplicate")
        self.documents.append({"_id": object(), **document})

    @staticmethod
    def _match(document: dict, query: dict) -> bool:
        return all(document.get(key) == value for key, value in query.items())

    @staticmethod
    def _project(document: dict) -> dict:
        return {key: value for key, value in document.items() if key != "_id"}

    def find(self, query: dict, projection: dict | None = None) -> FakeCursor:
        return FakeCursor([self._project(d) for d in self.documents if self._match(d, query)])

    def find_one(self, query: dict, projection: dict | None = None):
        found = list(self.find(query))
        return found[0] if found else None

    def count_documents(self, query: dict) -> int:
        return sum(1 for d in self.documents if self._match(d, query))


class FakeDatabase:
    def __init__(self, collection: FakeCollection) -> None:
        self._collection = collection

    def __getitem__(self, name: str) -> FakeCollection:
        return self._collection


class FakeClient:
    def __init__(self) -> None:
        self.collection = FakeCollection()

    def __getitem__(self, database: str) -> FakeDatabase:
        return FakeDatabase(self.collection)

    def close(self) -> None:
        pass


class StoreContract:
    """Behavior every store must share. Subclasses provide ``make_store``."""

    persistent = True

    def setUp(self) -> None:  # noqa: N802
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = self.make_store()
        self.addCleanup(self.store.close)

    def make_store(self):
        raise NotImplementedError

    def test_save_is_idempotent_and_get_returns_the_document(self) -> None:
        result = make_result()
        self.assertTrue(self.store.save(result))
        self.assertFalse(self.store.save(result))
        self.assertEqual(result.to_document(), self.store.get(result.session_id))
        self.assertIsNone(self.store.get(str(uuid4())))
        self.assertEqual(1, self.store.count())

    def test_null_metrics_stay_null(self) -> None:
        result = make_result(score=0, targetsCompleted=0, currentStreak=0, bestStreak=0, accuracy=None,
                             averageReactionTime=None, averageMovementTime=None,
                             averageHoldStability=None, pathEfficiency=None)
        self.store.save(result)
        stored = self.store.get(result.session_id)
        for name in ("accuracy", "averageReactionTime", "averageMovementTime", "averageHoldStability", "pathEfficiency"):
            self.assertIsNone(stored[name], name)

    def test_list_is_newest_first_limited_and_filterable(self) -> None:
        older = make_result(endedAt=1770000100000)
        newer = make_result(endedAt=1770000300000)
        middle = make_result(endedAt=1770000200000, game="other_game")
        for result in (older, newer, middle):
            self.store.save(result)
        order = [d["session_id"] for d in self.store.list_sessions()]
        self.assertEqual([newer.session_id, middle.session_id, older.session_id], order)
        self.assertEqual([newer.session_id], [d["session_id"] for d in self.store.list_sessions(limit=1)])
        only = self.store.list_sessions(game="other_game")
        self.assertEqual([middle.session_id], [d["session_id"] for d in only])
        self.assertEqual(2, self.store.count(game="reach_garden"))
        self.assertEqual(3, self.store.count())
        self.assertEqual([], self.store.list_sessions(game="nothing"))

    def test_rejects_a_bad_limit(self) -> None:
        for limit in (0, -1, True, 2.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                self.store.list_sessions(limit=limit)

    def test_returned_documents_are_copies(self) -> None:
        result = make_result()
        self.store.save(result)
        self.store.get(result.session_id)["score"] = 999
        self.assertEqual(result.score, self.store.get(result.session_id)["score"])


class JsonlStoreContract(StoreContract, unittest.TestCase):
    def make_store(self):
        self.path = Path(self.folder.name) / "r.jsonl"
        return JsonlResultStore(self.path)

    def test_survives_reopening(self) -> None:
        result = make_result()
        self.store.save(result)
        reopened = JsonlResultStore(self.path)
        self.assertFalse(reopened.save(result))
        self.assertEqual(result.to_document(), reopened.get(result.session_id))


class SqliteStoreContract(StoreContract, unittest.TestCase):
    def make_store(self):
        self.path = Path(self.folder.name) / "nested" / "m.db"
        return SqliteResultStore(self.path)

    def test_survives_reopening(self) -> None:
        result = make_result()
        self.store.save(result)
        reopened = SqliteResultStore(self.path)
        self.addCleanup(reopened.close)
        self.assertFalse(reopened.save(result))
        self.assertEqual(result.to_document(), reopened.get(result.session_id))

    def test_failures_become_storage_errors(self) -> None:
        with self.assertRaises(StorageError):
            SqliteResultStore(Path(self.folder.name))  # A directory is not a database file.
        self.store.close()
        with self.assertRaises(StorageError):
            self.store.save(make_result())
        with self.assertRaises(StorageError):
            self.store.list_sessions()


class MongoStoreContract(StoreContract, unittest.TestCase):
    def make_store(self):
        self.client = FakeClient()
        return MongoResultStore("mongodb://unused", "db", client=self.client)

    def test_database_errors_become_storage_errors(self) -> None:
        from pymongo.errors import PyMongoError

        def broken(*_args, **_kwargs):
            raise PyMongoError("down")
        self.client.collection.find = broken
        self.client.collection.find_one = broken
        self.client.collection.count_documents = broken
        with self.assertRaises(StorageError):
            self.store.list_sessions()
        with self.assertRaises(StorageError):
            self.store.get(str(uuid4()))
        with self.assertRaises(StorageError):
            self.store.count()


class FactoryTests(unittest.TestCase):
    def test_opens_each_file_store_and_rejects_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            for kind, name in (("jsonl", "a.jsonl"), ("sqlite", "a.db")):
                store = open_store(kind, path=Path(folder) / name)
                self.assertEqual(0, store.count())
                store.close()
            with self.assertRaises(StorageError):
                open_store("postgres")


class SessionsCliTests(unittest.TestCase):
    def run_cli(self, *argv: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = sessions.main(list(argv))
        return code, out.getvalue()

    def test_import_then_list_shows_dashes_for_missing_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "old.jsonl"
            good = make_result(endedAt=1770000200000)
            empty = make_result(endedAt=1770000100000, score=0, targetsCompleted=0, currentStreak=0,
                                bestStreak=0, accuracy=None, averageReactionTime=None,
                                averageMovementTime=None, averageHoldStability=None, pathEfficiency=None)
            lines = [json.dumps(good.to_document()), "not json", json.dumps(empty.to_document()),
                     json.dumps({**good.to_document(), "accuracy": 9}), json.dumps(good.to_document()), ""]
            source.write_text("\n".join(lines), encoding="utf-8")
            db = str(Path(folder) / "m.db")

            code, output = self.run_cli("import", str(source), "--store", "sqlite", "--file", db)
            self.assertEqual(0, code)
            self.assertIn("Imported 2 new, 1 already present, 2 invalid", output)

            code, output = self.run_cli("list", "--store", "sqlite", "--file", db, "--limit", "5")
            self.assertEqual(0, code)
            rows = output.splitlines()
            self.assertIn("2 session(s) stored", rows[0])
            self.assertIn(good.session_id, rows[1])
            self.assertIn("75%", rows[1])
            self.assertIn("react       -", rows[2])
            self.assertIn(empty.session_id, rows[2])

    def test_bad_arguments_and_missing_source_fail_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db = str(Path(folder) / "m.db")
            self.assertEqual(1, self.run_cli("list", "--store", "sqlite", "--file", db, "--limit", "0")[0])
            self.assertEqual(1, self.run_cli("import", str(Path(folder) / "missing.jsonl"),
                                             "--store", "sqlite", "--file", db)[0])

    def test_format_row_never_invents_zero(self) -> None:
        row = sessions.format_row({**make_result(accuracy=None, averageReactionTime=None).to_document()})
        self.assertIn("acc    -", row)
        self.assertNotIn("0.00s", row)


if __name__ == "__main__":
    unittest.main()
