"""Centralized ingestion writer for rate_records (schema v2).

EVERY harvester writes through `write_rate_batch`. It exists to make three mistakes impossible:

  1. Judge-and-jury evidence. The caller must hand over the response bytes; the writer writes the
     file, hashes it and registers it. Evidence graded RAW must be the verbatim response text.
  2. Silent data loss. The writer never deletes a hotel's rows wholesale, refuses to overwrite a row
     that has points with one that has none (`WOULD_ERASE_POINTS`) unless the caller says the points
     fetch really completed, and refuses to clobber another source's row (`CONFLICT_OTHER_SOURCE`).
  3. Unlabelled prices. Every row names its room; `room_class` is derived here, once, from
     engine.room_classifier, so a Standard rate and a Suite rate can never share one series.

Rows that break the contract are returned in `WriteResult.rejected` with a reason code. They are
never dropped silently: callers must log or store them (see engine.harvest_state).
"""
import hashlib
import os
import random
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from engine.provenance_gate import (
    FORBIDDEN_KEYWORDS,
    ProvenanceViolationError,
    check_batch_source,
    check_row,
    validate_and_hash_rate_record,
)
from engine.room_classifier import classify_room_name
from engine.schema import schema_version

UNKNOWN_ROOM_PREFIX = "UNKNOWN"


# Labels some crawlers put in the room column for calendar rows. They name a RATE or a calendar, not a room:
# the source gave only the lowest price of the day. They must never be classified as a room tier.
CALENDAR_LABELS = frozenset({"best available baseline", "best available rate calendar"})
CALENDAR_UNKNOWN_ROOM = "UNKNOWN (calendar lowest rate, room not stated by the source)"


def room_class_for(room_name: str) -> str:
    """Tier of a room name. Names beginning 'UNKNOWN' (source does not say) and calendar labels stay UNKNOWN."""
    if not room_name or room_name.strip().upper().startswith(UNKNOWN_ROOM_PREFIX):
        return "UNKNOWN"
    if room_name.strip().lower() in CALENDAR_LABELS:
        return "UNKNOWN"
    return classify_room_name(room_name)


def room_id_for(hotel_id: str, room_name: str) -> str:
    """Stable id of one real room type at one hotel (<= 96 chars)."""
    digest = hashlib.sha1(room_name.strip().encode("utf-8")).hexdigest()[:6]
    slug = re.sub(r"[^a-z0-9]+", "_", room_name.lower()).strip("_")
    room = 96 - len(hotel_id) - 2 - 1 - len(digest)
    slug = slug[: max(room, 0)].strip("_")
    return f"{hotel_id}__{slug}_{digest}" if slug else f"{hotel_id}__{digest}"


@dataclass
class RateRow:
    stay_date: str                        # YYYY-MM-DD
    room_name: str                        # verbatim from the source; 'UNKNOWN (...)' if it does not say
    cash_rate: Optional[float] = None     # FULLY TAXED final price per stay, or None. Never 0.0.
    currency: Optional[str] = None        # ISO code taken from the response; required with cash_rate
    points_required: Optional[int] = None  # or None. Never 0.
    source_url: Optional[str] = None      # the exact request URL for this row (defaults to the batch URL)
    notes: Optional[str] = None


@dataclass
class WriteResult:
    written: int = 0
    superseded: int = 0
    rejected: List[Tuple[str, str]] = field(default_factory=list)   # (stay_date, reason_code)
    evidence_sha256: Optional[str] = None
    room_ids: List[str] = field(default_factory=list)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _write_evidence(workspace_dir: str, relpath: str, data: bytes) -> str:
    relpath = relpath.replace("\\", "/")
    full = os.path.join(workspace_dir, relpath)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    tmp = full + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, full)
    return relpath


