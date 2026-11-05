"""Empirical Percentile Baseline Engine ($P_0, P_{10}, P_{50}, P_{90}, P_{100}$).
Computes exact mathematical distributions from real scraped rate data.
Zero hardcoded assumptions.
"""
import sqlite3
import numpy as np
import logging
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("baseline_engine")

DB_PATH = "hotel_stays.db"

def update_property_and_brand_baselines():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 1. Drop old property_baselines table if schema needs migration
    c.execute("DROP TABLE IF EXISTS property_baselines")
    c.execute("""
        CREATE TABLE property_baselines (
            room_id VARCHAR(96) NOT NULL PRIMARY KEY,
            cash_p0 FLOAT NOT NULL,
            cash_p10 FLOAT NOT NULL,
            cash_p50 FLOAT NOT NULL,
            cash_p90 FLOAT NOT NULL,
            cash_p100 FLOAT NOT NULL,
            points_p0 INTEGER,
            points_p10 INTEGER,
            points_p50 INTEGER,
            points_p90 INTEGER,
            points_p100 INTEGER,
            val_p0 FLOAT,
            val_p10 FLOAT,
            val_p50 FLOAT,
            val_p90 FLOAT,
            val_p100 FLOAT,
            avg_cash_rate FLOAT NOT NULL,
            ceiling_surge_pct FLOAT NOT NULL,
            sample_count INTEGER NOT NULL,
            updated_at DATETIME,
            FOREIGN KEY(room_id) REFERENCES room_categories (id) ON DELETE CASCADE
        )
    """)

    # 2. Compute per-room empirical percentiles
    c.execute("SELECT id FROM room_categories")
    rooms = [r[0] for r in c.fetchall()]

    updated_count = 0
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    for room_id in rooms:
        c.execute("""
            SELECT cash_rate, points_required 
            FROM rate_records 
            WHERE room_id = ? AND cash_rate > 0
            ORDER BY stay_date ASC
        """, (room_id,))
        rows = c.fetchall()
        if not rows:
            continue

        cash_arr = np.array([r[0] for r in rows], dtype=float)
        pts_valid = [r[1] for r in rows if r[1] is not None and r[1] > 0]
        pts_arr = np.array(pts_valid, dtype=float) if pts_valid else None
        
        val_valid = [r[0] / r[1] for r in rows if r[1] is not None and r[1] > 0]
        val_arr = np.array(val_valid, dtype=float) if val_valid else None

        # Cash percentiles
        c_p0 = float(np.min(cash_arr))
        c_p10 = float(np.percentile(cash_arr, 10))
        c_p50 = float(np.percentile(cash_arr, 50))
        c_p90 = float(np.percentile(cash_arr, 90))
        c_p100 = float(np.max(cash_arr))
        avg_cash = float(np.mean(cash_arr))
        surge_pct = (c_p100 / c_p0) * 100.0 if c_p0 > 0 else 100.0

        # Points percentiles
        p_p0 = int(np.min(pts_arr)) if pts_arr is not None and len(pts_arr) > 0 else None
        p_p10 = int(np.percentile(pts_arr, 10)) if pts_arr is not None and len(pts_arr) > 0 else None
        p_p50 = int(np.percentile(pts_arr, 50)) if pts_arr is not None and len(pts_arr) > 0 else None
        p_p90 = int(np.percentile(pts_arr, 90)) if pts_arr is not None and len(pts_arr) > 0 else None
        p_p100 = int(np.max(pts_arr)) if pts_arr is not None and len(pts_arr) > 0 else None

        # Valuation percentiles (IDR / pt)
        v_p0 = float(np.min(val_arr)) if val_arr is not None and len(val_arr) > 0 else None
        v_p10 = float(np.percentile(val_arr, 10)) if val_arr is not None and len(val_arr) > 0 else None
        v_p50 = float(np.percentile(val_arr, 50)) if val_arr is not None and len(val_arr) > 0 else None
        v_p90 = float(np.percentile(val_arr, 90)) if val_arr is not None and len(val_arr) > 0 else None
        v_p100 = float(np.max(val_arr)) if val_arr is not None and len(val_arr) > 0 else None

        c.execute("""
            INSERT OR REPLACE INTO property_baselines (
                room_id, cash_p0, cash_p10, cash_p50, cash_p90, cash_p100,
                points_p0, points_p10, points_p50, points_p90, points_p100,
                val_p0, val_p10, val_p50, val_p90, val_p100,
                avg_cash_rate, ceiling_surge_pct, sample_count, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            room_id, c_p0, c_p10, c_p50, c_p90, c_p100,
            p_p0, p_p10, p_p50, p_p90, p_p100,
            v_p0, v_p10, v_p50, v_p90, v_p100,
            avg_cash, surge_pct, len(rows), now_str
        ))
        updated_count += 1

    conn.commit()

    # 3. Create brand composite summary table
    c.execute("""
        CREATE TABLE IF NOT EXISTS brand_composites (
            brand VARCHAR(32) NOT NULL PRIMARY KEY,
            cash_p0 FLOAT NOT NULL,
            cash_p10 FLOAT NOT NULL,
            cash_p50 FLOAT NOT NULL,
            cash_p90 FLOAT NOT NULL,
            cash_p100 FLOAT NOT NULL,
            val_p0 FLOAT,
            val_p10 FLOAT,
            val_p50 FLOAT,
            val_p90 FLOAT,
            val_p100 FLOAT,
            hotel_count INTEGER NOT NULL,
            rate_count INTEGER NOT NULL,
            updated_at DATETIME
        )
    """)

    c.execute("""
        SELECT h.brand, r.cash_rate, r.points_required 
        FROM rate_records r
        JOIN room_categories rc ON r.room_id = rc.id
        JOIN hotels h ON rc.hotel_id = h.id
    """)
    brand_data = {}
    for brand, cash, pts in c.fetchall():
        if brand not in brand_data:
            brand_data[brand] = {'cash': [], 'val': [], 'hotels': set()}
        if cash is not None and cash > 0:
            brand_data[brand]['cash'].append(cash)
            if pts and pts > 0:
                brand_data[brand]['val'].append(cash / pts)

    for brand, d in brand_data.items():
        if not d['cash']:
            continue
        c_arr = np.array(d['cash'])
        v_arr = np.array(d['val']) if d['val'] else None
        
        c.execute("SELECT count(DISTINCT h.id) FROM hotels h WHERE h.brand = ?", (brand,))
        h_cnt = c.fetchone()[0]

        c.execute("""
            INSERT OR REPLACE INTO brand_composites (
                brand, cash_p0, cash_p10, cash_p50, cash_p90, cash_p100,
                val_p0, val_p10, val_p50, val_p90, val_p100,
                hotel_count, rate_count, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            brand,
            float(np.min(c_arr)), float(np.percentile(c_arr, 10)), float(np.percentile(c_arr, 50)), float(np.percentile(c_arr, 90)), float(np.max(c_arr)),
            float(np.min(v_arr)) if v_arr is not None and len(v_arr) > 0 else None,
            float(np.percentile(v_arr, 10)) if v_arr is not None and len(v_arr) > 0 else None,
            float(np.percentile(v_arr, 50)) if v_arr is not None and len(v_arr) > 0 else None,
            float(np.percentile(v_arr, 90)) if v_arr is not None and len(v_arr) > 0 else None,
            float(np.max(v_arr)) if v_arr is not None and len(v_arr) > 0 else None,
            h_cnt, len(c_arr), now_str
        ))

    conn.commit()
    conn.close()
    logger.info(f"✅ Successfully updated empirical baselines for {updated_count} rooms and {len(brand_data)} brand composites.")

if __name__ == "__main__":
    update_property_and_brand_baselines()
