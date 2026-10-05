"""Test result validation, idempotent storage, acknowledgements, and real loopback delivery."""

from __future__ import annotations

import json
import socket
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

from backend.result_receiver import ResultReceiver, serve
from backend.storage import JsonlResultStore, MongoResultStore, StorageError
from shared.protocol import ProtocolError, SessionEnd, decode_session_end, encode_result_ack


def make_result(**changes) -> SessionEnd:
    base = SessionEnd(
        stream_id=str(uuid4()), sequence=3, timestamp=1770000001000, session_id=str(uuid4()),
        game="reach_garden", hand="right", difficulty="default",
        startedAt=1770000000000, endedAt=1770000060000, duration=60.0,
        score=6, targetsAttempted=8, targetsCompleted=6, currentStreak=2, bestStreak=4,
        accuracy=0.75, averageReactionTime=0.42, averageMovementTime=1.1,
        averageHoldStability=0.9, pathEfficiency=0.8,
    )
    return replace(base, **changes)


def wire(**changes) -> dict:
    return json.loads(make_result(**changes).to_bytes())


class SessionEndTests(unittest.TestCase):
    def test_round_trips(self) -> None:
        result = make_result()
        self.assertEqual(result, decode_session_end(result.to_bytes()))

    def test_null_metrics_are_allowed(self) -> None:
        result = make_result(score=0, targetsCompleted=0, currentStreak=0, bestStreak=0, accuracy=None,
                             averageReactionTime=None, averageMovementTime=None,
                             averageHoldStability=None, pathEfficiency=None)
        self.assertIsNone(decode_session_end(result.to_bytes()).averageReactionTime)

    def test_rejects_bad_values(self) -> None:
        bad = [
            {"session_id": "not-a-uuid"}, {"hand": "both"}, {"game": ""}, {"duration": -1.0},
            {"accuracy": 1.5}, {"averageReactionTime": -0.1}, {"endedAt": 1}, {"score": -1},
            {"targetsCompleted": 9}, {"bestStreak": 1}, {"bestStreak": 7}, {"score": True},
            {"accuracy": float("nan")},
        ]
        for change in bad:
            with self.subTest(change=change), self.assertRaises(ProtocolError):
                make_result(**change)

    def test_decode_rejects_malformed_packets(self) -> None:
        good = wire()
        missing = {k: v for k, v in good.items() if k != "pathEfficiency"}
        cases = [
            b"", b"not json", b"[]", b"x" * 1300, json.dumps({**good, "type": "CV_STATE"}).encode(),
            json.dumps({**good, "version": 2}).encode(), json.dumps(missing).encode(),
            json.dumps(good).replace('"game"', '"game":"a","game"').encode(),
            json.dumps(good).replace('0.75', 'NaN').encode(),
        ]
        for payload in cases:
            with self.subTest(payload=payload[:40]), self.assertRaises(ProtocolError):
                decode_session_end(payload)

    def test_ack_validation(self) -> None:
        self.assertEqual(json.loads(encode_result_ack(str(uuid4()), "stored"))["status"], "stored")
        with self.assertRaises(ProtocolError):
            encode_result_ack("nope", "stored")
        with self.assertRaises(ProtocolError):
            encode_result_ack(str(uuid4()), "maybe")


