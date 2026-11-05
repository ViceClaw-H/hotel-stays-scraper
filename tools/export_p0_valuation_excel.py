#!/usr/bin/env python3
"""Export Hotel P0 Cash Baselines and Points Valuations to CSV."""
import os
import sys
import sqlite3
import csv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "hotel_stays.db")
OUT_CSV = os.path.join(ROOT, "hotel_p0_valuation_export.csv")

def main():
    print(f"Connecting to database: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    query = """
        SELECT 
            h.brand,
            h.name as hotel_name,
            h.city,
            h.country,
            rc.raw_name as room_name,
            rc.standardized_type as room_class,
            pb.p0_cash,
            pb.p50_cash,
            pb.p100_cash,
            pb.currency,
            pb.median_points,
            pb.points_valuation_cents_per_pt,
            pb.rate_count
        FROM property_baselines pb
        JOIN room_categories rc ON rc.id = pb.room_id
        JOIN hotels h ON h.id = rc.hotel_id
        ORDER BY h.brand, h.country, h.name
    """
    
    rows = cur.execute(query).fetchall()
    conn.close()
    
    headers = [
        "Brand", "Hotel Name", "City", "Country", "Room Name", "Room Class",
        "P0 Cash Floor", "P50 Cash Median", "P100 Cash Ceiling", "Currency",
        "Median Points", "Points Valuation (cents/pt)", "Sample Rates Count"
    ]
    
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
        
    print(f"Exported {len(rows):,} baseline valuation records to: {OUT_CSV}")

if __name__ == "__main__":
    main()
