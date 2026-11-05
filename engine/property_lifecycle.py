# -*- coding: utf-8 -*-
"""Hotel Property Lifecycle State Machine.

Single source of truth for hotel operational lifecycle:
  ACTIVE       -> Currently bookable / operating hotel.
  INACTIVE     -> Deflagged from brand, permanently closed, or defunct.
  REACTIVATED  -> Property that was previously INACTIVE but returned with live rates.
  PENDING      -> New property awaiting first harvest verification.

All state transitions are persisted in `property_lifecycle_log` and mirrored
to `hotels.lifecycle_status`, ensuring portable context across machines.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple, Any

log = logging.getLogger("lifecycle")

LIFECYCLE_LOG_DDL = """
CREATE TABLE IF NOT EXISTS property_lifecycle_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hotel_id TEXT NOT NULL,
    brand TEXT NOT NULL,
    event_type TEXT NOT NULL,       -- 'DEFLAGGED', 'CLOSED', 'REACTIVATED', 'REOPENED', 'VERIFIED_ACTIVE'
    previous_status TEXT,
    new_status TEXT NOT NULL,
    reason TEXT NOT NULL,           -- e.g. 'REDIRECT_TO_SEARCH', 'RESURRECTED_WITH_LIVE_RATES', 'PROPERTY_NOT_ACTIVE'
    detail TEXT,
    evidence_url TEXT,
    transitioned_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_lifecycle_hotel ON property_lifecycle_log(hotel_id);
CREATE INDEX IF NOT EXISTS ix_lifecycle_event ON property_lifecycle_log(event_type);
"""

# Explicit triggers for declaring a property INACTIVE
INACTIVE_REASONS = {
    "REDIRECT_TO_SEARCH",          # Wyndham: 301/302 to search -> franchise lost
    "PROPERTY_NOT_ACTIVE",         # IHG error 50037
    "INVALID_PROPERTY_CODE",       # IHG error 50010
    "CLOSED_OR_DEFLAGGED",         # Accor invalid hotel code
    "HTTP_404",                    # Dead link
    "HTTP_410",                    # Gone
    "HOTEL_CLOSED",                # Official notice on page
    "DEFLAGGED_OR_CLOSED",         # Removed from directory
    "PAGE_NO_PROPERTY_ID",         # Landing page defunct
}


def ensure_lifecycle_schema(conn: sqlite3.Connection) -> None:
    """Ensures hotels table has lifecycle columns and lifecycle_log table exists."""
    conn.executescript(LIFECYCLE_LOG_DDL)
    
    # Check if lifecycle_status column exists in hotels
    cur = conn.cursor()
    columns = [col[1] for col in cur.execute("PRAGMA table_info(hotels)").fetchall()]
    if "lifecycle_status" not in columns:
        log.info("Migrating hotels table: adding lifecycle_status column...")
        conn.execute("ALTER TABLE hotels ADD COLUMN lifecycle_status TEXT DEFAULT 'ACTIVE'")
    if "status_updated_at" not in columns:
        log.info("Migrating hotels table: adding status_updated_at column...")
        conn.execute("ALTER TABLE hotels ADD COLUMN status_updated_at TEXT")
    conn.commit()


def record_transition(
    conn: sqlite3.Connection,
    hotel_id: str,
    brand: str,
    event_type: str,
    previous_status: Optional[str],
    new_status: str,
    reason: str,
    detail: Optional[str] = None,
    evidence_url: Optional[str] = None,
    commit: bool = True
) -> None:
    """Records a lifecycle transition in the permanent audit log and updates hotels table."""
    now_iso = datetime.now().isoformat(timespec="seconds")
    
    # 1. Insert into permanent audit log
    conn.execute("""
        INSERT INTO property_lifecycle_log 
            (hotel_id, brand, event_type, previous_status, new_status, reason, detail, evidence_url, transitioned_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (hotel_id, brand, event_type, previous_status, new_status, reason, (detail or "")[:1000], evidence_url, now_iso))
    
    # 2. Update current state in hotels table
    conn.execute("""
        UPDATE hotels 
        SET lifecycle_status = ?, status_updated_at = ?
        WHERE id = ?
    """, (new_status, now_iso, hotel_id))
    
    if commit:
        conn.commit()
    log.info(f"[LIFECYCLE] {hotel_id} ({brand}): {previous_status or 'NEW'} -> {new_status} [{event_type}]: {reason}")


