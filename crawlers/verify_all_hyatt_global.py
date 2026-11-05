"""Live HTTP Verifier for ALL 229 Hyatt Hotels Globally.
Checks every Hyatt hotel URL in the database and reports HTTP 200 OK vs 404.
"""
import sys
import asyncio
import sqlite3
import httpx

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = "hotel_stays.db"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

async def check_hyatt_url(client: httpx.AsyncClient, semaphore: asyncio.Semaphore, hid: str, name: str, country: str, url: str):
    async with semaphore:
        if not url or not url.startswith("http"):
            return {"id": hid, "name": name, "country": country, "url": url, "status": "NO_URL", "valid": False}

        try:
            resp = await client.get(url, headers=HEADERS, follow_redirects=True, timeout=10.0)
            status_code = resp.status_code
            is_valid = (200 <= status_code < 400)
            return {
                "id": hid,
                "name": name,
                "country": country,
                "url": url,
                "status": f"HTTP {status_code}",
                "valid": is_valid
            }
        except Exception as e:
            return {
                "id": hid,
                "name": name,
                "country": country,
                "url": url,
                "status": "TIMEOUT/ERR",
                "valid": False
            }

async def run_hyatt_verification():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    hyatt_hotels = c.execute("SELECT id, name, country, official_url FROM hotels WHERE brand = 'HYATT' ORDER BY country, name").fetchall()
    conn.close()

    print("\n=======================================================")
    print(f"[*] Memulai Verifikasi HTTP Live untuk Seluruh {len(hyatt_hotels)} Hotel Hyatt Global")
    print("=======================================================\n")

    semaphore = asyncio.Semaphore(15)
    async with httpx.AsyncClient(verify=False) as client:
        tasks = [
            check_hyatt_url(client, semaphore, hid, name, country, url)
            for hid, name, country, url in hyatt_hotels
        ]
        results = await asyncio.gather(*tasks)

    valid_list = [r for r in results if r["valid"]]
    failed_list = [r for r in results if not r["valid"]]

    print("=== SAMPEL HASIL BERHASIL (200 OK) ===")
    for r in valid_list[:15]:
        print(f"[OK]   {r['name'][:35]:<35} ({r['country']}) | {r['status']} | {r['url']}")

    print("\n=== SAMPEL HASIL GAGAL (404 / FORMAT LAMA) ===")
    for r in failed_list[:15]:
        print(f"[FAIL] {r['name'][:35]:<35} ({r['country']}) | {r['status']} | {r['url']}")

    print(f"\n-------------------------------------------------------")
    print(f"Total Hotel Hyatt Global: {len(results)}")
    print(f"✅ Valid (HTTP 200 OK): {len(valid_list)} ({len(valid_list)/len(results)*100:.1f}%)")
    print(f"❌ Perlu Perbaikan Property Code: {len(failed_list)}")
    print(f"-------------------------------------------------------\n")

if __name__ == "__main__":
    asyncio.run(run_hyatt_verification())
