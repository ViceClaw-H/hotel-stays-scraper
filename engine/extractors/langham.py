"""Langham Hospitality Group CRS / Flexible Calendar response parser: raw evidence -> list[RateRow].

Pure functions: deterministic, zero network, zero database, zero I/O.

Evidence format (`langham-calendar-evidence` v1) - gzip or plain JSON containing verbatim
calendar observations per property across requested calendar months:

    {
        "format": "langham-calendar-evidence",
        "version": 1,
        "hotel_id": "lang_the_langham_sydney",
        "synxis_id": "16758",
        "source_url": "https://reservations.brilliantbylangham.com/api/booking/calendar_availability",
        "harvested_at": "2026-09-24T00:05:00Z",
        "currency": "AUD",
        "tax_inclusive": 1,
        "calendar": [
            {
                "date": "2026-10-01",
                "amount": 658.63,
                "amountWithTax": 658.63,
                "currency": "AUD"
            },
            ...
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

EVIDENCE_FORMAT = "langham-calendar-evidence"
EVIDENCE_VERSION = 1
GZIP_MAGIC = b"\x1f\x8b"


def _decompress(data: bytes) -> bytes:
    if data.startswith(GZIP_MAGIC):
        return gzip.decompress(data)
    return data


def parse_evidence(evidence_bytes: bytes) -> List[RateRow]:
    """Replay saved Langham calendar evidence bytes into RateRows.

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
    calendar_entries = data.get("calendar", [])
    today_iso = date.today().isoformat()

    rows: List[RateRow] = []

    for item in calendar_entries:
        if not isinstance(item, dict):
            continue

        stay_date = item.get("date")
        if not stay_date or not re.match(r"^\d{4}-\d{2}-\d{2}$", stay_date):
            continue
        if stay_date < today_iso:
            continue

        # Langham gives 'amountWithTax' (fully taxed gross) and 'amount' (net)
        amount_with_tax = item.get("amountWithTax")
        amount_net = item.get("amount")

        cash_val = amount_with_tax if amount_with_tax is not None else amount_net
        if cash_val is not None:
            try:
                cash_val = float(cash_val)
                if cash_val <= 0:
                    cash_val = None
            except (ValueError, TypeError):
                cash_val = None

        points_req = item.get("points")
        if points_req is not None:
            try:
                points_req = int(points_req)
                if points_req <= 0:
                    points_req = None
            except (ValueError, TypeError):
                points_req = None

        if cash_val is None and points_req is None:
            continue

        curr = item.get("currency") or base_currency
        if cash_val is not None and (not curr or len(curr) != 3):
            continue

        note_parts = ["Langham calendar lowest rate"]
        if amount_with_tax is not None and amount_net is not None and amount_with_tax != amount_net:
            note_parts.append(f"gross={amount_with_tax}, net={amount_net}")

        rows.append(RateRow(
            stay_date=stay_date,
            room_name=CALENDAR_UNKNOWN_ROOM,
            cash_rate=cash_val,
            currency=curr.upper() if curr else None,
            points_required=points_req,
            notes="; ".join(note_parts)
        ))

    return rows
