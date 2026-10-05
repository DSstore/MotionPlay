"""Test account rules, password hashing, lockout, the account commands, and receiver ownership."""

from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend import users as users_cli
from backend.auth import (AccountLocked, AuthError, InvalidCredentials, InvalidInput, UserStore, UsernameTaken,
                          validate_password, validate_username)
from backend.result_receiver import ResultReceiver
from backend.storage import SqliteResultStore, StorageError
from tests.test_results import make_result


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_770_000_000.0

    def __call__(self) -> float:
        return self.now


class AuthTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "m.db"
        self.clock = FakeClock()
        self.users = UserStore(self.path, rounds=4, clock=self.clock)
        self.addCleanup(self.users.close)


class ValidationTests(unittest.TestCase):
    def test_usernames(self) -> None:
        for good in ("abc", "Player_1", "a.b-c", "x" * 32):
            self.assertEqual(good, validate_username(good))
        for bad in ("ab", "x" * 33, "has space", "emoji\U0001F600", "semi;colon", "", None, 5, "line\nbreak"):
            with self.subTest(bad=bad), self.assertRaises(InvalidInput):
                validate_username(bad)

    def test_passwords(self) -> None:
        validate_password("correct horse")
        validate_password("é" * 36)  # 72 bytes exactly
        for bad in ("short", "x" * 73, "é" * 37, "nul\x00byte-password", None, b"bytes-password"):
            with self.subTest(bad=bad), self.assertRaises(InvalidInput):
                validate_password(bad)
        with self.assertRaises(InvalidInput):
            validate_password("Alice-Pass", "alice-pass")


