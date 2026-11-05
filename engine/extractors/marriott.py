"""Marriott Bonvoy CRS / Flexible Calendar response parser: raw evidence -> list[RateRow].

Pure functions: no network, no database, no I/O.

Evidence format (`marriott-calendar-evidence` v1) - gzip or plain JSON containing verbatim
calendar observations per property across requested calendar months:

    {
        "format": "marriott-calendar-evidence",
        "version": 1,
        "hotel_id": "marr_jktjw",
        "marsha": "jktjw",
        "source_url": "https://www.marriott.com/search/availabilityCalendar.mi?...",
        "harvested_at": "2026-09-23T23:14:00Z",
        "currency": "IDR",
        "tax_inclusive": 1,
        "months": [
            {
                "caption": "October 2026",
                "days": [
                    {
                        "stay_date": "2026-10-01",
                        "cash_rate": 2755000.0,
                        "currency": "IDR",
                        "points_required": null,
                        "available": true,
                        "is_low": false,
                        "raw_text": "Rp2,755,000"
                    },
                    ...
                ]
            }
        ]
    }

Every DB write goes through `engine.rate_writer.write_rate_batch()`.
"""
import gzip
import json
import re
from datetime import datetime, date
from typing import Any, Dict, List, Optional

from engine.rate_writer import CALENDAR_UNKNOWN_ROOM, RateRow

EVIDENCE_FORMAT = "marriott-calendar-evidence"
EVIDENCE_VERSION = 1
GZIP_MAGIC = b"\x1f\x8b"

CURRENCY_SYMBOLS = {
    "RP": "IDR",
    "IDR": "IDR",
    "$": "USD",
    "USD": "USD",
    "EUR": "EUR",
    "€": "EUR",
    "GBP": "GBP",
    "£": "GBP",
    "SGD": "SGD",
    "S$": "SGD",
    "JPY": "JPY",
    "¥": "JPY",
    "CNY": "CNY",
    "RMB": "CNY",
    "MYR": "MYR",
    "RM": "MYR",
    "THB": "THB",
    "฿": "THB",
    "AUD": "AUD",
    "A$": "AUD",
    "CAD": "CAD",
    "C$": "CAD",
    "HKD": "HKD",
    "HK$": "HKD",
    "KRW": "KRW",
    "₩": "KRW",
}


def _decompress(data: bytes) -> bytes:
    if data.startswith(GZIP_MAGIC):
        return gzip.decompress(data)
    return data


def parse_price_amount(text: str) -> Optional[float]:
    """Parse numeric price amount from string like 'Rp2,755,000' or '$149.00'."""
    if not text:
        return None
    # Strip currency letters/symbols
    clean = re.sub(r"[^\d\.,]", "", text).strip()
    if not clean:
        return None

    # Determine whether comma is thousand separator or decimal
    if "," in clean and "." in clean:
        if clean.rfind(",") > clean.rfind("."):
            # European format: 1.250,50
            clean = clean.replace(".", "").replace(",", ".")
        else:
            # Standard format: 1,250.50
            clean = clean.replace(",", "")
    elif "," in clean:
        parts = clean.split(",")
        if len(parts[-1]) == 3 or len(parts) > 2:
            # Thousands separator: 2,755,000
            clean = clean.replace(",", "")
        elif len(parts[-1]) in (1, 2):
            # Decimal separator: 125,50
            clean = clean.replace(",", ".")
        else:
            clean = clean.replace(",", "")

    try:
        val = float(clean)
        return val if val > 0 else None
    except ValueError:
        return None


