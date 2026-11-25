"""Daily capture: fetch each listing's calendar (and a price quote) and append it to the data files."""
from __future__ import annotations

import csv
import json
import random
import time
from datetime import date, datetime, timedelta

from . import notify
from .config import CALENDAR_CSV, PRICES_CSV, RAW_DIR, SNAPSHOTS_CSV, Listing
from .parser import find_display_price, parse_calendar, parse_host_name, parse_quote, parse_review_count
from .scraper import browser_context, fetch_calendar
from .storage import CALENDAR_FIELDS, PRICE_FIELDS, SNAPSHOT_FIELDS, append_rows, log
from .viewer_data import export_viewer_data

WEEKEND_NIGHTS = (4, 5)  # a stay is "weekend" if it includes a Friday or Saturday night


def _previous_calendars(before: str) -> dict[str, dict[str, tuple]]:
    """Per label, the last calendar captured before `before`: date -> (available, min_nights).

    Streams calendar.csv (chronological) instead of loading it whole.
    """
    best: dict[str, tuple] = {}            # label -> (observed_date, observed_time)
    cal: dict[str, dict[str, tuple]] = {}
    if not CALENDAR_CSV.exists():
        return cal
    with CALENDAR_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["observed_date"] >= before:
                continue
            key, stamp = row["label"], (row["observed_date"], row["observed_time"])
            if key not in best or stamp > best[key]:
                best[key], cal[key] = stamp, {}
            if stamp == best[key]:
                avail = {"true": True, "false": False}.get(str(row["available"]).lower())
                try:
                    min_n = int(float(row.get("min_nights") or 0)) or None
                except ValueError:
                    min_n = None
                cal[key][row["date"]] = (avail, min_n)
    return cal


def choose_stay(previous: dict | None, today: date, settings: dict) -> dict | None:
    """Dates to quote: a free stay 12-20 days out, alternating weekend and weekday by day.

    Weekend = the stay includes a Friday or Saturday night; weekday = only Sunday-Thursday nights.

    Uses yesterday's calendar so we do not ask for nights that were already taken.
    Returns None when nothing suitable was free.
    """
    lo, hi = settings.get("quote_lead_days", [12, 20])
    max_nights = int(settings.get("quote_max_nights", 7))
    want_weekend = today.toordinal() % 2 == 0
    options = []
    for lead in range(int(lo), int(hi) + 1):
        check_in = today + timedelta(days=lead)
        nights = 2
        if previous is not None:
            info = previous.get(check_in.isoformat())
            if not info or info[0] is not True:
                continue
            nights = max(2, info[1] or 2)
            if nights > max_nights:
                continue
            if any((previous.get((check_in + timedelta(days=k)).isoformat()) or (None,))[0] is not True
                   for k in range(nights)):
                continue
        weekend = any((check_in + timedelta(days=k)).weekday() in WEEKEND_NIGHTS for k in range(nights))
        options.append((weekend != want_weekend, abs(lead - 14), lead, check_in, nights, weekend))
    if not options:
        return None
    _, _, lead, check_in, nights, weekend = min(options)
    return {"check_in": check_in.isoformat(), "check_out": (check_in + timedelta(days=nights)).isoformat(),
            "nights": nights, "lead_days": lead, "weekend": weekend,
            "guests": int(settings.get("quote_guests", 2))}


def _covers_today(days: list[dict], observed_date: str) -> bool:
    return any(d["date"] == observed_date for d in days)


def _capture_one(context, listing: Listing, stamp: dict, observed_date: str,
                 previous: dict | None, settings: dict) -> dict:
    stay = None
    if settings.get("quote_enabled", True):
        stay = choose_stay(previous, date.fromisoformat(observed_date), settings)
    url_stay = {k: stay[k] for k in ("check_in", "check_out", "guests")} if stay else None

    result = fetch_calendar(context, listing.listing_id, stay=url_stay)
    days = parse_calendar(result.payloads)

    # Opened with dates, the page might ask for the calendar from the check-in month
    # onwards. If today is missing, load the listing once more without dates.
    if stay and days and not _covers_today(days, observed_date):
        time.sleep(random.uniform(20, 60))
        log(f"{listing.label}: el calendario con fechas no incluye hoy; se carga sin fechas")
        plain = fetch_calendar(context, listing.listing_id)
        if parse_calendar(plain.payloads):
            plain.quote_payloads = result.quote_payloads
            result, days = plain, parse_calendar(plain.payloads)

    if result.payloads:
        raw_path = RAW_DIR / f"{listing.label}_{listing.listing_id}_{observed_date}.json"
        raw_path.write_text(json.dumps(result.payloads, ensure_ascii=False), encoding="utf-8")
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
        new_nights = sum(1 for d in upcoming
                         if d["available"] is False and (previous.get(d["date"]) or (None,))[0] is True)

    append_rows(SNAPSHOTS_CSV, SNAPSHOT_FIELDS, [{
        **stamp, "status": result.status, "days_captured": len(days),
        "unavailable_next_7d": blocked_7, "unavailable_next_30d": blocked_30,
        "review_count": parse_review_count(result.page_text),
        "host_name": parse_host_name(result.page_text), "note": result.note,
    }])

    # Price quote
    price_row, per_night = None, None
    if settings.get("quote_enabled", True):
        price_row = {**stamp, "guests": settings.get("quote_guests", 2)}
        if not stay:
            price_row.update(status="no_dates", note="ninguna estadía libre a 12-20 días según la captura anterior")
        else:
            display = find_display_price(result.quote_payloads)
            quote = parse_quote(display)
            price_row.update({k: stay[k] for k in ("check_in", "check_out", "nights", "lead_days", "weekend")})
            if display:
                raw_q = RAW_DIR / f"{listing.label}_{listing.listing_id}_{observed_date}_quote.json"
                raw_q.write_text(json.dumps(display, ensure_ascii=False), encoding="utf-8")
            if quote and quote["total"]:
                nights = quote["nights"] or stay["nights"]
                per_night = round(quote["total"] / nights)
                price_row.update({k: v for k, v in quote.items() if k != "nights"})
                price_row.update(status="ok", nights=nights, per_night=per_night)
            else:
                price_row.update(status="no_quote", note="la página no mostró precio para esas fechas")

    quote_txt = f" Precio: ${per_night:,.0f}/noche ({stay['check_in']}, {stay['nights']} n)." if per_night else ""
    log(f"{listing.label} ({listing.listing_id}): {result.status}, {len(days)} días, "
        f"no disp. 7d={blocked_7} 30d={blocked_30}.{quote_txt} {result.note}".rstrip())
    return {"label": listing.label, "status": result.status, "blocked_30": blocked_30,
            "new_nights": new_nights, "per_night": per_night, "price_row": price_row}


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
    previous = _previous_calendars(observed_date)
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
            prev = previous.get(listing.label)
            outcome = _capture_one(context, listing, stamp, observed_date, prev, settings)
            if outcome["status"] != "ok" and settings.get("retry_failed"):
                time.sleep(random.uniform(60, 120))
                log(f"{listing.label}: reintento")
                outcome = _capture_one(context, listing, stamp, observed_date, prev, settings)
            if outcome["price_row"]:
                append_rows(PRICES_CSV, PRICE_FIELDS, [outcome["price_row"]])
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
