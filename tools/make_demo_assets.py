"""Generate the dashboard and report images used in the documentation from clearly synthetic demo data.

Nothing here touches your real data: it builds a throwaway SQLite database with an invented player ("demo") and about
five weeks of invented rounds, then renders the real dashboard window, the real login dialog, and the real PDF report
pages from it. The numbers are made up to show the layout; they are not measurements.

    .\\.venv\\Scripts\\python.exe -m tools.make_demo_assets            # writes into docs/images/
    .\\.venv\\Scripts\\python.exe -m tools.make_demo_assets --out DIR  # somewhere else

The window screenshots use Qt's real platform (Qt's "offscreen" platform has no fonts, so text would be missing), so a
window may flash briefly on your screen while it runs. Pass --no-windows to skip them and write only the report pages.
"""

from __future__ import annotations

import argparse
import random
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from shared.protocol import SessionEnd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = PROJECT_ROOT / "docs" / "images"
DEMO_USER = "demo"
DEMO_PASSWORD = "demo-password-1"
# Fixed, so regenerating the images gives the same pictures.
NOW = datetime(2026, 10, 6, 18, 0)
SEED = 20261006


def demo_rounds(count: int = 42) -> list[SessionEnd]:
    """Invented rounds with a plausible learning curve and difficulty levels that rise as accuracy does."""
    rng = random.Random(SEED)
    stream = str(uuid4())
    rounds = []
    level = 3
    streak = 0
    start = NOW - timedelta(days=34)
    for index in range(count):
        progress = index / (count - 1)
        accuracy = min(1.0, max(0.25, 0.58 + 0.46 * progress + rng.uniform(-0.12, 0.12) - 0.03 * (level - 3)))
        attempted = 8
        completed = max(0, min(attempted, round(accuracy * attempted)))
        reaction = max(0.28, 0.95 - 0.45 * progress + rng.uniform(-0.12, 0.12) + 0.03 * (level - 3))
        movement = max(0.5, 1.5 - 0.5 * progress + rng.uniform(-0.2, 0.2))
        stability = min(1.0, max(0.4, 0.62 + 0.30 * progress + rng.uniform(-0.08, 0.08)))
        efficiency = min(1.0, max(0.35, 0.50 + 0.32 * progress + rng.uniform(-0.08, 0.08)))
        # Mimic the adaptive rule: two easy rounds in a row raise the level, two hard ones lower it.
        if completed / attempted >= 0.9 and stability >= 0.8:
            streak = streak + 1 if streak > 0 else 1
        elif completed / attempted <= 0.5:
            streak = streak - 1 if streak < 0 else -1
        else:
            streak = 0
        label = f"level_{level}"
        if streak >= 2 and level < 5:
            level, streak = level + 1, 0
        elif streak <= -2 and level > 1:
            level, streak = level - 1, 0
        ended = min(start + timedelta(days=progress * 33.5 + rng.uniform(0, 0.4), hours=rng.uniform(0, 3)), NOW - timedelta(minutes=30))
        duration = rng.uniform(22, 40) + (1 - progress) * 12
        best = min(completed, max(1, completed - rng.randint(0, 2))) if completed else 0
        ended_ms = int(ended.timestamp() * 1000)
        rounds.append(SessionEnd(
            stream_id=stream, sequence=index, timestamp=ended_ms, session_id=str(uuid4()), game="reach_garden",
            hand="right", difficulty=label, startedAt=ended_ms - int(duration * 1000), endedAt=ended_ms,
            duration=round(duration, 2), score=completed, targetsAttempted=attempted, targetsCompleted=completed,
            currentStreak=min(best, completed), bestStreak=best, accuracy=completed / attempted,
            averageReactionTime=round(reaction, 3) if completed else None,
            averageMovementTime=round(movement, 3) if completed else None,
            averageHoldStability=round(stability, 3) if completed else None,
            pathEfficiency=round(efficiency, 3) if completed else None,
        ))
    return rounds


def build_demo_store(folder: Path):
    """Create the throwaway database; returns (store, users, user)."""
    from backend.auth import UserStore
    from backend.storage import SqliteResultStore

    database = folder / "demo.db"
    users = UserStore(database, rounds=4)  # fewer bcrypt rounds: this account is never used for real
    user = users.create_user(DEMO_USER, DEMO_PASSWORD)
    store = SqliteResultStore(database)
    for result in demo_rounds():
        store.save(result, user.user_id)
    return store, users, user


def write_report_assets(store, user, out: Path) -> list[Path]:
    from app.report import build_report, write_pdf

    documents = store.list_sessions(user_id=user.user_id, limit=5000)
    pages = build_report(documents, DEMO_USER, NOW, "Demo data (invented)")
    written = []
    for number, figure in enumerate(pages[:3], start=1):  # summary, trends, first table page
        name = {1: "report-summary.png", 2: "report-trends.png", 3: "report-rounds.png"}[number]
        figure.savefig(out / name, dpi=110)
        written.append(out / name)
    write_pdf(pages, out / "sample-report.pdf")
    written.append(out / "sample-report.pdf")
    return written


def write_window_assets(store, users, user, out: Path) -> list[Path]:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication

    from app.dashboard import DashboardWindow, LoginDialog

    app = QApplication.instance() or QApplication(sys.argv[:1])
    written = []

    dialog = LoginDialog(users)
    dialog.username_edit.setText(DEMO_USER)
    dialog.adjustSize()
    dialog.show()
    app.processEvents()
    dialog.grab().save(str(out / "login.png"))
    written.append(out / "login.png")
    dialog.close()

    window = DashboardWindow(store, user, refresh_ms=0)
    window.resize(1180, 760)
    # The screenshot must not pick up the real mouse pointer hovering over a table cell.
    window.table.setMouseTracking(False)
    window.table.viewport().setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    window.show()
    for _ in range(5):  # let layout and the chart settle
        app.processEvents()
    window.table.setCurrentItem(None)  # no focus highlight on one stray cell
    window.table.clearSelection()
    app.processEvents()
    window.grab().save(str(out / "dashboard.png"))
    written.append(out / "dashboard.png")
    window.close()
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate documentation images from synthetic demo data")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Folder for the images (default: docs/images)")
    parser.add_argument("--no-windows", action="store_true", help="Skip the window screenshots (no window is shown)")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        store, users, user = build_demo_store(Path(folder))
        try:
            written = write_report_assets(store, user, args.out)
            if not args.no_windows:
                written += write_window_assets(store, users, user, args.out)
        finally:
            store.close()
            users.close()
    for path in written:
        print(f"wrote {path}  ({path.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
