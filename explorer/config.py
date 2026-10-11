"""Project paths and listing configuration."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
ANALYSIS_DIR = DATA_DIR / "analysis"
CALENDAR_CSV = DATA_DIR / "calendar.csv"
SNAPSHOTS_CSV = DATA_DIR / "snapshots.csv"
LOG_FILE = DATA_DIR / "capture.log"

BROWSER_PROFILE_DIR = DATA_DIR / "browser_profile"

VIEWER_DATA_JS = ROOT / "viewer" / "data.js"
LISTINGS_FILE = ROOT / "listings.json"
SETTINGS_FILE = ROOT / "settings.json"

DEFAULT_SETTINGS = {
    "ntfy_topic": "",
    "ntfy_server": "https://ntfy.sh",
    "start_delay_minutes": 0,                # optional random delay before a scheduled run
    "pause_between_listings_seconds": [60, 300],
    "retry_failed": True,
    "publish_github_pages": False,           # push the viewer to the gh-pages branch after each capture
    "public_url": "",                        # link opened from the notification
    "public_include_identifiers": False,     # host names and listing IDs on the public page
}


def load_settings(path: Path = SETTINGS_FILE) -> dict:
    """settings.json merged over the defaults (the file is optional)."""
    settings = dict(DEFAULT_SETTINGS)
    if path.exists():
        settings.update(json.loads(path.read_text(encoding="utf-8")))
    return settings


@dataclass(frozen=True)
class Listing:
    label: str
    listing_id: str
    zone: str = ""
    host: str = ""  # optional manual override of the host name shown in the viewer
    note: str = ""


def load_listings(path: Path = LISTINGS_FILE) -> list[Listing]:
    """Read listings.json and return the valid listings."""
    if not path.exists():
        raise SystemExit(
            f"No encontré {path.name}. Copia listings.example.json como listings.json "
            "y pon los IDs de tus anuncios."
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    listings: list[Listing] = []
    seen: set[str] = set()
    for item in raw.get("listings", []):
        listing_id = str(item.get("id", "")).strip()
        label = str(item.get("label", "")).strip() or listing_id
        if not listing_id.isdigit():
            print(f"Aviso: '{label}' no tiene un ID numérico ({listing_id!r}); se omite.")
            continue
        if label in seen:
            raise SystemExit(f"La etiqueta '{label}' está repetida en {path.name}.")
        seen.add(label)
        listings.append(Listing(
            label=label,
            listing_id=listing_id,
            zone=str(item.get("zone", "")).strip(),
            host=str(item.get("host", "")).strip(),
            note=str(item.get("note", "")),
        ))
    if not listings:
        raise SystemExit(f"{path.name} no tiene anuncios válidos.")
    return listings
