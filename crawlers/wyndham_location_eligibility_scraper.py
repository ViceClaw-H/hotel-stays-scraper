"""Wyndham location eligibility scanner -- deliberately separate from rate harvesting.

Why this exists
---------------
Wyndham's booking-box suggestions are Google Maps places (cities, landmarks,
airports and countries).  They are *not* a Wyndham hotel catalogue, so they
must never create a hotel or location record.  A country search also searches
only around the country's map centre (150 km by default), so it cannot prove
the whole country's Wyndham footprint.

This scanner instead takes the already-known Wyndham property candidates as
*leads only*, skips every hotel that already has any rate evidence, and asks
Wyndham's own per-property booking endpoint whether a full Free Night (FNS)
award room is available.  It writes location-policy observations and raw
booking evidence, but intentionally writes **no rate_records**.  Cash and
Cash + Points values in the same answers are ignored.

For Wyndham's REDEMPTION_REQUIRED policy:
  * an observed FNS room on any test date -> IN_SCOPE_REDEEMABLE;
  * definitive no-availability on every test date ->
    REDEEMABLE_SOLD_OUT_IN_TEST_WINDOW;
  * a transport/API failure -> UNKNOWN_ELIGIBILITY, never "sold out".

Run examples (from the project root):
  python crawlers\\wyndham_location_eligibility_scraper.py --country Indonesia
  python crawlers\\wyndham_location_eligibility_scraper.py --limit 50
  python crawlers\\wyndham_location_eligibility_scraper.py --hotel wynd_royaldarmosurabaya

The default is intentionally bounded.  Use --all-unpriced only when starting
the resumable wider pass; it contains thousands of official-property checks.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crawlers.wyndham_stream_harvester import (  # shared Wyndham-specific HTTP/page parsing only
    AdaptiveThrottle,
    Fetcher,
    PageVerdict,
    Stats,
    api_url,
    classify_page,
)
from engine.extractors import wyndham as wx
from engine.location_writer import LocationObservation, write_location_observation


SOURCE = "OFFICIAL_WYNDHAM_CRS"
EVIDENCE_DIR = "evidence/wyndham/location"
# One near, then two far dates.  A single award date is enough to qualify a
# location; all three must be definitive no-availability to call it sold out.
TEST_DATES = ("2026-10-07", "2027-03-10", "2027-06-05")


@dataclass(frozen=True)
class Candidate:
    hotel_id: str
    name: str
    country: str
    url: str
    property_id: str | None
    brand_id: str | None


def has_rate(conn: sqlite3.Connection, hotel_id: str) -> bool:
    return bool(conn.execute(
        """SELECT 1 FROM room_categories rc JOIN rate_records rr ON rr.room_id = rc.id
           WHERE rc.hotel_id = ? LIMIT 1""", (hotel_id,)
    ).fetchone())


def load_candidates(conn: sqlite3.Connection, *, country: str | None,
                    hotel_ids: list[str] | None, limit: int | None,
                    all_unpriced: bool) -> list[Candidate]:
    """Load only unpriced candidates.  The catalog is a lead list, not evidence."""
    where = ["h.brand = 'WYNDHAM'", "NOT EXISTS (SELECT 1 FROM room_categories rc "
             "JOIN rate_records rr ON rr.room_id = rc.id WHERE rc.hotel_id = h.id)"]
    args: list[object] = []
    if country:
        where.append("h.country = ?")
        args.append(country)
    if hotel_ids:
        where.append("h.id IN (%s)" % ",".join("?" for _ in hotel_ids))
        args.extend(hotel_ids)
    sql = f"""SELECT h.id, h.name, h.country, h.official_url, m.property_id, m.brand_id
                 FROM hotels h LEFT JOIN wyndham_property_map m ON m.hotel_id = h.id
                 WHERE {' AND '.join(where)} ORDER BY h.country, h.id"""
    rows = [Candidate(*row) for row in conn.execute(sql, args)]
    # A plain invocation must not accidentally start a multi-hour global run.
    if not all_unpriced and not country and not hotel_ids:
        rows = rows[: (limit or 25)]
    elif limit:
        rows = rows[:limit]
    return rows


def full_award_present(body: str | None) -> bool:
    """True only for Wyndham's pure Free Night plan; PAC/hybrid plans do not qualify."""
    try:
        payload = json.loads(body or "")
    except ValueError:
        return False
    for room in (payload.get("roomsAndRates") or {}).get("rooms") or []:
        for rate in room.get("rates") or []:
            if wx.fns_points(rate):
                return True
    return False


def outcome(responses: Iterable[wx.ParsedResponse]) -> tuple[bool, bool, str]:
    """Return (award_attempted, full_award, notes) without converting failure to sold-out."""
    parsed = list(responses)
    if any(full_award_present(getattr(item, "_body", None)) for item in parsed):
        return True, True, "full Free Night award room observed"
    definite = [p for p in parsed if p.kind in (wx.KIND_OK, wx.KIND_NOAVAIL)]
    failures = [p for p in parsed if p.kind == wx.KIND_FAIL]
    if len(definite) == len(parsed) and definite:
        return True, False, "no full Free Night award room on the three-date test window"
    reasons = ",".join(sorted({p.code for p in failures if p.code})) or "incomplete response"
    return False, False, f"award test incomplete: {reasons}"


