"""Policy-enforced ingestion for the live, bookable hotel-location universe.

Location crawlers submit observations, never their own eligibility verdict.  This writer derives
the verdict from the central chain policy and records the official booking evidence used to make it.
Cash + Points is intentionally absent from the eligibility inputs: it can never qualify a hotel.
"""
import hashlib
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from engine.chain_policy import LocationScope, policy_for
from engine.provenance_gate import ProvenanceViolationError, check_batch_source
from engine.schema import ensure_location_schema


IN_SCOPE_REDEEMABLE = "IN_SCOPE_REDEEMABLE"
IN_SCOPE_BOOKABLE = "IN_SCOPE_BOOKABLE"
REDEEMABLE_SOLD_OUT_IN_TEST_WINDOW = "REDEEMABLE_SOLD_OUT_IN_TEST_WINDOW"
CASH_SOLD_OUT_IN_TEST_WINDOW = "CASH_SOLD_OUT_IN_TEST_WINDOW"
OUT_OF_SCOPE_PARTNER_NONREDEEMABLE = "OUT_OF_SCOPE_PARTNER_NONREDEEMABLE"
UNKNOWN_ELIGIBILITY = "UNKNOWN_ELIGIBILITY"


@dataclass(frozen=True)
class LocationObservation:
    """Facts observed in one official booking-engine test window.

    `full_points_bookable` means a room redeemable entirely with points.  A Cash + Points offer
    must be ignored by the parser and must never set this field.
    """

    cash_search_attempted: bool = False
    cash_bookable: bool = False
    award_search_attempted: bool = False
    full_points_bookable: bool = False
    partner_nonredeemable_confirmed: bool = False
    notes: Optional[str] = None


@dataclass(frozen=True)
class LocationWriteResult:
    observation_id: str
    chain: str
    policy_mode: str
    status: str
    evidence_sha256: str


def _as_int(value: bool) -> int:
    return 1 if value else 0


def derive_location_status(policy_mode: LocationScope, observation: LocationObservation) -> str:
    """Derive the only permissible state; callers cannot nominate a more favorable label."""
    if observation.full_points_bookable and observation.partner_nonredeemable_confirmed:
        raise ValueError("Contradictory observation: full-points redemption and confirmed nonredeemable partner.")
    if policy_mode == LocationScope.REDEMPTION_REQUIRED:
        if observation.full_points_bookable:
            return IN_SCOPE_REDEEMABLE
        if observation.partner_nonredeemable_confirmed:
            return OUT_OF_SCOPE_PARTNER_NONREDEEMABLE
        if observation.award_search_attempted:
            return REDEEMABLE_SOLD_OUT_IN_TEST_WINDOW
        return UNKNOWN_ELIGIBILITY
    if policy_mode == LocationScope.BOOKABLE_ONLY:
        if observation.cash_bookable:
            return IN_SCOPE_BOOKABLE
        if observation.cash_search_attempted:
            return CASH_SOLD_OUT_IN_TEST_WINDOW
        return UNKNOWN_ELIGIBILITY
    raise ValueError(f"Unsupported policy mode: {policy_mode}")


def _write_evidence(workspace_dir: str, relpath: str, data: bytes) -> str:
    relpath = relpath.replace("\\", "/")
    full = os.path.join(workspace_dir, relpath)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    tmp = full + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, full)
    return relpath


def write_location_observation(
    conn: sqlite3.Connection,
    *,
    hotel_id: str,
    source_type: str,
    source_url: str,
    observation: LocationObservation,
    evidence_relpath: str,
    evidence_bytes: bytes,
    evidence_grade: str = "RAW",
    workspace_dir: str = ".",
    commit: bool = True,
) -> LocationWriteResult:
    """Store one policy-derived result with official, hash-registered booking evidence."""
    ensure_location_schema(conn)
    if evidence_grade not in ("RAW", "SUMMARY"):
        raise ProvenanceViolationError("Location evidence must be RAW or SUMMARY; UNVERIFIED is refused.")
    if not evidence_bytes or len(evidence_bytes) < 10:
        raise ProvenanceViolationError("Location observation without official evidence is refused.")
    check_batch_source(source_url, source_type, observation.notes)
    hotel = conn.execute("SELECT brand FROM hotels WHERE id = ?", (hotel_id,)).fetchone()
    if hotel is None:
        raise ValueError(f"Unknown hotel_id {hotel_id!r}; location observation is refused.")
    policy = policy_for(hotel[0])
    status = derive_location_status(policy.location_scope, observation)
    sha = hashlib.sha256(evidence_bytes).hexdigest()
    evidence_file = _write_evidence(workspace_dir, evidence_relpath, evidence_bytes)
    observation_id = uuid.uuid4().hex
    now = datetime.now().isoformat(timespec="seconds")
    try:
        conn.execute(
            """INSERT INTO evidence_registry (id, evidence_file, sha256_hash, file_bytes_size, source_url,
                   source_type, has_award_data, verified_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(evidence_file) DO UPDATE SET sha256_hash=excluded.sha256_hash,
                   file_bytes_size=excluded.file_bytes_size, source_url=excluded.source_url,
                   source_type=excluded.source_type, has_award_data=excluded.has_award_data,
                   verified_at=excluded.verified_at""",
            (uuid.uuid4().hex, evidence_file, sha, len(evidence_bytes), source_url, source_type,
             _as_int(observation.full_points_bookable)),
        )
        conn.execute(
            """INSERT INTO location_observations (
                   id, hotel_id, chain, policy_mode, status, cash_search_attempted, cash_bookable,
                   award_search_attempted, full_points_bookable, partner_nonredeemable_confirmed,
                   source_url, source_type, source_payload_hash, evidence_file, evidence_grade, observed_at, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (observation_id, hotel_id, policy.chain, policy.location_scope.value, status,
             _as_int(observation.cash_search_attempted), _as_int(observation.cash_bookable),
             _as_int(observation.award_search_attempted), _as_int(observation.full_points_bookable),
             _as_int(observation.partner_nonredeemable_confirmed), source_url, source_type, sha,
             evidence_file, evidence_grade, now, observation.notes),
        )
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    return LocationWriteResult(observation_id, policy.chain, policy.location_scope.value, status, sha)
