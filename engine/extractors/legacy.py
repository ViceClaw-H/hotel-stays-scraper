"""Replayers for the two evidence formats written before schema v2 (pure, no I/O).

Both return {stay_date: (cash_rate, points, currency, room_name)} read from the evidence itself, so the
verifier and the migration can check a stored row against what its own evidence says.
"""
import json
from typing import Dict, Optional, Tuple

HYATT_EXCLUDED = ("SUITE", "CLUB", "VILLA", "PREMIUM", "PENTHOUSE", "DELUXE")
Replay = Dict[str, Tuple[Optional[float], Optional[int], Optional[str], str]]

ANY_DATE = "*"   # replay key for evidence that lists prices but does not carry the stay date itself


class UnsupportedEvidence(ValueError):
    """The file is not in the format this replayer understands: rows cannot be value-checked from it."""


def select_hyatt_key(rooms):
    """Standard-room rule of the award harvester: STANDARD_ROOM, else STANDARD, else the lowest-points room
    that is not a suite/club/villa/premium/penthouse/deluxe. Returns (key, points) or (None, None)."""
    if "STANDARD_ROOM" in rooms:
        key = "STANDARD_ROOM"
    elif "STANDARD" in rooms:
        key = "STANDARD"
    else:
        cands = []
        for k, v in rooms.items():
            if not isinstance(v, dict) or any(b in k.upper() for b in HYATT_EXCLUDED):
                continue
            pv = (v.get("pointsValue") or [None])[0]
            if pv:
                cands.append((int(pv), k))
        if not cands:
            return None, None
        key = sorted(cands)[0][1]
    pv = ((rooms.get(key) or {}).get("pointsValue") or [None])[0]
    return key, (int(pv) if pv else None)


def hyatt_award_replay(evidence_bytes: bytes) -> Replay:
    """evidence/hyatt/avail_days/*.json: the raw avail/days response."""
    days = json.loads(evidence_bytes.decode("utf-8", errors="replace")).get("days", {})
    out: Replay = {}
    for stay_date, rooms in days.items():
        if isinstance(rooms, dict):
            key, pts = select_hyatt_key(rooms)
            if key and pts:
                out[stay_date] = (None, pts, None, key)
    return out


def wyndham_summary_replay(evidence_bytes: bytes) -> Replay:
    """evidence/wyndham/calendar/*_stratified_benchmark.json: the old harvester's own summary."""
    d = json.loads(evidence_bytes.decode("utf-8", errors="replace"))
    out: Replay = {}
    for r in d.get("rates", []):
        cash = r.get("cash_rate") or None
        pts = r.get("points_required") or None
        if cash or pts:
            out[r["stay_date"]] = (cash, pts, r.get("currency") if cash else None, (r.get("room_name") or "").strip())
    return out


def ihg_summary_replay(evidence_bytes: bytes) -> Replay:
    """evidence/ihg/calendar/ihg_*_ui_calendar.json written by the old API harvester: its own summary.
    The calendar API does not name the room, so the room is the fixed UNKNOWN label."""
    d = json.loads(evidence_bytes.decode("utf-8", errors="replace"))
    out: Replay = {}
    for r in d.get("rates", []):
        cash = r.get("cash_rate") or None
        pts = r.get("points_required") or None
        if cash or pts:
            out[r["stay_date"]] = (cash, pts, r.get("currency") if cash else None, "")   # "" = room not checked
    return out


def langham_calendar_replay(evidence_bytes: bytes) -> Replay:
    """evidence/langham/calendar/*.json: the raw calendar response. The all-in price is `amountWithTax`."""
    d = json.loads(evidence_bytes.decode("utf-8", errors="replace"))
    cal = (d.get("data") or {}).get("calendar") if isinstance(d, dict) else None
    if not isinstance(cal, list):
        raise UnsupportedEvidence("not a Langham calendar response")
    return {e["date"]: (e.get("amountWithTax"), None, e.get("currency"), "") for e in cal if e.get("date") and e.get("amountWithTax")}


def gha_rooms_replay(evidence_bytes: bytes) -> Replay:
    """evidence/gha/**/*_rooms_*.json: the raw rooms response. It does not carry the stay date, so the replay
    lists every (room, price, currency) it offers under ANY_DATE; a stored row must match one of them."""
    d = json.loads(evidence_bytes.decode("utf-8", errors="replace"))
    rooms = d.get("rooms") if isinstance(d, dict) else None
    if not isinstance(rooms, list):
        raise UnsupportedEvidence("not a GHA rooms response")
    out = []
    for rm in rooms:
        for rt in rm.get("rates") or []:
            # The stored value is the per-night `dailyPrice`; `price` is the stay total. Either may be what a row holds.
            for field in ("dailyPrice", "price"):
                try:
                    out.append((float(rt.get(field)), None, rt.get("currency"), (rm.get("roomName") or "").strip()))
                except (TypeError, ValueError):
                    continue
    return {ANY_DATE: out}


LEGACY_REPLAYERS = {
    "OFFICIAL_LANGHAM_SYNXIS": langham_calendar_replay,
    "OFFICIAL_GHA_CRS": gha_rooms_replay,
    "OFFICIAL_IHG_CRS": ihg_summary_replay,
    "OFFICIAL_HYATT_AVAIL_DAYS": hyatt_award_replay,
    "OFFICIAL_WYNDHAM_CRS": wyndham_summary_replay,
}
