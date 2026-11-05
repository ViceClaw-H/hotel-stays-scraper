"""Shangri-La CRS -> RateRow. Pure functions: no network, no disk, no database.

Source: Shangri-La's own booking gateway  POST https://www.shangri-la.com/v1/website  (the header
`x-sl-service: <service name>` is REQUIRED - without it the gateway answers HTTP 200 with the body
{"status":403,"message":"访问失败"}; that is why every old *_calendar_q*.json file is 69 bytes).

Two services matter (both verified live, see docs/SHANGRILA_SCRAPING_MANUAL.md and the harvester):

  hotelDetailService.queryHotelDetail(query)      one stay date per request, ALL rooms x ALL rate plans.
      query.taxModel = "INCLUDED" | "EXCLUDED"  is the request parameter behind the site's
      "Tax & Fee Incl." toggle. Every rate carries originPrice = the HOTEL's own currency:
          money        the amount for the requested taxModel
          moneyWithTax the fully taxed amount (service charge + tax + fees), always present
          tax          the tax/fee part
      Horizon: check-in from tomorrow up to today+363 days; anything else is answered with
      status 21000 "the date you have selected was expired".
  searchSuggestService.queryCalendarPrice(query)  the date-picker prices: ONE call returns at most ~90
      days (nothing is priced beyond today+91 whatever startDate is), the amount is the LOWEST rate of
      the day WITHOUT service charge and tax, in the requested userCurrency, with no room name.
      It ignores every tax / room / rate filter. It cannot yield an all-in price, so it never becomes a
      RateRow (the writer would have to call a Tax-Excl. number final).

Evidence format (`shangrila-crs-evidence` v1) - one document per hotel and run, gzip-compressed JSON:

    {"format": "shangrila-crs-evidence", "version": 1, "hotel_id": ..., "hotel_code": ..., "harvested_at": ...,
     "responses": [{"kind": "detail", "stay_date": "2026-10-07", "request_url": <page URL of that date>,
                    "api_url": ..., "service": ..., "request": {<query sent>}, "http_status": 200,
                    "fetched_at": ..., "body": "<the response text, unmodified>"}, ...]}

`body` is the unmodified response text. Requests that never produced an answer are stored with
"body": null and an "error" text. `parse_evidence(bytes)` turns the file back into rows, so the
verifier can replay it offline and a change of parsing rules needs no re-scrape. It also reads the two
pre-contract raw formats so that old evidence can be replayed (see parse_legacy_card_evidence).

Rules implemented here:
  * cash = originPrice.moneyWithTax.amount of a `standard` rate plan (the site's own "Standard" tab). It is the
    hotel-currency, all-in ("Tax & Fee Incl.") price for ONE night, 1 adult. Nothing pre-tax is ever used.
    The "Packages" tab (rates that bundle breakfast etc.) is used ONLY on nights where the Standard tab is
    empty - many resorts (Mactan, Boracay, Fiji, Rasa Sayang ...) sell nothing else - and the row's notes say
    "package rate". A package is never preferred over an existing standard rate, even when it is cheaper.
  * currency = the rate's own currency code (aliases: NTD -> TWD). The user-currency `price` block is
    never used, so a geo/IP display currency can never leak into a label.
  * room per date = the room of the CHEAPEST all-in standard rate (what the site calls the lowest
    available rate). room_name is the room card's own title, verbatim; room_class comes from the writer.
    v9f (user rule 2026-11-03): the cheapest MEMBER rate (Shangri-La Circle, free to join) is used when the
    night offers one; otherwise the cheapest public rate. Notes say which ("member rate").
  * points: the CRS shows redemption prices only to a signed-in member (`pointsRates` is empty
    anonymously), so points_required is always None.
"""
import gzip
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from engine.rate_writer import RateRow

EVIDENCE_FORMAT = "shangrila-crs-evidence"
EVIDENCE_VERSION = 1
GZIP_MAGIC = b"\x1f\x8b"

API_URL = "https://www.shangri-la.com/v1/website"
SERVICE_DETAIL = "hotelDetailService.queryHotelDetail(query)"
SERVICE_CALENDAR = "searchSuggestService.queryCalendarPrice(query)"
HORIZON_DAYS = 363           # last check-in the CRS accepts is today + 363 (checked live 2026-09-21)
CALENDAR_DAYS = 91           # last day the calendar prices is today + 91

