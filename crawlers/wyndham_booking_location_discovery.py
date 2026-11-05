"""Discover Wyndham hotels from a live booking-search destination.

This is Wyndham's *additional* location source, deliberately separate from
both the sitemap importer and the full-award eligibility scanner.

Important distinction:
  1. The booking box's suggestions are Google Maps places, not hotels.
  2. Selecting one place and searching produces Wyndham's live hotel cards.
  3. Those returned cards are the discovery evidence.  Their Wyndham property
     id / official URL is compared with the sitemap-derived catalog.
  4. A card already in the catalog is reported and left alone.  A card absent
     from the catalog is immediately tested on three dates for a full Free
     Night award room.  No cash rate is written by this script.

The endpoint has a 150 km default search radius, so a country centre does not
enumerate an entire country.  Run this once for each destination suggestion
(city, airport, etc.) that the booking UI exposes.  Overlapping searches are
safe because matching uses Wyndham's property id first.

Example:
  python crawlers\\wyndham_booking_location_discovery.py \\
      --label jakarta-indonesia --latitude -6.2088 --longitude 106.8456
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from curl_cffi import requests
from crawlers.wyndham_stream_harvester import api_url
from engine.extractors import wyndham as wx
from engine.location_writer import LocationObservation, write_location_observation


SEARCH_URL = "https://www.wyndhamhotels.com/BWSServices/services/search/getMultiPropertySearch"
SOURCE_TYPE = "OFFICIAL_WYNDHAM_CRS"
TEST_DATES = ("2026-10-07", "2027-03-10", "2027-06-05")
# Exact core brand set configured by Wyndham's current live Search Results page
# for the Hotels by Wyndham host brand.  It is intentionally not inferred from
# our database.
INCLUDE_BRANDS = ",".join((
    "aa", "bu", "ce", "di", "dz:fe", "dx", "es:fe", "bh", "hj", "lq", "mt", "ra", "re",
    "se", "tq", "tl", "wt", "wg", "lv", "gn:wy", "gr:wy", "hr:wy", "wr", "whg", "vo", "lt", "vi", "ww",
))
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.wyndhamhotels.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}


@dataclass(frozen=True)
class LiveHotelCard:
    property_id: str
    hotel_code: str
    brand_id: str
    name: str
    city: str
    country: str
    country_code: str
    latitude: str
    longitude: str
    official_url: str
    distance_km: str
    catalog_status: str
    catalog_hotel_ids: list[str]


def canonical_url(url: str | None) -> str:
    """Canonicalise only presentation differences; never fuzzy-match hotel names."""
    if not url:
        return ""
    parsed = urlparse(url if "://" in url else "https://www.wyndhamhotels.com/" + url.lstrip("/"))
    path = parsed.path.rstrip("/").lower()
    return f"{parsed.netloc.lower()}{path}"


def stable_property_url_key(url: str | None) -> str:
    """Wyndham hotel URLs use ``/<brand>/<location>/<hotel-slug>/overview``.

    Wyndham can rename the location segment (for example, South Tangerang to
    Banten) while retaining the actual hotel's URL slug.  Matching the brand
    plus final hotel slug handles that official URL migration without using a
    loose name match.
    """
    parsed = urlparse(url if url and "://" in url else "https://www.wyndhamhotels.com/" + (url or "").lstrip("/"))
    parts = [piece.lower() for piece in parsed.path.split("/") if piece]
    if len(parts) >= 3 and parts[-1] == "overview":
        return f"{parts[0]}/{parts[-2]}"
    return ""


def request_url(latitude: float, longitude: float, radius: int) -> str:
    params = {
        "latitude": str(latitude), "longitude": str(longitude), "language": "en-us",
        "useLimitedProperties": "false", "recordsPerPage": "200", "pageNumber": "1",
        "distanceUnit": "kilometer", "radius": str(radius), "includeBrands": INCLUDE_BRANDS,
        "brandId": "whg",
    }
    return f"{SEARCH_URL}?{urlencode(params)}"


def fetch_live_search(url: str):
    """Fetch a live card list without ever treating a temporary block as no results."""
    last = None
    for attempt in range(1, 4):
        response = requests.get(url, headers=HEADERS, impersonate="chrome124", timeout=25)
        last = response
        if response.status_code == 200:
            return response
        if response.status_code not in (412, 429) and response.status_code < 500:
            break
        if attempt < 3:
            time.sleep(3 * attempt)
    return last


def parse_live_cards(payload: dict) -> list[dict]:
    if payload.get("status") != "OK":
        message = payload.get("errmsg") or payload.get("errorMessage") or "unknown response"
        raise ValueError(f"Wyndham search did not return live cards: {message}")
    availability = payload.get("availability") or {}
    cards: list[dict] = []
    for group in ("hostBrand", "altSell"):
        cards.extend((availability.get(group) or {}).get("availability") or [])
    unique: dict[str, dict] = {}
    for card in cards:
        property_id = str(card.get("hotelId") or card.get("hotelCode") or "").strip()
        if property_id:
            unique[property_id] = card
    return [unique[key] for key in sorted(unique, key=lambda value: (int(value) if value.isdigit() else value))]


def catalog_index(conn: sqlite3.Connection) -> tuple[dict[str, list[str]], dict[str, list[str]], dict[str, list[str]]]:
    by_property: dict[str, list[str]] = {}
    for hotel_id, property_id in conn.execute("SELECT hotel_id, property_id FROM wyndham_property_map"):
        by_property.setdefault(str(property_id), []).append(hotel_id)
    by_url: dict[str, list[str]] = {}
    by_stable_url: dict[str, list[str]] = {}
    for hotel_id, url in conn.execute("SELECT id, official_url FROM hotels WHERE brand = 'WYNDHAM'"):
        key = canonical_url(url)
        if key:
            by_url.setdefault(key, []).append(hotel_id)
        stable = stable_property_url_key(url)
        if stable:
            by_stable_url.setdefault(stable, []).append(hotel_id)
    return by_property, by_url, by_stable_url


def compare_cards(cards: list[dict], conn: sqlite3.Connection) -> list[LiveHotelCard]:
    by_property, by_url, by_stable_url = catalog_index(conn)
    results: list[LiveHotelCard] = []
    for card in cards:
        property_id = str(card.get("hotelId") or card.get("hotelCode") or "")
        relative_url = str(card.get("uniqueUrl") or "").lstrip("/")
        official_url = f"https://www.wyndhamhotels.com/{relative_url}" if relative_url else ""
        id_matches = sorted(set(by_property.get(property_id, [])))
        url_matches = sorted(set(by_url.get(canonical_url(official_url), [])))
        stable_url_matches = sorted(set(by_stable_url.get(stable_property_url_key(official_url), [])))
        matched = id_matches or url_matches or stable_url_matches
        status = "ALREADY_IN_CATALOG_BY_PROPERTY_ID" if id_matches else (
            "ALREADY_IN_CATALOG_BY_OFFICIAL_URL" if url_matches else (
                "ALREADY_IN_CATALOG_BY_STABLE_OFFICIAL_URL" if stable_url_matches else "NEW_LIVE_BOOKING_CANDIDATE"
            )
        )
        results.append(LiveHotelCard(
            property_id=property_id, hotel_code=str(card.get("hotelCode") or ""), brand_id=str(card.get("brand") or ""),
            name=str(card.get("hotelName") or ""), city=str(card.get("city") or ""),
            country=str(card.get("country") or ""), country_code=str(card.get("countryCode") or ""),
            latitude=str(card.get("latitude") or ""), longitude=str(card.get("longitude") or ""),
            official_url=official_url, distance_km=str(card.get("distance") or ""),
            catalog_status=status, catalog_hotel_ids=matched,
        ))
    return results


def safe_label(value: str) -> str:
    clean = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    return clean or "destination"


def write_snapshot(workspace: Path, label: str, url: str, raw: bytes, cards: list[LiveHotelCard]) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    evidence_path = workspace / "evidence" / "wyndham" / "discovery" / f"{safe_label(label)}__{stamp}.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_bytes(raw)
    snapshot = {
        "source": SOURCE_TYPE,
        "source_url": url,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "raw_evidence_file": str(evidence_path.relative_to(workspace)).replace("\\", "/"),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "live_cards": [asdict(card) for card in cards],
        "counts": {
            "live_cards": len(cards),
            "already_catalogued": sum(card.catalog_status.startswith("ALREADY") for card in cards),
            "new_candidates": sum(card.catalog_status == "NEW_LIVE_BOOKING_CANDIDATE" for card in cards),
        },
    }
    snapshot_path = workspace / "data" / "snapshots" / "wyndham" / "location" / f"{safe_label(label)}__{stamp}.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return snapshot_path


def raw_currency_from_responses(bodies: list[str | None]) -> str:
    """Return only a currency literally present in Wyndham's booking answer.

    This is hotel metadata, not a rate write.  ``XXX`` is ISO 4217's reserved
    no-currency code and is used only when the official answer has no currency
    at all (for example a pure-points-only response).
    """
    for body in bodies:
        try:
            payload = json.loads(body or "")
        except ValueError:
            continue
        for room in (payload.get("roomsAndRates") or {}).get("rooms") or []:
            for rate in room.get("rates") or []:
                code = str(rate.get("currencyCode") or "").strip().upper()
                if len(code) == 3 and code.isalpha():
                    return code
    return "XXX"


def full_award_present(body: str | None) -> bool:
    """Recognise only Wyndham FNS/full-points plans; hybrid PAC never qualifies."""
    try:
        payload = json.loads(body or "")
    except ValueError:
        return False
    for room in (payload.get("roomsAndRates") or {}).get("rooms") or []:
        for rate in room.get("rates") or []:
            if wx.fns_points(rate):
                return True
    return False


def new_hotel_id(card: LiveHotelCard) -> str:
    """A deterministic internal id derived from Wyndham's authoritative property id."""
    return f"wynd_live_{card.brand_id.lower()}_{card.property_id}"[:64]


