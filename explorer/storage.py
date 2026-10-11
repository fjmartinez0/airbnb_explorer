"""CSV files and the capture log."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from .config import DATA_DIR, LOG_FILE

CALENDAR_FIELDS = [
    "observed_date", "observed_time", "label", "listing_id", "date",
    "available", "available_checkin", "available_checkout",
    "min_nights", "max_nights", "price",
]

SNAPSHOT_FIELDS = [
    "observed_date", "observed_time", "label", "listing_id", "status",
    "days_captured", "unavailable_next_7d", "unavailable_next_30d",
    "review_count", "host_name", "note",
]


def append_rows(path: Path, fields: list[str], rows: list[dict]) -> None:
    """Append rows to a CSV, writing the header the first time."""
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if is_new:
            writer.writeheader()
        writer.writerows(rows)


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def log(message: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {message}"
    print(line)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
