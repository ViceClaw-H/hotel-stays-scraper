"""Wyndham BWS getRoomsAndRates -> RateRow. Pure functions: no network, no disk, no database.

Evidence format (`wyndham-bws-evidence` v1) - one document per hotel and run, gzip-compressed JSON:

    {"format": "wyndham-bws-evidence", "version": 1, "hotel_id": ..., "property_id": ..., "brand_id": ...,
     "grid_id": ..., "harvested_at": ...,
     "responses": [{"stay_date": "2026-10-07", "request_url": ..., "http_status": 200,
                    "fetched_at": ..., "body": "<the response text, unmodified>"}, ...]}

Every request whose answer was parsed is stored with its response body as an unmodified string
(including the "425 No availability" answers, which are what justify a NO_AVAILABILITY verdict or a
booking horizon). Requests that never produced an answer (timeout, connection error) are stored with
"body": null and an "error" text. `parse_evidence(bytes)` turns that file back into rows, so the
verifier can replay it offline and a change of parsing rules needs no re-scrape.

Rules implemented here (verified against live responses, see tests/fixtures/wyndham):
  * cash = `totalAfterTax` of a pure-cash rate plan (not Points+Cash `pac*`, not Free Night `fns*`).
    It is the sum totalBeforeTax + every entry of taxList (taxes AND fees such as resort fees); it is
    never replaced by a before-tax figure. `averageAfterTax` is used only for a one-night stay when
    `totalAfterTax` is absent. Nothing pre-tax is ever used.
  * currency = the rate's own `currencyCode`; without a valid ISO code there is no cash.
  * room per date = cheapest all-in cash among rooms classified STANDARD; if no STANDARD room has an
    all-in cash rate, the cheapest overall (it lands in its own room row, labelled with its true class).
  * points = Free Night award (`totalFnsPoints`). Wyndham sets them per hotel category, so every FNS
    plan of one response carries the same number; then the minimum over all rooms is used (so points
    are not lost when the cheapest room has no FNS plan). If the values ever differ inside one
    response, only the chosen room's own FNS points are used.
"""
import gzip
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from engine.rate_writer import RateRow, room_class_for

EVIDENCE_FORMAT = "wyndham-bws-evidence"
EVIDENCE_VERSION = 1
GZIP_MAGIC = b"\x1f\x8b"

KIND_OK = "OK"                # rooms returned
KIND_NOAVAIL = "NOAVAIL"      # the source answered "nothing available" (HTTP 200 + Error 425, or no rooms)
KIND_FAIL = "FAIL"            # transport / block / server error / unreadable answer - NOT "no availability"

REASON_425_CHANNEL = "HTTP_425_CHANNEL"
REASON_425_NO_MATCH = "HTTP_425_NO_MATCH"
REASON_EMPTY_ROOMS = "EMPTY_ROOMS"

_ISO = re.compile(r"^[A-Za-z]{3}$")


# ------------------------------------------------------------------------------------------------
# One response
# ------------------------------------------------------------------------------------------------
@dataclass
class ParsedResponse:
    stay_date: str
    kind: str                              # KIND_OK / KIND_NOAVAIL / KIND_FAIL
    code: str = ""                         # machine reason for NOAVAIL / FAIL
    message: str = ""                      # verbatim error text (body or error string)
    url: str = ""
    row: Optional[RateRow] = None          # only for KIND_OK, and only if the response carried a price
    n_rooms: int = 0
    cash_missing: bool = False             # KIND_OK but no all-in cash rate anywhere in the response


def _num(v) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def is_pac(rt: dict) -> bool:
    """Points + Cash plan."""
    return bool(rt.get("pacRatePlan")) or (_num(rt.get("pacPoints")) or 0) > 0 or (_num(rt.get("totalPacPoints")) or 0) > 0


def is_fns(rt: dict) -> bool:
    """Free Night (pure points) plan."""
    return bool(rt.get("fnsRatePlan")) or (_num(rt.get("totalFnsPoints")) or 0) > 0


def fns_points(rt: dict) -> Optional[int]:
    if not is_fns(rt):
        return None
    pts = _num(rt.get("totalFnsPoints")) or _num(rt.get("fnsPoints"))
    return int(pts) if pts and pts > 0 else None


