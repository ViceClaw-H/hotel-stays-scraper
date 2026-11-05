"""Discover Marriott Bonvoy locations through the live booking search.

This is deliberately not Marriott's sitemap crawler.  A supplied URL must be
copied from the official *Find Hotels* booking flow after selecting a country,
city, or other destination.  The browser reads the live property cards and
their Marriott ``data-marsha`` codes.  Existing codes are only reported;
only genuinely new live cards are added and award-tested.

The search is run with ``Use Points/Awards`` on.  A card counts as redeemable
only when Marriott displays a standalone ``N Points / Stay`` value.  Cash
prices are retained as evidence context, never written by this location
scraper, and Cash + Points is never parsed as an award.

Example (the URL should come from an official live booking search):
  python crawlers\\marriott_booking_location_discovery.py --country Indonesia \
    --search-url "https://www.marriott.com/search/findHotels.mi?..." --ingest
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.location_writer import LocationObservation, write_location_observation


SOURCE_TYPE = "OFFICIAL_MARRIOTT_CRS"
CHROME_PATH = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
DEFAULT_DATES = ("2026-10-07", "2027-03-10", "2027-06-05")
POINTS_RE = re.compile(r"(?<![+\d])(\d[\d,]*)\s*Points\s*/\s*Stay", re.I)


@dataclass(frozen=True)
class LiveCard:
    marsha: str
    brand_code: str
    name: str
    currency: str
    cash_price: str
    latitude: float | None
    longitude: float | None
    points: int | None
    catalog_status: str
    catalog_hotel_ids: list[str]


def date_search_url(source_url: str, stay_date: str) -> str:
    """Keep the user-selected live destination but replace only the stay dates."""
    check_in = date.fromisoformat(stay_date)
    check_out = check_in + timedelta(days=1)
    parts = urlsplit(source_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({
        "fromDate": check_in.strftime("%m/%d/%Y"),
        "toDate": check_out.strftime("%m/%d/%Y"),
        "fromDateDefaultFormat": check_in.strftime("%m/%d/%Y"),
        "toDateDefaultFormat": check_out.strftime("%m/%d/%Y"),
        "fromToDate_submit": check_out.strftime("%m/%d/%Y"),
        "t-start": check_in.isoformat(),
        "t-end": check_out.isoformat(),
        "fromToDate": check_in.strftime("%m/%d/%Y"),
        "lengthOfStay": "1",
        "useRewardsPoints": "true",
        "recordsPerPage": "40",
    })
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), "#/0/"))


def valid_source_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in {"www.marriott.com", "marriott.com"}:
        raise ValueError("--search-url must be an HTTPS URL on www.marriott.com")
    if "/search/findHotels.mi" not in parts.path:
        raise ValueError("--search-url must be copied from Marriott's Find Hotels booking results")


def card_rows(page) -> list[dict]:
    """Read DOM-backed live card data; scroll cards to make virtual rows render."""
    cards = page.locator(".property-card[data-marsha]")
    count = cards.count()
    rows: list[dict] = []
    for index in range(count):
        card = cards.nth(index)
        card.scroll_into_view_if_needed(timeout=10_000)
        page.wait_for_timeout(40)
        raw = card.get_attribute("data-property") or "{}"
        try:
            data = json.loads(raw)
        except ValueError:
            data = {}
        text = card.inner_text(timeout=10_000)
        match = POINTS_RE.search(text)
        rows.append({
            "marsha": (card.get_attribute("data-marsha") or "").upper(),
            "brand_code": card.get_attribute("data-brand") or "",
            "property": data,
            "text": text,
            "points": int(match.group(1).replace(",", "")) if match else None,
        })
    return rows


def fetch_date(page, search_url: str) -> tuple[list[dict], str]:
    page.goto(search_url, wait_until="domcontentloaded", timeout=60_000)
    try:
        page.locator(".property-card[data-marsha]").first.wait_for(state="attached", timeout=35_000)
    except PlaywrightError as exc:
        body = page.locator("body").inner_text(timeout=10_000)
        raise RuntimeError(f"Marriott booking cards did not load ({type(exc).__name__}); no eligibility was inferred. {body[:240]!r}") from exc

    seen: dict[str, dict] = {}
    raw_pages: list[str] = []
    for _ in range(20):
        page.wait_for_timeout(1_500)
        raw_pages.append(page.content())
        for row in card_rows(page):
            if row["marsha"]:
                seen[row["marsha"]] = row
        next_button = page.get_by_role("button", name="NextPage")
        if next_button.count() == 0 or not next_button.is_enabled():
            break
        before = tuple(sorted(seen))
        next_button.click(timeout=10_000)
        page.wait_for_timeout(1_000)
        page.locator(".property-card[data-marsha]").first.wait_for(state="attached", timeout=30_000)
        # A disabled/stuck next button must not create an infinite loop.
        if tuple(sorted(row["marsha"] for row in card_rows(page) if row["marsha"])) == before:
            break
    else:
        raise RuntimeError("Marriott pagination exceeded the 20-page safety limit")
    return list(seen.values()), "\n<!-- MARriott page boundary -->\n".join(raw_pages)


def catalog_matches(conn: sqlite3.Connection, code: str) -> list[str]:
    """Match immutable Marriott's Marsha code, never a fuzzy hotel name."""
    code = code.lower()
    rows = conn.execute(
        """SELECT id FROM hotels
           WHERE brand = 'MARRIOTT' AND (lower(id) = ? OR lower(coalesce(official_url, '')) LIKE ?)""",
        (f"marr_{code}", f"%/{code}-%"),
    ).fetchall()
    return sorted({row[0] for row in rows})


