# Phase 14: Progress reports

## What changed

You can save a PDF progress report for a player. It summarizes their rounds, compares
earlier rounds with later ones, charts the trends, and lists every round. Make one
from the dashboard (**Export report...**) or from the command line.

```text
dashboard "Export report..." ─┐
                               ├─► app/report.py ─► build_report() ─► pages ─► write_pdf() ─► your .pdf
python -m app.report --user ───┘        │
                                        └─ uses app/dashboard_model.py for the numbers and text
```

- `app/report.py`: the report builder, the PDF writer, and the command.
- It reads rounds through the Phase 11 store interface, only for the logged-in player (Phase 12).
- The PDF is made with matplotlib, which is already a project dependency; nothing new to install.

## What is in the report

| Page | Contents |
|---|---|
| 1 | Player, period, when it was made, a plain disclaimer; a summary table; an earlier-versus-later comparison |
| 2 | Four trend charts by round, oldest to newest: accuracy, reaction time, hold stability, path efficiency |
| 3 onward | Every round, newest first, 28 per page |

Each page has a footer with the player's name and the page number.

### The earlier-versus-later comparison

With at least 4 rounds, the rounds (by time) are split in half. The first half is
"earlier" and the rest is "later". For each measure the report shows both values, the
change, and a word:

| Measure | Counted as a change when it moves by | Better is |
|---|---|---|
| Accuracy | 2 points or more | higher |
| Reaction time | 0.03 s or more | lower |
| Hold stability | 2 points or more | higher |
| Path efficiency | 2 points or more | higher |

Smaller moves read "about the same". If either half has no value for a measure (for
example, nothing was watered), it says "not enough data" rather than treating the
missing value as zero. With fewer than 4 rounds the page says there are not enough
rounds to compare yet.

These words describe the numbers, not the player. With few rounds a difference can
come from luck, tiredness, or lighting as easily as from practice, and the report says
so on the page. Metric definitions are in [Phase 9](phase9_session_stats.md). This is a
gameplay prototype for a portfolio project, not a medical device or therapy tool, and
the report must not be used for health conclusions.

## Make a report (Windows 11, PowerShell)

From the dashboard: open it (`python -m app.dashboard`), log in, click **Export report...**,
and pick where to save. The suggested folder is `reports/` in the project (ignored by Git)
and the name looks like `MotionPlay-progress-steve-20261006-1200.pdf`. The status line
at the bottom says whether it was saved, or why not.

From the command line (asks for the password at a hidden prompt):

```powershell
.\.venv\Scripts\python.exe -m app.report --user steve
.\.venv\Scripts\python.exe -m app.report --user steve --days 30
.\.venv\Scripts\python.exe -m app.report --user steve --since 2026-10-01 --out my-report.pdf
```

`--days N` or `--since YYYY-MM-DD` limit the period (not both). Without `--out` the file
goes to `reports/`. A relative `--out` is relative to where you ran the command. The
store options match the other tools (`--store sqlite|jsonl|mongo`, `--file`, `--users-db`).
The report covers up to 5,000 of the most recent rounds. If there are no rounds in the
period it says so and writes nothing. The file is written through a temporary copy, so a
failure never leaves a half-written report.

## Acceptance checklist

- [ ] **Export report...** opens a save dialog starting in `reports/` with a sensible file name.
- [ ] The PDF opens in your PDF viewer and has a summary page, a charts page, and a rounds table.
- [ ] Rounds and totals match the dashboard for the same player.
- [ ] A round where nothing was watered shows "-" in the table and a gap in the reaction chart, not 0.
- [ ] Another player's rounds never appear in your report.
- [ ] `python -m app.report --user steve --days 1` only includes today's rounds.
- [ ] A player with no rounds gets "nothing to report" and no file.
- [ ] Text is not cut off at the page edges when printed or viewed at 100%.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_report -v
```

22 new cases: the comparison (too few rounds, direction of better, small differences,
missing values, time order), the pages (text, charts, paging, dashes and chart gaps),
the PDF file (valid PDF, atomic write, unwritable target), the period filter and
filename, the command (own rounds only, `--days`, wrong password, no rounds, bad
arguments), and the dashboard export (writes a PDF, reports failures, own rounds only).
They check the report's content and structure, not how it looks; I reviewed sample
pages by eye while building it, so please check the last item above on your own screen.
Reports for a whole group of players, scheduled reports, and emailing them are not
included.
