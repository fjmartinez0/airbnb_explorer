"""Push notifications through ntfy (https://ntfy.sh).

Topics on the public server are open: anyone who knows the topic name can read
it. Messages therefore carry only labels, statuses and counts.
"""
from __future__ import annotations

import json
import urllib.request

from .storage import log


def send(settings: dict, title: str, message: str, priority: int = 3, tags: list[str] | None = None) -> bool:
    topic = (settings.get("ntfy_topic") or "").strip()
    if not topic:
        return False
    payload = {"topic": topic, "title": title, "message": message,
               "priority": priority, "tags": tags or []}
    request = urllib.request.Request(
        settings.get("ntfy_server", "https://ntfy.sh").rstrip("/"),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15):
            return True
    except Exception as exc:  # a failed notification must never break the capture
        log(f"No se pudo enviar la notificación: {exc}")
        return False


def capture_summary(results: list[dict]) -> tuple[str, str, int, list[str]]:
    """Title, body, priority and tags for the daily capture notification."""
    ok = [r for r in results if r["status"] == "ok"]
    failed = [r for r in results if r["status"] != "ok"]
    lines = []
    for r in sorted(results, key=lambda r: r["label"]):
        if r["status"] != "ok":
            lines.append(f"✗ {r['label']}: {r['status']}")
            continue
        change = ""
        if r.get("new_nights") is not None:
            change = f" · +{r['new_nights']} noches reservadas" if r["new_nights"] else " · sin reservas nuevas"
        lines.append(f"✓ {r['label']}: {r['blocked_30']}/30 no disp.{change}")
    total_new = sum(r.get("new_nights") or 0 for r in ok)
    title = f"Airbnb explorer · {len(ok)}/{len(results)} ok"
    if total_new:
        title += f" · +{total_new} noches"
    priority = 4 if failed else 3
    tags = ["warning"] if failed else ["white_check_mark"]
    return title, "\n".join(lines) or "Sin anuncios.", priority, tags