KIND_OK = "OK"               # rooms returned and an all-in standard cash rate found
KIND_NOAVAIL = "NOAVAIL"     # the CRS answered, but nothing can be booked / priced that night
KIND_HORIZON = "HORIZON"     # date beyond the booking window (status 21000): a definitive answer too
KIND_INACTIVE = "INACTIVE"   # the hotel code no longer resolves ("HOTEL_CLOSE ... ceased operation")
KIND_FAIL = "FAIL"           # transport / block / server error / unreadable answer - NOT "no availability"
KIND_CALENDAR = "CALENDAR"   # a calendar response (informational, never a row)

REASON_SOLD_OUT = "SOLD_OUT"
REASON_NO_RATES = "NO_RATES"
REASON_NO_CASH = "NO_ALL_IN_CASH"
REASON_HORIZON = "BEYOND_BOOKING_WINDOW"
REASON_CLOSED = "HOTEL_CLOSED"


def is_member_rate(pr: dict) -> bool:
    """v9f: a Shangri-La Circle member rate (free membership). Preferred over the public rate (user rule)."""
    if pr.get("gcExclusive") or pr.get("loginBooking") or pr.get("slcMemberRate"):
        return True
    name = str(pr.get("rateName") or pr.get("name") or "")
    return bool(re.search(r"\bmembers?\b", name, re.I))

CURRENCY_ALIASES = {"NTD": "TWD", "RMB": "CNY"}
_ISO = re.compile(r"^[A-Za-z]{3}$")


# ------------------------------------------------------------------------------------------------
# Requests (pure builders, shared by the harvester and the verifier so both ask the same question)
# ------------------------------------------------------------------------------------------------
def detail_query(hotel_code: str, check_in: str, check_out: str, user_currency: str = "USD",
                 tax_model: str = "INCLUDED", adults: int = 1) -> Dict[str, Any]:
    return {"hotelCode": hotel_code, "checkInDate": check_in, "checkOutDate": check_out,
            "peopleCondition": [{"adultNum": adults, "childNum": 0}], "roomNum": 1,
            "currency": user_currency, "openHeroRecommend": True, "taxModel": tax_model}


def calendar_query(hotel_code: str, start_date: str, user_currency: str) -> Dict[str, Any]:
    return {"hotelCode": hotel_code, "includeMinStay": True, "excludePrice": False, "startDate": start_date,
            "roomClassCodeList": [], "rateCodeList": [], "userCurrency": user_currency}


def request_envelope(service: str, query: Dict[str, Any]) -> Dict[str, Any]:
    return {"service": service, "query": query,
            "context": {"appVersion": "99.9.9", "platform": "BROWSER/MW", "lang": "English", "source": "WEBSITE"}}


def page_url(city_slug: str, brand_slug: str, hotel_code: str, check_in: str, check_out: str) -> str:
    """The human-openable room-rate page of the same request (the slugs are cosmetic; hotelCode decides)."""
    return (f"https://www.shangri-la.com/en/{city_slug}/{brand_slug}/reservations/select-room-rate/"
            f"?hotelCode={hotel_code}&checkInDate={check_in}&checkOutDate={check_out}"
            f"&rooms=%5B%7B%22adultNum%22%3A1%2C%22childNum%22%3A0%7D%5D")


# ------------------------------------------------------------------------------------------------
# One response
# ------------------------------------------------------------------------------------------------
@dataclass
class ParsedResponse:
    stay_date: str
    kind: str
    code: str = ""                       # machine reason for NOAVAIL / HORIZON / INACTIVE / FAIL
    message: str = ""                    # verbatim error text (body or error string)
    url: str = ""
    row: Optional[RateRow] = None        # only for KIND_OK
    n_rooms: int = 0
    n_rates: int = 0                     # standard rate plans seen
    currency: Optional[str] = None       # hotel currency, when the response carried a price


def _num(v) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def iso_currency(code: Any) -> Optional[str]:
    if not isinstance(code, str) or not _ISO.match(code.strip()):
        return None
    c = code.strip().upper()
    return CURRENCY_ALIASES.get(c, c)