async def resolve_candidate(candidate: Candidate, fetcher: Fetcher) -> tuple[Candidate, PageVerdict | None, bytes | None]:
    """Resolve an official hotel-page property id only when the map lacks one."""
    if candidate.property_id and candidate.brand_id:
        return candidate, None, None
    raw = await fetcher.get(candidate.url, page=True)
    verdict = classify_page(candidate.url, raw.http_status, raw.body, raw.error, raw.final_url)
    if verdict.kind != "OK":
        return candidate, verdict, None
    return Candidate(candidate.hotel_id, candidate.name, candidate.country, candidate.url,
                     verdict.property_id, verdict.brand_id), verdict, (raw.body or "").encode("utf-8")


async def inspect_candidate(candidate: Candidate, fetcher: Fetcher, workspace: Path,
                            conn: sqlite3.Connection, dry_run: bool) -> str:
    # A rate could arrive while this scanner is running.  Re-check just before
    # use, so this location-only path never reprocesses an accounted room.
    if has_rate(conn, candidate.hotel_id):
        return f"SKIP_PRICED {candidate.hotel_id}"

    resolved, verdict, _page_bytes = await resolve_candidate(candidate, fetcher)
    if verdict and verdict.kind != "OK":
        return f"{verdict.kind} {candidate.hotel_id} {verdict.reason}"
    if not resolved.property_id or not resolved.brand_id:
        return f"FAILED {candidate.hotel_id} NO_PROPERTY_ID"

    raw_items: list[dict] = []
    parsed: list[wx.ParsedResponse] = []
    for stay_date in TEST_DATES:
        request_url = api_url(resolved.property_id, resolved.brand_id, stay_date)
        raw = await fetcher.get(request_url)
        item = {
            "stay_date": stay_date, "request_url": request_url,
            "http_status": raw.http_status, "fetched_at": raw.fetched_at,
            "body": raw.body,
        }
        if raw.error:
            item["error"] = raw.error
        raw_items.append(item)
        parsed_response = wx.parse_response(stay_date, request_url, raw.http_status, raw.body, raw.error)
        # Keep the raw body alongside the pure parsed object solely for the
        # FNS scan; no cash/PAC amount is persisted or emitted by this script.
        object.__setattr__(parsed_response, "_body", raw.body)
        parsed.append(parsed_response)

    attempted, full_award, note = outcome(parsed)
    evidence = wx.build_evidence(resolved.hotel_id, resolved.property_id, resolved.brand_id,
                                 "LOCATION-W3-2026-09-23", datetime.now().isoformat(timespec="seconds"), raw_items)
    digest = hashlib.sha256(evidence).hexdigest()[:16]
    relpath = f"{EVIDENCE_DIR}/{resolved.hotel_id}__{digest}.json.gz"
    source_url = raw_items[0]["request_url"]

    if dry_run:
        label = "IN_SCOPE_REDEEMABLE" if full_award else (
            "REDEEMABLE_SOLD_OUT_IN_TEST_WINDOW" if attempted else "UNKNOWN_ELIGIBILITY")
        return f"{label} {resolved.hotel_id} ({note})"

    # Persist a newly resolved official property id.  It is a traceable lookup
    # key, not a location verdict; the writer below owns the verdict.
    if verdict and verdict.kind == "OK":
        conn.execute(
            """INSERT INTO wyndham_property_map (hotel_id, property_id, brand_id, resolved_at)
               VALUES (?,?,?,?) ON CONFLICT(hotel_id) DO UPDATE SET property_id=excluded.property_id,
               brand_id=excluded.brand_id, resolved_at=excluded.resolved_at""",
            (resolved.hotel_id, resolved.property_id, resolved.brand_id,
             datetime.now().isoformat(timespec="seconds")),
        )
    result = write_location_observation(
        conn, hotel_id=resolved.hotel_id, source_type=SOURCE, source_url=source_url,
        observation=LocationObservation(award_search_attempted=attempted,
                                        full_points_bookable=full_award, notes=note),
        evidence_relpath=relpath, evidence_bytes=evidence, evidence_grade="RAW",
        workspace_dir=str(workspace), commit=False,
    )
    conn.commit()
    return f"{result.status} {resolved.hotel_id} ({note})"


async def run(args: argparse.Namespace) -> int:
    db_path = Path(args.db).resolve()
    workspace = db_path.parent
    conn = sqlite3.connect(db_path)
    candidates = load_candidates(conn, country=args.country, hotel_ids=args.hotel,
                                 limit=args.limit, all_unpriced=args.all_unpriced)
    print(f"Wyndham unpriced candidates queued: {len(candidates)}")
    if not candidates:
        return 0

    import logging
    stats = Stats()
    throttle = AdaptiveThrottle(max_rps=args.max_rps)
    logger = logging.getLogger("wyndham_location")
    logger.addHandler(logging.NullHandler())
    async with Fetcher(throttle, stats, logger, timeout=args.timeout) as fetcher:
        for number, candidate in enumerate(candidates, 1):
            line = await inspect_candidate(candidate, fetcher, workspace, conn, args.dry_run)
            print(f"[{number}/{len(candidates)}] {line}")
            if throttle.blocked:
                print("STOPPED source blocking threshold reached; no further calls made.")
                break
    print(f"HTTP: api={stats.api_requests} page={stats.page_requests} retries={stats.retries} failures={stats.failed_requests}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Wyndham full-award location scanner; does not write rate records.")
    parser.add_argument("--db", default=str(ROOT / "hotel_stays.db"))
    parser.add_argument("--country", help="Existing catalog country value used only to scope candidates.")
    parser.add_argument("--hotel", nargs="+", help="Explicit Wyndham hotel ids.")
    parser.add_argument("--limit", type=int, help="Maximum unpriced candidates to inspect.")
    parser.add_argument("--all-unpriced", action="store_true", help="Allow a global run; otherwise default is a 25-hotel safe batch.")
    parser.add_argument("--max-rps", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
