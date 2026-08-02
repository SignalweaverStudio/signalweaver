from __future__ import annotations

import csv
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


EPOCH = "B2"
ACTIVE_SESSION_FILE = Path(".lacunar_active_session.json")


def timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def append_event(notes_path: Path, event: str, detail: str) -> None:
    new_file = not notes_path.exists()

    with notes_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)

        if new_file:
            writer.writerow(["event", "timestamp", "detail"])

        writer.writerow([event, timestamp(), detail])


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python lacunar_day_start.py 009")
        return 2

    try:
        day = int(sys.argv[1])
    except ValueError:
        print("Day must be a number, for example: 009")
        return 2

    day_text = f"{day:03d}"

    recording_path = Path(f"experiment_{day_text}_all_day.csv")
    notes_path = Path(f"experiment_{day_text}_notes.csv")

    if recording_path.exists():
        print(f"START STOPPED: {recording_path} already exists.")
        return 1

    if notes_path.exists():
        print(f"START STOPPED: {notes_path} already exists.")
        return 1

    if ACTIVE_SESSION_FILE.exists():
        print(
            "START STOPPED: an active Lacuna session marker already exists:\n"
            f"  {ACTIVE_SESSION_FILE}"
        )
        return 1

    session = {
        "day": day_text,
        "epoch": EPOCH,
        "recording": str(recording_path),
        "notes": str(notes_path),
        "started_at": timestamp(),
    }

    append_event(notes_path, "recording_start", recording_path.name)
    append_event(notes_path, "engine_epoch", EPOCH)

    ACTIVE_SESSION_FILE.write_text(
        json.dumps(session, indent=2),
        encoding="utf-8",
    )

    print()
    print("=" * 64)
    print(f"LACUNA DAY {day_text} — ENGINE EPOCH {EPOCH}")
    print("=" * 64)
    print(f"Recording: {recording_path}")
    print(f"Notes:     {notes_path}")
    print()
    print('Add a note from another PowerShell window with:')
    print('python .\\lacunar_note.py "Your note here"')
    print()

    command = [
        sys.executable,
        "lacunar_mirror_v0.py",
        "--mode",
        "live",
        "--log",
        str(recording_path),
    ]

    exit_code = 0

    try:
        result = subprocess.run(command, check=False)
        exit_code = result.returncode
    except KeyboardInterrupt:
        exit_code = 130
    finally:
        append_event(notes_path, "recording_stop", recording_path.name)

        try:
            ACTIVE_SESSION_FILE.unlink()
        except FileNotFoundError:
            pass

        print()
        print(f"Day {day_text} session closed.")
        print(f"Notes written to: {notes_path}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
