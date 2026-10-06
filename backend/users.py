"""Manage local player accounts: create, check a login, change a password, list.

Passwords are always typed at a hidden prompt, never given on the command line.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from backend.auth import AuthError, User, UserStore
from backend.storage import StorageError
from shared.config import PROJECT_ROOT, ConfigurationError, load_settings
from shared.logger import start_logging

DEFAULT_USERS_DB = Path("data") / "motionplay.db"
Prompt = Callable[[str], str]


def add_user_arguments(parser: argparse.ArgumentParser, *, required_user: bool = False) -> None:
    parser.add_argument("--user", required=required_user,
                        help="Log in as this player (the password is asked for at a hidden prompt)")
    parser.add_argument("--users-db", type=Path, default=DEFAULT_USERS_DB,
                        help="SQLite file holding accounts (default: data/motionplay.db)")


def open_users(path: Path, **options) -> UserStore:
    path = path if path.is_absolute() else PROJECT_ROOT / path
    return UserStore(path, **options)


def log_in(username: str, users_db: Path, prompt: Prompt = getpass.getpass, **options) -> User:
    """Ask for the password and return the verified user. Raises AuthError on failure."""
    users = open_users(users_db, **options)
    try:
        return users.authenticate(username, prompt(f"Password for {username}: "))
    finally:
        users.close()


def _create(users: UserStore, args: argparse.Namespace, prompt: Prompt) -> str:
    password = prompt("New password: ")
    if prompt("Repeat password: ") != password:
        raise AuthError("The two passwords do not match.")
    user = users.create_user(args.username, password)
    return f"Created player {user.username}."


def _login(users: UserStore, args: argparse.Namespace, prompt: Prompt) -> str:
    user = users.authenticate(args.username, prompt(f"Password for {args.username}: "))
    return f"Login OK for {user.username}."


def _passwd(users: UserStore, args: argparse.Namespace, prompt: Prompt) -> str:
    old = prompt("Current password: ")
    new = prompt("New password: ")
    if prompt("Repeat new password: ") != new:
        raise AuthError("The two passwords do not match.")
    users.change_password(args.username, old, new)
    return f"Password changed for {args.username}."


def _list(users: UserStore, args: argparse.Namespace, prompt: Prompt) -> str:
    found = users.list_users()
    lines = [f"{len(found)} player(s)."]
    for user in found:
        created = datetime.fromtimestamp(user.created_at / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        lines.append(f"  {user.username:<20} created {created}")
    return "\n".join(lines)


def _start_logging() -> None:
    """Record account events in the log file. Accounts still work if logging cannot be set up."""
    try:
        start_logging(load_settings(), "accounts", console=False)
    except (ConfigurationError, OSError) as error:
        print(f"Note: account events will not be logged ({error}).", file=sys.stderr)


def main(argv: list[str] | None = None, *, prompt: Prompt = getpass.getpass, **options) -> int:
    parser = argparse.ArgumentParser(description="MotionPlay player accounts")
    parser.add_argument("--users-db", type=Path, default=DEFAULT_USERS_DB,
                        help="SQLite file holding accounts (default: data/motionplay.db)")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, helptext in (("create", "Create a player"), ("login", "Check a username and password"),
                           ("passwd", "Change a password")):
        commands.add_parser(name, help=helptext).add_argument("username")
    commands.add_parser("list", help="List players")
    args = parser.parse_args(argv)

    actions = {"create": _create, "login": _login, "passwd": _passwd, "list": _list}
    users = None
    _start_logging()
    try:
        users = open_users(args.users_db, **options)
        print(actions[args.command](users, args, prompt))
    except AuthError as error:
        print(f"Account error: {error}", file=sys.stderr)
        return 1
    except (StorageError, OSError, EOFError) as error:
        print(f"Account error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 1
    finally:
        if users is not None:
            users.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
