from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path


ACTIVE_SESSION_FILE = Path(".lacunar_active_session.json")


def timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def main() -> int:
    if len(sys.argv) < 2:
        print('Usage: python lacunar_note.py "Away to make coffee"')
        return 2

    if not ACTIVE_SESSION_FILE.exists():
        print("No active Lacuna recording session was found.")
        return 1

    session = json.loads(
        ACTIVE_SESSION_FILE.read_text(encoding="utf-8")
    )

    notes_path = Path(session["notes"])
    note = " ".join(sys.argv[1:]).strip()

    if not note:
        print("Note cannot be empty.")
        return 2

    with notes_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["note", timestamp(), note])

    print(f"Note added: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
