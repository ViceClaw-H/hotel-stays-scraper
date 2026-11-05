"""Hyatt response parsers: raw response bytes -> list[RateRow]. Pure functions: no I/O, no database.

Two Hyatt responses are understood; `parse_evidence` picks the right one from the response shape.

1. AWARD calendar  (GET /explore-hotels/service/avail/days?spiritCode=..&startDate=..&endDate=..)
       {"days": {"2026-11-09": {"STANDARD_ROOM": {"pointsValue": [17000], "pointsLevel": "OFF_PEAK",
                                                   "rate": null}, "CLUB": {...}}}}
   One award row per date for ONE room key (see `choose_award_room`). `rate` is null in every cell
   Hyatt has ever returned from this endpoint (788,482 of 788,482 archived cells), so this endpoint
   carries no cash and the rows are points-only (cash_rate None, currency None).

2. CASH per night (GET /en-US/shop/service/rooms/roomrates/{spirit}?...&checkinDate=D&checkoutDate=D+1)
       {"roomRates": {"KING": {"roomCategory": "STANDARD", "roomType": {"title": "1 King Bed"},
                               "ratePlans": [{"id": "RACK", "ratePlanCategory": "CASH",
                                              "totalAfterTax": 3272.75, "currencyCode": "AED", ...}]}}}
   The response does not repeat the stay date, so the caller passes it (`stay_date`). Cash is the
   plan's `totalAfterTax` (the checkout total: all taxes and fees). Never the pre-tax `rate`.

If a parsing rule changes (room choice, plan choice) re-run the extractor over the saved evidence;
no re-scrape is needed.
"""
import json
import re
from dataclasses import dataclass
from typing import List, Optional

from engine.rate_writer import RateRow, room_class_for

# ---------------------------------------------------------------------------------------------
# Award: which room is priced
# ---------------------------------------------------------------------------------------------
# The award calendar lists several room keys per date (STANDARD_ROOM, STANDARD_SUITE, PREMIUM_SUITE,
# CLUB, and numbered variants such as STANDARD_ROOM_3). We follow one entry-level room per hotel so a
# standard-room series is never contaminated by suite prices:
#   1. "STANDARD_ROOM" if the date lists it (even with no points: then the date is skipped, we do NOT
#      fall through to a different room)
#   2. else "STANDARD"
#   3. else the lowest-points key that does not contain SUITE/CLUB/VILLA/PREMIUM/PENTHOUSE/DELUXE
#      (in the archive this is what picks e.g. STANDARD_ROOM_3 for hotels that never list STANDARD_ROOM)
#   4. else nothing: the date is skipped (suites/clubs are never recorded as the standard room)
# The chosen key is stored verbatim as room_name, so different keys are different series.
AWARD_PRIMARY_KEYS = ("STANDARD_ROOM", "STANDARD")
AWARD_EXCLUDED_WORDS = ("SUITE", "CLUB", "VILLA", "PREMIUM", "PENTHOUSE", "DELUXE")

SOURCE_TAG_AWARD = "HYATT_AWARD"
SOURCE_TAG_CASH = "HYATT_CASH"


def _points(cell) -> Optional[int]:
    """First entry of pointsValue as a positive int, else None."""
    if not isinstance(cell, dict):
        return None
    pv = cell.get("pointsValue")
    if not isinstance(pv, list) or not pv:
        return None
    try:
        v = int(pv[0])
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def choose_award_room(rooms: dict) -> Optional[str]:
    """Room key priced for one date (see module comment), or None when the date has no standard room."""
    if not isinstance(rooms, dict):
        return None
    for key in AWARD_PRIMARY_KEYS:
        if key in rooms:
            return key
    candidates = []
    for key, cell in rooms.items():
        if any(w in key.upper() for w in AWARD_EXCLUDED_WORDS):
            continue
        pts = _points(cell)
        if pts:
            candidates.append((pts, key))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


def parse_award_evidence(evidence_bytes: bytes) -> List[RateRow]:
    data = json.loads(evidence_bytes)
    days = data.get("days") if isinstance(data, dict) else None
    if not isinstance(days, dict):
        return []
    rows: List[RateRow] = []
    for stay_date in sorted(days):
        rooms = days[stay_date]
        key = choose_award_room(rooms)
        if key is None:
            continue
        cell = rooms[key]
        pts = _points(cell)
        if not pts:
            continue
        level = cell.get("pointsLevel") if isinstance(cell, dict) else None
        rows.append(RateRow(
            stay_date=stay_date,
            room_name=key,
            cash_rate=None,
            currency=None,
            points_required=pts,
            notes=f"{SOURCE_TAG_AWARD} {level}" if level else SOURCE_TAG_AWARD,
        ))
    return rows


