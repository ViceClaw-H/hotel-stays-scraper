"""Accor PriceCalendar GraphQL response parser: raw evidence -> list[RateRow].

Pure functions: no network, no database, no I/O.

Evidence format (`accor-calendar-evidence` v1) - gzip or plain JSON containing verbatim
calendar observations per property across requested calendar windows (7-day chunks):

    {
        "format": "accor-calendar-evidence",
        "version": 1,
        "hotel_id": "accor_5704",
        "hotel_code": "5704",
        "source_url": "https://api.accor.com/bff/v1/graphql",
        "harvested_at": "2026-09-24T05:54:10Z",
        "currency": "IDR",
        "tax_inclusive": 1,
        "calendar": [
            {
                "date": "2026-10-01",
                "availability": { "status": "AVAILABLE", "reasons": [] },
                "offer": {
                    "pricing": {
                        "currency": "IDR",
                        "aggregationType": "TOTAL_STAY",
                        "main": { "amount": 769500, "formattedAmount": "Rp 769.500" },
                        "alternative": { "amount": 810000, "formattedAmount": "Rp 810.000" }
                    }
                }
            }
        ]
    }

Every DB write goes through `engine.rate_writer.write_rate_batch()`.
"""
import gzip
import json
import re
from typing import Any, Dict, List, Optional

from engine.rate_writer import CALENDAR_UNKNOWN_ROOM, RateRow
from engine.currency_source import currency_from_text, is_iso

EVIDENCE_FORMAT = "accor-calendar-evidence"
EVIDENCE_VERSION = 1
GZIP_MAGIC = b"\x1f\x8b"


def _decompress(data: bytes) -> bytes:
    if data.startswith(GZIP_MAGIC):
        return gzip.decompress(data)
    return data


def parse_formatted_amount(text: str) -> Optional[float]:
    """Fallback numeric parser for formatted strings like 'Rp 769.500', '€184', 'US$105'."""
    if not text:
        return None
    clean = re.sub(r"[^\d\.,]", "", str(text)).strip()
    if not clean:
        return None
    if "," in clean and "." in clean:
        if clean.rfind(",") > clean.rfind("."):
            clean = clean.replace(".", "").replace(",", ".")
        else:
            clean = clean.replace(",", "")
    elif "," in clean:
        parts = clean.split(",")
        if len(parts[-1]) == 3 or len(parts) > 2:
            clean = clean.replace(",", "")
        elif len(parts[-1]) in (1, 2):
            clean = clean.replace(",", ".")
        else:
            clean = clean.replace(",", "")
    elif "." in clean:
        parts = clean.split(".")
        if len(parts[-1]) == 3 or len(parts) > 2:
            # Thousands separator e.g. 769.500
            clean = clean.replace(".", "")
        else:
            # Standard decimal e.g. 183.10
            pass
    try:
        val = float(clean)
        return val if val > 0 else None
    except ValueError:
        return None


def parse_evidence(evidence_bytes: bytes) -> List[RateRow]:
    """Replay saved Accor calendar evidence bytes into RateRows.

    Pure function: deterministic, zero I/O.
    """
    raw = _decompress(evidence_bytes)
    data = json.loads(raw.decode("utf-8"))

    if not isinstance(data, dict):
        raise ValueError("Invalid evidence payload: expected top-level JSON object")

    fmt = data.get("format")
    if fmt != EVIDENCE_FORMAT:
        raise ValueError(f"Unsupported evidence format: {fmt!r}, expected {EVIDENCE_FORMAT!r}")

    base_currency = data.get("currency")
    source_url = data.get("source_url")

    # Support flat 'calendar' list, or list of 'chunks'
    days: List[Dict[str, Any]] = []
    if "calendar" in data and isinstance(data["calendar"], list):
        days.extend(data["calendar"])
    # Verbatim server responses as the harvester saves them: raw_responses[i]["data"]["data"]["hotelOffers"]["calendar"]
    for rr in (data.get("raw_responses") or []):
        try:
            cal = rr["data"]["data"]["hotelOffers"]["calendar"]
        except (KeyError, TypeError):
            continue
        if isinstance(cal, list):
            days.extend(cal)
    if "chunks" in data and isinstance(data["chunks"], list):
        for chunk in data["chunks"]:
            if isinstance(chunk, dict) and "calendar" in chunk and isinstance(chunk["calendar"], list):
                days.extend(chunk["calendar"])

    # Deduplicate days by date, preserving last observed
    by_date: Dict[str, Dict[str, Any]] = {}
    for d in days:
        if isinstance(d, dict) and d.get("date"):
            by_date[d["date"]] = d

    rows: List[RateRow] = []

    for stay_date, day in sorted(by_date.items()):
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", stay_date):
            continue

        avail_status = (day.get("availability") or {}).get("status")
        if avail_status != "AVAILABLE":
            continue

        offer = day.get("offer")
        if not isinstance(offer, dict):
            continue

        pricing = offer.get("pricing")
        if not isinstance(pricing, dict):
            continue

        main_pricing = pricing.get("main") or {}
        alt_pricing = pricing.get("alternative") or {}

        # 1. Prefer unformatted exact numeric amount from API
        amount = main_pricing.get("amount")
        if amount is None:
            amount = alt_pricing.get("amount")

        # 2. Fallback to parsing formatted amount
        if amount is None:
            fmt_str = main_pricing.get("formattedAmount") or alt_pricing.get("formattedAmount")
            if fmt_str:
                amount = parse_formatted_amount(fmt_str)

        if amount is None or amount <= 0:
            continue

        # The currency is read from the server's own price text ("IDR 1,318,750", "€66"); no default is ever assumed.
        currency = (pricing.get("currency") or base_currency or "").strip().upper()
        if not currency:
            currency = currency_from_text(main_pricing.get("formattedAmount")) or currency_from_text(alt_pricing.get("formattedAmount")) or ""
        if not is_iso(currency):
            continue

        agg_type = pricing.get("aggregationType") or "TOTAL_STAY"
        notes = f"Accor PriceCalendar lowest rate ({agg_type})"

        rows.append(
            RateRow(
                stay_date=stay_date,
                room_name=CALENDAR_UNKNOWN_ROOM,
                cash_rate=round(float(amount), 2),
                currency=currency,
                points_required=None,
                source_url=source_url,
                notes=notes,
            )
        )

    return rows
