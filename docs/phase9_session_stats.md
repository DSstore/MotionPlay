# Phase 9: Session statistics

## What changed

Reach Garden now measures each round. `Core/ReachGardenStats.cs` (`MotionPlay.Games`)
holds the metric definitions and has no Unity types, so the .NET harness tests the
same code Unity runs. `ReachGardenGame.Stats` exposes it, it resets whenever a round
starts, and the end-of-round HUD panel shows the summary.

Nothing is saved or sent yet. Statistics live in memory for the current round only.
Sending results to Python and storing them is Phase 10.

## Metrics

Times are seconds of **tracked** hand time, distances are camera-plane world units,
ratios are 0 to 1. A metric with no samples is `null` (shown as "-"), never zero.

| Metric | Definition |
|---|---|
| `Attempted` | Flowers finished, watered plus missed |
| `Watered` / `Score` | Flowers watered (score equals watered for now) |
| `Accuracy` | Watered ÷ attempted |
| `CurrentStreak` / `BestStreak` | Consecutive watered flowers; a miss resets the current streak |
| `AverageReactionTime` | Tracked time from the flower appearing until the cursor first moves 0.1 units from where it started (or enters the flower, if sooner) |
| `AverageMovementTime` | Tracked time from that movement onset until the cursor first enters the flower |
| `AverageHoldStability` | Share of tracked time since first entry that the cursor stayed inside the flower |
| `AveragePathEfficiency` | Straight-line distance to the entry point ÷ distance the cursor actually travelled; skipped if tracking was lost on the way or the cursor started inside the flower |
| `DurationSeconds` | Play time since the round began, including time the hand was lost |

Reaction, movement, stability, and efficiency use every flower the cursor entered,
watered or not. A flower the cursor never entered contributes only to attempted,
accuracy, and the streak.

These are gameplay measurements for a portfolio project, not a medical device, and
carry no clinical meaning. `startedAt`, `endedAt`, `hand`, and `difficulty` from the
reserved protocol fields need a clock and settings plumbing and were added in Phase 10.

## Check it in Unity

1. Play **ReachGarden** with the Python CV engine running (see the [Phase 8 guide](phase8_reach_garden.md)).
2. Finish a round. The panel at the top right shows accuracy, best streak, reaction,
   movement, hold stability, path efficiency, and time.
3. Let one or two flowers time out and confirm accuracy drops and the streak resets.
4. Press **R** and confirm the next round starts from zero.

## Tests

The standalone harness has 96 C# cases, including 9 new statistics cases (null before
data, direct approach, detour, leaving the flower, never-entered miss, streaks, lost
tracking, restart reset, and a full round staying in range):

```powershell
dotnet run --project tests/csharp/MotionPlay.ReceiverHarness.csproj -- --noresult
```

The HUD summary needs the manual check above in the Unity Editor.
