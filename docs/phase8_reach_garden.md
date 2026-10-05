# Phase 8: Reach Garden gameplay

## What changed

Reach Garden is the first game built on the Phase 7 hand cursor. Flowers (plain
geometric circles, no artwork) appear one at a time. Hold the cursor on a flower
to water it; the flower's fill grows and turns green as you dwell. If you do not
finish in time, the flower is missed and the next one appears. After eight
flowers the round ends and a blue "play again" circle appears at the center.

```text
HandCursorController ──(cursor position, IsTracking)──► ReachGardenController ──► ReachGardenGame (Core rules)
                                                              │
                                                              └─► geometric target + HUD
```

- `Core/ReachGardenGame.cs` (`MotionPlay.Games`) holds all rules and has no
  Unity types, so the .NET harness tests the same code Unity runs.
- `Runtime/ReachGardenController.cs` converts the cursor to camera-plane
  coordinates, steps the game each frame, and draws the target and HUD.
- `Editor/ReachGardenSceneSetup.cs` adds **MotionPlay → Create Reach Garden Scene**.

## Rules

| Rule | Default | Notes |
|---|---|---|
| Flowers per round | 8 | `targetCount` |
| Target radius | 0.5 world units | Cursor center must be inside the circle |
| Dwell to water | 0.8 s | Progress drains 1.5× faster than it fills when you leave or lose tracking |
| Time per flower | 8 s | Counts down only while the hand is tracked; pauses on loss |
| Minimum reach | 1.5 units | Consecutive flowers are at least this far apart |
| Start | Hand first tracked | Round begins when the selected hand appears |
| Restart | Dwell on blue circle, or **R** | You must leave the circle once first, so a cursor parked at the center cannot restart instantly |

A single frame step is capped at 0.1 s so a hitch cannot water a flower. Targets
are always placed inside the view, inset by the target radius and an edge margin,
and are re-clamped if the Game view is resized. Flower positions are random per
play (seeded from the clock); tests use fixed seeds.

This phase keeps only the counts the current round needs (watered, missed). Session
statistics, reaction times, and saving results come in later phases. Gesture
recognition does not affect gameplay yet; position and dwell only.

## Run it on Windows 11

1. Open `unity/MotionPlay` in Unity 2022.3.62f3 and wait for scripts to compile.
   Check the Console for red errors.
2. Click **MotionPlay → Create Reach Garden Scene**. This saves
   `Assets/MotionPlay/Scenes/ReachGarden.unity` and leaves the other scenes alone.
3. Click **Game**, press **Play**. The HUD (top right) says "Show your hand to begin."
4. Close any Python UDP monitor, then run:

   ```powershell
   .\.venv\Scripts\python.exe -m cv_engine.controller
   ```

5. Show your hand. Flowers appear; move the cursor onto one and hold still.

## Acceptance checklist

- [ ] No flower appears until the hand is first tracked.
- [ ] Holding on a flower waters it in about 0.8 s and the next flower appears elsewhere.
- [ ] Moving off a flower mid-dwell drains the fill instead of resetting instantly.
- [ ] Flowers never appear partly outside the Game view, including after changing the aspect ratio.
- [ ] Hiding your hand pauses the flower timer; the HUD time stops counting down.
- [ ] Leaving a flower alone for 8 tracked seconds counts it as missed.
- [ ] After flower 8 the summary appears; sitting on the blue circle does not restart until you leave and return.
- [ ] Dwelling on the blue circle, or pressing **R**, starts a new round with counts at zero.
- [ ] Close Python mid-round, restart it, and play continues.
- [ ] Note whether 0.8 s dwell and 8 s timeout feel reasonable. They are inspector fields on **Reach Garden**.

## Tests

The standalone harness has 87 C# cases, including 15 new Reach Garden cases
(phase changes, placement bounds and separation, dwell fill/drain, timeout pause,
frame-step cap, completion, restart arming, resize, bad input, and validation):

```powershell
dotnet run --project tests/csharp/MotionPlay.ReceiverHarness.csproj -- --noresult
```

The Unity controller, rendering, HUD, and keyboard restart are not covered by
automated tests; they need the manual checklist above in the Unity Editor. This is
a gameplay prototype for a portfolio project, not a medical device or therapy tool.
