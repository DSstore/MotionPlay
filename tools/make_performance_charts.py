"""Draw the charts in docs/performance.md from the measurements recorded during development.

Every number below was measured on one Windows 11 PC with one webcam while building MotionPlay; where it came from is noted beside it.
The runs were not controlled experiments (the hand movement differed between runs, and the samples are small), so the charts
show what was observed, not a benchmark.

    .\\.venv\\Scripts\\python.exe -m tools.make_performance_charts            # writes into docs/images/
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "docs" / "images"

# Seconds from "Opening webcam" to "Webcam opened" in the CV engine's log, one value per run.
CAMERA_OPEN = {
    "Default backend\n(Media Foundation)": [6.3, 20.4, 22.6, 29.0],
    "DirectShow,\nfirst version": [4.3, 4.4, 4.5],
    "DirectShow, skipping\nredundant settings": [2.5, 2.6, 2.7, 2.8],
}

# Median of the engine's 5-second frame-rate readings during live play (about three minutes each).
FRAME_RATE_LIVE = [
    ("Original:\nfull model,\npreview window", 10.6),
    ("Lighter model", 15.0),
    ("No preview\nwindow", 21.4),
    ("+ label\ncontinuity", 22.0),
]
# Average over a six-minute live session after the DirectShow change (a whole-run average, not a median).
FRAME_RATE_FINAL = ("+ DirectShow\n(whole-run average)", 27.2)
# Camera and MediaPipe only, no Unity, 20-second recordings.
HEADLESS = {"full model": 17.1, "lighter model": 29.4}

# Short tracking flickers (hand lost for under half a second) per minute of play, from the engine's log.
FLICKERS = [
    ("Full model,\npreview", 2.4, "7 in 177 s"),
    ("Lighter model,\npreview", 8.8, "25 in 171 s"),
    ("Lighter model,\nno preview", 3.9, "13 in 201 s"),
    ("+ label\ncontinuity", 1.6, "4 in 151 s"),
]

BASE = "#4a6fa5"
ACCENT = "#c8553d"
GREY = "#7a7a7a"


def style(axis) -> None:
    axis.spines[["top", "right"]].set_visible(False)
    axis.grid(axis="y", alpha=0.25)
    axis.set_axisbelow(True)


def camera_open_chart(out: Path) -> Path:
    figure, axis = plt.subplots(figsize=(8, 4.6))
    names = list(CAMERA_OPEN)
    for position, name in enumerate(names):
        runs = CAMERA_OPEN[name]
        color = ACCENT if position == len(names) - 1 else BASE
        axis.bar(position, sum(runs) / len(runs), color=color, alpha=0.35, width=0.55)
        axis.scatter([position] * len(runs), runs, color=color, zorder=3, s=36)
        axis.text(position, max(runs) + 1, f"{min(runs):.1f} to {max(runs):.1f} s" if len(runs) > 1 else f"{runs[0]:.1f} s",
                  ha="center", fontsize=10)
    axis.set_xticks(range(len(names)), names)
    axis.set_ylabel("Seconds to open the camera")
    axis.set_ylim(0, 34)
    axis.set_title("Opening the webcam in the CV engine (each dot is one run)", loc="left", fontsize=12)
    style(axis)
    figure.text(0.01, 0.01, "One Windows 11 PC, one webcam. The default backend's open time varied a lot from run to run.",
                fontsize=8, color=GREY)
    figure.tight_layout(rect=(0, 0.03, 1, 1))
    path = out / "perf-camera-open.png"
    figure.savefig(path, dpi=130)
    plt.close(figure)
    return path


def frame_rate_chart(out: Path) -> Path:
    figure, axis = plt.subplots(figsize=(8.6, 4.8))
    labels = [name for name, _ in FRAME_RATE_LIVE] + [FRAME_RATE_FINAL[0]]
    values = [value for _, value in FRAME_RATE_LIVE] + [FRAME_RATE_FINAL[1]]
    colors = [BASE] * len(FRAME_RATE_LIVE) + [ACCENT]
    bars = axis.bar(range(len(values)), values, color=colors, width=0.6)
    for bar, value in zip(bars, values):
        axis.text(bar.get_x() + bar.get_width() / 2, value + 0.5, f"{value:.1f}", ha="center", fontsize=10)
    axis.axhline(30, color=GREY, linestyle=":", linewidth=1)
    axis.text(len(values) - 0.45, 30.4, "30 FPS target", ha="right", fontsize=8, color=GREY)
    for style_, (name, value) in zip(("--", "-."), HEADLESS.items()):
        axis.axhline(value, color=ACCENT if style_ == "--" else BASE, linestyle=style_, linewidth=0.8, alpha=0.7)
        # The lighter model's line sits right under the 30 FPS target, so its label goes below the line.
        above = value < 25
        axis.text(-0.45, value + (0.4 if above else -0.5), f"{name}, camera and MediaPipe alone: {value:.1f}",
                  fontsize=8, color=GREY, va="bottom" if above else "top")
    axis.set_xticks(range(len(values)), labels, fontsize=9)
    axis.set_ylabel("Frames per second of the CV loop")
    axis.set_ylim(0, 35)
    axis.set_title("CV engine frame rate during live play, with Unity running", loc="left", fontsize=12)
    style(axis)
    figure.text(0.01, 0.01, "Live bars are medians of 5-second readings (the last is a whole-run average). Hand movement differed between runs.",
                fontsize=8, color=GREY)
    figure.tight_layout(rect=(0, 0.03, 1, 1))
    path = out / "perf-frame-rate.png"
    figure.savefig(path, dpi=130)
    plt.close(figure)
    return path


def flicker_chart(out: Path) -> Path:
    figure, axis = plt.subplots(figsize=(8, 4.6))
    bars = axis.bar(range(len(FLICKERS)), [row[1] for row in FLICKERS],
                    color=[BASE] * (len(FLICKERS) - 1) + [ACCENT], width=0.6)
    for bar, (_, value, sample) in zip(bars, FLICKERS):
        axis.text(bar.get_x() + bar.get_width() / 2, value + 0.2, f"{value:.1f}", ha="center", fontsize=10)
        axis.text(bar.get_x() + bar.get_width() / 2, 0.15, sample, ha="center", fontsize=8, color="white")
    axis.set_xticks(range(len(FLICKERS)), [row[0] for row in FLICKERS], fontsize=9)
    axis.set_ylabel("Brief hand losses per minute (under 0.5 s)")
    axis.set_ylim(0, 10.5)
    axis.set_title("Short tracking flickers during live play", loc="left", fontsize=12)
    style(axis)
    figure.text(0.01, 0.01, "Small samples (white text inside each bar) and different movement each run: a direction, not a measurement.",
                fontsize=8, color=GREY)
    figure.tight_layout(rect=(0, 0.03, 1, 1))
    path = out / "perf-flicker.png"
    figure.savefig(path, dpi=130)
    plt.close(figure)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Draw the performance charts from recorded measurements")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Folder for the images (default: docs/images)")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    for path in (camera_open_chart(args.out), frame_rate_chart(args.out), flicker_chart(args.out)):
        print(f"wrote {path}  ({path.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
