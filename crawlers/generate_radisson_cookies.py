"""
Radisson Hotel Group Session & Akamai Cookie Generator
Clean, robust, user-friendly tool to acquire and refresh valid session cookies for Radisson crawlers.
"""
import os
import sys
import json
import time
import threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COOKIE_DIR = os.path.join(ROOT, "crawlers", "pw_radisson_session")
COOKIE_FILE = os.path.join(COOKIE_DIR, "radisson_cookies.json")
PROFILE_DIR = os.path.join(COOKIE_DIR, "generator_profile")
os.makedirs(COOKIE_DIR, exist_ok=True)
os.makedirs(PROFILE_DIR, exist_ok=True)

CHROME_CANDIDATES = [
    os.environ.get("CHROME_BIN") or "",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
]
CHROME_BIN = next((p for p in CHROME_CANDIDATES if p and os.path.exists(p)), None)


def run_generator():
    print("=" * 70)
    print("       RADISSON HOTEL GROUP SESSION COOKIE GENERATOR")
    print("=" * 70)
    print(f"Browser Engine : {'Google Chrome' if 'chrome' in (CHROME_BIN or '').lower() else 'System Browser'}")
    print(f"Target Output  : {COOKIE_FILE}")
    print("=" * 70)
    
    user_confirmed = threading.Event()
    
    def wait_for_user_enter():
        try:
            input("\n>> Tekan [ENTER] kapan saja di sini jika halaman sudah selesai loading di browser...\n")
            user_confirmed.set()
        except Exception:
            pass

    t_enter = threading.Thread(target=wait_for_user_enter, daemon=True)
    t_enter.start()

    with sync_playwright() as p:
        print("\n[1/3] Meluncurkan browser di layar desktop...")
        channel = "chrome" if (CHROME_BIN and "chrome.exe" in CHROME_BIN.lower()) else "msedge" if (CHROME_BIN and "msedge.exe" in CHROME_BIN.lower()) else None
        
        context = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=False,
            channel=channel,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-default-browser-check",
                "--start-maximized"
            ],
            viewport=None,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="en-US"
        )
        
        page = context.pages[0] if context.pages else context.new_page()
        
        target_url = "https://www.radissonhotels.com/en-us"
        print(f"[2/3] Membuka halaman Radisson: {target_url}")
        try:
            page.goto(target_url, timeout=45000, wait_until="domcontentloaded")
        except Exception as e:
            print(f"[!] Navigasi: {e}")
            
        print("\n" + "-" * 70)
        print(" PETUNJUK:")
        print(" 1. Jika muncul banner 'Accept All Cookies', silakan klik Accept.")
        print(" 2. Jika muncul verifikasi Akamai / Cloudflare, selesaikan di layar.")
        print(" 3. Script ini mendeteksi cookies secara otomatis setiap 2 detik.")
        print("    ATAU tekan [ENTER] pada terminal ini begitu halaman Radisson tampil normal.")
        print("-" * 70)
        
        captured_cookies = []
        max_wait = 60
        start_t = time.time()
        
        while time.time() - start_t < max_wait:
            cookies = context.cookies()
            c_dict = {c['name']: c['value'] for c in cookies}
            
            # Check for critical Akamai session cookies
            has_abck = "_abck" in c_dict and len(c_dict["_abck"]) > 20
            has_bm = any(k in c_dict for k in ["bm_sz", "bm_s", "ak_bmsc"])
            
            if (has_abck and has_bm) or user_confirmed.is_set():
                captured_cookies = cookies
                print("\n[+] Sesi dan Cookie Akamai Radisson berhasil terdeteksi!")
                break
                
            time.sleep(2)
            
        if not captured_cookies:
            captured_cookies = context.cookies()
            
        print(f"\n[3/3] Menyimpan {len(captured_cookies)} cookies ke {COOKIE_FILE}...")
        with open(COOKIE_FILE, "w", encoding="utf-8") as f:
            json.dump(captured_cookies, f, indent=2)
            
        print("\n" + "=" * 70)
        print(" [SUKSES] Cookie Radisson berhasil diperbarui!")
        print(f" File tersimpan di: {COOKIE_FILE}")
        print("=" * 70 + "\n")
        
        context.close()

if __name__ == "__main__":
    run_generator()
