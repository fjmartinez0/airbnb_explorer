"""Turn Airbnb's calendar responses and page text into plain records."""
from __future__ import annotations

import re
from typing import Any


def find_key(obj: Any, key: str) -> Any:
    """Return the first value stored under `key` at any depth of a JSON object.

    Searching by key instead of a fixed path keeps the parser working when
    Airbnb reshuffles the surrounding structure.
    """
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for value in obj.values():
            found = find_key(value, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = find_key(value, key)
            if found is not None:
                return found
    return None


def _calendar_days(obj):
    """Every object that carries a calendarDate, wherever it sits in the response.

    Walking the whole response (instead of a fixed path such as
    calendarMonths -> days) survives Airbnb's renames of the surrounding structure.
    """
    if isinstance(obj, dict):
        if obj.get("calendarDate"):
            yield obj
            return
        for value in obj.values():
            yield from _calendar_days(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _calendar_days(value)


def _first(day: dict, *keys):
    for key in keys:
        if day.get(key) is not None:
            return day[key]
    return None


def parse_calendar(payloads: list[dict]) -> list[dict]:
    """Merge the days of every captured calendar response, one record per date.

    Days without a recognisable availability flag are skipped; if none has one,
    the capture is reported as format_changed and the raw response is kept.
    """
    days: dict[str, dict] = {}
    for payload in payloads:
        for day in _calendar_days(payload):
            available = _first(day, "available", "isAvailable")
            if not isinstance(available, bool):
                continue
            price = day.get("price") or {}
            if isinstance(price, dict):
                price = price.get("localPriceFormatted") or price.get("localPrice") or ""
            days[day["calendarDate"]] = {
                "date": day["calendarDate"],
                "available": available,
                "available_checkin": _first(day, "availableForCheckin", "isAvailableForCheckin"),
                "available_checkout": _first(day, "availableForCheckout", "isAvailableForCheckout"),
                "min_nights": _first(day, "minNights", "minimumNights"),
                "max_nights": _first(day, "maxNights", "maximumNights"),
                "price": price or "",
            }
    return [days[d] for d in sorted(days)]


_REVIEWS = re.compile(
    r"(\d[\d.,]*)\s+(?:reseñas|reseña|evaluaciones|evaluación|reviews|review)\b", re.I
)


def parse_review_count(page_text: str) -> str:
    """Best-effort review count from the listing page text ('' if not found)."""
    match = _REVIEWS.search(page_text or "")
    return re.sub(r"[.,]", "", match.group(1)) if match else ""


_HOST = re.compile(
    r"(?:Anfitri[oó]na?|Hospedado por|Hospedada por|Hosted by)\s*:?\s*([^\n·|•]{2,40})", re.I
)


def parse_host_name(page_text: str) -> str:
    """Best-effort host name from the listing page text ('' if not found)."""
    match = _HOST.search(page_text or "")
    if not match:
        return ""
    name = match.group(1).strip()
    # Drop trailing badges such as "Superanfitrión" or "Superhost".
    name = re.split(r"\s+(?:Superanfitri|Superhost|\d)", name)[0].strip(" .,")
    return name
