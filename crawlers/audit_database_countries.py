import sqlite3

def audit():
    conn = sqlite3.connect('hotel_stays.db')
    c = conn.cursor()

    brands = ['ACCOR', 'GHA', 'HILTON', 'HYATT', 'IHG', 'LANGHAM', 'MARRIOTT', 'SHANGRI-LA', 'WYNDHAM']

    for b in brands:
        print(f"\n==================== BRAND: {b} ====================")
        c.execute("SELECT COUNT(*) FROM hotels WHERE brand = ?", (b,))
        total = c.fetchone()[0]
        print(f"Total Hotels: {total}")
        
        c.execute("SELECT country, COUNT(*) FROM hotels WHERE brand = ? GROUP BY country ORDER BY COUNT(*) DESC LIMIT 10", (b,))
        top_countries = c.fetchall()
        print("Top Countries:")
        for cntry, count in top_countries:
            print(f"  - {cntry}: {count}")

        c.execute("SELECT id, name, city, country, official_url FROM hotels WHERE brand = ? LIMIT 3", (b,))
        print("Sample Hotels:")
        for r in c.fetchall():
            print(f"  [{r[0]}] {r[1]} | {r[2]}, {r[3]} -> {r[4]}")

    conn.close()

if __name__ == '__main__':
    audit()
