"""
All Hotel Stays - Core Catalog & Scraped Links Exporter
Unified export utility fixing legacy hardcoded paths.
Exports 48,310+ hotel catalog status to All_Hotel_Scraped_Links.xlsx.
"""

import sqlite3
import pandas as pd
import time
import os

def export_catalog_to_excel(db_path: str = None, output_path: str = None) -> str:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if db_path is None:
        db_path = os.path.join(base_dir, "hotel_stays.db")
    if output_path is None:
        output_path = os.path.join(base_dir, "All_Hotel_Scraped_Links.xlsx")
        
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found at: {db_path}")

    print(f"[INFO] Fetching hotel catalog from: {db_path}")
    t0 = time.time()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # 1. Get scraped counts
    cur.execute("""
        SELECT rc.hotel_id, count(rr.id) as rate_count
        FROM room_categories rc
        JOIN rate_records rr ON rc.id = rr.room_id
        GROUP BY rc.hotel_id
    """)
    rate_counts = dict(cur.fetchall())

    # 2. Check harvest_status OK
    try:
        cur.execute("SELECT hotel_id FROM harvest_status WHERE status = 'OK'")
        hs_ok_ids = set(r[0] for r in cur.fetchall())
    except Exception:
        hs_ok_ids = set()

    # 3. Get all hotels
    cur.execute("SELECT id, brand, name, official_url, city, country FROM hotels ORDER BY brand, name")
    all_hotels = cur.fetchall()

    scraped_rows = []
    all_rows = []

    for h_id, brand, name, url, city, country in all_hotels:
        is_scraped = (h_id in rate_counts) or (h_id in hs_ok_ids)
        n_rates = rate_counts.get(h_id, 0)
        status_str = "SCRAPED" if is_scraped else "PENDING"
        
        row_dict = {
            "Brand": brand,
            "Link": url,
            "Hotel Name": name,
            "City": city,
            "Country": country,
            "Status": status_str,
            "Rates Recorded": n_rates
        }
        all_rows.append(row_dict)
        if is_scraped:
            scraped_rows.append(row_dict)

    # Summary by brand
    brands = sorted(list(set(h[1] for h in all_hotels)))
    summary_data = []
    for b in brands:
        tot = sum(1 for r in all_rows if r["Brand"] == b)
        sc = sum(1 for r in scraped_rows if r["Brand"] == b)
        pct = round(sc / tot * 100, 1) if tot > 0 else 0
        tot_rates = sum(r["Rates Recorded"] for r in all_rows if r["Brand"] == b)
        summary_data.append({
            "Brand": b,
            "Scraped Hotels": sc,
            "Total Hotels": tot,
            "Progress (%)": f"{pct}%",
            "Total Rates Recorded": tot_rates,
            "Status": "COMPLETED" if pct >= 95 else "IN PROGRESS"
        })

    tot_cat = len(all_rows)
    tot_sc = len(scraped_rows)
    tot_all_rates = sum(r["Rates Recorded"] for r in all_rows)
    summary_data.append({
        "Brand": "TOTAL",
        "Scraped Hotels": tot_sc,
        "Total Hotels": tot_cat,
        "Progress (%)": f"{round(tot_sc/tot_cat*100, 1)}%",
        "Total Rates Recorded": tot_all_rates,
        "Status": f"{tot_sc:,} / {tot_cat:,} ({round(tot_sc/tot_cat*100, 1)}%)"
    })

    df_summary = pd.DataFrame(summary_data)
    df_scraped = pd.DataFrame(scraped_rows)
    df_all = pd.DataFrame(all_rows)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df_summary.to_excel(writer, sheet_name="Summary by Brand", index=False)
        df_scraped.to_excel(writer, sheet_name="Scraped Hotel Links", index=False)
        df_all.to_excel(writer, sheet_name="All Hotels Catalog", index=False)

    print(f"[SUCCESS] Export completed in {time.time()-t0:.2f}s: {output_path}")
    conn.close()
    return output_path

if __name__ == "__main__":
    export_catalog_to_excel()