def all_in_cash(rt: dict) -> Optional[float]:
    """Fully taxed price for the stay from a pure-cash plan, else None. Never a pre-tax number."""
    if is_pac(rt) or is_fns(rt):
        return None
    total = rt.get("totalAfterTax")
    if total is not None:
        v = _num(total)
        return v if v is not None and v > 0 else None
    # totalAfterTax absent: only a one-night stay may fall back to the per-night average (= the total)
    nights = rt.get("nightRatesAfterTax") or rt.get("nightRatesBeforeTax") or []
    avg = _num(rt.get("averageAfterTax"))
    if avg is not None and avg > 0 and len(nights) == 1:
        return avg
    return None


def _room_name(rm: dict) -> str:
    name = (rm.get("shortName") or "").strip()
    if name:
        return name
    code = (rm.get("roomTypeCode") or "").strip()
    return f"UNKNOWN (room type code {code or '?'})"


def _is_accessible(rm: dict) -> bool:
    return bool(rm.get("accessible")) or "accessible" in (rm.get("shortName") or "").lower()


def choose_row(payload: dict, stay_date: str, url: str) -> Tuple[Optional[RateRow], bool]:
    """Pick the room and build the row for one OK response. Returns (row or None, cash_missing)."""
    rooms = (payload.get("roomsAndRates") or {}).get("rooms") or []

    # cheapest pure-cash all-in price per room name (two room codes can share a name)
    cash_by_room: Dict[str, dict] = {}
    for rm in rooms:
        name = _room_name(rm)
        for rt in rm.get("rates") or []:
            price = all_in_cash(rt)
            cur = (rt.get("currencyCode") or "").strip()
            if price is None or not _ISO.match(cur):
                continue
            cand = {"price": price, "cur": cur.upper(), "plan": rt.get("ratePlanId") or "?",
                    "acc": _is_accessible(rm), "name": name, "rm": rm}
            cur_best = cash_by_room.get(name)
            if cur_best is None or (cand["price"], cand["plan"]) < (cur_best["price"], cur_best["plan"]):
                cash_by_room[name] = cand

    # FNS points, per room and over the whole response
    room_fns: Dict[str, int] = {}
    all_fns = set()
    for rm in rooms:
        name = _room_name(rm)
        for rt in rm.get("rates") or []:
            p = fns_points(rt)
            if p:
                all_fns.add(p)
                room_fns[name] = min(room_fns.get(name, p), p)
    identical = len(all_fns) == 1

    mixed_ccy = False
    chosen = None
    if cash_by_room:
        currencies = sorted({c["cur"] for c in cash_by_room.values()})
        if len(currencies) > 1:      # never seen live; never compare prices across currencies
            mixed_ccy = True
            count = {cu: sum(1 for c in cash_by_room.values() if c["cur"] == cu) for cu in currencies}
            keep = max(currencies, key=lambda cu: (count[cu], cu))
            pool = {n: c for n, c in cash_by_room.items() if c["cur"] == keep}
        else:
            pool = cash_by_room
        std = {n: c for n, c in pool.items() if room_class_for(n) == "STANDARD"}
        pick_from = std or pool
        chosen = min(pick_from.values(), key=lambda c: (c["price"], c["acc"], c["name"].lower(), c["name"]))
        room_name = chosen["name"]
    else:
        # points-only response: attribute the award to a stable room (STANDARD first, then any) that has an FNS plan
        names = sorted(room_fns) if room_fns else []
        std_names = [n for n in names if room_class_for(n) == "STANDARD"]
        pool_names = std_names or names
        if not pool_names:
            return None, True
        pool_names.sort(key=lambda n: (_accessible_by_name(rooms, n), n.lower(), n))
        room_name = pool_names[0]

    points = None
    own = room_fns.get(room_name)
    if identical:
        points = next(iter(all_fns))
    elif own:
        points = own

    cash = round(chosen["price"], 2) if chosen else None
    currency = chosen["cur"] if chosen else None
    if cash is None and points is None:
        return None, True

    notes = _notes(chosen, points, identical, own, len(rooms), len(all_fns), mixed_ccy)
    return RateRow(stay_date=stay_date, room_name=room_name, cash_rate=cash, currency=currency,
                   points_required=points, source_url=url, notes=notes), cash is None


def _accessible_by_name(rooms: List[dict], name: str) -> bool:
    for rm in rooms:
        if _room_name(rm) == name:
            return _is_accessible(rm)
    return False


