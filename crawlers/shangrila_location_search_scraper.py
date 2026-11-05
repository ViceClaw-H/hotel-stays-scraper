"""Live Shangri-La location discovery from its official Find a Hotel search.

This is intentionally not a generic directory or sitemap crawler.  Shangri-La's live
``/en/find-a-hotel/`` response is the data behind the country's destination suggestions.  It
already presents the complete hierarchy in one official response: country -> property rows.

The country/city labels in the autocomplete are navigation containers, never hotel rows.  This
scraper emits only the property rows.  It does not open each hotel: opening every property merely
repeats the information the official live search has already supplied.

Output is a discovery snapshot, not a rate write.  A price crawler and the central location writer
remain separate by design.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urljoin
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SEARCH_URL = "https://www.shangri-la.com/en/find-a-hotel/"
USER_AGENT = "All-Hotel-Stays/1.0 (official location discovery; contact: repository owner)"


@dataclass(frozen=True)
class Location:
    country: str
    name: str
    official_url: str
    booking_domain: str
    brand: str


class FindHotelParser(HTMLParser):
    """Parse only the server-rendered country headings and their property lists."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.current_country: Optional[str] = None
        self._in_country = False
        self._country_parts: list[str] = []
        self._in_hotel_list = False
        self._hotel_href: Optional[str] = None
        self._hotel_parts: list[str] = []
        self.locations: list[Location] = []
        self.declared_counts: dict[str, int] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attr = dict(attrs)
        classes = set((attr.get("class") or "").split())
        if tag == "div" and "country-name" in classes:
            self._in_country = True
            self._country_parts = []
        elif tag == "ul" and "hotel-items" in classes:
            self._in_hotel_list = True
        elif tag == "a" and self._in_hotel_list:
            self._hotel_href = attr.get("href")
            self._hotel_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_country:
            self._country_parts.append(data)
        if self._hotel_href is not None:
            self._hotel_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._in_country:
            text = " ".join("".join(self._country_parts).split())
            match = re.fullmatch(r"(.+?)\s*\((\d+)\)", text)
            if match:
                self.current_country = match.group(1).strip()
                self.declared_counts[self.current_country] = int(match.group(2))
            self._in_country = False
        elif tag == "a" and self._hotel_href is not None:
            name = " ".join("".join(self._hotel_parts).split())
            if self.current_country and name and self._hotel_href:
                url = urljoin(SEARCH_URL, self._hotel_href)
                domain = url.split("/", 3)[2].lower()
                self.locations.append(Location(
                    country=self.current_country,
                    name=name,
                    official_url=url,
                    booking_domain=domain,
                    brand=brand_for(name),
                ))
            self._hotel_href = None
            self._hotel_parts = []
        elif tag == "ul" and self._in_hotel_list:
            self._in_hotel_list = False


def brand_for(name: str) -> str:
    upper = name.upper()
    if upper.startswith("JEN "):
        return "JEN"
    if upper.startswith("TRADERS ") or upper.startswith("TRADERS HOTEL"):
        return "TRADERS"
    if upper.startswith("KERRY "):
        return "KERRY"
    return "SHANGRI-LA"


def parse_locations(html: str) -> tuple[list[Location], dict[str, int]]:
    parser = FindHotelParser()
    parser.feed(html)
    parser.close()
    if not parser.locations:
        raise ValueError("Official Find a Hotel response contained no property rows.")
    actual_counts: dict[str, int] = {}
    for location in parser.locations:
        actual_counts[location.country] = actual_counts.get(location.country, 0) + 1
    mismatches = {
        country: (expected, actual_counts.get(country, 0))
        for country, expected in parser.declared_counts.items()
        if expected != actual_counts.get(country, 0)
    }
    if mismatches:
        raise ValueError(f"Country heading counts do not match scraped property rows: {mismatches}")
    return parser.locations, parser.declared_counts


