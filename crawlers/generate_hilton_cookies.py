"""
Hilton Honors Session & Akamai Cookie Generator (From Scratch V2)
Clean, robust, user-friendly tool to acquire and refresh valid session cookies for Hilton crawlers.
"""
import os
import sys
import json
import time
import threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COOKIE_DIR = os.path.join(ROOT, "crawlers", "pw_hilton_session")
COOKIE_FILE = os.path.join(COOKIE_DIR, "hilton_cookies.json")
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
    print("       HILTON HONORS SESSION COOKIE GENERATOR (V2)")
    print("=" * 70)
    print(f"Browser Engine : {'Google Chrome' if 'chrome' in (CHROME_BIN or '').lower() else 'System Browser'}")
    print(f"Target Output  : {COOKIE_FILE}")
    print("=" * 70)
    
    stop_event = threading.Event()
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
        print("\n[1/3] Meluncurkan browser di layar...")
        channel = "chrome" if (CHROME_BIN and "chrome.exe" in CHROME_BIN.lower()) else "msedge" if (CHROME_BIN and "msedge.exe" in CHROME_BIN.lower()) else None
        
        # Use persistent context with user data dir so sessions and tokens persist naturally
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
        
        target_url = "https://www.hilton.com/en/"
        print(f"[2/3] Membuka halaman Hilton: {target_url}")
        try:
            page.goto(target_url, timeout=45000, wait_until="domcontentloaded")
        except Exception as e:
            print(f"[!] Navigasi: {e}")
            
        print("\n" + "-" * 70)
        print(" PETUNJUK:")
        print(" 1. Jika muncul banner 'Accept All Cookies', silakan klik Accept.")
        print(" 2. Jika muncul verifikasi Akamai (kotak verifikasi / Press & Hold), selesaikan di layar.")
        print(" 3. Script ini mendeteksi cookies secara otomatis setiap 2 detik.")
        print("    ATAU tekan [ENTER] pada terminal ini begitu halaman utama Hilton tampil normal.")
        print("-" * 70 + "\n")
        
        # Monitoring loop: check for cookies and non-block title
        cookies_saved = False
        start_time = time.time()
        
        while time.time() - start_time < 90:  # Maximum 90 seconds wait
            time.sleep(2.0)
            
            # Check user enter trigger
            if user_confirmed.is_set():
                print("[*] Konfirmasi [ENTER] diterima dari pengguna!")
                break
                
            try:
                title = page.title()
                current_cookies = context.cookies()
                abck = next((c for c in current_cookies if c["name"] == "_abck"), None)
                
                # Check cookie banner button and click if found
                try:
                    btn = page.query_selector("#onetrust-accept-btn-handler, button:has-text('Accept All')")
                    if btn and btn.is_visible():
                        print("[*] Mengklik banner cookie consent otomatis...")
                        btn.click()
                        time.sleep(1.0)
                except Exception:
                    pass

                # If title is normal (not blocked) and cookies are present
                if "Reference Code" not in title and "Access Denied" not in title and len(current_cookies) > 10:
                    # Check if akamai cookie is verified (~0) or present
                    if abck:
                        val = abck["value"]
                        if "~0~" in val or val.endswith("~0"):
                            print(f"[+] Akamai Verified Token terdeteksi (~0)! Judul: {title[:40]}")
                            cookies_saved = True
                            break
                        else:
                            print(f"[*] Menunggu Akamai token menyelesaikan validasi (saat ini: ~-1)...")
                    else:
                        print(f"[*] Terdeteksi {len(current_cookies)} cookies. Halaman: {title[:40]}")
                        if len(current_cookies) >= 15:
                            # Let sensor finish
                            time.sleep(3.0)
                            cookies_saved = True
                            break
            except Exception as e:
                pass

        # Extract final cookies
        final_cookies = context.cookies()
        if final_cookies:
            with open(COOKIE_FILE, "w", encoding="utf-8") as f:
                json.dump(final_cookies, f, indent=2)
                
            akamai_names = [c["name"] for c in final_cookies if any(x in c["name"].lower() for x in ["_abck", "bm_sz", "ak_bmsc"])]
            print("\n" + "=" * 70)
            print(f" [BERHASIL] {len(final_cookies)} session cookies berhasil disimpan!")
            print(f" File Tujuan     : {COOKIE_FILE}")
            print(f" Akamai Tokens   : {akamai_names}")
            print(" Scraper Hilton kini siap dijalankan tanpa hambatan Akamai.")
            print("=" * 70 + "\n")
        else:
            print("\n[ERROR] Tidak ada cookies yang tertangkap. Silakan coba lagi.\n")

        try:
            context.close()
        except Exception:
            pass

if __name__ == "__main__":
    run_generator()
