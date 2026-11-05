"""IHG availability calendar -> RateRow. Pure functions: no network, no disk, no database.

Evidence format (`ihg-calendar-evidence` v1) - one document per hotel and run, gzip-compressed JSON:

    {"format": "ihg-calendar-evidence", "version": 1, "hotel_id": "ihg_aadal", "mnemonic": "AADAL",
     "harvested_at": "...",
     "requests": [{"kind": "profile"|"money"|"points", "window": ["2026-09-21", "2026-11-22"] | null,
                   "method": "GET"|"POST", "url": "...", "request_body": {...} | null,
                   "http_status": 200 | null, "fetched_at": "...",
                   "body": "<the response text, unmodified>" | null, "error": "..." | null}, ...]}

Every request that was parsed is stored with its response text as an unmodified string. `parse_evidence`
turns that file back into rows, so the verifier can replay it offline and a change of parsing rules needs
no re-scrape.

Rules implemented here (each verified live on 2026-09-21, numbers in scripts/verify_live_ihg.py output):

  * cash = `totalAmountAfterFeeTax` of the calendar day's LOWEST offer(s) (`lowestRate.refIds`). It only
    exists when the request carries `options.returnAmountsAfterTaxForLowestOffer` (the old option name
    `returnAmountAfterTax` is silently ignored by the API). It equals the price ihg.com shows after the
    "Includes taxes and fees" switch on the room-selection page (9 hotels, 9 countries: identical to
    the displayed whole unit). `lowestRate.totalAmount` and every `offers[].totalAmount` are BEFORE
    tax/fees - they are never used. If the lowest offer has no AfterFeeTax figure the cash is None.
  * stay length 1 uses the total; stay length N>1 (Six Senses hotels that refuse a 1-night stay) uses the
    per-night average (`averageDailyAmountAfterFeeTax`, `averageDailyPoints`) so every row is one night.
  * currency = `lowestRate.currency` (else `hotel.propertyCurrency`), only if it is a 3-letter ISO code.
  * points = the Reward Night rate plan (`ratePlans[].isRewardNight`) of the SAME room type as the cash
    row. IHG publishes cash all-in only for the lowest offer, so the row's room is that offer's room type;
    when several room types tie for the lowest price the one that also has reward nights wins, then the
    STANDARD-class one, then the one that is the lowest offer most often at this hotel (stable series).
    If the cash room has no reward offer that day, the cash row keeps points None (cash and points are never
    mixed across rooms) and the reward night is emitted as a SEPARATE points-only row (cash None, currency
    None) on the reward room, so the points are not lost; the two rows coexist on the date, one per room. A day
    with reward nights but no all-in cash is a points-only row on the reward room too. The reward room is the
    STANDARD-class one first, then the one with the fewest points.
  * room name = the hotel profile's `roomTypeDetails[].shortRoomDescription` + " [CODE]"; a code the
    profile does not describe becomes 'UNKNOWN (IHG room type CODE)'.
"""
import gzip
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from engine.rate_writer import RateRow, room_class_for

EVIDENCE_FORMAT = "ihg-calendar-evidence"
EVIDENCE_VERSION = 1
GZIP_MAGIC = b"\x1f\x8b"

KIND_PROFILE = "profile"
KIND_MONEY = "money"
KIND_POINTS = "points"

CALENDAR_URL = "https://apis.ihg.com/availability/v1/calendar"
PROFILE_URL = "https://apis.ihg.com/hotels/v3/profiles/{mn}/details"

# Warning / error codes seen in live answers.
WARN_INVALID_PROPERTY = "50010"     # {"message": "Invalid property code"}
WARN_NOT_ACTIVE = "50037"           # {"message": "The property is not active"}
WARN_OUT_OF_RANGE = "50027"         # {"message": "Invalid system range"}: window is beyond the booking horizon

_ISO = re.compile(r"^[A-Z]{3}$")
_CLASS_RANK = {"STANDARD": 0, "DELUXE": 1, "CLUB": 2, "SUITE": 3, "UNKNOWN": 4}