# ---------------------------------------------------------------------------------------------
# Cash: which room and which rate plan are priced
# ---------------------------------------------------------------------------------------------
# Room: only rooms the API itself files under roomCategory == "STANDARD" (its entry-level tier; the
# "PREMIUM" tier is never used) and whose title is not a suite/villa by engine.room_classifier (the API
# files e.g. "Suite, 1 King Bed, Bathtub" under STANDARD). The cheapest such room that has an eligible
# plan wins; the room title is stored verbatim as room_name.
# Plan: like-for-like with an award night (refundable, room only). Eligible = ratePlanCategory CASH
#   (not POINTS / CASH_POINTS), a fully-taxed total present, and NOT
#     * flagged UNMODIFIABLE (prepaid / non-changeable),
#     * a meal bundle (flag BED_BREAKFAST or a name that mentions breakfast / dine / dining / meal /
#       package).
#   Member-discount plans (MYHI...) ARE eligible: World of Hyatt membership is free and every award
#   redeemer is a member. The winning plan id and name are written to notes so the choice is visible.
# Price: `totalAfterTax` (the checkout total for the stay). If absent, `rateAfterTax`. Never `rate`,
#   `totalBeforeTax` or `lowestCashRate` (all pre-tax): if no fully-taxed figure exists the plan is
#   ineligible and, if no plan is left, cash is None (no row).
CASH_ROOM_CATEGORY = "STANDARD"
_MEAL_NAME = re.compile(r"breakfast|\bdine\b|dining|\bmeal|package", re.IGNORECASE)
_EXCLUDED_PLAN_FLAGS = {"UNMODIFIABLE", "BED_BREAKFAST"}


@dataclass
class CashChoice:
    room_code: str
    room_name: str          # roomType.title, verbatim (falls back to the room code)
    plan_id: str
    plan_name: str
    total_after_tax: float
    currency: str


def _num(v) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def eligible_cash_plan(plan) -> Optional[tuple]:
    """(total_after_tax, currency) if this plan is an eligible fully-taxed cash plan, else None."""
    if not isinstance(plan, dict) or plan.get("ratePlanCategory") != "CASH":
        return None
    flags = set(plan.get("rateFlags") or [])
    if flags & _EXCLUDED_PLAN_FLAGS:
        return None
    if plan.get("mealPlan") or _MEAL_NAME.search(str(plan.get("name") or "")):
        return None
    total = _num(plan.get("totalAfterTax"))
    if total is None:
        total = _num(plan.get("rateAfterTax"))
    cur = str(plan.get("currencyCode") or "").upper()
    if total is None or len(cur) != 3:
        return None
    return total, cur


def choose_cash(data: dict) -> Optional[CashChoice]:
    rooms = data.get("roomRates") if isinstance(data, dict) else None
    if not isinstance(rooms, dict):
        return None
    best = None
    for code in sorted(rooms):
        room = rooms[code]
        if not isinstance(room, dict) or room.get("roomCategory") != CASH_ROOM_CATEGORY:
            continue
        rtype = room.get("roomType") if isinstance(room.get("roomType"), dict) else {}
        title = (rtype.get("title") or code).strip()
        if room_class_for(title) == "SUITE":
            continue
        for plan in room.get("ratePlans") or []:
            got = eligible_cash_plan(plan)
            if got is None:
                continue
            total, cur = got
            if best is None or total < best.total_after_tax:
                best = CashChoice(code, title, str(plan.get("id")), str(plan.get("name") or ""), total, cur)
    return best


def parse_cash_evidence(evidence_bytes: bytes, stay_date: str) -> List[RateRow]:
    """One row for `stay_date` (the check-in night of the request) or [] if no eligible cash plan."""
    choice = choose_cash(json.loads(evidence_bytes))
    if choice is None:
        return []
    note = f"{SOURCE_TAG_CASH} plan={choice.plan_id} ({choice.plan_name}) room={choice.room_code}"
    return [RateRow(stay_date=stay_date, room_name=choice.room_name, cash_rate=choice.total_after_tax,
                    currency=choice.currency, points_required=None, notes=note[:250])]


def stay_date_from_cash_filename(name: str) -> Optional[str]:
    """evidence/hyatt/cash_benchmarks/hyatt_{spirit}_{YYYY-MM-DD}_cash.json -> 'YYYY-MM-DD'."""
    m = re.search(r"_(\d{4}-\d{2}-\d{2})_cash\.json$", name)
    return m.group(1) if m else None


