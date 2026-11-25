"""Write viewer/data.js so the viewer loads the latest captures on its own.

Each observation is stored as a start date plus one character per night
('1' available, '0' unavailable, '-' missing), which keeps the file small.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from .config import CALENDAR_CSV, PRICES_CSV, SNAPSHOTS_CSV, VIEWER_DATA_JS, load_listings
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


def capture_runs(snapshots: list[dict]) -> list[dict]:
    """Capture health per day: how many listings ended the day with status ok.

    A retry or a later run on the same day overrides earlier rows for that listing.
    """
    final: dict[tuple, tuple] = {}
    for snap in snapshots:  # chronological
        final[(snap["observed_date"], snap["label"])] = (snap.get("observed_time", ""), snap.get("status", ""))
    by_date: dict[str, dict] = {}
    for (day, _label), (run_time, status) in final.items():
        entry = by_date.setdefault(day, {"date": day, "time": run_time, "ok": 0, "total": 0})
        entry["total"] += 1
        entry["ok"] += status == "ok"
        entry["time"] = max(entry["time"], run_time)
    return [by_date[d] for d in sorted(by_date)]


def price_quotes(rows: list[dict]) -> dict[str, list[dict]]:
    """Successful price quotes per label, in the compact form the viewer reads."""
    quotes: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("status") != "ok" or not r.get("per_night"):
            continue
        quotes.setdefault(r["label"], []).append({
            "observed_date": r["observed_date"], "check_in": r["check_in"],
            "nights": int(float(r["nights"] or 0)), "per_night": round(float(r["per_night"])),
            "total": round(float(r["total"] or 0)), "weekend": str(r.get("weekend")) == "True",
        })
    return quotes


def build_viewer_data(rows: list[dict], details: dict[str, dict] | None = None,
                      runs: list[dict] | None = None, quotes: dict[str, list[dict]] | None = None) -> dict:
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
            "quotes": (quotes or {}).get(label, []),
            "observations": []})
        entry["observations"].append({
            "observed_date": observed_date, "observed_time": obs["time"],
            "start": first.isoformat(), "availability": availability,
        })
    return {"generated_at": datetime.now().isoformat(timespec="minutes"),
            "runs": runs or [],
            "listings": list(listings.values())}


def export_viewer_data() -> None:
    snapshots = read_rows(SNAPSHOTS_CSV)
    data = build_viewer_data(read_rows(CALENDAR_CSV), listing_details(snapshots), capture_runs(snapshots),
                             price_quotes(read_rows(PRICES_CSV)))
    VIEWER_DATA_JS.parent.mkdir(parents=True, exist_ok=True)
    VIEWER_DATA_JS.write_text(
        "window.AIRBNB_DATA = " + json.dumps(data, ensure_ascii=False) + ";\n", encoding="utf-8")
