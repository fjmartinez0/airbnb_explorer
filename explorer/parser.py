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


def parse_calendar(payloads: list[dict]) -> list[dict]:
    """Merge the days of every captured calendar response, one record per date."""
    days: dict[str, dict] = {}
    for payload in payloads:
        for month in find_key(payload, "calendarMonths") or []:
            for day in month.get("days") or []:
                date = day.get("calendarDate")
                if not date:
                    continue
                price = day.get("price") or {}
                if isinstance(price, dict):
                    price = price.get("localPriceFormatted") or price.get("localPrice") or ""
                days[date] = {
                    "date": date,
                    "available": day.get("available"),
                    "available_checkin": day.get("availableForCheckin"),
                    "available_checkout": day.get("availableForCheckout"),
                    "min_nights": day.get("minNights"),
                    "max_nights": day.get("maxNights"),
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
