"""Radisson Hotel Group availability response parser: raw evidence -> list[RateRow].

Pure functions: no network, no database, no I/O. Every database write goes through
`engine.rate_writer.write_rate_batch()`.

Evidence format (`radisson-stays-evidence` v1) - plain JSON (or gzip) written by
`crawlers/radisson_harvester.py`. It wraps VERBATIM server responses; nothing is added to them:

    {
      "format": "radisson-stays-evidence",
      "version": 1,
      "hotel_id": "rad_radisson_blu_wiesbaden_schwarzer_bock",
      "hotel_code": "DEUWEBCK",
      "source_url": "https://www.radissonhotels.com/availability-api/stays-by-rooms",
      "harvested_at": "2026-11-02T04:12:00Z",
      "occupancy": {"adults": 2, "children": 0},
      "rooms_response": { "rooms": [ {"code": "BSTD------", "name": "Standard Room", ...} ] },
      "stays": [
        {"stay_date": "2026-12-10", "response": { <verbatim /availability-api/stays-by-rooms JSON> }},
        ...
      ]
    }

Row rules (what ONE RateRow means):
  * one row per (stay date, room): the cheapest MEMBER rate (category "loyalty", memberOnly True --
    each `group` carries its own `staysMember` list alongside `staysPublic`) that is room-only
    (mealPlan "RO", breakfast not included) and not a professional/corporate rate, when the night
    offers one; otherwise the cheapest PUBLIC rate (category "standard", not member-only) with the
    same room-only/professional filter. v9f rate rule (user, 2026-11-03): member rate is always the
    reference when available -- membership is free, so every user is effectively a member for
    arbitrage-comparison purposes; restricted-audience rates (resident/corporate/government) are
    never used regardless. Notes say which ("member rate" / "public rate").
  * cash_rate = the server's price.amount for that one night. Only used when the server says
    isTaxInclusive is true; the currency is the one in the response;
  * points_required = the server's cashWithPoints.points of the SAME rate, only when the rate is
    redeemable and no extra cash is required (extraCashAmount == 0);
  * a room with no qualifying rate on a date produces NO row. Nothing is ever filled in.
"""
import gzip
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from engine.rate_writer import RateRow

EVIDENCE_FORMAT = "radisson-stays-evidence"
EVIDENCE_VERSION = 1
GZIP_MAGIC = b"\x1f\x8b"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _decompress(data: bytes) -> bytes:
    if data.startswith(GZIP_MAGIC):
        return gzip.decompress(data)
    return data


def load_evidence(evidence_bytes: bytes) -> Dict[str, Any]:
    data = json.loads(_decompress(evidence_bytes).decode("utf-8"))
    if not isinstance(data, dict) or data.get("format") != EVIDENCE_FORMAT:
        raise ValueError("Not a radisson-stays-evidence document")
    if data.get("version") != EVIDENCE_VERSION:
        raise ValueError(f"Unsupported radisson-stays-evidence version: {data.get('version')!r}")
    return data


def room_names(rooms_response: Any) -> Dict[str, str]:
    """room code -> room name exactly as the hotel's content API states it."""
    out: Dict[str, str] = {}
    rooms = rooms_response.get("rooms") if isinstance(rooms_response, dict) else None
    for r in rooms or []:
        if isinstance(r, dict) and r.get("code") and r.get("name"):
            out[str(r["code"])] = str(r["name"]).strip()
    return out


def _stay_night(stay: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    nights = stay.get("nights")
    if isinstance(nights, list) and len(nights) == 1 and isinstance(nights[0], dict):
        return nights[0]
    return None


def _is_public_room_only(stay: Dict[str, Any]) -> bool:
    return (
        stay.get("category") == "standard"
        and not stay.get("memberOnly")
        and not stay.get("professional")
        and stay.get("mealPlan") == "RO"
        and stay.get("breakfastIncluded") is False
    )


def _is_member_room_only(stay: Dict[str, Any]) -> bool:
    """v9f: a Radisson Rewards member rate (free to join). Preferred over the public rate (user rule)."""
    return (
        stay.get("memberOnly") is True
        and not stay.get("professional")
        and stay.get("mealPlan") == "RO"
        and stay.get("breakfastIncluded") is False
    )


def _candidates(room: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(member candidates, public candidates) -- each group carries its own staysMember alongside
    staysPublic; both lists are gathered across all groups of the room."""
    member: List[Dict[str, Any]] = []
    public: List[Dict[str, Any]] = []
    for g in room.get("groups") or []:
        for s in g.get("staysPublic") or []:
            if isinstance(s, dict) and _is_public_room_only(s):
                public.append(s)
        for s in g.get("staysMember") or []:
            if isinstance(s, dict) and _is_member_room_only(s):
                member.append(s)
    return member, public


def _best_of(candidates: List[Dict[str, Any]], stay_date: str):
    """Cheapest priced, tax-inclusive, this-date candidate among a pool, or None."""
    best = None   # (amount, ccy, stay, night)
    for s in candidates:
        night = _stay_night(s)
        if not night or night.get("date") != stay_date:
            continue    # the night the server priced must be the night we asked for
        price = ((night.get("pricing") or {}).get("price")) or {}
        amount, ccy = price.get("amount"), price.get("currency")
        if not isinstance(amount, (int, float)) or isinstance(amount, bool) or amount <= 0:
            continue
        if price.get("isTaxInclusive") is not True or not ccy:
            continue
        if best is None or amount < best[0]:
            best = (float(amount), str(ccy).upper(), s, night)
    return best


def parse_stay_response(stay_date: str, response: Any, names: Dict[str, str]) -> List[RateRow]:
    """Rows for ONE searched night (stay_date) from one verbatim stays-by-rooms response."""
    if not isinstance(response, dict) or not isinstance(response.get("rooms"), dict):
        return []
    rows: List[RateRow] = []
    for code, room in response["rooms"].items():
        if not isinstance(room, dict):
            continue
        member_cands, public_cands = _candidates(room)
        # v9f rate rule (user, 2026-11-03): member rate (free to join) is the reference whenever
        # the night offers one; public rate is only the fallback when no member rate qualifies.
        best = _best_of(member_cands, stay_date)
        is_member = best is not None
        if best is None:
            best = _best_of(public_cands, stay_date)
        if best is None:
            continue
        amount, ccy, stay, night = best
        cwp = (night.get("pricing") or {}).get("cashWithPoints") or {}
        points = None
        if stay.get("redeemable") is True and cwp.get("extraCashAmount") == 0:
            p = cwp.get("points")
            if isinstance(p, int) and not isinstance(p, bool) and p > 0:
                points = p
        room_name = names.get(code) or f"UNKNOWN (room code {code}; name not given by the source)"
        rate_kind = "member" if is_member else "public"
        rows.append(RateRow(
            stay_date=stay_date,
            room_name=room_name,
            cash_rate=amount,
            currency=ccy,
            points_required=points,
            notes=f"Radisson {rate_kind} rate {stay.get('name')} ({stay.get('code')}), room only, tax inclusive, 1 night, 2 adults",
        ))
    return rows


def parse_evidence(evidence_bytes: bytes) -> List[RateRow]:
    """Replay saved Radisson evidence into RateRows. Pure and deterministic."""
    doc = load_evidence(evidence_bytes)
    names = room_names(doc.get("rooms_response"))
    rows: List[RateRow] = []
    for entry in doc.get("stays") or []:
        d = entry.get("stay_date") if isinstance(entry, dict) else None
        if not isinstance(d, str) or not _DATE_RE.match(d):
            continue
        rows.extend(parse_stay_response(d, entry.get("response"), names))
    return rows
