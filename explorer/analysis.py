"""Compare consecutive captures and detect bookings, releases and lead times.

For each listing, every observation is compared with the previous one:
- new booking: a future night that went from available to unavailable
- release:     a night that went from unavailable to available
               (cancellation or the host unblocking it)
Consecutive nights that change on the same day are grouped into one event
(roughly one stay). Very long new blocks are flagged as probable host blocks.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import ANALYSIS_DIR, CALENDAR_CSV

LONG_BLOCK_NIGHTS = 28


def load_calendar(path: Path = CALENDAR_CSV) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"listing_id": str, "observed_time": str})
    df["date"] = pd.to_datetime(df["date"])
    df["observed_date"] = pd.to_datetime(df["observed_date"])
    df["available"] = df["available"].astype(str).str.lower().map({"true": True, "false": False})
    df = df.dropna(subset=["available"])
    # Several runs on the same day: keep the last one.
    last_run = df.groupby(["label", "observed_date"])["observed_time"].transform("max")
    return df[df["observed_time"] == last_run]


def _group_runs(dates: list, kind: str, label: str, listing_id: str, prev_obs, obs) -> list[dict]:
    events, dates = [], sorted(dates)
    start = 0
    for i in range(1, len(dates) + 1):
        if i < len(dates) and (dates[i] - dates[i - 1]).days == 1:
            continue
        first, last = dates[start], dates[i - 1]
        nights = (last - first).days + 1
        events.append({
            "label": label, "listing_id": listing_id, "type": kind,
            "previous_observation": prev_obs.date(), "detected_on": obs.date(),
            "days_between_observations": (obs - prev_obs).days,
            "check_in": first.date(), "check_out": (last + pd.Timedelta(days=1)).date(),
            "nights": nights, "lead_time_days": (first - obs).days,
            "probable_host_block": kind == "new_booking" and nights >= LONG_BLOCK_NIGHTS,
        })
        start = i
    return events


def analyze_listing(label: str, listing_id: str, g: pd.DataFrame) -> tuple[list[dict], dict]:
    grid = g.pivot(index="date", columns="observed_date", values="available").sort_index(axis=1)
    observations = list(grid.columns)
    events: list[dict] = []
    for prev_obs, obs in zip(observations, observations[1:]):
        before, after = grid[prev_obs], grid[obs]
        comparable = before.notna() & after.notna() & (grid.index >= obs)  # past nights always show unavailable
        booked = grid.index[comparable & (before == True) & (after == False)]
        released = grid.index[comparable & (before == False) & (after == True)]
        events += _group_runs(list(booked), "new_booking", label, listing_id, prev_obs, obs)
        events += _group_runs(list(released), "release", label, listing_id, prev_obs, obs)

    ev = pd.DataFrame(events)
    bookings = ev[(ev["type"] == "new_booking") & (~ev["probable_host_block"])] if len(ev) else ev

    # Occupancy of the observed period: nights between the first and last capture,
    # judged by the last state seen before each night passed.
    first, last = observations[0], observations[-1]
    period = pd.date_range(first, last - pd.Timedelta(days=1))
    occupied = 0
    for night in period:
        if night not in grid.index:
            continue
        seen = [o for o in observations if o <= night and pd.notna(grid.at[night, o])]
        if seen and grid.at[night, seen[-1]] == False:
            occupied += 1

    # Nights 30-90 days out that never changed while blocked: likely host blocks.
    window = grid.loc[(grid.index >= first + pd.Timedelta(days=30)) & (grid.index < first + pd.Timedelta(days=90))]
    always_blocked = int((window == False).all(axis=1).sum()) if len(window) else 0

    def stat(series, fn):
        return round(float(fn(series)), 1) if len(series) else None

    summary = {
        "label": label, "listing_id": listing_id,
        "observations": len(observations),
        "first_observation": first.date(), "last_observation": last.date(),
        "bookings_detected": len(bookings),
        "nights_booked": int(bookings["nights"].sum()) if len(bookings) else 0,
        "median_lead_time_days": stat(bookings.get("lead_time_days", []), pd.Series.median),
        "pct_booked_within_14d": stat((bookings["lead_time_days"] <= 14) if len(bookings) else [], lambda s: 100 * s.mean()),
        "median_stay_nights": stat(bookings.get("nights", []), pd.Series.median),
        "nights_released": int(ev.loc[ev["type"] == "release", "nights"].sum()) if len(ev) else 0,
        "probable_host_blocks": int(ev["probable_host_block"].sum()) if len(ev) else 0,
        "period_nights": len(period),
        "period_occupancy_pct": round(100 * occupied / len(period), 1) if len(period) else None,
        "nights_30_90d_always_blocked": always_blocked,
        "nights_30_90d_total": int(len(window)),
    }
    return events, summary


def run_analysis(path: Path = CALENDAR_CSV) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not path.exists():
        raise SystemExit(f"No hay datos todavía: falta {path}. Corre primero la captura.")
    df = load_calendar(path)
    all_events, summaries = [], []
    for (label, listing_id), g in df.groupby(["label", "listing_id"]):
        events, summary = analyze_listing(label, listing_id, g)
        all_events += events
        summaries.append(summary)
    events_df, summary_df = pd.DataFrame(all_events), pd.DataFrame(summaries)
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    events_df.to_csv(ANALYSIS_DIR / "events.csv", index=False)
    summary_df.to_csv(ANALYSIS_DIR / "summary.csv", index=False)
    return events_df, summary_df
