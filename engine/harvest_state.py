"""Per-hotel harvest state, stored in the database (table `harvest_status`).

Replaces the JSON progress/inactive/probe files. Every hotel that is not simply OK has a machine
reason, the verbatim error text and the URL where it got stuck - and a date after which it is worth
trying again. Nothing is blacklisted forever.

Status vocabulary
    OK               all planned dates were tried and at least one price was stored
    PARTIAL          some dates failed for a non-availability reason (timeouts, HTTP 5xx, blocks)
    NO_AVAILABILITY  the source answered "nothing available" on every probe (booking horizon or channel)
    INACTIVE         the hotel page no longer resolves to a property (removed / deflagged)
    DUPLICATE        another hotel id in our catalog is the same physical property (reason holds it)
    FAILED           we could not get a usable answer at all (network, auth, block)
"""
import random
import sqlite3
import time
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional

# Days until an automatic retry, per status. None = never retried automatically.
DEFAULT_RETRY_DAYS = {"FAILED": 1, "PARTIAL": 2, "NO_AVAILABILITY": 14, "INACTIVE": 30, "DUPLICATE": None, "OK": None}


def record(conn: sqlite3.Connection, source: str, hotel_id: str, status: str, *, reason: str = None,
           detail: str = None, url: str = None, grid_id: str = None, dates_ok: int = None,
           dates_total: int = None, horizon_last_ok: str = None, retry_days: Optional[int] = -1,
           commit: bool = True) -> None:
    """Upsert the state of one hotel. `retry_days=-1` means 'use the default for this status'."""
    if retry_days == -1:
        retry_days = DEFAULT_RETRY_DAYS.get(status)
    retry_after = (date.today() + timedelta(days=retry_days)).isoformat() if retry_days is not None else None

    max_retries = 6
    for attempt in range(max_retries):
        try:
            conn.execute(
                """INSERT INTO harvest_status (source, hotel_id, status, reason, detail, url, grid_id, dates_ok,
                       dates_total, horizon_last_ok, attempts, last_attempt_at, retry_after)
                   VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?)
                   ON CONFLICT(source, hotel_id) DO UPDATE SET status=excluded.status, reason=excluded.reason,
                       detail=excluded.detail, url=excluded.url, grid_id=excluded.grid_id, dates_ok=excluded.dates_ok,
                       dates_total=excluded.dates_total, horizon_last_ok=excluded.horizon_last_ok,
                       attempts=harvest_status.attempts + 1, last_attempt_at=excluded.last_attempt_at,
                       retry_after=excluded.retry_after""",
                (source, hotel_id, status, reason, (detail or "")[:1000] or None, url, grid_id, dates_ok, dates_total,
                 horizon_last_ok, datetime.now().isoformat(timespec="seconds"), retry_after),
            )
            
            # Integrated Lifecycle State Machine hook
            try:
                from engine import property_lifecycle
                brand_row = conn.execute("SELECT brand FROM hotels WHERE id = ?", (hotel_id,)).fetchone()
                brand = brand_row[0] if brand_row else "UNKNOWN"
                property_lifecycle.handle_harvest_result(
                    conn, hotel_id=hotel_id, brand=brand, harvest_status=status,
                    harvest_reason=reason, dates_ok=dates_ok or 0, evidence_url=url, detail=detail
                )
            except Exception:
                pass  # Lifecycle hook is non-blocking on write failure
            
            if commit:
                conn.commit()
            return
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


def load_all(conn: sqlite3.Connection, source: str) -> Dict[str, dict]:
    cur = conn.execute("SELECT hotel_id, status, reason, retry_after, last_attempt_at FROM harvest_status WHERE source = ?", (source,))
    return {h: {"status": s, "reason": r, "retry_after": ra, "last_attempt_at": la} for h, s, r, ra, la in cur}


def is_due(state: Optional[dict], today: Optional[date] = None, refresh_days: Optional[int] = None) -> bool:
    """Should this hotel be attempted now?

    * never seen -> yes
    * DUPLICATE -> no (its canonical hotel carries the data)
    * OK -> only when older than `refresh_days` (if given)
    * anything else -> when its retry_after date has passed
    """
    today = today or date.today()
    if state is None:
        return True
    st = state["status"]
    if st == "DUPLICATE":
        return False
    if st == "OK":
        if refresh_days is None:
            return False
        last = (state.get("last_attempt_at") or "")[:10]
        return not last or date.fromisoformat(last) <= today - timedelta(days=refresh_days)
    ra = state.get("retry_after")
    return ra is None or date.fromisoformat(ra) <= today


def due_hotels(hotels: Iterable[dict], states: Dict[str, dict], key: str = "id", refresh_days: Optional[int] = None) -> List[dict]:
    """Filter a hotel list to those that should be attempted now (never-seen first)."""
    todo = [h for h in hotels if is_due(states.get(h[key]), refresh_days=refresh_days)]
    todo.sort(key=lambda h: 0 if states.get(h[key]) is None else 1)
    return todo


def summary(conn: sqlite3.Connection, source: str) -> Dict[str, int]:
    return dict(conn.execute("SELECT status, COUNT(*) FROM harvest_status WHERE source = ? GROUP BY status", (source,)).fetchall())
