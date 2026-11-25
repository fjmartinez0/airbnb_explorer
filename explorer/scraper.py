"""Open a listing in a real browser and catch the calendar Airbnb loads for it.

The calendar is not in the page HTML: the site requests it with JavaScript
(an API call whose name contains "AvailabilityCalendar"). Letting a real browser load the page and
copying that response avoids hard-coding Airbnb's internal URLs or API keys.

The browser keeps a persistent profile (cookies, cache) between runs and moves
at a human pace: variable waits and scrolling. Volume stays low by design.
"""
from __future__ import annotations

import json
import random
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

from playwright.sync_api import BrowserContext, sync_playwright

from .config import BROWSER_PROFILE_DIR

# Airbnb renames this call from time to time:
#   until 9 Nov 2026: PdpAvailabilityCalendar
#   from 10 Nov 2026: StaysPdpAtomicAvailabilityCalendarV2Query
# Any API call whose name contains this marker is treated as the calendar.
CALENDAR_MARKER = "AvailabilityCalendar"
# Calls that carry the price quote when the page is opened with dates.
QUOTE_MARKERS = ("StaysPdpBookItQuery", "StaysPdpSections")
LISTING_URL = "https://www.airbnb.com.co/rooms/{listing_id}?currency=COP"
DATED_SUFFIX = "&check_in={check_in}&check_out={check_out}&adults={guests}"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)
VIEWPORTS = [(1366, 900), (1440, 900), (1536, 864), (1680, 1050)]


@dataclass
class FetchResult:
    payloads: list[dict] = field(default_factory=list)
    quote_payloads: list[dict] = field(default_factory=list)
    page_text: str = ""
    status: str = "ok"  # ok | redirected | no_calendar | error
    note: str = ""


@contextmanager
def browser_context(visible: bool = False) -> Iterator[BrowserContext]:
    """A Chromium context with a persistent profile, so each run looks like a returning visitor."""
    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    width, height = random.choice(VIEWPORTS)
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_PROFILE_DIR),
            headless=not visible,
            user_agent=USER_AGENT,
            locale="es-CO",
            timezone_id="America/Bogota",
            viewport={"width": width, "height": height},
        )
        try:
            yield context
        finally:
            context.close()


def fetch_calendar(context: BrowserContext, listing_id: str, max_wait_s: int = 45,
                   stay: dict | None = None) -> FetchResult:
    """Load a listing page and keep its calendar response.

    With `stay` ({check_in, check_out, guests}) the page is opened with dates,
    the way a guest browses, and the price quote it shows is kept as well.
    """
    result = FetchResult()
    page = context.new_page()

    def on_response(response):
        url = response.url
        if "/api/" not in url:
            return
        if CALENDAR_MARKER in url:
            try:
                result.payloads.append(response.json())
            except Exception:
                pass
        elif stay and any(m in url for m in QUOTE_MARKERS):
            try:
                body = response.text()
            except Exception:
                return
            if "structuredDisplayPrice" in body:
                try:
                    result.quote_payloads.append(json.loads(body))
                except ValueError:
                    pass

    page.on("response", on_response)
    url = LISTING_URL.format(listing_id=listing_id)
    if stay:
        url += DATED_SUFFIX.format(**stay)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(random.uniform(2500, 6000))  # a person looks at the photos first
        started = time.time()
        # Scrolling triggers the lazy-loaded calendar when it does not arrive on its own.
        while not result.payloads and time.time() - started < max_wait_s:
            page.mouse.wheel(0, random.randint(500, 1300))
            page.wait_for_timeout(random.uniform(1200, 3200))
        page.wait_for_timeout(random.uniform(1500, 3500))  # a second calendar response sometimes follows
        quote_wait = time.time()
        while stay and not result.quote_payloads and time.time() - quote_wait < 12:
            page.wait_for_timeout(1000)
        try:
            result.page_text = page.inner_text("body", timeout=10_000)
        except Exception:
            result.page_text = ""
        if "/rooms/" not in page.url:
            result.status, result.note = "redirected", f"terminó en {page.url}"
        elif not result.payloads:
            result.status, result.note = "no_calendar", "no llegó la respuesta del calendario"
    except Exception as exc:
        result.status, result.note = "error", f"{type(exc).__name__}: {exc}"[:300]
    finally:
        page.close()
    return result
