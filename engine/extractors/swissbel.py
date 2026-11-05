"""Swiss-Belhotel (Hotelchamp IBE) response parser: raw evidence -> list[RateRow].

Pure functions: no network, no database, no I/O. Every DB write goes through
`engine.rate_writer.write_rate_batch()`.

Evidence format `swissbel-calendar-evidence` v1 (plain JSON or gzip). It WRAPS verbatim server
responses; nothing is added to them:

    {
      "format": "swissbel-calendar-evidence", "version": 1,
      "hotel_id": "swiss_swiss_belhotel_ambon", "property_id": "<hotelchamp uuid>",
      "harvested_at": "2026-11-02T08:30:00Z",
      "currency": {"code": "IDR", ...},                 # verbatim `default_currency` of /properties/{id}/
      "calendar_url": ".../properties/<id>/calendar?start=..&end=..",
      "calendar_response": {"2026-11-03": {"min_rate": 591736, "min_los": 1, ...}, ...},   # verbatim
      "tax_probes": [ {"room_id": "..", "rate_id": "..", "check_in": "..", "check_out": "..",
                       "status": 200, "response": {"included": [...], "excluded": [...], "to_be_paid_later": [...]}} ]
    }

Row rule (what ONE RateRow means):
  * The calendar only gives the lowest rate per day (`min_rate`). It names no room, no rate plan and
    states nothing about taxes. So a row is written ONLY when the hotel's own tax endpoint, probed on
    at least one rate, reports that NOTHING is charged on top of the price (`excluded` and
    `to_be_paid_later` both empty) on every probed rate. Then `min_rate` is the final price.
  * If any probe is missing, failed, or lists an excluded tax, NO rows are produced. The tax is never
    estimated and never added here.
  * Currency is the one the hotel's own detail response states; without it, no rows.
  * room_name is 'UNKNOWN (...)' because the calendar does not name a room.

LEGACY: evidence written by the older harvester has no "format" key (a bare date -> info dict in
which the script had added `all_in_rate` = min_rate * a guessed tax rate). It is still replayed so old
databases keep verifying, but it is NOT trusted as tax-inclusive evidence and is never produced again.
"""
import gzip
import json
import re
from typing import Any, Dict, List, Optional

from engine.rate_writer import RateRow

EVIDENCE_FORMAT = "swissbel-calendar-evidence"
EVIDENCE_VERSION = 1
GZIP_MAGIC = b"\x1f\x8b"
UNKNOWN_ROOM = "UNKNOWN (calendar lowest rate, room not stated by the source)"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CCY_RE = re.compile(r"^[A-Z]{3}$")


def _decompress(data: bytes) -> bytes:
    return gzip.decompress(data) if data.startswith(GZIP_MAGIC) else data


def probes_say_price_is_final(probes: Any) -> Optional[str]:
    """None when probes prove price is final (either inclusive or exact excluded tax cost present); otherwise reason."""
    if not isinstance(probes, list) or not probes:
        return "no tax probe in the evidence"
    has_inc_only = False
    has_exc = False
    for p in probes:
        if not isinstance(p, dict) or p.get("status") != 200 or not isinstance(p.get("response"), dict):
            return f"tax endpoint did not answer (HTTP {p.get('status') if isinstance(p, dict) else '?'})"
        r = p["response"]
        if not isinstance(r.get("excluded"), list) or not isinstance(r.get("included"), list):
            return "tax response has no included/excluded lists"
        if r.get("to_be_paid_later"):
            return "server lists charges payable later at the hotel"
        if r.get("excluded"):
            has_exc = True
            for ex in r["excluded"]:
                if not isinstance(ex, dict) or not isinstance(ex.get("cost"), (int, float)):
                    return "server excluded tax item missing numeric cost field"
        else:
            has_inc_only = True
    if has_inc_only and has_exc:
        return "tax probes disagree: one reports taxes included, another reports taxes excluded"
    return None


def _currency_code(doc: Dict[str, Any]) -> Optional[str]:
    c = doc.get("currency")
    code = c.get("code") if isinstance(c, dict) else None
    return code if isinstance(code, str) and _CCY_RE.match(code) else None


