import sqlite3

conn = sqlite3.connect("hotel_stays.db")
c = conn.cursor()
c.execute("""
    SELECT country, hotel_count, rate_count, val_p10, val_p50, val_p90, avg_cpp
    FROM country_composites
    WHERE country IN ('Indonesia', 'Japan', 'United States', 'Singapore', 'Thailand', 'United Kingdom', 'France', 'Australia', 'Malaysia', 'China')
    ORDER BY hotel_count DESC
""")

print(f"{'Country':<16} | {'Hotels':<6} | {'Rates':<8} | {'P10 (CPP)':<9} | {'P50 (CPP)':<9} | {'P90 (CPP)':<9} | {'Avg CPP':<8}")
print("-" * 80)
for r in c.fetchall():
    print(f"{r[0]:<16} | {r[1]:<6} | {r[2]:<8} | {r[3]:<9.2f} | {r[4]:<9.2f} | {r[5]:<9.2f} | {r[6]:<8.2f}")

conn.close()
