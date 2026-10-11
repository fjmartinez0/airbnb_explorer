"""Write viewer/data.js so the viewer loads the latest captures on its own.

Each observation is stored as a start date plus one character per night
('1' available, '0' unavailable, '-' missing), which keeps the file small.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from .config import CALENDAR_CSV, SNAPSHOTS_CSV, VIEWER_DATA_JS, load_listings
from .storage import read_rows


def _flag(value: str) -> str:
    v = str(value).strip().lower()
    return "1" if v == "true" else "0" if v == "false" else "-"


def listing_details(snapshots: list[dict]) -> dict[str, dict]:
    """Zone and host name per label: listings.json first, then the latest captured host name."""
    details: dict[str, dict] = {}
    for snap in snapshots:  # chronological, so later captures overwrite earlier ones
        if snap.get("host_name"):
            details.setdefault(snap["label"], {})["host"] = snap["host_name"]
    try:
        configured = load_listings()
    except SystemExit:
        configured = []
    for listing in configured:
        entry = details.setdefault(listing.label, {})
        entry["zone"] = listing.zone
        if listing.host:
            entry["host"] = listing.host
    return details


def build_viewer_data(rows: list[dict], details: dict[str, dict] | None = None) -> dict:
    # Keep only the last run of each day for each listing.
    latest: dict[tuple, dict] = {}
    for row in rows:
        key = (row["label"], row["listing_id"], row["observed_date"])
        run_time = row["observed_time"]
        current = latest.get(key)
        if current is None or run_time > current["time"]:
            current = latest[key] = {"time": run_time, "nights": {}}
        if run_time == current["time"]:
            current["nights"][row["date"]] = _flag(row["available"])

    listings: dict[tuple, dict] = {}
    for (label, listing_id, observed_date), obs in sorted(latest.items()):
        nights = obs["nights"]
        first = date.fromisoformat(min(nights))
        last = date.fromisoformat(max(nights))
        span = (last - first).days + 1
        availability = "".join(
            nights.get((first + timedelta(days=i)).isoformat(), "-") for i in range(span)
        )
        info = (details or {}).get(label, {})
        entry = listings.setdefault((label, listing_id), {
            "label": label, "listing_id": listing_id,
            "zone": info.get("zone", ""), "host": info.get("host", ""),
            "observations": []})
        entry["observations"].append({
            "observed_date": observed_date, "observed_time": obs["time"],
            "start": first.isoformat(), "availability": availability,
        })
    return {"generated_at": datetime.now().isoformat(timespec="minutes"),
            "listings": list(listings.values())}


def export_viewer_data() -> None:
    data = build_viewer_data(read_rows(CALENDAR_CSV), listing_details(read_rows(SNAPSHOTS_CSV)))
    VIEWER_DATA_JS.parent.mkdir(parents=True, exist_ok=True)
    VIEWER_DATA_JS.write_text(
        "window.AIRBNB_DATA = " + json.dumps(data, ensure_ascii=False) + ";\n", encoding="utf-8")
