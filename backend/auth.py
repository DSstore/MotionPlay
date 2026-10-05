"""Local player accounts: bcrypt-hashed passwords in the SQLite database, with login lockout.

This separates player profiles on one machine. It is not a defence against someone who can
read the database file or run code as the player, and it never leaves the machine.
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from uuid import uuid4

import bcrypt

from backend.storage import StorageError

USERNAME_PATTERN = re.compile(r"[A-Za-z0-9_.-]{3,32}")
MIN_PASSWORD_CHARACTERS = 8
MAX_PASSWORD_BYTES = 72  # bcrypt ignores anything longer, so longer passwords are refused, not truncated
DEFAULT_ROUNDS = 12
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 300


class AuthError(Exception):
    """Base class; messages are safe to show to the player."""


class InvalidInput(AuthError):
    """A username or password breaks the rules."""


class UsernameTaken(AuthError):
    """That username (compared case-insensitively) already has an account."""


class InvalidCredentials(AuthError):
    """Unknown user or wrong password; deliberately the same message for both."""

    def __init__(self) -> None:
        super().__init__("Invalid username or password.")


class AccountLocked(AuthError):
    """Too many wrong passwords in a row."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        super().__init__(f"Too many failed attempts. Try again in {max(1, round(seconds / 60))} minute(s).")


@dataclass(frozen=True)
class User:
    """A player. Never carries the password hash."""

    user_id: str
    username: str
    created_at: int  # UTC milliseconds


def validate_username(username: object) -> str:
    if not isinstance(username, str) or not USERNAME_PATTERN.fullmatch(username):
        raise InvalidInput("Username must be 3 to 32 letters, digits, dots, dashes, or underscores.")
    return username


def validate_password(password: object, username: str | None = None) -> str:
    if not isinstance(password, str) or "\x00" in password:
        raise InvalidInput("Password is not valid.")
    if len(password) < MIN_PASSWORD_CHARACTERS:
        raise InvalidInput(f"Password must be at least {MIN_PASSWORD_CHARACTERS} characters.")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise InvalidInput(f"Password must be at most {MAX_PASSWORD_BYTES} bytes.")
    if username is not None and password.lower() == username.lower():
        raise InvalidInput("Password must not be the same as the username.")
    return password


class UserStore:
    """Create players and check their passwords. ``clock`` (seconds) and ``rounds`` are injectable for tests."""

    def __init__(self, path: Path, *, rounds: int = DEFAULT_ROUNDS, clock: Callable[[], float] = time.time,
                 max_attempts: int = MAX_FAILED_ATTEMPTS, lockout_seconds: float = LOCKOUT_SECONDS) -> None:
        if not 4 <= rounds <= 16:
            raise ValueError("bcrypt rounds must be from 4 to 16.")
        if max_attempts < 1 or lockout_seconds <= 0:
            raise ValueError("Lockout settings must be positive.")
        self._rounds, self._clock = rounds, clock
        self._max_attempts, self._lockout = max_attempts, lockout_seconds
        self._decoy: bytes | None = None
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(path)
            self._db.row_factory = sqlite3.Row
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, username TEXT NOT NULL, "
                "username_key TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, created_at INTEGER NOT NULL, "
                "failed_attempts INTEGER NOT NULL DEFAULT 0, locked_until REAL NOT NULL DEFAULT 0)")
            self._db.commit()
        except (OSError, sqlite3.Error) as error:
            raise StorageError(f"Cannot open the user database: {error}") from error

    # -- helpers -----------------------------------------------------------------------------

    def _hash(self, password: str) -> str:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(self._rounds)).decode("ascii")

    def _burn_time(self, password: str) -> None:
        """Spend the same effort as a real check so an unknown username does not answer faster."""
        if self._decoy is None:
            self._decoy = bcrypt.hashpw(b"decoy-password", bcrypt.gensalt(self._rounds))
        try:
            bcrypt.checkpw(password.encode("utf-8")[:MAX_PASSWORD_BYTES], self._decoy)
        except ValueError:
            pass

    def _row(self, username: str) -> sqlite3.Row | None:
        try:
            return self._db.execute("SELECT * FROM users WHERE username_key = ?", (username.lower(),)).fetchone()
        except sqlite3.Error as error:
            raise StorageError(f"User database read failed: {error}") from error

    @staticmethod
    def _user(row: sqlite3.Row) -> User:
        return User(row["user_id"], row["username"], row["created_at"])

    # -- accounts ----------------------------------------------------------------------------

    def create_user(self, username: str, password: str) -> User:
        validate_username(username)
        validate_password(password, username)
        user = User(str(uuid4()), username, int(self._clock() * 1000))
        try:
            with self._db:
                self._db.execute(
                    "INSERT INTO users (user_id, username, username_key, password_hash, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (user.user_id, username, username.lower(), self._hash(password), user.created_at))
        except sqlite3.IntegrityError:
            raise UsernameTaken("That username is already taken.") from None
        except sqlite3.Error as error:
            raise StorageError(f"User database write failed: {error}") from error
        return user

    def authenticate(self, username: str, password: str) -> User:
        """Return the user for a correct password. Wrong guesses count toward a temporary lockout."""
        if not isinstance(username, str) or not isinstance(password, str):
            raise InvalidCredentials()
        row = self._row(username)
        if row is None:
            self._burn_time(password)
            raise InvalidCredentials()
        now = self._clock()
        if row["locked_until"] > now:
            raise AccountLocked(row["locked_until"] - now)
        try:
            ok = (len(password.encode("utf-8")) <= MAX_PASSWORD_BYTES and "\x00" not in password
                  and bcrypt.checkpw(password.encode("utf-8"), row["password_hash"].encode("ascii")))
        except ValueError:
            ok = False
        try:
            with self._db:
                if ok:
                    self._db.execute("UPDATE users SET failed_attempts = 0, locked_until = 0 WHERE user_id = ?",
                                     (row["user_id"],))
                else:
                    failed = row["failed_attempts"] + 1
                    locked = now + self._lockout if failed >= self._max_attempts else 0
                    self._db.execute("UPDATE users SET failed_attempts = ?, locked_until = ? WHERE user_id = ?",
                                     (0 if locked else failed, locked, row["user_id"]))
        except sqlite3.Error as error:
            raise StorageError(f"User database write failed: {error}") from error
        if not ok:
            raise InvalidCredentials()
        return self._user(row)

    def change_password(self, username: str, old_password: str, new_password: str) -> None:
        user = self.authenticate(username, old_password)
        validate_password(new_password, user.username)
        try:
            with self._db:
                self._db.execute("UPDATE users SET password_hash = ? WHERE user_id = ?",
                                 (self._hash(new_password), user.user_id))
        except sqlite3.Error as error:
            raise StorageError(f"User database write failed: {error}") from error

    def get_by_username(self, username: str) -> User | None:
        row = self._row(username) if isinstance(username, str) else None
        return self._user(row) if row is not None else None

    def list_users(self) -> list[User]:
        try:
            rows = self._db.execute("SELECT * FROM users ORDER BY created_at, username_key").fetchall()
        except sqlite3.Error as error:
            raise StorageError(f"User database read failed: {error}") from error
        return [self._user(row) for row in rows]

    def close(self) -> None:
        self._db.close()