def room_title(rm: dict) -> str:
    name = (rm.get("name") or rm.get("nameEn") or "").strip()
    if name:
        return name
    code = (rm.get("code") or "").strip()
    return f"UNKNOWN (room code {code or '?'})"


def all_in_cash(pr: dict) -> Tuple[Optional[float], Optional[str]]:
    """(amount, ISO currency) of the fully taxed nightly price of one rate plan, else (None, None)."""
    mt = ((pr.get("originPrice") or {}).get("moneyWithTax")) or {}
    amount = _num(mt.get("amount"))
    cur = iso_currency(mt.get("currency"))
    if amount is None or amount <= 0 or cur is None:
        return None, None
    return round(amount, 2), cur


def _rate_notes(pr: dict, n_pool: int, fallback: bool) -> str:
    op = pr.get("originPrice") or {}
    tax = _num((op.get("tax") or {}).get("amount"))
    name = (pr.get("rateName") or pr.get("rateCode") or "?").strip()
    bed = (pr.get("bedName") or "").strip()
    parts = [f"{name}{f' ({bed})' if bed else ''} [{pr.get('rateCode') or '?'}]"]
    if fallback:
        parts.append("package rate: no standard rate this night")
    if pr.get("gcExclusive") or pr.get("loginBooking") or pr.get("slcMemberRate"):
        parts.append("member rate")
    tag = (pr.get("cancelTag") or "").strip()
    if tag:
        parts.append(tag.replace(", fees apply", ""))
    pay = (pr.get("payTypeTag") or "").strip()
    if pay:
        parts.append(pay)
    if pr.get("hasBreakfastTag"):
        parts.append("breakfast")
    if tax:
        parts.append(f"incl. service charge+tax {tax:g}")
    parts.append(f"cheapest of {n_pool} {'package' if fallback else 'standard'} rates")
    return "; ".join(parts)[:250]


def choose_row(payload: dict, stay_date: str, url: str) -> Tuple[Optional[RateRow], str, int, int, Optional[str]]:
    """Pick room + rate and build the row for one successful detail response.

    Returns (row or None, reason-if-none, n_rooms, n_standard_rates, currency)."""
    hd = (payload.get("data") or {}).get("hotelDetail") or {}
    rooms = hd.get("rooms") or []
    std, pkg = [], []      # (amount, room title, rate code, currency, pr)
    n_std = n_all = 0
    for rm in rooms:
        rr = rm.get("roomRate") or {}
        if rr.get("canBook") is False:
            continue
        for pr in rr.get("productRates") or []:
            n_all += 1
            is_std = pr.get("rateCategory") == "standard"
            n_std += is_std
            amount, cur = all_in_cash(pr)
            if amount is not None:
                (std if is_std else pkg).append((amount, room_title(rm), pr.get("rateCode") or "", cur, pr))
    fallback = not std and bool(pkg)
    cands = std or pkg
    # v9f rate rule (user, 2026-11-03): the MEMBER rate (Shangri-La Circle, free to join) is the price stored;
    # the public rate only when no member rate is offered.
    member_cands = [c for c in cands if is_member_rate(c[4])]
    if member_cands:
        cands = member_cands
    if not cands:
        if not n_all:
            return None, REASON_SOLD_OUT if (payload.get("data") or {}).get("sellOut") else REASON_NO_RATES, len(rooms), 0, None
        return None, REASON_NO_CASH, len(rooms), n_std, None
    # never compare prices across currencies: keep the most common one (never seen live)
    count: Dict[str, int] = {}
    for c in cands:
        count[c[3]] = count.get(c[3], 0) + 1
    keep = max(count, key=lambda cu: (count[cu], cu))
    pool = [c for c in cands if c[3] == keep]
    amount, name, rcode, cur, pr = min(pool, key=lambda c: (c[0], c[1].lower(), c[1], c[2]))
    row = RateRow(stay_date=stay_date, room_name=name, cash_rate=amount, currency=cur, points_required=None,
                  source_url=url or None, notes=_rate_notes(pr, len(pool), fallback))
    return row, "", len(rooms), n_std, cur