def fetch_live_page(timeout: int = 45) -> bytes:
    request = Request(SEARCH_URL, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def write_snapshot(raw: bytes, locations: Iterable[Location], counts: dict[str, int], output: Path,
                   evidence_file: Path) -> Path:
    observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    evidence_file.parent.mkdir(parents=True, exist_ok=True)
    evidence_file.write_bytes(raw)
    payload = {
        "source_url": SEARCH_URL,
        "source_type": "OFFICIAL_SHANGRILA_LOCATION_SEARCH",
        "observed_at": observed_at,
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "evidence_file": str(evidence_file.relative_to(ROOT)).replace("\\", "/"),
        "country_counts": counts,
        "locations": [asdict(location) for location in locations],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return output


def canonical_url(url: str) -> str:
    """Compare official URLs without treating www and a trailing slash as different hotels."""
    return url.rstrip("/").replace("://www.", "://")


def ingest_locations(db_path: Path, raw: bytes, evidence_file: Path, locations: Iterable[Location]) -> tuple[int, int]:
    """Write only currently listed properties through the central policy gate.

    The page itself is the official live location-search evidence.  We do not touch the seven
    historical catalog entries that disappeared from the live response; absence is preserved as a
    fact to investigate, never converted into a destructive catalog deletion.
    """
    sys.path.insert(0, str(ROOT))
    from engine.location_writer import LocationObservation, write_location_observation

    locations = list(locations)
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        hotel_by_url = {
            canonical_url(url): hotel_id
            for hotel_id, url in conn.execute(
                "SELECT id, official_url FROM hotels WHERE brand IN ('SHANGRI-LA', 'JEN', 'TRADERS', 'KERRY') "
                "AND official_url IS NOT NULL"
            )
        }
        sha = hashlib.sha256(raw).hexdigest()
        evidence_relpath = str(evidence_file.relative_to(ROOT)).replace("\\", "/")
        written = skipped = 0
        for location in locations:
            hotel_id = hotel_by_url.get(canonical_url(location.official_url))
            if hotel_id is None:
                raise ValueError(f"Live property has no exact official_url match in catalog: {location.name}")
            already = conn.execute(
                "SELECT 1 FROM location_observations WHERE hotel_id=? AND source_payload_hash=? LIMIT 1",
                (hotel_id, sha),
            ).fetchone()
            if already:
                skipped += 1
                continue
            write_location_observation(
                conn,
                hotel_id=hotel_id,
                source_type="OFFICIAL_SHANGRILA_CRS",
                source_url=SEARCH_URL,
                observation=LocationObservation(cash_search_attempted=True, cash_bookable=True,
                                                notes="Listed by official live Find a Hotel location search."),
                evidence_relpath=evidence_relpath,
                evidence_bytes=raw,
                evidence_grade="RAW",
                workspace_dir=str(ROOT),
                commit=False,
            )
            written += 1
        conn.commit()
        return written, skipped
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Shangri-La's official live location search.")
    parser.add_argument("--country", help="Keep only one exact country/region after validating the full response.")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "data" / "snapshots" / "shangrila" / "location_search_latest.json")
    parser.add_argument("--evidence", type=Path,
                        help="Raw official HTML evidence path. Defaults to a timestamped Shangri-La evidence file.")
    parser.add_argument("--db", type=Path, default=ROOT / "hotel_stays.db")
    parser.add_argument("--ingest", action="store_true",
                        help="Write live-listed catalog matches through the central location-policy gate.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and validate, but do not write a snapshot.")
    args = parser.parse_args(argv)

    raw = fetch_live_page()
    text = raw.decode("utf-8", errors="replace")
    locations, counts = parse_locations(text)
    if args.country:
        if args.country not in counts:
            raise SystemExit(f"Country/region {args.country!r} was not returned by Shangri-La's live search.")
        locations = [location for location in locations if location.country == args.country]
        counts = {args.country: counts[args.country]}
    print(f"Live official search: {sum(counts.values())} properties across {len(counts)} countries/regions")
    for country, count in counts.items():
        print(f"  {country}: {count}")
    if not args.dry_run:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        evidence_file = args.evidence or ROOT / "evidence" / "shangrila" / "location" / f"find_a_hotel_{stamp}.html"
        path = write_snapshot(raw, locations, counts, args.output, evidence_file)
        print(f"Wrote {path}")
        if args.ingest:
            written, skipped = ingest_locations(args.db, raw, evidence_file, locations)
            print(f"Policy-gated location ingest: {written} written, {skipped} already present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