class UserStoreTests(AuthTestCase):
    def test_create_and_log_in(self) -> None:
        user = self.users.create_user("Alice", "a long password")
        self.assertEqual("Alice", user.username)
        self.assertEqual(self.users.authenticate("alice", "a long password"), user)
        self.assertEqual(self.users.get_by_username("ALICE"), user)
        self.assertIsNone(self.users.get_by_username("nobody"))
        self.assertEqual([user], self.users.list_users())

    def test_passwords_are_stored_hashed_and_salted(self) -> None:
        self.users.create_user("alice", "a long password")
        self.users.create_user("bob", "a long password")
        with sqlite3.connect(self.path) as db:
            hashes = [row[0] for row in db.execute("SELECT password_hash FROM users ORDER BY username")]
        db.close()
        self.assertTrue(all(h.startswith("$2b$04$") for h in hashes))
        self.assertNotEqual(hashes[0], hashes[1], "the same password must not give the same hash")
        self.assertFalse(any("a long password" in h for h in hashes))

    def test_usernames_are_unique_ignoring_case(self) -> None:
        self.users.create_user("Alice", "a long password")
        with self.assertRaises(UsernameTaken):
            self.users.create_user("aLICE", "another password")

    def test_bad_credentials_look_the_same(self) -> None:
        self.users.create_user("alice", "a long password")
        messages = set()
        for username, password in (("alice", "wrong password"), ("nobody", "a long password"),
                                   ("alice", "x" * 200), (None, "a long password"), ("alice", None)):
            with self.assertRaises(InvalidCredentials) as caught:
                self.users.authenticate(username, password)
            messages.add(str(caught.exception))
        self.assertEqual({"Invalid username or password."}, messages)

    def test_lockout_after_repeated_failures_then_expires(self) -> None:
        self.users.create_user("alice", "a long password")
        for _ in range(4):
            with self.assertRaises(InvalidCredentials):
                self.users.authenticate("alice", "wrong password")
        with self.assertRaises(InvalidCredentials):  # The fifth failure starts the lockout.
            self.users.authenticate("alice", "wrong password")
        with self.assertRaises(AccountLocked):
            self.users.authenticate("alice", "a long password")  # Even the right password is refused.
        self.clock.now += 301
        self.assertEqual("alice", self.users.authenticate("alice", "a long password").username)

    def test_success_resets_the_failure_count(self) -> None:
        self.users.create_user("alice", "a long password")
        for _ in range(4):
            with self.assertRaises(InvalidCredentials):
                self.users.authenticate("alice", "wrong password")
        self.users.authenticate("alice", "a long password")
        for _ in range(4):  # Four more failures are still below the limit.
            with self.assertRaises(InvalidCredentials):
                self.users.authenticate("alice", "wrong password")
        self.users.authenticate("alice", "a long password")

    def test_change_password(self) -> None:
        self.users.create_user("alice", "a long password")
        with self.assertRaises(InvalidCredentials):
            self.users.change_password("alice", "wrong password", "a new password")
        with self.assertRaises(InvalidInput):
            self.users.change_password("alice", "a long password", "short")
        self.users.change_password("alice", "a long password", "a new password")
        with self.assertRaises(InvalidCredentials):
            self.users.authenticate("alice", "a long password")
        self.users.authenticate("alice", "a new password")

    def test_accounts_persist_across_opens(self) -> None:
        self.users.create_user("alice", "a long password")
        reopened = UserStore(self.path, rounds=4, clock=self.clock)
        self.addCleanup(reopened.close)
        self.assertEqual("alice", reopened.authenticate("alice", "a long password").username)

    def test_rejects_bad_settings_and_broken_files(self) -> None:
        for options in ({"rounds": 3}, {"rounds": 17}, {"max_attempts": 0}, {"lockout_seconds": 0}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                UserStore(self.path, **options)
        with self.assertRaises(StorageError):
            UserStore(Path(self.folder.name))  # A directory is not a database file.

    def test_invalid_account_input_never_reaches_the_database(self) -> None:
        with self.assertRaises(InvalidInput):
            self.users.create_user("a;--", "a long password")
        with self.assertRaises(InvalidInput):
            self.users.create_user("alice", "short")
        self.assertEqual([], self.users.list_users())


class AccountCommandTests(AuthTestCase):
    def run_cli(self, *argv: str, passwords: tuple[str, ...] = ()) -> tuple[int, str, str]:
        answers = iter(passwords)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = users_cli.main(["--users-db", str(self.path), *argv], prompt=lambda _text: next(answers),
                                  rounds=4)
        return code, out.getvalue(), err.getvalue()

    def test_create_login_passwd_list(self) -> None:
        self.users.close()
        code, out, _ = self.run_cli("create", "alice", passwords=("a long password", "a long password"))
        self.assertEqual((0, "Created player alice.\n"), (code, out))
        self.assertEqual(0, self.run_cli("login", "alice", passwords=("a long password",))[0])
        code, _, err = self.run_cli("login", "alice", passwords=("wrong password",))
        self.assertEqual(1, code)
        self.assertIn("Invalid username or password", err)
        self.assertEqual(0, self.run_cli("passwd", "alice",
                                         passwords=("a long password", "a new password", "a new password"))[0])
        self.assertEqual(0, self.run_cli("login", "alice", passwords=("a new password",))[0])
        code, out, _ = self.run_cli("list")
        self.assertEqual(0, code)
        self.assertIn("1 player(s).", out)
        self.assertIn("alice", out)
        self.assertNotIn("password", out.lower())
        self.users = UserStore(self.path, rounds=4, clock=self.clock)
        self.addCleanup(self.users.close)

    def test_mismatched_and_weak_passwords_are_refused(self) -> None:
        self.users.close()
        code, _, err = self.run_cli("create", "alice", passwords=("a long password", "different one"))
        self.assertEqual(1, code)
        self.assertIn("do not match", err)
        code, _, err = self.run_cli("create", "alice", passwords=("short", "short"))
        self.assertEqual(1, code)
        self.assertIn("at least 8", err)
        self.users = UserStore(self.path, rounds=4, clock=self.clock)
        self.addCleanup(self.users.close)
        self.assertEqual([], self.users.list_users())


class ReceiverOwnershipTests(AuthTestCase):
    def test_rounds_are_saved_for_the_logged_in_player(self) -> None:
        alice = self.users.create_user("alice", "a long password")
        store = SqliteResultStore(self.path)
        self.addCleanup(store.close)
        result = make_result()
        reply = json.loads(ResultReceiver(store, alice.user_id).handle(result.to_bytes()))
        self.assertEqual("stored", reply["status"])
        self.assertEqual(alice.user_id, store.get(result.session_id)["user_id"])
        unowned = make_result()
        ResultReceiver(store).handle(unowned.to_bytes())
        self.assertIsNone(store.get(unowned.session_id)["user_id"])

    def test_a_resent_round_keeps_its_first_owner(self) -> None:
        store = SqliteResultStore(self.path)
        self.addCleanup(store.close)
        result = make_result()
        ResultReceiver(store, "user-a").handle(result.to_bytes())
        reply = json.loads(ResultReceiver(store, "user-b").handle(result.to_bytes()))
        self.assertEqual("duplicate", reply["status"])
        self.assertEqual("user-a", store.get(result.session_id)["user_id"])


if __name__ == "__main__":
    unittest.main()