def to_live_card(row: dict, conn: sqlite3.Connection) -> LiveCard:
    data = row["property"]
    code = row["marsha"]
    matched = catalog_matches(conn, code)
    price = str(data.get("price") or "")
    currency = str(data.get("currency") or "XXX").upper()
    return LiveCard(
        marsha=code,
        brand_code=row["brand_code"],
        name=str(data.get("hotelName") or "").strip(),
        currency=currency if re.fullmatch(r"[A-Z]{3}", currency) else "XXX",
        cash_price=price,
        latitude=data.get("lat"),
        longitude=data.get("long"),
        points=row["points"],
        catalog_status="ALREADY_IN_CATALOG_BY_MARSHA" if matched else "NEW_LIVE_BOOKING_CANDIDATE",
        catalog_hotel_ids=matched,
    )


def snapshot_paths(workspace: Path, label: str) -> tuple[Path, Path]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    clean = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or "destination"
    evidence = workspace / "evidence" / "marriott" / "location" / f"{clean}__{stamp}.html.gz"
    snapshot = workspace / "data" / "snapshots" / "marriott" / "location" / f"{clean}__{stamp}.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    return evidence, snapshot


def materialize_new_hotel(conn: sqlite3.Connection, card: LiveCard, country: str, official_url: str) -> str:
    hotel_id = f"marr_{card.marsha.lower()}"
    conn.execute(
        """INSERT INTO hotels (id, brand, name, city, country, currency, loyalty_model,
                                award_category, track_points, official_url, created_at)
           VALUES (?, 'MARRIOTT', ?, 'Unknown', ?, ?, 'DYNAMIC_AWARD', NULL, 1, ?, ?)
           ON CONFLICT(id) DO NOTHING""",
        (hotel_id, card.name or card.marsha, country, card.currency, official_url,
         datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )
    return hotel_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Live Marriott booking-search location discovery.")
    parser.add_argument("--search-url", required=True, help="Official Marriott Find Hotels result URL after selecting a destination.")
    parser.add_argument("--country", required=True, help="Country of the selected live destination, stored only for new cards.")
    parser.add_argument("--label", default="marriott-live-destination")
    parser.add_argument("--dates", default=",".join(DEFAULT_DATES), help="Three or more YYYY-MM-DD check-in dates.")
    parser.add_argument("--db", default=str(ROOT / "hotel_stays.db"))
    parser.add_argument("--ingest", action="store_true", help="Write observations for new live cards only.")
    parser.add_argument("--headed", action="store_true", help="Show Chrome while scraping (useful for a booking-site challenge).")
    args = parser.parse_args()
    valid_source_url(args.search_url)
    dates = tuple(part.strip() for part in args.dates.split(",") if part.strip())
    if not dates:
        raise SystemExit("At least one --dates value is required")
    for stay_date in dates:
        date.fromisoformat(stay_date)
    if not CHROME_PATH.exists():
        raise SystemExit(f"Chrome was not found at {CHROME_PATH}")

    all_by_date: dict[str, list[dict]] = {}
    raw_by_date: dict[str, str] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(CHROME_PATH), headless=not args.headed)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, locale="en-US")
        try:
            for stay_date in dates:
                url = date_search_url(args.search_url, stay_date)
                rows, raw = fetch_date(page, url)
                all_by_date[stay_date] = rows
                raw_by_date[stay_date] = raw
        finally:
            browser.close()

    conn = sqlite3.connect(Path(args.db).resolve())
    try:
        cards_by_code: dict[str, list[LiveCard]] = {}
        for rows in all_by_date.values():
            for row in rows:
                card = to_live_card(row, conn)
                cards_by_code.setdefault(card.marsha, []).append(card)

        # Each code is compared once; any date with standalone points makes it redeemable.
        combined: list[LiveCard] = []
        for code, observations in sorted(cards_by_code.items()):
            first = observations[0]
            points = next((card.points for card in observations if card.points is not None), None)
            combined.append(LiveCard(**{**asdict(first), "points": points}))

        evidence_file, snapshot_file = snapshot_paths(Path(args.db).resolve().parent, args.label)
        raw_bundle = json.dumps({"source_urls": {d: date_search_url(args.search_url, d) for d in dates}, "pages": raw_by_date}, ensure_ascii=False).encode("utf-8")
        evidence_file.write_bytes(gzip.compress(raw_bundle, mtime=0))
        relative_evidence = str(evidence_file.relative_to(Path(args.db).resolve().parent)).replace("\\", "/")
        summary = {
            "source_type": SOURCE_TYPE,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "test_dates": dates,
            "cards_by_date": {key: len(value) for key, value in all_by_date.items()},
            "live_cards": [asdict(card) for card in combined],
            "counts": {
                "live_unique": len(combined),
                "existing": sum(card.catalog_status.startswith("ALREADY") for card in combined),
                "new": sum(card.catalog_status == "NEW_LIVE_BOOKING_CANDIDATE" for card in combined),
            },
            "raw_evidence_file": relative_evidence,
            "raw_sha256": hashlib.sha256(evidence_file.read_bytes()).hexdigest(),
        }
        snapshot_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        for card in combined:
            print(f"{card.catalog_status}\t{card.marsha}\t{card.name}\tpoints={card.points or '-'}")
            if not args.ingest or card.catalog_status != "NEW_LIVE_BOOKING_CANDIDATE":
                continue
            hotel_id = materialize_new_hotel(conn, card, args.country, date_search_url(args.search_url, dates[0]))
            result = write_location_observation(
                conn,
                hotel_id=hotel_id,
                source_type=SOURCE_TYPE,
                source_url=date_search_url(args.search_url, dates[0]),
                observation=LocationObservation(
                    award_search_attempted=True,
                    full_points_bookable=card.points is not None,
                    notes=("new Marriott live booking card; standalone full-points award observed" if card.points is not None
                           else "new Marriott live booking card; no standalone full-points award in observed test dates"),
                ),
                evidence_relpath=relative_evidence,
                evidence_bytes=evidence_file.read_bytes(),
                evidence_grade="RAW",
                workspace_dir=str(Path(args.db).resolve().parent),
                commit=False,
            )
            print(f"IMMEDIATE_AWARD_TEST\t{card.marsha}\t{result.status}")
        if args.ingest:
            conn.commit()
    finally:
        conn.close()
    print(f"Snapshot: {snapshot_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
