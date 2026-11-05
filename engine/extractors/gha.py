"""GHA DISCOVERY availability response parser: raw evidence -> list[RateRow].

Pure functions: no network, no database, no I/O. Every database write goes through
`engine.rate_writer.write_rate_batch()`.

Evidence format (`gha-rates-evidence` v1) - JSON, gzip-compressed by the harvester. It wraps VERBATIM
server responses of POST oscp.ghadiscovery.com/api/v3/booking/hotel/rooms/rates:

    {"format": "gha-rates-evidence", "version": 1, "hotel_id": "gha_kempinski_the_boulevard_dubai",
     "hotel_code": "KIDXB10", "source_url": "https://oscp.ghadiscovery.com/api/v3/booking/hotel/rooms/rates",
     "harvested_at": "...", "occupancy": {"adults": 2, "children": 0},
     "stays": [{"stay_date": "2026-12-10", "response": { <verbatim JSON: {"rooms": [...]} > }}]}

Row rules (what ONE RateRow means):
  * v9f: one row per (stay date, room): the MEMBER rate (memberRate true; GHA DISCOVERY is free to join) when the
    room has one (user rule 2026-11-03); otherwise the public (memberRate false) "Best Available Rate" (rateCode DAILY),
    one night, 2 adults. Measured 2026-11-03: only some brands use the code DAILY (Kempinski does; Rotana sells RAFL/RFLEX,
    Anantara/Minor S14BFXBE...). When a room has NO public DAILY rate, the cheapest other PUBLIC (memberRate false) rate is
    used and its code and name are written in the row's notes, so no hotel is dropped and nothing is hidden.
    v9f: rate plans for a restricted audience (residents, government, corporate, senior ...) are never used;
  * cash_rate = the server's amountWithTaxesFees (price including taxes and fees), currency = the
    response's currency. Rows are skipped if that field is missing, not a number, not positive, or below
    the pre-tax price;
  * points_required is always None: GHA DISCOVERY pays Discovery Dollars, not points;
  * a room without such a rate on a date produces NO row. Nothing is filled in.
"""
import gzip
import json
import re
from typing import Any, Dict, List, Optional

from engine.rate_writer import RateRow

EVIDENCE_FORMAT = "gha-rates-evidence"
EVIDENCE_VERSION = 1
GZIP_MAGIC = b"\x1f\x8b"
BAR_RATE_CODE = "DAILY"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# v9f: rates sold only to a restricted group are not public, even when memberRate is false
# (seen live: "UAE Resident Rate Including Breakfast (LOCALBB)").
_RESTRICTED_RE = re.compile(
    r"resident|\blocals?\b|citizen|national\b|\bgcc\b|government|\bgovt\b|military|veteran|senior|"
    r"corporate|\bcorp\b|\baaa\b|\bcaa\b|employee|\bstaff\b|travel agent|\biata\b|industry|"
    r"wholesale|\bgroup\b|wedding|\bmice\b|student|\bpromo code\b",
    re.I,
)
_RESTRICTED_CODES = {"LOCALBB", "LOCAL", "RESIDENT", "GOV", "GOVT", "MIL", "SENIOR", "CORP", "AAA", "IATA"}


def is_restricted_rate(rate: Dict[str, Any]) -> bool:
    """True when the rate plan is for a restricted audience (residents, government, corporate ...)."""
    code = str(rate.get("rateCode") or "").upper()
    if code in _RESTRICTED_CODES:
        return True
    return bool(_RESTRICTED_RE.search(str(rate.get("rateName") or "")))


def _decompress(data: bytes) -> bytes:
    return gzip.decompress(data) if data.startswith(GZIP_MAGIC) else data


def load_evidence(evidence_bytes: bytes) -> Dict[str, Any]:
    data = json.loads(_decompress(evidence_bytes).decode("utf-8"))
    if not isinstance(data, dict) or data.get("format") != EVIDENCE_FORMAT:
        raise ValueError("Not a gha-rates-evidence document")
    if data.get("version") != EVIDENCE_VERSION:
        raise ValueError(f"Unsupported gha-rates-evidence version: {data.get('version')!r}")
    return data


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_stay_response(stay_date: str, response: Any) -> List[RateRow]:
    """v9f rate rule (user, 2026-11-03): the MEMBER rate (GHA DISCOVERY, free to join) is the price stored;
    only when a room has no member rate is the public rate used (DAILY first, else the cheapest public plan).
    Restricted-audience plans (residents, government, corporate ...) are never used."""
    if not isinstance(response, dict) or not isinstance(response.get("rooms"), list):
        return []
    rows: List[RateRow] = []
    for room in response["rooms"]:
        if not isinstance(room, dict) or not room.get("roomName"):
            continue
        best = {"member": None, "daily": None, "public": None}
        for rate in room.get("rates") or []:
            if not isinstance(rate, dict) or rate.get("memberRate") not in (True, False):
                continue
            if is_restricted_rate(rate):
                continue          # v9f: not bookable by every (free) member
            total, pre_tax, ccy = _num(rate.get("amountWithTaxesFees")), _num(rate.get("price")), rate.get("currency")
            if total is None or total <= 0 or not ccy or not re.fullmatch(r"[A-Za-z]{3}", str(ccy)):
                continue
            if pre_tax is not None and total < pre_tax:
                continue
            kind = "member" if rate.get("memberRate") is True else ("daily" if rate.get("rateCode") == BAR_RATE_CODE else "public")
            if best[kind] is None or total < best[kind][0]:
                best[kind] = (total, str(ccy).upper(), rate)
        kind = next((k for k in ("member", "daily", "public") if best[k] is not None), None)
        if kind is None:
            continue
        total, ccy, rate = best[kind]
        label = {
            "member": "member rate (GHA DISCOVERY, free membership)",
            "daily": "public Best Available Rate - no member rate offered for this room",
            "public": "public rate - no member rate and no DAILY rate offered for this room, cheapest public rate plan of this room used",
        }[kind]
        rows.append(RateRow(
            stay_date=stay_date,
            room_name=str(room["roomName"]).strip(),
            cash_rate=total,
            currency=ccy,
            points_required=None,
            notes=f"GHA DISCOVERY {rate.get('rateName')} ({rate.get('rateCode')}): {label}, taxes and fees included, 1 night, 2 adults",
        ))
    return rows


def parse_evidence(evidence_bytes: bytes) -> List[RateRow]:
    doc = load_evidence(evidence_bytes)
    rows: List[RateRow] = []
    for entry in doc.get("stays") or []:
        d = entry.get("stay_date") if isinstance(entry, dict) else None
        if isinstance(d, str) and _DATE_RE.match(d):
            rows.extend(parse_stay_response(d, entry.get("response")))
    return rows
