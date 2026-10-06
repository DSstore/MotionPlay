# Recording the demo

The generated images (dashboard, login, sample report, charts) are in `docs/images/` and come from invented demo data. Two things only you can capture, because they need your camera and Unity:
a **short clip of the game** and a **picture of the hand tracking**. This guide says what to capture and how to add it.

## What to capture

| File | What | Notes |
|---|---|---|
| `docs/images/demo.gif` | 10 to 20 seconds of Reach Garden being played, ideally showing a flower filling, the next one appearing, and the end-of-round panel | Keep it under about 5 MB so GitHub shows it inline. Crop to the Unity Game view. |
| `docs/images/tracking-preview.png` | The CV engine's preview window (run `python -m cv_engine.controller` without `--no-preview`) showing the landmarks, the white circle for the raw palm and the magenta cross for the smoothed one | Crop to the hand, or use your own hand against a plain background: the preview shows whatever is behind you. |
| `docs/images/game.png` (optional) | A still of the Unity Game view mid-round | The HUD shows the level and the flower count. |

## How

1. Start everything with `MotionPlay-Start.cmd -User <name>` and press Play in Unity.
2. Record with **Win+G** (Xbox Game Bar) or **ScreenToGif**. For a GIF, ScreenToGif can record and export in one step; to convert an MP4, `ffmpeg -i demo.mp4 -vf "fps=12,scale=720:-1" demo.gif`.
3. Save the files under `docs/images/` with the names above.
4. Add them to the README's gallery (see the commented lines in the **Screenshots** section).

## Privacy checklist before you commit

- Your face, room, or other people may be visible in the preview and in any screen recording. Crop them out or use a plain background.
- Check the window title bars and the desktop for names, email addresses, tabs and notifications.
- The dashboard images here use the invented player `demo`. If you record your own dashboard, your player name and play history become public.

## Regenerating the generated images

```powershell
.\.venv\Scripts\python.exe -m tools.make_demo_assets          # dashboard, login, sample report
.\.venv\Scripts\python.exe -m tools.make_performance_charts   # the performance charts
```

The first command briefly shows a window on screen (Qt's real platform is needed for text). Both are deterministic, so the images only change when the code that draws them does.
