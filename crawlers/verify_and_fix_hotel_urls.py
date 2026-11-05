"""High-Performance Asynchronous Hotel URL Live HTTP Verifier.
Pings hotel official booking URLs in real-time to verify HTTP 200 OK status.
Uses realistic browser headers and records authentic HTTP response codes.
"""
import sys
import asyncio
import sqlite3
import httpx
from datetime import datetime

# Configure standard output to UTF-8 for Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = "hotel_stays.db"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
}

async def check_url(client: httpx.AsyncClient, semaphore: asyncio.Semaphore, hid: str, brand: str, name: str, url: str):
    async with semaphore:
        if not url or not url.startswith("http"):
            return {
                "id": hid,
                "brand": brand,
                "name": name,
                "url": url,
                "status": "NO_URL",
                "code": 0,
                "final_url": "",
                "valid": False
            }

        try:
            resp = await client.get(url, headers=HEADERS, follow_redirects=True, timeout=12.0)
            status_code = resp.status_code
            final_url = str(resp.url)
            
            is_valid = (200 <= status_code < 400)
            return {
                "id": hid,
                "brand": brand,
                "name": name,
                "url": url,
                "status": f"HTTP {status_code}",
                "code": status_code,
                "final_url": final_url,
                "valid": is_valid
            }
        except httpx.TimeoutException:
            return {
                "id": hid,
                "brand": brand,
                "name": name,
                "url": url,
                "status": "TIMEOUT",
                "code": 408,
                "final_url": url,
                "valid": False
            }
        except Exception as e:
            return {
                "id": hid,
                "brand": brand,
                "name": name,
                "url": url,
                "status": f"ERR: {str(e)[:20]}",
                "code": 500,
                "final_url": url,
                "valid": False
            }

async def verify_hotels(country="Indonesia", limit=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    if country:
        query = "SELECT id, brand, name, official_url FROM hotels WHERE country = ? ORDER BY brand, name"
        params = (country,)
    else:
        query = "SELECT id, brand, name, official_url FROM hotels ORDER BY brand, name"
        params = ()

    if limit:
        query += f" LIMIT {limit}"

    hotels = c.execute(query, params).fetchall()
    conn.close()

    print("\n=======================================================")
    print(f"[*] Memulai Verifikasi HTTP Live untuk {len(hotels)} Hotel ({country or 'Global'})")
    print("=======================================================\n")

    semaphore = asyncio.Semaphore(15)
    
    async with httpx.AsyncClient(verify=False) as client:
        tasks = [
            check_url(client, semaphore, hid, brand, name, url)
            for hid, brand, name, url in hotels
        ]
        results = await asyncio.gather(*tasks)

    valid_count = sum(1 for r in results if r["valid"])
    failed_count = len(results) - valid_count

    print("\n=== HASIL VERIFIKASI HTTP RESMI HOTEL ===")
    for r in results:
        icon = "[OK]" if r["valid"] else "[FAIL]"
        print(f"{icon} [{r['brand']:<8}] {r['name'][:38]:<38} | {r['status']:<10} | {r['url']}")

    print(f"\n-------------------------------------------------------")
    print(f"Total Diverifikasi: {len(results)}")
    print(f"Berhasil (200 OK / Valid): {valid_count} ({valid_count/len(results)*100:.1f}%)")
    print(f"Gagal (404 / Error / Timeout): {failed_count}")
    print(f"-------------------------------------------------------\n")

    return results

if __name__ == "__main__":
    asyncio.run(verify_hotels(country="Indonesia"))
