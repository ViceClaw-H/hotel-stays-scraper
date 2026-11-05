import sqlite3

conn = sqlite3.connect('hotel_stays.db')
c = conn.cursor()

# 1. Purge all formula-generated rates, baselines, and composite calculations
c.execute("DELETE FROM rate_records")
c.execute("DELETE FROM room_categories")
c.execute("DELETE FROM property_baselines")
c.execute("DELETE FROM brand_composites")

# 2. Clean out any non-hotel links scraped into hotels table
c.execute("""
    DELETE FROM hotels 
    WHERE official_url LIKE '%terms-and-conditions%' 
       OR official_url LIKE '%privacy%' 
       OR official_url LIKE '%cookie%'
       OR LOWER(name) LIKE '%terms and conditions%' 
       OR LOWER(name) LIKE '%privacy policy%'
       OR LOWER(name) LIKE '%cookie policy%'
""")

conn.commit()

print("=" * 60)
print("STATUS DATABASE SETELAH PEMBERSIHAN TOTAL")
print("=" * 60)
for table in ['hotels', 'room_categories', 'rate_records', 'property_baselines', 'brand_composites']:
    cnt = c.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    print(f"Table '{table}': {cnt:,} rows")
print("=" * 60)

conn.close()
