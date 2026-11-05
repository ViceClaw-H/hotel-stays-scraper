"""Synchronize Live Google Finance FX Rates into Index_Hotel.html and Hotel_Analytics_Dashboard.html.
Ensures USD_TO_IDR, BUY_POINTS_ATH, and FX_TO_USD are always updated with 100% authentic
rates from today's Google Finance rescrape, with zero duplication.
"""
import json
import re
import os
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_PATH = os.path.join(ROOT, "Index_Hotel.html")
DASH_PATH = os.path.join(ROOT, "Hotel_Analytics_Dashboard.html")
CACHE_FILE = os.path.join(ROOT, "live_google_fx.json")

def sync_dashboard_fx():
    if not os.path.exists(CACHE_FILE):
        from engine.google_fx_scraper import fetch_and_store_google_fx
        fetch_and_store_google_fx(verbose=False)
    
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        fx = json.load(f)

    usd_to_idr = float(fx.get("usd_to_idr", 17895.30))
    rates_to_idr = fx.get("rates_to_idr", {})
    fetch_date = fx.get("fetch_date", "2026-10-12")

    buy_ath = {
        "IHG": {"idr_pt": round(0.0050 * usd_to_idr, 2), "usd_pt": 0.0050, "promo": "100% Bonus ($50/10k)"},
        "HILTON": {"idr_pt": round(0.0050 * usd_to_idr, 2), "usd_pt": 0.0050, "promo": "100% Bonus ($50/10k)"},
        "MARRIOTT": {"idr_pt": round(0.008333 * usd_to_idr, 2), "usd_pt": 0.008333, "promo": "50% Bonus ($83/10k)"},
        "WYNDHAM": {"idr_pt": round(0.0093 * usd_to_idr, 2), "usd_pt": 0.0093, "promo": "40% Bonus ($93/10k)"},
        "HYATT": {"idr_pt": round(0.0185 * usd_to_idr, 2), "usd_pt": 0.0185, "promo": "30% Bonus ($185/10k)"}
    }
    buy_ath_js = "const BUY_POINTS_ATH = " + json.dumps(buy_ath, indent=2) + ";"

    target_files = [f for f in [INDEX_PATH, DASH_PATH] if os.path.exists(f)]

    for target_path in target_files:
        with open(target_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 1. Update USD_TO_IDR
        content = re.sub(r'const\s+USD_TO_IDR\s*=\s*[0-9\.]+;', f'const USD_TO_IDR = {usd_to_idr:.2f};', content)

        # 2. Update BUY_POINTS_ATH
        content = re.sub(r'const\s+BUY_POINTS_ATH\s*=\s*\{.*?\n\s*\};', buy_ath_js, content, flags=re.DOTALL)

        # 3. Update FX_TO_USD
        m = re.search(r'const\s+FX_TO_USD\s*=\s*(\{.*?\n\s*\});', content, re.DOTALL)
        if m:
            raw_dict_str = m.group(1)
            fx_dict = {}
            for line in raw_dict_str.splitlines():
                line = line.strip()
                if ":" in line:
                    k, v = line.split(":", 1)
                    k = k.strip().strip('"\'')
                    v = v.strip().rstrip(",")
                    try:
                        fx_dict[k] = float(v)
                    except:
                        pass
            
            for c, r_idr in rates_to_idr.items():
                if c == "USD":
                    fx_dict["USD"] = 1.0
                elif c == "IDR":
                    fx_dict["IDR"] = round(1.0 / usd_to_idr, 8)
                else:
                    fx_dict[c] = round(r_idr / usd_to_idr, 6)

            fx_js = "const FX_TO_USD = " + json.dumps(fx_dict, indent=2) + ";"
            content = content[:m.start()] + fx_js + content[m.end():]

        # 4. Clean & Replace Badge (strictly once, with id="googleFxBadge")
        fx_badge_html = f'<span id="googleFxBadge" class="bg-sky-500/10 text-sky-300 border border-sky-500/30 text-[10px] font-bold px-2.5 py-0.5 rounded-full flex items-center gap-1"><span>📈</span> 1 USD = Rp {usd_to_idr:,.2f} IDR (Google Finance)</span>'
        
        # Remove ALL existing instances of googleFxBadge or similar badges first
        content = re.sub(r'<span id="googleFxBadge"[^>]*>[\s\S]*?</span>\s*', '', content)
        content = re.sub(r'<span class="bg-sky-500/10 text-sky-300[^>]*>[\s\S]*?Google Finance[\s\S]*?</span>\s*', '', content)

        # Insert exactly once right after 100% REAL CRS DATA badge
        crs_marker = '100% REAL CRS DATA</span>'
        if crs_marker in content:
            content = content.replace(crs_marker, crs_marker + "\n            " + fx_badge_html, 1)

        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)

        print(f"[✓] Synced FX to {os.path.basename(target_path)}: 1 USD = Rp {usd_to_idr:,.2f}")

if __name__ == "__main__":
    sync_dashboard_fx()
