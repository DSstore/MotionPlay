# Phase 15: Adaptive difficulty

## What changed

Reach Garden now has five difficulty levels. After each finished round the game looks at how
you did and may move the level one step for the next round. The rules live in
`Core/ReachGardenDifficulty.cs` (`MotionPlay.Games`, no Unity types), so the .NET harness tests
the same code Unity runs.

## Levels

| Level | Target radius | Dwell | Time per flower | Min. separation |
|---|---|---|---|---|
| 1 | 0.70 | 0.50 s | 10 s | 1.00 |
| 2 | 0.60 | 0.65 s | 9 s | 1.25 |
| **3** | 0.50 | 0.80 s | 8 s | 1.50 |
| 4 | 0.40 | 1.00 s | 6.5 s | 1.85 |
| 5 | 0.30 | 1.20 s | 5 s | 2.20 |

Level 3 equals the original Phase 8 rules and is the starting level. The flower count
(`targetCount`, default 8) is not part of difficulty.

## How the level moves

Judged once per finished round, ignoring rounds with fewer than 4 finished flowers:

- **Too easy:** accuracy ≥ 90% *and* hold stability ≥ 80%.
- **Too hard:** accuracy ≤ 50%.
- The level changes by one step only after **two such rounds in a row**. A round in between
  that is neither resets the count. The level never leaves 1 to 5.

Adjustment happens between rounds only; the settings are never changed mid-round. The end-of-round
panel says when the level changed. These thresholds are first guesses to tune with real play.

## Using it in Unity

- The level is saved with `PlayerPrefs` (key `MotionPlay.ReachGarden.Level`), so it is per
  Windows user on this machine, not per MotionPlay account.
- **[** and **]** lower or raise the level by hand while waiting or on the summary screen
  (ignored mid-round). A manual change is saved too.
- Untick **Adaptive** on the Reach Garden component to stop automatic changes; manual keys still work.
- The `targetRadius`, `dwellSeconds` and `targetTimeoutSeconds` inspector fields are gone: the level
  now decides them. Old scenes load fine; the stale values are ignored.
- Each result is sent with `difficulty` = `level_N`, the level the round was *played* at (not the
  level it leads to).

## Dashboard and reports

The round table has a **Level** column. Rounds saved before this phase (`default`) are shown as
level 3, which matches the rules they used. Unknown labels show a dash. When a report's rounds span more
than one level, the progress comparison carries a note that earlier and later rounds are not like
for like, because a higher level is harder and can lower accuracy even when play improves.

## Tests

```powershell
dotnet run --project tests/csharp/MotionPlay.ReceiverHarness.csproj -- --noresult
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

New C# cases cover preset validity and ordering, label parsing, the two-round rule, streak reset,
end clamps, manual set, no-data rounds, and applying settings only between rounds. New Python cases
cover level parsing, the table column, and the mixed-level report note.

Not covered by automated tests: the `PlayerPrefs` save/load, the `[`/`]` keys, and the HUD. Check in the
Unity Editor:

- [ ] A fresh install starts at level 3 and the HUD shows "Level 3 (auto)".
- [ ] Two near-perfect rounds raise the level and show "Level up"; the next flowers are smaller.
- [ ] Two poor rounds lower it.
- [ ] `[` and `]` change the level on the waiting and summary screens but not mid-round.
- [ ] Stop and restart Play Mode; the level is remembered.
- [ ] The dashboard Level column matches what you played.

This is a gameplay-tuning feature for a portfolio project, not a clinical assessment.
