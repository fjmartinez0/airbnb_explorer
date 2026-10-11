"""Publish the viewer to GitHub Pages (branch gh-pages of the project's own repo).

Each publish rebuilds data/site/ from scratch (viewer + data.js + .nojekyll)
and force-pushes it as a single commit to gh-pages, so the branch never grows
with daily history. The main branch is never touched.

By default the public copy leaves out host names and listing IDs.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime

from .config import CALENDAR_CSV, DATA_DIR, ROOT, SNAPSHOTS_CSV
from .storage import log, read_rows
from .viewer_data import build_viewer_data, listing_details

SITE_DIR = DATA_DIR / "site"
BRANCH = "gh-pages"


def _git(args: list[str], cwd) -> str:
    git = shutil.which("git") or "/usr/bin/git"
    done = subprocess.run([git, *args], cwd=cwd, capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])}: {(done.stderr or done.stdout).strip()[:300]}")
    return done.stdout.strip()


def public_data(include_identifiers: bool) -> dict:
    data = build_viewer_data(read_rows(CALENDAR_CSV), listing_details(read_rows(SNAPSHOTS_CSV)))
    if not include_identifiers:
        for listing in data["listings"]:
            listing["host"] = ""
            listing["listing_id"] = ""
    data["public"] = True
    return data


def publish_site(settings: dict) -> str:
    """Build and push the public site. Returns the public URL (or '' if unknown)."""
    remote = _git(["remote", "get-url", "origin"], ROOT)
    data = public_data(bool(settings.get("public_include_identifiers")))

    shutil.rmtree(SITE_DIR, ignore_errors=True)
    SITE_DIR.mkdir(parents=True)
    shutil.copy(ROOT / "viewer" / "index.html", SITE_DIR / "index.html")
    (SITE_DIR / "data.js").write_text(
        "window.AIRBNB_DATA = " + json.dumps(data, ensure_ascii=False) + ";\n", encoding="utf-8")
    (SITE_DIR / ".nojekyll").write_text("", encoding="utf-8")

    _git(["init", "-q"], SITE_DIR)
    _git(["checkout", "-q", "-b", BRANCH], SITE_DIR)
    _git(["add", "-A"], SITE_DIR)
    _git(["commit", "-q", "-m", f"Datos al {datetime.now():%Y-%m-%d %H:%M}"], SITE_DIR)
    _git(["push", "-q", "--force", remote, f"{BRANCH}:{BRANCH}"], SITE_DIR)

    url = settings.get("public_url", "")
    log(f"Publicado en GitHub Pages{f': {url}' if url else ''}")
    return url