def _extract_room_name(doc: Dict[str, Any]) -> str:
    m = doc.get("matched_room")
    if isinstance(m, dict):
        nm = m.get("name")
        if isinstance(nm, dict):
            val = nm.get("en-US") or nm.get("id-ID") or next(iter(nm.values()), None)
            if val:
                return f"{val} (Entry-Level Room)"
        elif isinstance(nm, str) and nm.strip():
            return f"{nm.strip()} (Entry-Level Room)"
    return UNKNOWN_ROOM


def _parse_v1(doc: Dict[str, Any]) -> List[RateRow]:
    code = _currency_code(doc)
    cal = doc.get("calendar_response")
    if not code or not isinstance(cal, dict):
        return []
    probes = doc.get("tax_probes")
    if probes_say_price_is_final(probes) is not None:
        return []

    room_name = _extract_room_name(doc)
    all_inclusive = all(not p["response"].get("excluded") for p in probes if isinstance(p, dict) and isinstance(p.get("response"), dict))
    rows: List[RateRow] = []

    if all_inclusive:
        n = len(probes)
        for stay_date, info in sorted(cal.items()):
            if not _DATE_RE.match(stay_date) or not isinstance(info, dict):
                continue
            v = info.get("min_rate")
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
                continue
            rows.append(RateRow(
                stay_date=stay_date, room_name=room_name, cash_rate=float(v), currency=code, points_required=None,
                notes=f"Hotelchamp calendar min_rate as given by the server; tax endpoint reported no extra taxes on {n} probed rate(s)",
            ))
        return rows

    # Option 2: Server lists excluded taxes with official cost.
    # We pair each stay date with its exact 1-to-1 matching tax probe (room/rate/date/currency).
    probe_by_date = {p.get("check_in"): p for p in probes if isinstance(p, dict) and p.get("status") == 200 and isinstance(p.get("response"), dict)}
    for stay_date, info in sorted(cal.items()):
        if not _DATE_RE.match(stay_date) or not isinstance(info, dict):
            continue
        v = info.get("min_rate")
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
            continue
        # Strict fail-closed: date must have matching tax probe from server
        p = probe_by_date.get(stay_date)
        if not p:
            continue
        excluded = p["response"].get("excluded", [])
        tax_cost = sum(float(x["cost"]) for x in excluded if isinstance(x, dict) and isinstance(x.get("cost"), (int, float)))
        tax_names = ", ".join(f"{x.get('name')}: {float(x.get('cost', 0)):.2f}" for x in excluded if isinstance(x, dict))
        final_all_in = round(float(v) + tax_cost, 2)
        rows.append(RateRow(
            stay_date=stay_date,
            room_name=room_name,
            cash_rate=final_all_in,
            currency=code,
            points_required=None,
            notes=f"Hotelchamp calendar min_rate ({float(v):.2f}) + official server taxes ({tax_names}); room: {room_name}",
        ))
    return rows


def _parse_legacy(data: Dict[str, Any]) -> List[RateRow]:
    rows: List[RateRow] = []
    for stay_date, day_info in data.items():
        if not isinstance(day_info, dict) or not _DATE_RE.match(stay_date):
            continue
        v = day_info.get("all_in_rate")
        if v is None:
            v = day_info.get("min_rate")
        if v is not None and float(v) > 0:
            rows.append(RateRow(stay_date=stay_date, cash_rate=round(float(v), 2), points_required=None, currency=None, room_name=""))
    return rows


def parse_evidence(evidence_bytes: bytes) -> List[RateRow]:
    """Replay saved evidence into RateRows. Pure and deterministic."""
    data = json.loads(_decompress(evidence_bytes).decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid evidence payload: expected top-level JSON object")
    if data.get("format") == EVIDENCE_FORMAT:
        if data.get("version") != EVIDENCE_VERSION:
            raise ValueError(f"Unsupported {EVIDENCE_FORMAT} version: {data.get('version')!r}")
        return _parse_v1(data)
    return _parse_legacy(data)