class JsonlStoreTests(unittest.TestCase):
    def test_stores_once_and_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "nested" / "results.jsonl"
            result = make_result()
            store = JsonlResultStore(path)
            self.assertTrue(store.save(result))
            self.assertFalse(store.save(result))
            self.assertFalse(JsonlResultStore(path).save(result))  # Fresh process, same file.
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(1, len(lines))
            self.assertEqual(result.session_id, json.loads(lines[0])["session_id"])

    def test_damaged_line_is_skipped_and_unwritable_path_fails(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "results.jsonl"
            path.write_text("garbage\n", encoding="utf-8")
            self.assertTrue(JsonlResultStore(path).save(make_result()))
            with self.assertRaises(StorageError):
                JsonlResultStore(Path(folder))  # A directory is not a results file.


class MongoStoreTests(unittest.TestCase):
    def test_duplicate_key_means_already_stored(self) -> None:
        from pymongo.errors import DuplicateKeyError, PyMongoError
        collection = MagicMock()
        client = MagicMock()
        client.__getitem__.return_value.__getitem__.return_value = collection
        store = MongoResultStore("mongodb://x", "db", client=client)
        collection.create_index.assert_any_call("session_id", unique=True)
        self.assertTrue(store.save(make_result()))
        collection.insert_one.side_effect = DuplicateKeyError("dup")
        self.assertFalse(store.save(make_result()))
        collection.insert_one.side_effect = PyMongoError("down")
        with self.assertRaises(StorageError):
            store.save(make_result())

    def test_unreachable_server_is_a_storage_error(self) -> None:
        client = MagicMock()
        client.__getitem__.side_effect = RuntimeError("boom")
        with self.assertRaises(StorageError):
            MongoResultStore("mongodb://x", "db", client=client)


class ReceiverTests(unittest.TestCase):
    def test_stored_then_duplicate_then_rejected_then_error(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            receiver = ResultReceiver(JsonlResultStore(Path(folder) / "r.jsonl"))
            result = make_result()
            self.assertEqual("stored", json.loads(receiver.handle(result.to_bytes()))["status"])
            self.assertEqual("duplicate", json.loads(receiver.handle(result.to_bytes()))["status"])

            broken = wire(session_id=str(uuid4()))
            broken["accuracy"] = 7
            reply = json.loads(receiver.handle(json.dumps(broken).encode()))
            self.assertEqual(("rejected", broken["session_id"]), (reply["status"], reply["session_id"]))
            self.assertIsNone(receiver.handle(b"garbage"))

        failing = MagicMock()
        failing.save.side_effect = StorageError("disk full")
        reply = json.loads(ResultReceiver(failing).handle(make_result().to_bytes()))
        self.assertEqual("error", reply["status"])

    def test_loopback_delivery_is_acknowledged(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "r.jsonl"
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
            probe.close()
            server = threading.Thread(
                target=serve, args=(ResultReceiver(JsonlResultStore(path)), port),
                kwargs={"max_results": 2, "idle_timeout": 5}, daemon=True)
            server.start()
            result = make_result()
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                client.settimeout(3)
                statuses = []
                for _ in range(2):
                    for _attempt in range(20):  # The server thread may not have bound yet.
                        client.sendto(result.to_bytes(), ("127.0.0.1", port))
                        try:
                            statuses.append(json.loads(client.recvfrom(2048)[0])["status"])
                            break
                        except (socket.timeout, ConnectionResetError):
                            continue
            server.join(5)
            self.assertEqual(["stored", "duplicate"], statuses)
            self.assertEqual(1, len(path.read_text(encoding="utf-8").splitlines()))

    @staticmethod
    def free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind(("127.0.0.1", 0))
            return probe.getsockname()[1]

    def test_stop_request_ends_serving_promptly_without_traffic(self) -> None:
        stop = threading.Event()
        started = time.monotonic()
        server = threading.Thread(target=serve, args=(ResultReceiver(MagicMock()), self.free_port()),
                                  kwargs={"stop": stop}, daemon=True)
        server.start()
        time.sleep(0.3)
        stop.set()
        server.join(3)
        self.assertFalse(server.is_alive(), "serve must wake up on its own to notice a stop request")
        self.assertLess(time.monotonic() - started, 3)

    def test_idle_timeout_still_applies(self) -> None:
        started = time.monotonic()
        with self.assertRaises(socket.timeout):
            serve(ResultReceiver(MagicMock()), self.free_port(), idle_timeout=1)
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, 1)
        self.assertLess(elapsed, 3)

    def test_a_sender_that_vanishes_before_the_reply_does_not_stop_the_receiver(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            port = self.free_port()
            stop = threading.Event()
            server = threading.Thread(
                target=serve, args=(ResultReceiver(JsonlResultStore(Path(folder) / "r.jsonl")), port),
                kwargs={"stop": stop}, daemon=True)
            server.start()
            time.sleep(0.3)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as gone:
                gone.sendto(make_result().to_bytes(), ("127.0.0.1", port))
            time.sleep(0.3)  # The reply goes to a closed port; Windows reports that on the next receive.
            statuses = []
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                client.settimeout(2)
                for _attempt in range(5):
                    client.sendto(make_result().to_bytes(), ("127.0.0.1", port))
                    try:
                        statuses.append(json.loads(client.recvfrom(2048)[0])["status"])
                        break
                    except (socket.timeout, ConnectionResetError):
                        continue
            stop.set()
            server.join(3)
            self.assertEqual(["stored"], statuses)
            self.assertFalse(server.is_alive())


if __name__ == "__main__":
    unittest.main()