# ------------------------------------------------------------------------------------------------
# Request bodies (kept here so the harvester and the verifier send exactly what the site sends)
# ------------------------------------------------------------------------------------------------
# The reward-night rate plans the site itself asks for on the Points calendar.
REWARD_PLAN_CODES = ["IVAN1", "IVAN3", "IVAN5", "IVAN6", "IVAN7", "IVANI"]
SITE_OPTIONS = {
    "includeSellStrategy": "followChannel",
    "returnAmountsAfterTaxForLowestOffer": True,
    "returnAverages": True,
    "lowestOfferPerRatePlan": True,
    "identifyLowestOfferPerRatePlan": True,
}


def calendar_body(mnemonic: str, start: str, end: str, points: bool, los: int = 1) -> dict:
    """The body ihg.com posts to /availability/v1/calendar (Money calendar, or Points when points=True)."""
    body = {
        "hotelMnemonics": [mnemonic], "startDate": start, "endDate": end, "lengthOfStay": los,
        "guestCounts": [{"otaCode": "AQC10", "count": 1}], "options": dict(SITE_OPTIONS),
    }
    if points:
        body["rates"] = {"ratePlanCodes": list(REWARD_PLAN_CODES)}
    return body


# ------------------------------------------------------------------------------------------------
# Evidence documents
# ------------------------------------------------------------------------------------------------
def build_evidence(hotel_id: str, mnemonic: str, harvested_at: str, requests: List[Dict[str, Any]]) -> bytes:
    """Serialise raw requests/responses. Deterministic for a given input (gzip mtime fixed)."""
    order = {KIND_PROFILE: 0, KIND_MONEY: 1, KIND_POINTS: 2}
    reqs = sorted(requests, key=lambda r: (order.get(r["kind"], 9), (r.get("window") or [""])[0]))
    doc = {"format": EVIDENCE_FORMAT, "version": EVIDENCE_VERSION, "hotel_id": hotel_id, "mnemonic": mnemonic,
           "harvested_at": harvested_at, "requests": reqs}
    raw = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return gzip.compress(raw, compresslevel=9, mtime=0)


def load_evidence(evidence_bytes: bytes) -> dict:
    data = gzip.decompress(evidence_bytes) if evidence_bytes[:2] == GZIP_MAGIC else evidence_bytes
    doc = json.loads(data.decode("utf-8"))
    if not isinstance(doc, dict) or doc.get("format") != EVIDENCE_FORMAT:
        raise ValueError(f"not a {EVIDENCE_FORMAT} document")
    return doc