def handle_harvest_result(
    conn: sqlite3.Connection,
    hotel_id: str,
    brand: str,
    harvest_status: str,
    harvest_reason: Optional[str],
    dates_ok: int = 0,
    evidence_url: Optional[str] = None,
    detail: Optional[str] = None
) -> str:
    """State Machine Engine: Evaluates probe result and handles state transitions.
    
    Returns the resulting lifecycle status: 'ACTIVE' or 'INACTIVE'.
    """
    ensure_lifecycle_schema(conn)
    cur = conn.cursor()
    
    cur.execute("SELECT lifecycle_status FROM hotels WHERE id = ?", (hotel_id,))
    row = cur.fetchone()
    current_status = row[0] if row and row[0] else "ACTIVE"
    
    # -------------------------------------------------------------------------
    # CASE 1: REACTIVATION (Property was INACTIVE, but returned with valid rates)
    # -------------------------------------------------------------------------
    if current_status == "INACTIVE" and (dates_ok > 0 or harvest_status == "OK"):
        event = "REACTIVATED" if dates_ok > 0 else "REOPENED"
        reason = f"RESURRECTED_WITH_LIVE_RATES ({dates_ok} dates)" if dates_ok > 0 else "DIRECTORY_CONFIRMED_ACTIVE"
        record_transition(
            conn, hotel_id=hotel_id, brand=brand, event_type=event,
            previous_status=current_status, new_status="ACTIVE",
            reason=reason, detail=detail, evidence_url=evidence_url
        )
        return "ACTIVE"
    
    # -------------------------------------------------------------------------
    # CASE 2: DEFLAGGING / CLOSURE (Property became INACTIVE)
    # -------------------------------------------------------------------------
    is_inactive_trigger = (
        harvest_status == "INACTIVE" or 
        (harvest_reason and harvest_reason.upper() in INACTIVE_REASONS)
    )
    
    if is_inactive_trigger and current_status != "INACTIVE":
        event = "DEFLAGGED" if "REDIRECT" in (harvest_reason or "") or "DEFLAGGED" in (harvest_reason or "") else "CLOSED"
        record_transition(
            conn, hotel_id=hotel_id, brand=brand, event_type=event,
            previous_status=current_status, new_status="INACTIVE",
            reason=harvest_reason or "OFFICIAL_CHANNEL_INACTIVE",
            detail=detail, evidence_url=evidence_url
        )
        return "INACTIVE"
    
    # -------------------------------------------------------------------------
    # CASE 3: VERIFIED ACTIVE
    # -------------------------------------------------------------------------
    if current_status != "ACTIVE" and harvest_status in ("OK", "NO_AVAILABILITY"):
        record_transition(
            conn, hotel_id=hotel_id, brand=brand, event_type="VERIFIED_ACTIVE",
            previous_status=current_status, new_status="ACTIVE",
            reason=f"PROBE_{harvest_status}", detail=detail, evidence_url=evidence_url
        )
        return "ACTIVE"
        
    return current_status


def sync_all_existing_states(conn: sqlite3.Connection) -> Dict[str, int]:
    """Syncs existing harvest_status entries to initialize hotels.lifecycle_status."""
    ensure_lifecycle_schema(conn)
    cur = conn.cursor()
    
    log.info("Synchronizing hotel lifecycle states from historical harvest_status...")
    
    # Hotels marked INACTIVE in harvest_status
    cur.execute("""
        SELECT h.id, h.brand, hs.status, hs.reason, hs.detail, hs.url
        FROM hotels h
        JOIN harvest_status hs ON h.id = hs.hotel_id
        WHERE hs.status = 'INACTIVE' OR hs.reason IN ('REDIRECT_TO_SEARCH', 'PROPERTY_NOT_ACTIVE', 'INVALID_PROPERTY_CODE', 'HOTEL_CLOSED', 'CLOSED_OR_DEFLAGGED')
    """)
    inactive_props = cur.fetchall()
    
    for h_id, brand, status, reason, detail, url in inactive_props:
        record_transition(
            conn, hotel_id=h_id, brand=brand, event_type="DEFLAGGED" if "REDIRECT" in (reason or "") else "CLOSED",
            previous_status="ACTIVE", new_status="INACTIVE",
            reason=reason or "HISTORICAL_INACTIVE", detail=detail, evidence_url=url, commit=False
        )
    
    conn.commit()
    
    # Summary count
    cur.execute("SELECT lifecycle_status, count(*) FROM hotels GROUP BY lifecycle_status")
    summary = dict(cur.fetchall())
    log.info(f"Lifecycle synchronization complete: {summary}")
    return summary
