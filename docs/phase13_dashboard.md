# Phase 13: PyQt6 dashboard

## What changed

A desktop dashboard shows one player's Reach Garden history. You log in (or create an
account), then see summary numbers, a trend chart, and a table of your rounds. It
refreshes itself every 5 seconds, so a round you just finished appears without clicking.

```text
LoginDialog ──► UserStore (Phase 12) ──► DashboardWindow ──► ResultStore.list_sessions(user_id=you)
                                              │
                                              └─ app/dashboard_model.py (numbers and text, no Qt)
```

- `app/dashboard.py`: the login window and the dashboard window.
- `app/dashboard_model.py`: summary maths and formatting, separate from Qt so it is tested directly.
- It reads through the Phase 11 store interface, so it works with SQLite, JSONL, or MongoDB.
- The dashboard only reads. It never changes or deletes rounds.

## What you see

| Area | Contents |
|---|---|
| Header | Who is signed in, **Refresh**, **Log out** |
| Cards | Rounds, accuracy, best streak, average reaction time, hold stability, path efficiency |
| Chart | Accuracy (%) and reaction time (s) for each round, oldest on the left; a round with no value leaves a gap |
| Table | Newest round first: played, hand, watered, accuracy, reaction, movement, stability, efficiency, time |
| Status line | Last update time, how many rounds, and total play time |

How the numbers are built (definitions of each metric are in [Phase 9](phase9_session_stats.md)):

- **Accuracy** is flowers watered divided by flowers attempted across all shown rounds, so a long round counts more than a short one. It is not the average of each round's accuracy.
- **Reaction, hold stability, and path efficiency** are the average of the rounds that have a value. A round with none (for example, nothing was watered) is left out, never counted as zero, and shows as "-".
- **Best streak** is the longest run of watered flowers in any shown round.
- The dashboard shows the 500 most recent rounds.

With no rounds yet it says so and tells you how to start saving them.

## Run it on Windows 11

1. Create a player once, if you have not ([Phase 12](phase12_accounts.md)):

   ```powershell
   .\.venv\Scripts\python.exe -m backend.users create steve
   ```
2. Start the dashboard:

   ```powershell
   .\.venv\Scripts\python.exe -m app.dashboard
   ```

   It uses `data/motionplay.db` by default. `--store jsonl|sqlite|mongo`, `--file`, and `--users-db` match the other tools. Accounts are always looked up in the `--users-db` SQLite file.
3. To see rounds appear live, start the receiver for the same player in another terminal, then play Reach Garden:

   ```powershell
   .\.venv\Scripts\python.exe -m backend.result_receiver --store sqlite --user steve
   ```

The login window can create an account: click **Create account**, enter the password
twice, and it logs you in. Passwords are hidden as you type, and a wrong password gives
the same message whether or not the username exists. After five wrong passwords the
account locks for five minutes.

## Acceptance checklist

- [ ] `python -m app.dashboard` opens a login window; the password field hides what you type.
- [ ] A wrong password shows "Error: Invalid username or password." and stays on the login window.
- [ ] A correct login shows your name, six cards, the chart, and your rounds newest first.
- [ ] Rounds from another player never appear.
- [ ] Finish a round in Unity with the receiver running as your player; within about 5 seconds it appears (or click **Refresh**).
- [ ] A round where nothing was watered shows "-" for reaction, stability, and efficiency, and a gap in the reaction line.
- [ ] **Log out** returns to the login window; closing the dashboard window exits.
- [ ] A brand-new player sees the "No rounds yet" message.
- [ ] The window is readable in both light and dark Windows themes, and resizes without clipping the cards.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_dashboard -v
```

19 new cases: the numbers and formatting (empty data, overall accuracy, missing values
not counted as zero, trend order and gaps) and the windows (login success, wrong
password, hidden password field, account creation and its errors, lockout message,
only your own rounds, newest first, dashes, refresh, log out, and a storage failure).
They run with Qt's offscreen mode, so no display is needed. Colors, spacing, and how
the window looks in dark mode or on a high-DPI screen are not covered by tests; use
the checklist above.

The **Export report...** button, added in [Phase 14](phase14_reports.md), saves a PDF. This is a gameplay prototype for a
portfolio project, not a medical device or therapy tool, and the numbers have no
clinical meaning.