def parse_points_amount(cell_text: str) -> Optional[int]:
    """Parse points value from cell text, e.g. '1\\n26,500' or '4\\n21,000\\nLOW'."""
    if not cell_text:
        return None
    if "not available" in cell_text.lower():
        return None

    lines = [l.strip() for l in cell_text.split("\n") if l.strip()]
    for line in lines[1:]:
        clean = line.replace(",", "").replace(".", "").strip()
        m = re.match(r"^(\d{3,7})(?:\s*pts|\s*points)?$", clean, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            if val >= 1000:
                return val

    # Fallback search anywhere in text
    matches = re.findall(r"\b(\d{1,3}(?:,\d{3})+)\b", cell_text)
    for m in matches:
        val = int(m.replace(",", ""))
        if val >= 1000:
            return val
    return None


KNOWN_CURRENCIES = {
    "IDR", "USD", "EUR", "GBP", "SGD", "JPY", "CNY", "MYR", "THB", "AUD",
    "CAD", "HKD", "KRW", "CHF", "INR", "VND", "AED", "SAR", "QAR", "TWD",
    "NZD", "MXN", "BRL", "ZAR", "PHP", "TRY", "SEK", "NOK", "DKK", "PLN"
}


def detect_currency_code(raw_text: str, default_currency: Optional[str] = None) -> Optional[str]:
    """Identify 3-letter ISO-4217 currency from text header or raw text."""
    if not raw_text:
        return default_currency

    # Check for explicit parenthesized currency, e.g. "Total (IDR)"
    m_paren = re.search(r"\(([A-Z]{3})\)", raw_text.upper())
    if m_paren and m_paren.group(1) in KNOWN_CURRENCIES:
        return m_paren.group(1)

    # Check for Indonesian Rupiah prefix (Rp followed by digits)
    if re.search(r"\bRP\.?\s*\d+", raw_text, re.IGNORECASE):
        return "IDR"

    # Check for Malaysian Ringgit prefix (RM followed by digits)
    if re.search(r"\bRM\s*\d+", raw_text, re.IGNORECASE):
        return "MYR"

    # Check for explicit 3-letter ISO codes with word boundaries
    for ccode in KNOWN_CURRENCIES:
        if re.search(rf"\b{ccode}\b", raw_text.upper()):
            return ccode

    # Check unique symbols
    if "€" in raw_text:
        return "EUR"
    if "£" in raw_text:
        return "GBP"
    if "¥" in raw_text:
        return default_currency if default_currency in ("JPY", "CNY") else None      # bare "¥": JPY or CNY, not guessed
    if "$" in raw_text:
        return default_currency if default_currency in ("USD", "SGD", "AUD", "CAD", "HKD") else None   # bare "$": not guessed

    return default_currency


def parse_evidence(evidence_bytes: bytes) -> List[RateRow]:
    """Replay saved Marriott calendar evidence bytes into RateRows.

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
    tax_inclusive = data.get("tax_inclusive", 1)
    months = data.get("months", [])

    rows: List[RateRow] = []

    for month_data in months:
        if not isinstance(month_data, dict):
            continue
        days = month_data.get("days", [])
        for day in days:
            if not isinstance(day, dict):
                continue
            if not day.get("available", False):
                continue

            stay_date = day.get("stay_date")
            if not stay_date or not re.match(r"^\d{4}-\d{2}-\d{2}$", stay_date):
                continue

            cash_rate = day.get("cash_rate")
            if cash_rate is not None:
                cash_rate = float(cash_rate)

            points_required = day.get("points_required")
            if points_required is not None:
                points_required = int(points_required)

            # Must have either cash or points
            if cash_rate is None and points_required is None:
                continue

            curr = day.get("currency") or base_currency
            if cash_rate is not None and (not curr or len(curr) != 3):
                # Cannot store cash without valid 3-letter currency
                continue

            is_low = day.get("is_low", False)
            note_parts = ["Marriott Flexible Calendar lowest total rate"]
            if is_low:
                note_parts.append("lowest of month")
            raw_text = day.get("raw_text")
            if raw_text:
                note_parts.append(f"raw: {raw_text[:30]}")

            rows.append(RateRow(
                stay_date=stay_date,
                room_name=CALENDAR_UNKNOWN_ROOM,
                cash_rate=cash_rate,
                currency=curr.upper() if curr else None,
                points_required=points_required,
                notes="; ".join(note_parts)
            ))

    return rows
