"""Daily capture: fetch each listing's calendar and append it to the data files."""
from __future__ import annotations

import json
import random
import time
from datetime import date, datetime, timedelta

from . import notify
from .config import CALENDAR_CSV, RAW_DIR, SNAPSHOTS_CSV, Listing
from .parser import parse_calendar, parse_host_name, parse_review_count
from .scraper import browser_context, fetch_calendar
from .storage import CALENDAR_FIELDS, SNAPSHOT_FIELDS, append_rows, log, read_rows
from .viewer_data import build_viewer_data, export_viewer_data


def _previous_states(before: str) -> dict[str, dict[str, bool]]:
    """Last captured state per label from a day before `before` (date -> available)."""
    data = build_viewer_data(read_rows(CALENDAR_CSV))
    states: dict[str, dict[str, bool]] = {}
    for listing in data["listings"]:
        earlier = [o for o in listing["observations"] if o["observed_date"] < before]
        if not earlier:
            continue
        obs = earlier[-1]
        start = date.fromisoformat(obs["start"])
        states[listing["label"]] = {
            (start + timedelta(days=i)).isoformat(): c == "1"
            for i, c in enumerate(obs["availability"]) if c in "01"
        }
    return states


def _capture_one(context, listing: Listing, stamp: dict, observed_date: str,
                 previous: dict[str, bool] | None) -> dict:
    result = fetch_calendar(context, listing.listing_id)

    if result.payloads:
        raw_path = RAW_DIR / f"{listing.label}_{listing.listing_id}_{observed_date}.json"
        raw_path.write_text(json.dumps(result.payloads, ensure_ascii=False), encoding="utf-8")

    days = parse_calendar(result.payloads)
    if result.payloads and not days:
        result.status = "format_changed"
        result.note = "llegó la respuesta pero no se encontraron días; revisar data/raw"

    if days:
        append_rows(CALENDAR_CSV, CALENDAR_FIELDS, [{**stamp, **d} for d in days])

    upcoming = [d for d in days if d["date"] >= observed_date]
    blocked_7 = sum(1 for d in upcoming[:7] if d["available"] is False)
    blocked_30 = sum(1 for d in upcoming[:30] if d["available"] is False)
    new_nights = None
    if previous is not None and days:
        new_nights = sum(1 for d in upcoming if d["available"] is False and previous.get(d["date"]) is True)

    append_rows(SNAPSHOTS_CSV, SNAPSHOT_FIELDS, [{
        **stamp, "status": result.status, "days_captured": len(days),
        "unavailable_next_7d": blocked_7, "unavailable_next_30d": blocked_30,
        "review_count": parse_review_count(result.page_text),
        "host_name": parse_host_name(result.page_text), "note": result.note,
    }])
    log(f"{listing.label} ({listing.listing_id}): {result.status}, {len(days)} días, "
        f"no disp. 7d={blocked_7} 30d={blocked_30}. {result.note}".rstrip())
    return {"label": listing.label, "status": result.status,
            "blocked_30": blocked_30, "new_nights": new_nights}


def run_capture(listings: list[Listing], settings: dict, visible: bool = False,
                scheduled: bool = False) -> int:
    """Capture every listing once. Returns the number of listings that failed."""
    if scheduled and settings.get("start_delay_minutes"):
        delay = random.uniform(0, float(settings["start_delay_minutes"]) * 60)
        log(f"Inicio programado: espera aleatoria de {delay / 60:.1f} min")
        time.sleep(delay)

    now = datetime.now()
    observed_date, observed_time = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    previous = _previous_states(observed_date)
    pause_min, pause_max = settings.get("pause_between_listings_seconds", [60, 300])

    order = list(listings)
    random.shuffle(order)  # a different order every day
    results: list[dict] = []

    with browser_context(visible=visible) as context:
        for i, listing in enumerate(order):
            if i:
                time.sleep(random.uniform(pause_min, pause_max))
            stamp = {"observed_date": observed_date, "observed_time": observed_time,
                     "label": listing.label, "listing_id": listing.listing_id}
            outcome = _capture_one(context, listing, stamp, observed_date, previous.get(listing.label))
            if outcome["status"] != "ok" and settings.get("retry_failed"):
                time.sleep(random.uniform(60, 120))
                log(f"{listing.label}: reintento")
                outcome = _capture_one(context, listing, stamp, observed_date, previous.get(listing.label))
            results.append(outcome)

    export_viewer_data()
    title, body, priority, tags = notify.capture_summary(results)
    if settings.get("publish_github_pages"):
        from .publish import publish_site
        try:
            publish_site(settings)
        except Exception as exc:  # publishing must never lose the capture
            log(f"No se pudo publicar en GitHub Pages: {exc}")
            body += "\n⚠ No se pudo publicar el visor en GitHub Pages"
            priority = max(priority, 4)
    notify.send(settings, title, body, priority, tags)
    return sum(1 for r in results if r["status"] != "ok")