def _notes(chosen, points, identical, own, n_rooms, n_distinct_fns, mixed_ccy) -> str:
    parts = []
    if chosen:
        parts.append(f"cash=totalAfterTax plan {chosen['plan']}")
    else:
        parts.append("no all-in cash plan in response")
    if points:
        if identical:
            parts.append("pts=FNS min of all rooms, same value in every FNS plan" + ("" if own else "; chosen room has no own FNS plan"))
        else:
            parts.append("pts=FNS of chosen room only (FNS values differ inside response)")
    elif n_distinct_fns > 1:
        parts.append("pts=none: FNS values differ and chosen room has none")
    if mixed_ccy:
        parts.append("mixed currencies in response")
    return "; ".join(parts)[:250]


def parse_response(stay_date: str, url: str, http_status: Optional[int], body: Optional[str],
                   error: Optional[str] = None) -> ParsedResponse:
    """Classify one stored/received answer and, if it carries rooms, build the row."""
    if body is None or http_status is None:
        return ParsedResponse(stay_date, KIND_FAIL, "NO_RESPONSE", error or "no response", url)
    if http_status != 200:
        return ParsedResponse(stay_date, KIND_FAIL, f"HTTP_{http_status}", (body or error or "")[:500], url)
    try:
        payload = json.loads(body)
    except ValueError:
        return ParsedResponse(stay_date, KIND_FAIL, "NON_JSON", body[:300], url)
    if not isinstance(payload, dict):
        return ParsedResponse(stay_date, KIND_FAIL, "NON_JSON", body[:300], url)

    status = payload.get("status")
    if status == "OK":
        rooms = (payload.get("roomsAndRates") or {}).get("rooms") or []
        if not rooms:
            return ParsedResponse(stay_date, KIND_NOAVAIL, REASON_EMPTY_ROOMS, body[:500], url)
        row, cash_missing = choose_row(payload, stay_date, url)
        return ParsedResponse(stay_date, KIND_OK, "", "", url, row, len(rooms), cash_missing)

    code = str(payload.get("errorCode") or payload.get("statusCode") or "")
    if code == "425":
        msg = str(payload.get("errorMessage") or "")
        reason = REASON_425_CHANNEL if "channel connect" in msg.lower() else REASON_425_NO_MATCH
        return ParsedResponse(stay_date, KIND_NOAVAIL, reason, body[:500], url)
    return ParsedResponse(stay_date, KIND_FAIL, f"API_ERROR_{code or 'UNKNOWN'}", body[:500], url)


# ------------------------------------------------------------------------------------------------
# Evidence documents
# ------------------------------------------------------------------------------------------------
def build_evidence(hotel_id: str, property_id: str, brand_id: str, grid_id: str, harvested_at: str,
                   responses: List[Dict[str, Any]]) -> bytes:
    """Serialise raw responses. Each item: stay_date, request_url, http_status, fetched_at, body, error.
    The bytes are deterministic for a given input (gzip mtime fixed), so the file hash is stable."""
    doc = {
        "format": EVIDENCE_FORMAT, "version": EVIDENCE_VERSION, "hotel_id": hotel_id,
        "property_id": property_id, "brand_id": brand_id, "grid_id": grid_id, "harvested_at": harvested_at,
        "responses": sorted(responses, key=lambda r: r["stay_date"]),
    }
    raw = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return gzip.compress(raw, compresslevel=9, mtime=0)


def load_evidence(evidence_bytes: bytes) -> dict:
    data = gzip.decompress(evidence_bytes) if evidence_bytes[:2] == GZIP_MAGIC else evidence_bytes
    doc = json.loads(data.decode("utf-8"))
    if doc.get("format") != EVIDENCE_FORMAT:
        raise ValueError(f"not a {EVIDENCE_FORMAT} document")
    return doc


def parse_evidence_responses(evidence_bytes: bytes) -> List[ParsedResponse]:
    doc = load_evidence(evidence_bytes)
    return [parse_response(r["stay_date"], r.get("request_url", ""), r.get("http_status"), r.get("body"), r.get("error"))
            for r in doc["responses"]]


def parse_evidence(evidence_bytes: bytes) -> List[RateRow]:
    """Evidence file bytes (gzip or plain JSON) -> rate rows, sorted by stay_date. Pure."""
    rows = [p.row for p in parse_evidence_responses(evidence_bytes) if p.kind == KIND_OK and p.row is not None]
    rows.sort(key=lambda r: r.stay_date)
    return rows