def write_rate_batch(
    conn: sqlite3.Connection,
    *,
    hotel_id: str,
    source_type: str,
    source_url: str,
    rows: List[RateRow],
    evidence_relpath: str,
    evidence_bytes: bytes,
    evidence_grade: str,
    workspace_dir: str = ".",
    notes: Optional[str] = None,
    allow_points_removal: bool = False,
    today=None,
    commit: bool = True,
) -> WriteResult:
    """Validate, store evidence, and upsert one hotel's rows in a single transaction."""
    if evidence_grade not in ("RAW", "SUMMARY"):
        raise ProvenanceViolationError("evidence_grade must be 'RAW' or 'SUMMARY' for new rows.")
    if not evidence_bytes or len(evidence_bytes) < 10:
        raise ProvenanceViolationError("evidence_bytes is empty; a batch without evidence is refused.")
    check_batch_source(source_url, source_type, notes)

    result = WriteResult()
    good: List[RateRow] = []
    for r in rows:
        why = check_row(r.stay_date, r.cash_rate, r.currency, r.points_required, r.room_name, today)
        if r.notes:
            low = r.notes.lower()
            if any(k in low for k in FORBIDDEN_KEYWORDS):
                why = "FORBIDDEN_NOTE"
        if why:
            result.rejected.append((r.stay_date, why))
        else:
            good.append(r)
    if not good:
        return result

    sha = hashlib.sha256(evidence_bytes).hexdigest()
    result.evidence_sha256 = sha
    pts = [int(r.points_required) for r in good if r.points_required]
    now = _now()

    max_retries = 6
    for attempt in range(max_retries):
        try:
            ev_rel = _write_evidence(workspace_dir, evidence_relpath, evidence_bytes)
            conn.execute(
                """INSERT INTO evidence_registry (id, evidence_file, sha256_hash, file_bytes_size, source_url,
                       source_type, has_award_data, award_points_min, award_points_max, verified_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(evidence_file) DO UPDATE SET sha256_hash=excluded.sha256_hash,
                       file_bytes_size=excluded.file_bytes_size, source_url=excluded.source_url,
                       source_type=excluded.source_type, has_award_data=excluded.has_award_data,
                       award_points_min=excluded.award_points_min, award_points_max=excluded.award_points_max,
                       verified_at=excluded.verified_at""",
                (uuid.uuid4().hex, ev_rel, sha, len(evidence_bytes), source_url, source_type,
                 1 if pts else 0, min(pts) if pts else None, max(pts) if pts else None),
            )

            # Rooms: one row per real room type (UPSERT, never REPLACE - REPLACE + ON DELETE CASCADE
            # would wipe the room's rates if foreign keys were ever enabled).
            rooms: Dict[str, Tuple[str, str]] = {}
            for r in good:
                rid = room_id_for(hotel_id, r.room_name)
                rooms[rid] = (r.room_name.strip(), room_class_for(r.room_name))
            for rid, (rname, rclass) in rooms.items():
                std_type = rclass   # 'UNKNOWN' stays UNKNOWN so analytics never mistake it for a Standard room
                conn.execute(
                    """INSERT INTO room_categories (id, hotel_id, raw_name, standardized_type, max_occupancy)
                       VALUES (?, ?, ?, ?, 2)
                       ON CONFLICT(id) DO UPDATE SET raw_name=excluded.raw_name,
                           standardized_type=excluded.standardized_type""",
                    (rid, hotel_id, rname[:255], std_type),
                )
            result.room_ids = sorted(rooms)

            # What already exists for this hotel on these dates (any room).
            dates = sorted({r.stay_date for r in good})
            existing: Dict[str, List[Tuple[int, str, str, Optional[int]]]] = {}
            for i in range(0, len(dates), 400):
                chunk = dates[i:i + 400]
                q = ",".join("?" * len(chunk))
                for rid_, rr_id, sd, st, pt in conn.execute(
                    f"""SELECT rr.room_id, rr.id, rr.stay_date, rr.source_type, rr.points_required
                        FROM rate_records rr JOIN room_categories rc ON rc.id = rr.room_id
                        WHERE rc.hotel_id = ? AND rr.stay_date IN ({q})""",
                    [hotel_id, *chunk],
                ):
                    existing.setdefault(sd, []).append((rr_id, rid_, st, pt))

            to_delete: List[int] = []
            to_write: List[Tuple[RateRow, str]] = []
            for r in good:
                rid = room_id_for(hotel_id, r.room_name)
                reject = None
                for rr_id, ex_room, ex_src, ex_pts in existing.get(r.stay_date, []):
                    if ex_src != source_type:
                        if ex_room == rid:
                            reject = "CONFLICT_OTHER_SOURCE"   # would clobber another source's row
                            break
                        continue                                # different source, different room: coexist
                    if ex_pts and not r.points_required and not allow_points_removal:
                        reject = "WOULD_ERASE_POINTS"
                        break
                    if ex_room != rid:
                        to_delete.append(rr_id)                 # same source, room changed: newest wins
                if reject:
                    result.rejected.append((r.stay_date, reject))
                else:
                    to_write.append((r, rid))

            if to_delete:
                conn.executemany("DELETE FROM rate_records WHERE id = ?", [(i,) for i in to_delete])
                result.superseded = len(to_delete)

            params = []
            for r, rid in to_write:
                cash = round(float(r.cash_rate), 2) if r.cash_rate is not None else None
                cur = r.currency.upper() if cash is not None else None
                points = int(r.points_required) if r.points_required else None
                params.append((
                    rid, r.stay_date, cash, points, 1 if points else 0, now, (r.notes or notes), r.source_url or source_url,
                    source_type, sha, now, cur, cash, 1 if cash is not None else None, ev_rel,
                    r.room_name.strip(), room_class_for(r.room_name), evidence_grade,
                ))
            conn.executemany(
                """INSERT INTO rate_records (room_id, stay_date, cash_rate, points_required, award_available,
                       scraped_at, notes, source_url, source_type, source_payload_hash, observed_at,
                       raw_currency, raw_amount, tax_inclusive, evidence_file, room_name, room_class, evidence_grade)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(room_id, stay_date) DO UPDATE SET
                       cash_rate=excluded.cash_rate, points_required=excluded.points_required,
                       award_available=excluded.award_available, scraped_at=excluded.scraped_at,
                       notes=excluded.notes, source_url=excluded.source_url, source_type=excluded.source_type,
                       source_payload_hash=excluded.source_payload_hash, observed_at=excluded.observed_at,
                       raw_currency=excluded.raw_currency, raw_amount=excluded.raw_amount,
                       tax_inclusive=excluded.tax_inclusive, evidence_file=excluded.evidence_file,
                       room_name=excluded.room_name, room_class=excluded.room_class,
                       evidence_grade=excluded.evidence_grade""",
                params,
            )
            result.written = len(params)
            if commit:
                conn.commit()
            return result
        except sqlite3.OperationalError as e:
            conn.rollback()
            if "locked" in str(e).lower() and attempt < max_retries - 1:
                sleep_time = (0.5 * (2 ** attempt)) + random.uniform(0.1, 0.4)
                time.sleep(sleep_time)
                continue
            raise
        except Exception:
            conn.rollback()
            raise
    return result