ANY_DATE = "*"   # same convention as engine.extractors.legacy: evidence that lists prices but not the stay date


def parse_evidence(evidence_bytes: bytes, stay_date: Optional[str] = None) -> List[RateRow]:
    """Rows for any Hyatt response.

    A cash (roomrates) response does not contain its stay date. The harvester passes the date it
    requested; an offline auditor that has only the bytes gets the row under ANY_DATE ('*'), which
    can be compared on price / currency / room but not on date (and is never written: the writer
    rejects it as BAD_DATE)."""
    data = json.loads(evidence_bytes)
    if isinstance(data, dict) and "roomRates" in data:
        return parse_cash_evidence(evidence_bytes, stay_date or ANY_DATE)
    return parse_award_evidence(evidence_bytes)


# ---------------------------------------------------------------------------------------------
# Response classification (shared by both harvesters): what did Hyatt actually answer?
# ---------------------------------------------------------------------------------------------
# Verdicts
#   OK         a usable JSON answer with content (award days present / roomRates present)
#   SOLD_OUT   definitive "nothing": award JSON {"days": {}, "responseInfo": "soldOutHotel"}
#              (Hyatt also sends this for an unknown spirit code and for a window that ends beyond its
#              booking horizon, so callers confirm it before trusting it as NO_AVAILABILITY)
#   BLOCKED    Kasada / edge protection: 0-byte 200, HTTP 403/429/451, HTML challenge page
#   RETRY      transient: HTTP 5xx / 408, network error, timeout
#   BAD        HTTP 4xx other than the above, or JSON that is not the expected shape
@dataclass
class Verdict:
    kind: str
    reason: str
    detail: str = ""


def classify_award_response(status, text: str, error: Optional[str] = None) -> Verdict:
    if error:
        return Verdict("RETRY", "FETCH_ERROR", error[:300])
    text = text or ""
    if status in (403, 429, 451):
        return Verdict("BLOCKED", f"HTTP_{status}", text[:300])
    if status is not None and status >= 500 or status == 408:
        return Verdict("RETRY", f"HTTP_{status}", text[:300])
    if status != 200:
        return Verdict("BAD", f"HTTP_{status}", text[:300])
    if not text.strip():
        return Verdict("BLOCKED", "KASADA_0_BYTE", "HTTP 200 with an empty body")
    if text.lstrip()[:1] not in ("{", "["):
        return Verdict("BLOCKED", "NOT_JSON", text[:300])
    try:
        data = json.loads(text)
    except ValueError as ex:
        return Verdict("BAD", "JSON_PARSE_ERROR", f"{ex}: {text[:200]}")
    days = data.get("days") if isinstance(data, dict) else None
    if not isinstance(days, dict):
        return Verdict("BAD", "UNEXPECTED_SHAPE", text[:300])
    if days:
        return Verdict("OK", "DAYS")
    if data.get("responseInfo") == "soldOutHotel":
        return Verdict("SOLD_OUT", "soldOutHotel", text[:200])
    return Verdict("BAD", "EMPTY_DAYS_NO_INFO", text[:300])


def classify_cash_response(status, text: str, error: Optional[str] = None) -> Verdict:
    if error:
        return Verdict("RETRY", "FETCH_ERROR", error[:300])
    text = text or ""
    if status in (403, 429, 451):
        return Verdict("BLOCKED", f"HTTP_{status}", text[:300])
    if status is not None and status >= 500 or status == 408:
        return Verdict("RETRY", f"HTTP_{status}", text[:300])
    if status != 200:
        return Verdict("BAD", f"HTTP_{status}", text[:300])
    if not text.strip():
        return Verdict("BLOCKED", "KASADA_0_BYTE", "HTTP 200 with an empty body")
    if text.lstrip()[:1] not in ("{", "["):
        return Verdict("BLOCKED", "NOT_JSON", text[:300])
    try:
        data = json.loads(text)
    except ValueError as ex:
        return Verdict("BAD", "JSON_PARSE_ERROR", f"{ex}: {text[:200]}")
    rooms = data.get("roomRates") if isinstance(data, dict) else None
    if not isinstance(rooms, dict):
        return Verdict("BAD", "UNEXPECTED_SHAPE", text[:300])
    if rooms:
        return Verdict("OK", "ROOMRATES")
    return Verdict("SOLD_OUT", "NO_ROOMS", text[:200])
