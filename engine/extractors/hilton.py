"""Hilton Honors CRS / Flexible Calendar response parser: raw evidence -> list[RateRow].

Pure functions: no network, no database, no I/O.

Evidence format (`hilton-calendar-evidence` v1) - gzip or plain JSON containing verbatim
calendar observations per property across requested calendar months:

    {
        "format": "hilton-calendar-evidence",
        "version": 1,
        "hotel_id": "hilt_jktdidi",
        "ctyhocn": "jktdidi",
        "source_url": "https://www.hilton.com/en/book/reservation/flexibledates/?ctyhocn=JKTDIDI...",
        "harvested_at": "2026-09-25T11:20:00Z",
        "currency": "IDR",
        "tax_inclusive": 1,
        "months": [
            {
                "caption": "October 2026",
                "days": [
                    {
                        "stay_date": "2026-10-01",
                        "cash_rate": 1284493.0,
                        "currency": "IDR",
                        "points_required": 24000,
                        "available": true,
                        "is_low": false,
                        "rate_plan": "Honors Discount Advance Purchase",
                        "raw_text": "Rp 1,284,493 | 24,000 Points"
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

EVIDENCE_FORMAT = "hilton-calendar-evidence"
EVIDENCE_VERSION = 1
GZIP_MAGIC = b"\x1f\x8b"

CURRENCY_SYMBOLS = {
    "RP": "IDR",
    "IDR": "IDR",
    "US$": "USD",     # a bare "$" is ambiguous (USD/SGD/AUD/CAD...) and is not guessed
    "USD": "USD",
    "EUR": "EUR",
    "€": "EUR",
    "GBP": "GBP",
    "£": "GBP",
    "SGD": "SGD",
    "S$": "SGD",
    "JPY": "JPY",
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
    "AED": "AED",
    "SAR": "SAR",
    "QAR": "QAR",
    "TRY": "TRY",
    "₺": "TRY",
    "INR": "INR",
    "₹": "INR",
    "MXN": "MXN",
    "BRL": "BRL",
    "R$": "BRL",
}


def _decompress(data: bytes) -> bytes:
    if data.startswith(GZIP_MAGIC):
        return gzip.decompress(data)
    return data


def parse_price_amount(text: str) -> Optional[float]:
    """Parse numeric price amount from string like 'Rp 1,284,493' or '$149.00' or full aria-label."""
    if not text:
        return None

    # Exclude points strings
    if "point" in text.lower():
        return None

    # If full aria label or sentence, extract the currency amount portion first
    m = re.search(r'(?:Rp|USD|EUR|GBP|SGD|\$|€|£|¥|IDR|AUD|CAD|CHF|TRY|INR|AED|SAR|QAR|BRL|MXN|RM)\s*([\d,]+(?:\.\d{2})?)', text, re.I)
    if m:
        num_str = m.group(1)
    else:
        # If no currency prefix matched, look for digits with thousand separators (e.g. 1,284,493)
        m2 = re.search(r'\b([\d]{1,3}(?:,\d{3})+(?:\.\d{2})?)\b', text)
        if m2:
            num_str = m2.group(1)
        else:
            # Standalone decimal amount like '149.00'
            m3 = re.search(r'\b(\d+\.\d{2})\b', text)
            if m3:
                num_str = m3.group(1)
            else:
                return None

    clean = re.sub(r"[^\d\.,]", "", num_str).strip()
    if not clean:
        return None

    if "," in clean and "." in clean:
        if clean.rfind(",") > clean.rfind("."):
            clean = clean.replace(".", "").replace(",", ".")
        else:
            clean = clean.replace(",", "")
    elif "," in clean:
        parts = clean.split(",")
        if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]):
            clean = clean.replace(",", "")
        elif len(parts) == 2 and len(parts[1]) != 2:
            clean = clean.replace(",", "")
        else:
            clean = clean.replace(",", ".")

    try:
        val = float(clean)
        return val if val > 0 else None
    except ValueError:
        return None


def parse_points_amount(text: str) -> Optional[int]:
    """Parse Honors Points amount from string like '24,000 Points', '30K', or full aria-label."""
    if not text:
        return None

    # Must explicitly match points indicator (Points, pts, or K)
    m_pts = re.search(r'([\d,]+(?:\.\d+)?)\s*(?:Points|pts|K\b)', text, re.I)
    if not m_pts:
        return None
    target = m_pts.group(0).strip()

    m_k = re.search(r'(\d+(?:\.\d+)?)\s*[Kk]', target)
    if m_k:
        try:
            return int(float(m_k.group(1)) * 1000)
        except ValueError:
            pass

    clean = re.sub(r"[^\d]", "", target)
    if not clean:
        return None
    try:
        val = int(clean)
        return val if val > 0 else None
    except ValueError:
        return None


def detect_currency_code(text: str, default_currency: Optional[str] = None) -> Optional[str]:
    """Extract standard 3-letter currency code from header, price string, or fallback."""
    if not text:
        return default_currency

    # Check specific prefixes / symbols first
    if "Rp" in text or re.search(r'\bIDR\b', text, re.I):
        return "IDR"
    if "€" in text or re.search(r'\bEUR\b', text, re.I):
        return "EUR"
    if "£" in text or re.search(r'\bGBP\b', text, re.I):
        return "GBP"
    if re.search(r'\bJPY\b', text, re.I):          # a bare "¥" is JPY or CNY: ambiguous, so not guessed
        return "JPY"
    if re.search(r'\b(?:RM\s*[\d,]|MYR\b)', text, re.I):
        return "MYR"
    if re.search(r'\bSGD\b|\bS\$', text, re.I):
        return "SGD"
    if re.search(r'\bTHB\b|฿', text, re.I):
        return "THB"
    if re.search(r'\bAUD\b|\bA\$', text, re.I):
        return "AUD"
    if re.search(r'\bCAD\b|\bC\$', text, re.I):
        return "CAD"
    if re.search(r'\b(?:CNY|RMB)\b', text, re.I):
        return "CNY"
    if re.search(r'\bKRW\b|₩', text, re.I):
        return "KRW"
    if re.search(r'\bINR\b|₹', text, re.I):
        return "INR"
    if re.search(r'\bUSD\b|US\$', text, re.I):      # a bare "$" is USD/SGD/AUD/CAD...: ambiguous, so not guessed
        return "USD"

    return default_currency


def parse_evidence(evidence_bytes: bytes) -> List[RateRow]:
    """Replay saved Hilton calendar evidence bytes into RateRows."""
    raw = _decompress(evidence_bytes)
    data = json.loads(raw.decode("utf-8"))

    if not isinstance(data, dict):
        raise ValueError("Invalid evidence payload: expected top-level JSON object")

    fmt = data.get("format")
    if fmt != EVIDENCE_FORMAT:
        raise ValueError(f"Unsupported evidence format: {fmt!r}, expected {EVIDENCE_FORMAT!r}")

    base_currency = data.get("currency")
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

            if cash_rate is None and points_required is None:
                continue

            curr = day.get("currency") or base_currency
            if cash_rate is not None and (not curr or len(curr) != 3):
                continue

            r_plan = day.get("rate_plan") or "Honors Flexible"
            raw_text = day.get("raw_text") or ""
            note = f"Plan: {r_plan} | {raw_text[:30]}" if raw_text else f"Plan: {r_plan}"

            rows.append(RateRow(
                stay_date=stay_date,
                room_name=CALENDAR_UNKNOWN_ROOM,
                cash_rate=cash_rate,
                currency=curr.upper() if curr else None,
                points_required=points_required,
                notes=note
            ))

    return rows