# ------------------------------------------------------------------------------------------------
# Legacy single-row API, still used by the Langham / Shangri-La crawlers and the existing tests.
# ------------------------------------------------------------------------------------------------
def write_authentic_rate_record(
    conn: sqlite3.Connection,
    room_id: str,
    stay_date_str: str,
    raw_amount: float,
    raw_currency: str,
    source_url: str,
    source_type: str,
    raw_payload_str: Optional[str] = None,
    evidence_file: Optional[str] = None,
    points_required: Optional[int] = None,
    cash_rate_idr: Optional[float] = None,
    tax_inclusive: bool = True,
    notes: Optional[str] = None,
    commit: bool = True,
) -> Dict[str, Any]:
    """Validate through the provenance gate and store one row. Kept for the existing crawlers."""
    prov = validate_and_hash_rate_record(
        room_id=room_id, stay_date_str=stay_date_str, raw_amount=raw_amount, raw_currency=raw_currency,
        source_url=source_url, source_type=source_type, raw_payload_str=raw_payload_str,
        evidence_file=evidence_file, notes=notes,
    )
    max_retries = 6
    for attempt in range(max_retries):
        try:
            points = int(points_required) if points_required and points_required > 0 else None
            c = conn.cursor()
            if prov.get("evidence_file") and prov.get("source_payload_hash"):
                size = os.path.getsize(prov["evidence_file"]) if os.path.exists(prov["evidence_file"]) else 0
                c.execute(
                    """INSERT INTO evidence_registry (id, evidence_file, sha256_hash, file_bytes_size, source_url,
                           source_type, has_award_data, verified_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                       ON CONFLICT(evidence_file) DO UPDATE SET sha256_hash=excluded.sha256_hash,
                           file_bytes_size=excluded.file_bytes_size, source_url=excluded.source_url,
                           source_type=excluded.source_type, has_award_data=excluded.has_award_data,
                           verified_at=excluded.verified_at""",
                    (uuid.uuid4().hex, prov["evidence_file"], prov["source_payload_hash"], size, prov["source_url"],
                     prov["source_type"], 1 if points else 0),
                )
            values = [
                prov["room_id"], prov["stay_date"], prov["cash_rate"], points, 1 if points else 0,
                _now(), prov["notes"], prov["source_url"], prov["source_type"], prov["source_payload_hash"],
                _now(), prov["raw_currency"], prov["raw_amount"], 1 if tax_inclusive else 0, prov["evidence_file"],
            ]
            cols = ("room_id, stay_date, cash_rate, points_required, award_available, scraped_at, notes, source_url, "
                    "source_type, source_payload_hash, observed_at, raw_currency, raw_amount, tax_inclusive, evidence_file")
            marks = ",".join("?" * 15)
            if schema_version(conn) >= 2:
                row = c.execute("SELECT raw_name FROM room_categories WHERE id = ?", (room_id,)).fetchone()
                rname = row[0] if row else f"{UNKNOWN_ROOM_PREFIX} (room not named by crawler)"
                cols += ", room_name, room_class, evidence_grade"
                marks += ",?,?,?"
                values += [rname, room_class_for(rname), "RAW" if prov.get("evidence_file") else "UNVERIFIED"]
            c.execute(f"INSERT OR REPLACE INTO rate_records ({cols}) VALUES ({marks})", values)
            if commit:
                conn.commit()
            return prov
        except sqlite3.OperationalError as e:
            conn.rollback()
            if "locked" in str(e).lower() and attempt < max_retries - 1:
                sleep_time = (0.5 * (2 ** attempt)) + random.uniform(0.1, 0.4)
                time.sleep(sleep_time)
                continue
            raise
        except Exception:
            conn.rollback()
            raise
    return prov
