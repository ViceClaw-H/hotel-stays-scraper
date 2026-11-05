import os
import sys
import json
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COOKIE_DIR = os.path.join(ROOT, "crawlers", "pw_hilton_session")
COOKIE_FILE = os.path.join(COOKIE_DIR, "hilton_cookies.json")
os.makedirs(COOKIE_DIR, exist_ok=True)

def import_cookies_from_text(cookie_str: str):
    """
    Parses cookies from:
    1. Raw document.cookie string (key=value; key2=value2...)
    2. JSON array from Cookie-Editor / EditThisCookie
    3. Netscape/curl cookie format
    Saves directly to crawlers/pw_hilton_session/hilton_cookies.json
    """
    cookie_str = cookie_str.strip()
    if not cookie_str:
        print("[ERROR] Teks cookie kosong!")
        return False
        
    pw_cookies = []
    
    # Try parsing as JSON first
    if cookie_str.startswith("[") and cookie_str.endswith("]"):
        try:
            raw_list = json.loads(cookie_str)
            for item in raw_list:
                c = {
                    "name": item.get("name"),
                    "value": item.get("value"),
                    "domain": item.get("domain", ".hilton.com"),
                    "path": item.get("path", "/"),
                }
                if "secure" in item:
                    c["secure"] = item["secure"]
                if "httpOnly" in item:
                    c["httpOnly"] = item["httpOnly"]
                pw_cookies.append(c)
        except Exception as e:
            print(f"[WARN] Bukan format JSON valid ({e}), mencoba format raw string...")
            
    # Fallback to key=val; key=val string
    if not pw_cookies:
        pairs = [p.strip() for p in cookie_str.split(";") if p.strip()]
        for p in pairs:
            if "=" in p:
                k, v = p.split("=", 1)
                pw_cookies.append({
                    "name": k.strip(),
                    "value": v.strip(),
                    "domain": ".hilton.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": False
                })
                
    if not pw_cookies:
        print("[ERROR] Tidak dapat mendeteksi cookies dari input.")
        return False
        
    with open(COOKIE_FILE, "w", encoding="utf-8") as f:
        json.dump(pw_cookies, f, indent=2)
        
    akamai = [c["name"] for c in pw_cookies if any(x in c["name"].lower() for x in ["_abck", "bm_sz", "ak_bmsc"])]
    print("\n" + "=" * 65)
    print(f" [BERHASIL] {len(pw_cookies)} cookies berhasil disimpan ke:")
    print(f"  {COOKIE_FILE}")
    print(f"  Token Akamai terdeteksi: {akamai}")
    print("=" * 65 + "\n")
    return True

if __name__ == "__main__":
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            content = f.read()
        import_cookies_from_text(content)
    else:
        print("=" * 65)
        print("  HILTON MANUAL COOKIE IMPORTER")
        print("=" * 65)
        print("Buka Chrome biasa Anda -> hilton.com -> Buka Console (F12) -> Ketik:")
        print("  copy(document.cookie)")
        print("Lalu paste teksnya di sini (tekan Enter 2x setelah selesai):")
        print("-" * 65)
        lines = []
        try:
            while True:
                line = input()
                if not line and lines:
                    break
                lines.append(line)
        except EOFError:
            pass
        raw = "\n".join(lines)
        if raw.strip():
            import_cookies_from_text(raw)
        else:
            print("[INFO] Tidak ada input yang dimasukkan.")