def materialize_new_card(conn: sqlite3.Connection, card: LiveHotelCard, currency: str) -> str:
    """Create only a genuinely new live booking-card candidate.

    Callers have already checked all property-id and official-URL aliases, so
    this cannot overwrite a sitemap or inactive historical row.
    """
    hotel_id = new_hotel_id(card)
    conn.execute(
        """INSERT INTO hotels (id, brand, name, city, country, currency, loyalty_model,
                                award_category, track_points, official_url, created_at)
           VALUES (?, 'WYNDHAM', ?, ?, ?, ?, 'WYNDHAM_REWARDS', NULL, 1, ?, ?)
           ON CONFLICT(id) DO NOTHING""",
        (hotel_id, card.name, card.city or "Unknown", card.country or "Unknown", currency,
         card.official_url, datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )
    conn.execute(
        """INSERT INTO wyndham_property_map (hotel_id, property_id, brand_id, resolved_at)
           VALUES (?, ?, ?, ?) ON CONFLICT(hotel_id) DO NOTHING""",
        (hotel_id, card.property_id, card.brand_id, datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )
    return hotel_id


def immediately_test_new_card(conn: sqlite3.Connection, workspace: Path, card: LiveHotelCard) -> str:
    """Run the full-points test now, and persist location evidence but never a rate.

    An incomplete API run remains UNKNOWN_ELIGIBILITY.  It never becomes a
    false sold-out result just because Wyndham failed to answer.
    """
    responses: list[dict] = []
    parsed: list[wx.ParsedResponse] = []
    bodies: list[str | None] = []
    for stay_date in TEST_DATES:
        url = api_url(card.property_id, card.brand_id, stay_date)
        try:
            response = requests.get(url, headers=HEADERS, impersonate="chrome124", timeout=25)
            status, body, error = response.status_code, response.text, None
        except Exception as exc:
            status, body, error = None, None, f"{type(exc).__name__}: {exc}"
        responses.append({"stay_date": stay_date, "request_url": url, "http_status": status,
                          "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          "body": body, **({"error": error} if error else {})})
        parsed.append(wx.parse_response(stay_date, url, status, body, error))
        bodies.append(body)

    full_award = any(full_award_present(body) for body in bodies)
    definite = [item for item in parsed if item.kind in (wx.KIND_OK, wx.KIND_NOAVAIL)]
    attempted = len(definite) == len(parsed) and bool(definite)
    if full_award:
        note = "new live booking card; full Free Night award room observed"
    elif attempted:
        note = "new live booking card; no full Free Night award room on the three-date test window"
    else:
        failures = ",".join(sorted({item.code for item in parsed if item.kind == wx.KIND_FAIL and item.code}))
        note = f"new live booking card; award test incomplete: {failures or 'no response'}"

    currency = raw_currency_from_responses(bodies)
    hotel_id = materialize_new_card(conn, card, currency)
    evidence = wx.build_evidence(hotel_id, card.property_id, card.brand_id,
                                 "DISCOVERY-W3-2026-09-23", datetime.now(timezone.utc).isoformat(timespec="seconds"), responses)
    digest = hashlib.sha256(evidence).hexdigest()[:16]
    result = write_location_observation(
        conn, hotel_id=hotel_id, source_type=SOURCE_TYPE, source_url=responses[0]["request_url"],
        observation=LocationObservation(award_search_attempted=attempted, full_points_bookable=full_award, notes=note),
        evidence_relpath=f"evidence/wyndham/location/{hotel_id}__{digest}.json.gz",
        evidence_bytes=evidence, evidence_grade="RAW", workspace_dir=str(workspace), commit=False,
    )
    conn.commit()
    return f"{result.status} ({note})"


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover live Wyndham hotel cards for one selected destination.")
    parser.add_argument("--label", required=True, help="Human-readable selected suggestion, e.g. jakarta-indonesia")
    parser.add_argument("--latitude", required=True, type=float)
    parser.add_argument("--longitude", required=True, type=float)
    parser.add_argument("--radius", type=int, default=150, help="Wyndham result radius in km; default matches its UI")
    parser.add_argument("--db", default=str(ROOT / "hotel_stays.db"))
    args = parser.parse_args()

    url = request_url(args.latitude, args.longitude, args.radius)
    response = fetch_live_search(url)
    if response.status_code != 200:
        raise SystemExit(f"Wyndham booking discovery failed: HTTP {response.status_code}")
    raw = response.content
    cards = parse_live_cards(response.json())
    conn = sqlite3.connect(Path(args.db).resolve())
    try:
        matched = compare_cards(cards, conn)
        snapshot = write_snapshot(Path(args.db).resolve().parent, args.label, url, raw, matched)
        new_results = []
        for card in matched:
            if card.catalog_status == "NEW_LIVE_BOOKING_CANDIDATE":
                new_results.append((card.property_id, immediately_test_new_card(conn, Path(args.db).resolve().parent, card)))
    finally:
        conn.close()
    counts = {
        "live": len(matched),
        "existing": sum(card.catalog_status.startswith("ALREADY") for card in matched),
        "new": sum(card.catalog_status == "NEW_LIVE_BOOKING_CANDIDATE" for card in matched),
    }
    print(f"{args.label}: live={counts['live']} existing={counts['existing']} new={counts['new']}")
    for card in matched:
        print(f"{card.catalog_status}\t{card.property_id}\t{card.name}\t{card.city}, {card.country}\t{card.official_url}")
    for property_id, result in new_results:
        print(f"IMMEDIATE_AWARD_TEST\t{property_id}\t{result}")
    print(f"Snapshot: {snapshot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