def parse_response(stay_date: str, url: str, http_status: Optional[int], body: Optional[str],
                   error: Optional[str] = None, kind: str = "detail") -> ParsedResponse:
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
    if status != 0:
        msg = f'status {status}: {payload.get("message")}'
        if status == 21000:
            return ParsedResponse(stay_date, KIND_HORIZON, REASON_HORIZON, msg, url)
        if status == 403:
            return ParsedResponse(stay_date, KIND_FAIL, "BLOCKED_403", body[:300], url)
        return ParsedResponse(stay_date, KIND_FAIL, f"API_ERROR_{status}", body[:300], url)
    if kind == "calendar":
        return ParsedResponse(stay_date, KIND_CALENDAR, "", "", url)

    data = payload.get("data") or {}
    if data.get("hotelStatus") == "HOTEL_CLOSE":
        return ParsedResponse(stay_date, KIND_INACTIVE, REASON_CLOSED, str(data.get("hotelMsg") or "HOTEL_CLOSE"), url)
    if not data.get("hotelDetail"):
        return ParsedResponse(stay_date, KIND_FAIL, "NO_HOTEL_DETAIL", body[:300], url)
    row, why, n_rooms, n_std, cur = choose_row(payload, stay_date, url)
    if row is None:
        return ParsedResponse(stay_date, KIND_NOAVAIL, why, why, url, None, n_rooms, n_std)
    return ParsedResponse(stay_date, KIND_OK, "", "", url, row, n_rooms, n_std, cur)


# ------------------------------------------------------------------------------------------------
# Calendar (informational: lowest tax-EXCLUSIVE price per day)
# ------------------------------------------------------------------------------------------------
def parse_calendar(body: str) -> List[Tuple[str, Optional[float], Optional[str]]]:
    """[(date, amount or None, currency or None)] sorted by date. Amounts are WITHOUT service charge and tax."""
    payload = json.loads(body)
    items = ((payload.get("data") or {}).get("priceList")) or []
    out = []
    for it in items:
        p = it.get("price") or {}
        out.append((it["date"], _num(p.get("amount")), iso_currency(p.get("currency"))))
    out.sort(key=lambda t: t[0])
    return out


# ------------------------------------------------------------------------------------------------
# Evidence documents
# ------------------------------------------------------------------------------------------------
def build_evidence(hotel_id: str, hotel_code: str, harvested_at: str, responses: List[Dict[str, Any]]) -> bytes:
    """Serialise raw responses. Each item: kind, stay_date, request_url, api_url, service, request, http_status,
    fetched_at, body, error. Deterministic for a given input (gzip mtime fixed), so the file hash is stable."""
    doc = {
        "format": EVIDENCE_FORMAT, "version": EVIDENCE_VERSION, "hotel_id": hotel_id, "hotel_code": hotel_code,
        "harvested_at": harvested_at,
        "responses": sorted(responses, key=lambda r: (r.get("kind") != "calendar", r["stay_date"])),
    }
    raw = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return gzip.compress(raw, compresslevel=9, mtime=0)


def _decode(evidence_bytes: bytes) -> Any:
    data = gzip.decompress(evidence_bytes) if evidence_bytes[:2] == GZIP_MAGIC else evidence_bytes
    return json.loads(data.decode("utf-8"))


def load_evidence(evidence_bytes: bytes) -> dict:
    doc = _decode(evidence_bytes)
    if not isinstance(doc, dict) or doc.get("format") != EVIDENCE_FORMAT:
        raise ValueError(f"not a {EVIDENCE_FORMAT} document")
    return doc


def parse_evidence_responses(evidence_bytes: bytes) -> List[ParsedResponse]:
    doc = load_evidence(evidence_bytes)
    return [parse_response(r["stay_date"], r.get("request_url", ""), r.get("http_status"), r.get("body"),
                           r.get("error"), r.get("kind", "detail"))
            for r in doc["responses"]]


# ------------------------------------------------------------------------------------------------
# Pre-contract raw formats (replay only). Nothing new is ever written in these formats.
# ------------------------------------------------------------------------------------------------
_PRICE_JOINED = re.compile(r"^([A-Z]{3})\s?([0-9][0-9,]*(?:\.[0-9]+)?)$")
_CCY_ONLY = re.compile(r"^[A-Z]{3}$")
_NUMBER = re.compile(r"^[0-9][0-9,]*(?:\.[0-9]+)?$")
TAX_INCL = "Tax & Fee Incl."
TAX_EXCL = "Tax & Fee Excl."
_TAX_LABEL = re.compile(r"^Tax (?:& Fee )?(Incl|Excl)\.$")     # AUD / CAD hotels print "Tax Excl."