# ------------------------------------------------------------------------------------------------
# Small helpers
# ------------------------------------------------------------------------------------------------
def _num(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x > 0 else None


def _en(values) -> Optional[str]:
    """IHG localised text: [{'locale': 'en_US', 'value': '...'}]. English first, else the first entry."""
    if isinstance(values, str):
        return values.strip() or None
    if isinstance(values, list) and values:
        for v in values:
            if isinstance(v, dict) and str(v.get("locale", "")).lower().startswith("en") and v.get("value"):
                return str(v["value"]).strip() or None
        for v in values:
            if isinstance(v, dict) and v.get("value"):
                return str(v["value"]).strip() or None
    return None


def room_code(offer: dict) -> Optional[str]:
    """Room type code of a calendar offer: the inventory entry that carries the availability count
    (the other entries are add-on products such as 'BRK' = breakfast)."""
    inv = offer.get("inventoryTypesAvailable") or []
    for it in inv:
        if isinstance(it, dict) and "numberOfAvailableProducts" in it and it.get("inventoryTypeCode"):
            return str(it["inventoryTypeCode"])
    for it in inv:
        if isinstance(it, dict) and it.get("inventoryTypeCode"):
            return str(it["inventoryTypeCode"])
    return None


def room_display_name(code: str, names: Dict[str, str]) -> str:
    desc = names.get(code)
    return f"{desc} [{code}]" if desc else f"UNKNOWN (IHG room type {code})"


def parse_profile_room_names(body: Optional[str]) -> Dict[str, str]:
    """hotels/v3/profiles/{MN}/details -> {roomTypeCode: shortRoomDescription}. {} if unreadable."""
    if not body:
        return {}
    try:
        doc = json.loads(body)
        content = doc["hotelContent"]
        content = content[0] if isinstance(content, list) else content
        details = (content.get("roomTypes") or {}).get("roomTypeDetails") or []
    except (ValueError, KeyError, TypeError, IndexError):
        return {}
    out: Dict[str, str] = {}
    for d in details:
        code = d.get("roomTypeCode")
        desc = _en(d.get("shortRoomDescription"))
        if code and desc:
            out[str(code)] = desc
    return out


# ------------------------------------------------------------------------------------------------
# One calendar response
# ------------------------------------------------------------------------------------------------
@dataclass
class DayCash:
    stay_date: str
    currency: Optional[str]
    all_in: Optional[float]                      # totalAmountAfterFeeTax (per night); None if not given
    rooms: List[Tuple[str, Optional[float], str]] = field(default_factory=list)   # (code, all_in, rate plan) of the lowest offer(s)
    pre_tax: Optional[float] = None              # lowestRate.totalAmount: BEFORE tax, kept only for diagnostics
    currency_mismatch: bool = False


@dataclass
class ParsedCalendar:
    kind: str
    mnemonic: Optional[str] = None
    property_currency: Optional[str] = None
    los: int = 1
    cash_days: Dict[str, DayCash] = field(default_factory=dict)
    points_days: Dict[str, Dict[str, int]] = field(default_factory=dict)     # date -> {room code: points}
    calendar_days: int = 0                       # entries in hotels[0].calendar
    warnings: List[Tuple[str, str]] = field(default_factory=list)   # (code, message)
    ok: bool = False                             # 200 with a readable body


def _warnings(payload: dict) -> List[Tuple[str, str]]:
    out = []
    for w in payload.get("warnings") or []:
        if isinstance(w, dict):
            out.append((str(w.get("code", "")), str(w.get("message", ""))))
    return out


def parse_calendar_response(kind: str, http_status: Optional[int], body: Optional[str]) -> ParsedCalendar:
    res = ParsedCalendar(kind)
    if http_status != 200 or not body:
        return res
    try:
        payload = json.loads(body)
        data = payload["data"]
    except (ValueError, KeyError, TypeError):
        return res
    if not isinstance(data, dict):
        return res
    res.ok = True
    res.warnings = _warnings(payload)
    try:
        res.los = int(data.get("lengthOfStay") or 1)
    except (TypeError, ValueError):
        res.los = 1
    hotels = data.get("hotels") or []
    if not hotels or not isinstance(hotels[0], dict):
        return res
    h = hotels[0]
    hinfo = h.get("hotel") or {}
    res.mnemonic = hinfo.get("hotelMnemonic")
    pc = str(hinfo.get("propertyCurrency") or "").upper()
    res.property_currency = pc if _ISO.match(pc) else None
    reward_plans = {p.get("code") for p in h.get("ratePlans") or [] if isinstance(p, dict) and p.get("isRewardNight")}
    calendar = h.get("calendar") or []
    res.calendar_days = len(calendar)
    allin_key = "totalAmountAfterFeeTax" if res.los == 1 else "averageDailyAmountAfterFeeTax"
    pts_key = "totalPoints" if res.los == 1 else "averageDailyPoints"

    for entry in calendar:
        day = entry.get("start")
        if not day:
            continue
        offers = entry.get("offers") or []
        if kind == KIND_MONEY:
            lr = entry.get("lowestRate")
            if not isinstance(lr, dict):
                continue
            refs = set(lr.get("refIds") or [])
            cur = str(lr.get("currency") or res.property_currency or "").upper()
            cur = cur if _ISO.match(cur) else None
            rooms: List[Tuple[str, Optional[float], str]] = []
            for o in offers:
                if o.get("id") in refs and o.get("ratePlanCode") not in reward_plans:
                    code = room_code(o)
                    if code:
                        rooms.append((code, _num(o.get(allin_key)), str(o.get("ratePlanCode"))))
            allin_vals = [a for _, a, _ in rooms if a is not None]
            pre = _num(lr.get("averageDailyAmount") if res.los > 1 else lr.get("totalAmount"))
            all_in = min(allin_vals) if allin_vals else None
            if all_in is not None and pre is not None and all_in < pre * 0.999:
                all_in = None          # an "after tax" figure below the pre-tax one is not credible
            mismatch = bool(res.property_currency and lr.get("currency") and str(lr["currency"]).upper() != res.property_currency)
            keep = [(c, a, p) for c, a, p in rooms if a is not None and all_in is not None and abs(a - all_in) < 0.005] or rooms
            res.cash_days[day] = DayCash(day, cur, all_in, keep, pre, mismatch)
        else:
            by_room: Dict[str, int] = {}
            for o in offers:
                if o.get("ratePlanCode") in reward_plans:
                    code = room_code(o)
                    pts = o.get(pts_key)
                    if pts is None and res.los == 1:
                        pts = o.get("averageDailyPoints")
                    try:
                        pts = int(pts)
                    except (TypeError, ValueError):
                        continue
                    if code and pts > 0:
                        by_room[code] = min(pts, by_room.get(code, pts))
            if by_room:
                res.points_days[day] = by_room
    return res


# ------------------------------------------------------------------------------------------------
# Whole evidence document
# ------------------------------------------------------------------------------------------------
@dataclass
class Analysis:
    rows: List[RateRow] = field(default_factory=list)
    mnemonic: Optional[str] = None
    currency: Optional[str] = None
    los: int = 1
    profile_ok: bool = False
    room_names: Dict[str, str] = field(default_factory=dict)
    requests: Counter = field(default_factory=Counter)        # 'money_ok', 'points_fail', ...
    failures: List[Dict[str, Any]] = field(default_factory=list)   # non-200 / unreadable requests, verbatim
    warnings: List[Tuple[str, str, str]] = field(default_factory=list)   # (kind, code, message)
    money_days: int = 0            # calendar days that have a lowest offer
    cash_days: int = 0             # rows with an all-in cash price
    no_allin_days: int = 0         # lowest offer present but no all-in figure -> cash None
    points_days: int = 0           # rows carrying points
    points_only_days: int = 0      # rows with points and no cash
    paired_days: int = 0           # cash and points on the same room
    cash_days_reward_other_room: int = 0   # cash row whose room has no reward night although another room does -> separate points-only row
    separate_points_rows: int = 0          # points-only rows emitted next to a cash row of another room (same number)
    nonstandard_cash_days: int = 0         # cash row whose room class is not STANDARD
    unresolved_room_codes: List[str] = field(default_factory=list)
    currency_mismatch_days: int = 0
    plan_counts: Counter = field(default_factory=Counter)      # rate plan of the cash rows
    class_counts: Counter = field(default_factory=Counter)     # room class of the cash rows
    horizon_last_ok: Optional[str] = None
    windows_with_days: int = 0
    invalid_property: bool = False   # warning 50010: the mnemonic does not exist
    not_active: bool = False         # warning 50037: the property exists but is not active (closed / deflagged / not yet open)


def _points_only_row(day: str, room_pts: Dict[str, int], names: Dict[str, str], freq_pts: Counter,
                     unresolved: set, a: "Analysis", note: str) -> RateRow:
    """Points-only row on the reward room: STANDARD class first, then the fewest points, then the most common room."""
    best = min(room_pts, key=lambda c: (_CLASS_RANK[room_class_for(room_display_name(c, names))], room_pts[c], -freq_pts[c], c))
    if best not in names:
        unresolved.add(best)
    a.points_days += 1
    a.points_only_days += 1
    return RateRow(day, room_display_name(best, names), None, None, room_pts[best], CALENDAR_URL, note)


def analyze_evidence(evidence_bytes: bytes) -> Analysis:
    doc = load_evidence(evidence_bytes)
    a = Analysis(mnemonic=doc.get("mnemonic"))
    parsed: List[ParsedCalendar] = []
    for r in doc.get("requests", []):
        kind = r.get("kind")
        status, body = r.get("http_status"), r.get("body")
        if kind == KIND_PROFILE:
            names = parse_profile_room_names(body) if status == 200 else {}
            if names:
                a.profile_ok = True
                a.room_names.update(names)
            a.requests["profile_ok" if names else "profile_fail"] += 1
            if not names:
                a.failures.append({"kind": kind, "url": r.get("url"), "http_status": status,
                                   "text": (body or r.get("error") or "")[:500]})
            continue
        if kind not in (KIND_MONEY, KIND_POINTS):
            continue
        p = parse_calendar_response(kind, status, body)
        if not p.ok:
            a.requests[f"{kind}_fail"] += 1
            a.failures.append({"kind": kind, "url": r.get("url"), "window": r.get("window"), "http_status": status,
                               "text": (body or r.get("error") or "")[:500]})
            continue
        a.requests[f"{kind}_ok"] += 1
        parsed.append(p)
        for code, msg in p.warnings:
            a.warnings.append((kind, code, msg))
            if code == WARN_INVALID_PROPERTY:
                a.invalid_property = True
            elif code == WARN_NOT_ACTIVE:
                a.not_active = True
        if p.calendar_days:
            a.windows_with_days += 1
        if p.mnemonic and not a.mnemonic:
            a.mnemonic = p.mnemonic
        if p.los:
            a.los = max(a.los, p.los)
        if p.property_currency:
            a.currency = p.property_currency

    cash: Dict[str, DayCash] = {}
    pts: Dict[str, Dict[str, int]] = {}
    for p in parsed:
        cash.update(p.cash_days)
        for d, m in p.points_days.items():
            pts[d] = m
    a.money_days = len(cash)

    # Hotel-wide "how often is this room the lowest offer / a reward room": makes tie-breaks stable.
    freq_cash: Counter = Counter()
    for d in cash.values():
        if d.all_in is not None:
            for code in {c for c, _, _ in d.rooms}:
                freq_cash[code] += 1
    freq_pts: Counter = Counter()
    for m in pts.values():
        for code in m:
            freq_pts[code] += 1

    names = a.room_names
    def cls(code: str) -> str:
        return room_class_for(room_display_name(code, names))

    unresolved = set()
    rows: List[RateRow] = []
    for day in sorted(set(cash) | set(pts)):
        d = cash.get(day)
        room_pts = pts.get(day, {})
        if d is not None and d.currency_mismatch:
            a.currency_mismatch_days += 1
        if d is not None and d.all_in is not None and d.currency:
            # cash row: choose among the tied lowest rooms
            cands = sorted({c for c, al, _ in d.rooms if al is not None})
            best = min(cands, key=lambda c: (_CLASS_RANK[cls(c)], 0 if c in room_pts else 1, -freq_cash[c], c))
            plan = next(p for c, al, p in d.rooms if c == best and al is not None)
            points = room_pts.get(best)
            name = room_display_name(best, names)
            if best not in names:
                unresolved.add(best)
            note = f"cash: lowest offer plan {plan}, all-in (totalAmountAfterFeeTax)"
            if a.los > 1:
                note += f"; per-night average of a {a.los}-night stay"
            if points:
                note += "; points: reward night, same room"
            rows.append(RateRow(day, name, d.all_in, d.currency, points, CALENDAR_URL, note))
            a.cash_days += 1
            a.plan_counts[plan] += 1
            a.class_counts[room_class_for(name)] += 1
            if room_class_for(name) != "STANDARD":
                a.nonstandard_cash_days += 1
            if points:
                a.points_days += 1
                a.paired_days += 1
            elif room_pts:
                # The reward night exists, but not for the cash room: keep the one-room rule (no points on the cash
                # row) and store the points as their own row on the reward room.
                a.cash_days_reward_other_room += 1
                a.separate_points_rows += 1
                rows.append(_points_only_row(day, room_pts, names, freq_pts, unresolved, a,
                                             "points only: reward night only available on this room type; the lowest all-in cash offer "
                                             "that day is another room type, so cash and points are kept in separate rows"))
        elif room_pts:
            note = "points only: reward night"
            if d is not None:
                a.no_allin_days += 1
                note += "; the lowest cash offer carries no all-in (AfterFeeTax) amount, so cash is None"
            rows.append(_points_only_row(day, room_pts, names, freq_pts, unresolved, a, note))
        elif d is not None:
            a.no_allin_days += 1     # cash offer without an all-in figure and no points: no row at all
    a.rows = rows
    a.unresolved_room_codes = sorted(unresolved)
    if rows:
        a.horizon_last_ok = rows[-1].stay_date
    return a


def parse_evidence(evidence_bytes: bytes) -> List[RateRow]:
    """Evidence file bytes (gzip or plain JSON) -> rate rows, sorted by stay_date. Pure."""
    return analyze_evidence(evidence_bytes).rows
