"""Best Western (BWH Hotels) GraphQL BFF response parser: raw evidence -> list[RateRow].

Pure functions: no network, no database, no I/O.
"""
import gzip
import json
from typing import Any, Dict, List, Optional

from engine.extractors.legacy import ANY_DATE
from engine.rate_writer import RateRow

GZIP_MAGIC = b"\x1f\x8b"


def _decompress(data: bytes) -> bytes:
    if data.startswith(GZIP_MAGIC):
        return gzip.decompress(data)
    return data


def parse_evidence(evidence_bytes: bytes) -> List[RateRow]:
    """Replay saved Best Western BFF GraphQL search evidence bytes into RateRows.

    Pure function: deterministic, zero I/O.
    """
    raw = _decompress(evidence_bytes)
    data = json.loads(raw.decode("utf-8"))

    if not isinstance(data, dict):
        raise ValueError("Invalid evidence payload: expected top-level JSON object")

    rows: List[RateRow] = []
    search = data.get("data", {}).get("searchHotels", {})
    hotels = search.get("hotels", [])

    for h in hotels:
        rate = h.get("resortSearchRate")
        if not rate:
            continue
        amt = rate.get("totalAmount") or rate.get("averageNightlyRate")
        pts_obj = h.get("resortSearchPoint")
        pts = pts_obj.get("points") if isinstance(pts_obj, dict) else None

        if amt is not None and float(amt) > 0:
            rows.append(
                RateRow(
                    stay_date=ANY_DATE,
                    cash_rate=float(amt),
                    points_required=pts,
                    currency=None,
                    room_name="",
                )
            )

    return rows
