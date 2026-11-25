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


# ---------------------------------------------------------------------------
# Price quotes
# ---------------------------------------------------------------------------

def parse_money(text) -> float | None:
    """'$356,400.00 COP' -> 356400.0; also '356.400', '-$20,000'. None if not a number."""
    if text is None:
        return None
    raw = str(text)
    negative = "-" in raw or "−" in raw
    s = re.sub(r"[^\d.,]", "", raw)
    if not s or not any(c.isdigit() for c in s):
        return None
    if "," in s and "." in s:
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", s) else s.replace(",", ".")
    elif "." in s and re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        value = float(s)
    except ValueError:
        return None
    return -value if negative else value


def _price_items(obj):
    """Every {description, priceString} line inside a price explanation, at any depth."""
    if isinstance(obj, dict):
        if "description" in obj and "priceString" in obj:
            yield obj
        for value in obj.values():
            yield from _price_items(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _price_items(value)


def find_display_price(payloads: list) -> dict | None:
    """The first non-empty structuredDisplayPrice in the captured responses."""
    def walk(obj):
        if isinstance(obj, dict):
            sdp = obj.get("structuredDisplayPrice")
            if isinstance(sdp, dict) and sdp.get("primaryLine"):
                return sdp
            for value in obj.values():
                found = walk(value)
                if found:
                    return found
        elif isinstance(obj, list):
            for value in obj:
                found = walk(value)
                if found:
                    return found
        return None
    return walk(payloads)


_NIGHTS_X_RATE = re.compile(r"(\d+)\s*noches?\s*[x×]\s*(\S+)", re.I)
_NIGHTS = re.compile(r"(\d+)\s*noches?", re.I)


def parse_quote(display_price: dict | None) -> dict | None:
    """Total, per-night price and fee lines from Airbnb's structuredDisplayPrice.

    `total` is what the guest pays. In Colombia it is shown fees included
    (displayPriceStyle TOTAL_ONLY), so `per_night` = total / nights is the
    all-in nightly price, not what the host receives.
    """
    if not display_price:
        return None
    primary = display_price.get("primaryLine") or {}
    total = parse_money(primary.get("discountedPrice") or primary.get("price"))
    qualifier = primary.get("qualifier") or ""
    out = {"total": total, "nights": None, "nightly_rate": None, "cleaning": None,
           "service_fee": None, "taxes": None, "discount": None,
           "display_style": display_price.get("displayPriceStyle") or "", "items": ""}
    m = _NIGHTS.search(qualifier)
    if m:
        out["nights"] = int(m.group(1))
    lines = []
    for item in _price_items(display_price.get("explanationData") or {}):
        desc, amount = item.get("description") or "", parse_money(item.get("priceString"))
        lines.append(f"{desc}={item.get('priceString')}")
        low = desc.lower()
        m = _NIGHTS_X_RATE.search(desc)
        if m:
            out["nights"] = out["nights"] or int(m.group(1))
            out["nightly_rate"] = parse_money(m.group(2))
        elif "limpieza" in low or "cleaning" in low:
            out["cleaning"] = amount
        elif "servicio" in low or "service" in low:
            out["service_fee"] = amount
        elif "impuesto" in low or "tax" in low:
            out["taxes"] = amount
        elif "descuento" in low or "discount" in low or (amount is not None and amount < 0):
            out["discount"] = amount
    out["items"] = "; ".join(lines)
    return out