def _tax_label(lines: List[str]) -> Tuple[Optional[str], int]:
    """('INCL' | 'EXCL' | None, index of the label line) of one rate block."""
    for i, ln in enumerate(lines):
        m = _TAX_LABEL.match(ln)
        if m:
            return m.group(1).upper(), i
    return None, -1


def _card_prices(lines: List[str]) -> List[Tuple[str, float]]:
    out = []
    i = 0
    while i < len(lines):
        m = _PRICE_JOINED.match(lines[i])
        if m:
            out.append((m.group(1), float(m.group(2).replace(",", ""))))
        elif _CCY_ONLY.match(lines[i]) and i + 1 < len(lines) and _NUMBER.match(lines[i + 1]):
            out.append((lines[i], float(lines[i + 1].replace(",", ""))))
            i += 1
        i += 1
    return out


def legacy_card_room_rows(doc: dict) -> List[RateRow]:
    """One row per room card that has an all-in ('Tax & Fee Incl.') rate block: the cheapest such block.

    Old UI-crawler evidence: {"date", "url", "rooms": [{"name", "cardText"}]} (page innerText per room card).
    A rate block ends at 'Book Now' and states its tax basis in the line 'Tax & Fee Incl.' / 'Tax & Fee Excl.'.
    The LAST price token of the block is the hotel's own currency. A 'Tax & Fee Excl.' figure gives NO cash
    (never an assumed final price)."""
    stay_date = doc.get("date")
    out: List[RateRow] = []
    if not stay_date:
        return out
    for card in doc.get("rooms") or []:
        name = (card.get("name") or "").strip()
        text = card.get("cardText") or ""
        if not name or not text:
            continue
        best: Optional[Tuple[float, str]] = None
        for block in text.split("Book Now"):
            lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
            basis, at = _tax_label(lines)
            if basis != "INCL":
                continue
            prices = _card_prices(lines[:at])
            if not prices:
                continue
            cur, amount = prices[-1]
            cur = iso_currency(cur)
            if cur is None or amount <= 0:
                continue
            if best is None or (amount, cur) < best:
                best = (amount, cur)
        if best:
            out.append(RateRow(stay_date=stay_date, room_name=name, cash_rate=round(best[0], 2), currency=best[1],
                               source_url=doc.get("url"), notes="legacy page-text card, Tax & Fee Incl."))
    return out


def parse_legacy_card_evidence(doc: dict) -> List[RateRow]:
    """One row per date: the cheapest all-in card of the page-text evidence (same rule as the live rows)."""
    rows = legacy_card_room_rows(doc)
    if not rows:
        return []
    return [min(rows, key=lambda r: (r.cash_rate, r.room_name.lower(), r.room_name))]


def parse_evidence(evidence_bytes: bytes) -> List[RateRow]:
    """Evidence file bytes -> rate rows, sorted by stay_date, at most one per stay date. Pure.

    Understands (1) the shangrila-crs-evidence document (gzip or plain JSON) and (2) the pre-contract
    per-day page-text JSON. Anything else (calendar responses, script-written summaries) yields [] because
    it holds no all-in price - never an exception, never a guessed row."""
    try:
        obj = _decode(evidence_bytes)
    except Exception:                       # not gzip / not JSON / truncated: no evidence, no rows
        return []
    if not isinstance(obj, dict):
        return []
    if obj.get("format") == EVIDENCE_FORMAT:
        by_date: Dict[str, RateRow] = {}
        for p in parse_evidence_responses(evidence_bytes):
            if p.kind == KIND_OK and p.row is not None:
                by_date[p.stay_date] = p.row
        return [by_date[d] for d in sorted(by_date)]
    rooms = obj.get("rooms")
    if isinstance(rooms, list) and rooms and isinstance(rooms[0], dict) and "cardText" in rooms[0]:
        return parse_legacy_card_evidence(obj)
    return []
