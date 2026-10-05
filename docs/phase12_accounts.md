# Phase 12: Player accounts

## What changed

Players now have local accounts, and every saved round can belong to one player.
This is how later phases (dashboard, progress reports, adaptive difficulty) will tell
players apart.

```text
backend.users ──► backend.auth.UserStore ──► users table   ┐
                  (bcrypt, lockout)                         ├─ same SQLite file, data/motionplay.db
backend.result_receiver --user NAME ──► ResultStore ──► sessions table (user_id column)
backend.sessions list --user NAME / claim --user NAME
```

- `backend/auth.py`: accounts, password hashing, lockout.
- `backend/users.py`: the account commands (`create`, `login`, `passwd`, `list`).
- `backend/storage.py`: every store takes a `user_id` on save and can filter by it.
- Unity and the wire protocol are unchanged: the player is chosen when the receiver starts, not sent by the game.

## Account rules

| Rule | Detail |
|---|---|
| Username | 3 to 32 letters, digits, `.`, `-`, `_`; unique ignoring case; kept as typed |
| Password | At least 8 characters and at most 72 bytes (bcrypt ignores anything longer, so longer ones are refused, not silently cut); no NUL character; not the same as the username |
| Storage | bcrypt hash with a random salt (cost 12); the password itself is never stored or logged |
| Wrong login | One message for an unknown user and a wrong password: "Invalid username or password." An unknown username costs the same time as a real check |
| Lockout | 5 wrong passwords in a row lock that account for 5 minutes, even for the right password. A correct login resets the count |
| Password entry | Always at a hidden prompt, never as a command-line argument |

Accounts live in the `users` table of `data/motionplay.db` (`--users-db` changes the file).
They are in SQLite even when rounds are kept in JSONL or MongoDB.

## What accounts do and do not protect

This separates player profiles on one computer. The lockout slows guessing at the
command line, but someone who can open the database file or run code as you can read
the rounds directly, and a determined attacker can still try offline guesses against a
stolen hash file (bcrypt makes each guess slow, but not impossible). The message
"too many failed attempts" also reveals that the account exists. There are no
roles, no email, no password recovery, and nothing leaves the machine. Do not reuse a
password you use elsewhere.

## Commands (Windows 11, PowerShell)

```powershell
.\.venv\Scripts\python.exe -m backend.users create steve     # asks for the password twice
.\.venv\Scripts\python.exe -m backend.users login steve      # checks a password
.\.venv\Scripts\python.exe -m backend.users passwd steve     # change it
.\.venv\Scripts\python.exe -m backend.users list
```

Save rounds for a player (asks for the password once, then every round is theirs):

```powershell
.\.venv\Scripts\python.exe -m backend.result_receiver --store sqlite --user steve
```

Without `--user` the receiver still works and saves rounds with no player.

See your own rounds, or everyone's on this machine:

```powershell
.\.venv\Scripts\python.exe -m backend.sessions list --store sqlite --user steve
.\.venv\Scripts\python.exe -m backend.sessions list --store sqlite --all
```

`list` needs `--user` or `--all`, so a plain `list` never shows rounds by accident.

## Rounds saved before accounts

Rounds from earlier phases have no player. Give them to a player once:

```powershell
.\.venv\Scripts\python.exe -m backend.sessions claim --store sqlite --user steve
```

Only rounds with no player are assigned; rounds that already belong to someone stay
theirs. A SQLite database from Phase 11 gets its new column automatically the first time
it is opened. For JSONL files, `claim` rewrites the file through a temporary copy and
keeps any unreadable lines exactly as they were. `sessions import` keeps the player
each line was saved with; `--user` only fills in lines that have none.

If the same round arrives twice (Unity resending), the first owner is kept and the
receiver answers `duplicate`.

## Acceptance checklist

- [ ] `backend.users create` rejects a short password, mismatched repeats, and a taken name.
- [ ] `backend.users login` succeeds with the right password and says "Invalid username or password." otherwise.
- [ ] Five wrong passwords lock the account; the right password is refused until the lockout ends.
- [ ] The receiver started with `--user` saves a Reach Garden round, and `sessions list --user` shows it.
- [ ] A second player's `list` does not show it, but `list --all` shows both with names.
- [ ] `sessions claim` assigns your old rounds and a second `claim` reports 0.
- [ ] A wrong password at the receiver prompt stops it before it opens the port.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

26 new Python cases cover the username and password rules, hashing and salting,
unique names, identical failure messages, lockout and its expiry, password change,
persistence, the account commands, player ownership at the receiver, listing and
claiming by player, the Phase 11 database upgrade, and the stores' new `user_id`
behavior (shared contract, including the MongoDB stand-in). Unity is unchanged.
Password hashing runs at the lowest cost in tests to keep them fast; the real cost
(12) is only exercised by hand.

This is a gameplay prototype for a portfolio project, not a medical device or therapy tool.
