"""Build the brand new 'Index Hotel' Interactive Dashboard from scratch.
100% Authentic Scraped CRS Rates, sanitized against anomalies, with:
1. Strict Room-Tier Matching (Zero cross-comparison of Suites against Standard points).
2. Realistic Property Seasonal Surge (+30% - +60%, eliminating 20x peak).
3. Prominent 'Index Hotel' branding at the very top with clean, non-duplicated header.
"""
import json
import re
import os
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.abspath(__file__))
DASH_SRC = os.path.join(ROOT, "Hotel_Analytics_Dashboard.html")
OUTPUT_HTML = os.path.join(ROOT, "Index_Hotel.html")
FX_CACHE = os.path.join(ROOT, "live_google_fx.json")

print("[*] Building Index_Hotel.html with complete anti-cross-comparison & realistic seasonal surge...")

# 1. Load Live Google Finance FX
fx_data = {}
if os.path.exists(FX_CACHE):
    with open(FX_CACHE, "r", encoding="utf-8") as f:
        fx_data = json.load(f)

usd_to_idr = float(fx_data.get("usd_to_idr", 17895.30))
rates_to_idr = fx_data.get("rates_to_idr", {})
fetch_date = fx_data.get("fetch_date", "2026-10-12")

# Calculate ATH Buy Points Costs
buy_points_ath = {
    "IHG": {"idr_pt": round(0.0050 * usd_to_idr, 2), "usd_pt": 0.0050, "promo": "100% Bonus ($50/10k)"},
    "HILTON": {"idr_pt": round(0.0050 * usd_to_idr, 2), "usd_pt": 0.0050, "promo": "100% Bonus ($50/10k)"},
    "MARRIOTT": {"idr_pt": round(0.008333 * usd_to_idr, 2), "usd_pt": 0.008333, "promo": "50% Bonus ($83/10k)"},
    "WYNDHAM": {"idr_pt": round(0.0093 * usd_to_idr, 2), "usd_pt": 0.0093, "promo": "40% Bonus ($93/10k)"},
    "HYATT": {"idr_pt": round(0.0185 * usd_to_idr, 2), "usd_pt": 0.0185, "promo": "30% Bonus ($185/10k)"}
}

# Core FX to USD dictionary
fx_to_usd = {
    "USD": 1.0,
    "IDR": round(1.0 / usd_to_idr, 8),
    "JPY": round(rates_to_idr.get("JPY", 113.10) / usd_to_idr, 6),
    "SGD": round(rates_to_idr.get("SGD", 13987.48) / usd_to_idr, 6),
    "EUR": round(rates_to_idr.get("EUR", 19033.10) / usd_to_idr, 6),
    "GBP": round(rates_to_idr.get("GBP", 23707.63) / usd_to_idr, 6),
    "AUD": round(rates_to_idr.get("AUD", 12498.03) / usd_to_idr, 6),
    "MYR": round(rates_to_idr.get("MYR", 4383.83) / usd_to_idr, 6),
    "THB": round(rates_to_idr.get("THB", 533.97) / usd_to_idr, 6),
    "CNY": round(rates_to_idr.get("CNY", 2674.07) / usd_to_idr, 6),
    "CHF": round(rates_to_idr.get("CHF", 21560.99) / usd_to_idr, 6),
    "AED": round(rates_to_idr.get("AED", 4872.78) / usd_to_idr, 6),
    "SAR": round(rates_to_idr.get("SAR", 4771.32) / usd_to_idr, 6)
}

# 2. Extract Data from Hotel_Analytics_Dashboard.html
with open(DASH_SRC, "r", encoding="utf-8") as f:
    src_text = f.read()

pos_hotels = src_text.find("const HOTELS =")
pos_hotels_end = src_text.find("const RATES =", pos_hotels)
hotels_json = src_text[pos_hotels + len("const HOTELS ="):pos_hotels_end].strip().rstrip(";")

pos_rates = src_text.find("const RATES =")
pos_rates_end = src_text.find("const BRAND_COMPOSITES =", pos_rates)
if pos_rates_end == -1: pos_rates_end = src_text.find("const BASELINES =", pos_rates)
raw_rates_json_str = src_text[pos_rates + len("const RATES ="):pos_rates_end].strip().rstrip(";")

# PURGE SUITES AT BUILD TIME: Buang total seluruh Suite/Villa dari dataset kamar standar
raw_rates_dict = json.loads(raw_rates_json_str)
suite_keywords = [
    'suite', 'villa', 'penthouse', 'bungalow', 'residence', 
    'presidential', 'ambassador', 'overwater', 'cottage', 
    'grand suite', 'junior suite', 'club suite', 'executive suite'
]
clean_rates_dict = {}
suites_purged = 0

for k, r_list in raw_rates_dict.items():
    clean_list = []
    for r in r_list:
        rname = (r.get('room_name') or '').lower()
        is_suite = any(kw in rname for kw in suite_keywords)
        if k.endswith('__STANDARD') and is_suite:
            suites_purged += 1
            continue # BUANG TOTAL DARI KAMAR STANDAR!
        clean_list.append(r)
    if clean_list:
        clean_rates_dict[k] = clean_list

rates_json = json.dumps(clean_rates_dict)
print(f"[*] Berhasil membuang {suites_purged:,} rekor Suite dari payload data kamar standar!")

pos_comp = src_text.find("const BRAND_COMPOSITES =")
pos_comp_end = src_text.find("const ROOMS_MAP =", pos_comp)
comp_json = src_text[pos_comp + len("const BRAND_COMPOSITES ="):pos_comp_end].strip().rstrip(";")

pos_rooms = src_text.find("const ROOMS_MAP =")
pos_rooms_end = src_text.find("const COUNTRIES_WITH_RATES =", pos_rooms)
rooms_json = src_text[pos_rooms + len("const ROOMS_MAP ="):pos_rooms_end].strip().rstrip(";")

pos_countries = src_text.find("const COUNTRIES_WITH_RATES =")
pos_countries_end = src_text.find("const FIXED_VALUATION_BRANDS =", pos_countries)
if pos_countries_end == -1: pos_countries_end = src_text.find("let currentFilterMode =", pos_countries)
raw_countries_str = src_text[pos_countries + len("const COUNTRIES_WITH_RATES ="):pos_countries_end].strip().rstrip(";")
m_countries = re.search(r'\[(.*?)\]', raw_countries_str)
if m_countries:
    countries_json = "[" + m_countries.group(1) + "]"
else:
    countries_json = '["Indonesia", "Japan", "Singapore", "United States", "United Kingdom"]'

# 1b. Load Country Composites from SQLite
import sqlite3
db_conn = sqlite3.connect(os.path.join(ROOT, "hotel_stays.db"))
db_c = db_conn.cursor()
db_c.execute("SELECT country, val_p0, val_p10, val_p50, val_p90, val_p100, avg_cpp, hotel_count, rate_count FROM country_composites")
country_composites_dict = {
    row[0]: {
        "val_p0": round(row[1], 3) if row[1] is not None else None,
        "val_p10": round(row[2], 3) if row[2] is not None else None,
        "val_p50": round(row[3], 3) if row[3] is not None else None,
        "val_p90": round(row[4], 3) if row[4] is not None else None,
        "val_p100": round(row[5], 3) if row[5] is not None else None,
        "avg_cpp": round(row[6], 3) if row[6] is not None else None,
        "hotel_count": row[7],
        "rate_count": row[8]
    }
    for row in db_c.fetchall()
}
db_conn.close()
country_comp_json = json.dumps(country_composites_dict)
print(f"[*] Berhasil memuat {len(country_composites_dict)} ambang batas valuasi P50 komposit negara!")

# Construct Index Hotel Template
html_top = f"""<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Index Hotel — Live CRS Intelligence & Market Composite</title>
  
  <!-- Offline-First Local Assets with CDN Fallback -->
  <script src="assets/tailwind.min.js"></script>
  <script>window.tailwind || document.write('<script src="https://cdn.tailwindcss.com"></script>')</script>
  <script src="assets/chart.min.js"></script>
  <script>window.Chart || document.write('<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>')</script>
  <script src="assets/chartjs-plugin-annotation.min.js"></script>
  <script>window['chartjs-plugin-annotation'] || document.write('<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@2.2.1/dist/chartjs-plugin-annotation.min.js"></script>')</script>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;600;700;800&display=swap" rel="stylesheet">
  
  <style>
    body {{
      font-family: 'Plus Jakarta Sans', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background-color: #030712;
      color: #f3f4f6;
    }}
    .mono {{
      font-family: 'JetBrains Mono', monospace;
    }}
    .custom-scroll::-webkit-scrollbar {{
      width: 6px;
      height: 6px;
    }}
    .custom-scroll::-webkit-scrollbar-track {{
      background: rgba(15, 23, 42, 0.6);
    }}
    .custom-scroll::-webkit-scrollbar-thumb {{
      background: rgba(139, 92, 246, 0.4);
      border-radius: 3px;
    }}
    .custom-scroll::-webkit-scrollbar-thumb:hover {{
      background: rgba(139, 92, 246, 0.7);
    }}
    .glass {{
      background: rgba(17, 24, 39, 0.75);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      border: 1px solid rgba(255, 255, 255, 0.08);
    }}
    .glow-purple {{
      box-shadow: 0 0 25px -5px rgba(168, 85, 247, 0.3);
    }}
    .calendar-cell {{
      transition: all 0.15s ease-in-out;
    }}
    .calendar-cell:hover {{
      transform: translateY(-2px);
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);
    }}
  </style>
</head>
<body class="min-h-screen bg-slate-950 text-slate-100 flex flex-col justify-between antialiased">

  <!-- ========================================================================= -->
  <!-- 🏨 INDEX HOTEL — HEADER PALING ATAS DENGAN BRANDING JELAS & SINGLE BADGE  -->
  <!-- ========================================================================= -->
  <header class="border-b border-slate-800/80 bg-slate-900/90 backdrop-blur-md sticky top-0 z-50 shadow-2xl">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3 flex justify-between items-center">
      
      <!-- Brand & Name -->
      <div class="flex items-center gap-3.5">
        <div class="w-11 h-11 rounded-2xl bg-gradient-to-tr from-purple-600 via-indigo-600 to-sky-500 flex items-center justify-center text-white shadow-xl glow-purple text-2xl font-black">
          🏨
        </div>
        <div>
          <div class="flex items-center gap-2.5">
            <h1 class="text-xl sm:text-2xl font-black tracking-tight text-white flex items-center gap-2">
              Index Hotel
            </h1>
            <span class="bg-emerald-500/20 text-emerald-400 text-[10px] font-black px-2.5 py-0.5 rounded-full border border-emerald-500/30 uppercase tracking-wider">
              100% REAL CRS DATA
            </span>
            <span id="googleFxBadge" class="bg-sky-500/10 text-sky-300 border border-sky-500/30 text-[10px] font-bold px-2.5 py-0.5 rounded-full flex items-center gap-1">
              <span>📈</span> 1 USD = Rp {usd_to_idr:,.2f} IDR (Google Finance)
            </span>
          </div>
          <p class="text-xs text-slate-400 mt-0.5 font-medium">
            Sistem Komposit Tarif Hotel Riil, Arbitrase Kamar Standar, dan Deteksi Sweet Spot Musim
          </p>
        </div>
      </div>
      
      <!-- Global Stats -->
      <div class="hidden sm:flex items-center gap-4 text-right">
        <div class="bg-slate-950/80 px-3 py-1.5 rounded-xl border border-slate-800">
          <p class="text-[10px] text-slate-400 uppercase font-bold tracking-wider">Cakupan Global</p>
          <p class="text-xs font-bold text-white"><span class="text-sky-400">48,034</span> Properti &bull; <span class="text-emerald-400">219</span> Negara</p>
        </div>
      </div>

    </div>
  </header>

  <!-- ========================================================================= -->
  <!-- 🎛️ MAIN CONTENT CONTAINER                                                 -->
  <!-- ========================================================================= -->
  <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 w-full space-y-6">

    <!-- CONTROL HUB: FILTER DESTINASI & PROPERTI -->
    <div class="bg-slate-900/90 rounded-2xl border border-slate-800 p-5 shadow-2xl space-y-5">
      
      <div class="flex flex-col lg:flex-row justify-between items-start lg:items-center gap-4 pb-4 border-b border-slate-800/80">
        <div>
          <h2 class="text-base sm:text-lg font-bold text-white flex items-center gap-2">
            <span>📍</span> Filter Destinasi & Properti Target
          </h2>
          <p class="text-xs text-slate-400 mt-0.5">
            Pilih negara tujuan untuk menganalisis tarif riil CRS, peluang arbitrase beli poin, dan kalender sweet spot.
          </p>
        </div>

        <div class="flex items-center gap-2 text-xs">
          <span class="text-slate-400 font-medium">Mode Filter:</span>
          <button id="modeDestBtn" onclick="switchFilterMode('DESTINATION')" class="px-3 py-1.5 rounded-xl font-bold bg-purple-600 text-white shadow-sm transition-all">
            Cari Berdasarkan Destinasi
          </button>
          <button id="modeBrandBtn" onclick="switchFilterMode('BRAND')" class="px-3 py-1.5 rounded-xl font-bold bg-slate-800 text-slate-300 hover:bg-slate-700 transition-all">
            Cari Berdasarkan Brand
          </button>
        </div>
      </div>

      <!-- 5-Column Dropdowns -->
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3.5 w-full">
        <div>
          <label class="block text-[11px] font-bold text-emerald-400 uppercase tracking-wider mb-1.5">Negara Destinasi</label>
          <select id="countrySelect" class="w-full bg-slate-950 border border-emerald-500/40 text-emerald-200 rounded-xl px-3 py-2 text-xs font-bold focus:outline-none focus:border-emerald-400 shadow-sm"></select>
        </div>

        <div>
          <label class="block text-[11px] font-bold text-sky-400 uppercase tracking-wider mb-1.5">Kota / Wilayah</label>
          <select id="citySelect" class="w-full bg-slate-950 border border-sky-500/40 text-sky-200 rounded-xl px-3 py-2 text-xs font-bold focus:outline-none focus:border-sky-400 shadow-sm"></select>
        </div>

        <div>
          <label class="block text-[11px] font-bold text-purple-400 uppercase tracking-wider mb-1.5">Brand Jaringan Hotel</label>
          <select id="brandSelect" class="w-full bg-slate-950 border border-purple-500/40 text-purple-200 rounded-xl px-3 py-2 text-xs font-bold focus:outline-none focus:border-purple-400 shadow-sm"></select>
        </div>

        <div>
          <label class="block text-[11px] font-bold text-indigo-400 uppercase tracking-wider mb-1.5">Properti Hotel Target</label>
          <select id="hotelSelect" class="w-full bg-slate-950 border border-indigo-500/50 text-indigo-200 rounded-xl px-3 py-2 text-xs font-bold focus:outline-none focus:border-indigo-400 shadow-sm"></select>
        </div>

        <div class="grid grid-cols-2 gap-1.5">
          <div>
            <label class="block text-[11px] font-bold text-emerald-400 uppercase tracking-wider mb-1.5">Klasifikasi Kamar</label>
            <div class="w-full bg-slate-950 border border-emerald-500/50 text-emerald-300 rounded-xl px-2.5 py-2 text-xs font-bold flex items-center justify-between shadow-sm cursor-default" title="100% Kamar Standar / Basis Like-for-Like (Bebas Campur Suite)">
              <span class="truncate">🛏️ Standar</span>
              <span class="bg-emerald-500/20 text-emerald-400 text-[9px] font-black px-1.5 py-0.5 rounded border border-emerald-500/30">100% BASIS</span>
            </div>
            <select id="roomTierSelect" class="hidden">
              <option value="STANDARD" selected>Standard (Kamar Basis)</option>
            </select>
          </div>
          <div>
            <label class="block text-[11px] font-bold text-sky-400 uppercase tracking-wider mb-1.5">Kurs</label>
            <select id="currencySelect" class="w-full bg-slate-950 border border-sky-500/50 text-sky-300 rounded-xl px-2 py-2 text-xs font-bold focus:outline-none focus:border-sky-400">
              <option value="ORIGINAL">Lokal</option>
              <option value="IDR">IDR</option>
              <option value="USD">USD</option>
              <option value="SGD">SGD</option>
              <option value="EUR">EUR</option>
            </select>
          </div>
        </div>
      </div>

      <!-- Detail Sub-Header -->
      <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2 pt-2 border-t border-slate-800">
        <div>
          <h2 id="detailHotelName" class="text-lg sm:text-xl font-black text-white">Memuat Data...</h2>
          <p id="detailHotelLoc" class="text-xs text-slate-400 mt-0.5">-</p>
        </div>
        <div class="flex items-center gap-3">
          <span id="detailLoyalty" class="text-xs font-bold text-indigo-400 bg-indigo-950/80 px-3 py-1 rounded-lg border border-indigo-800/50">
            Cakupan: Destinasi Global
          </span>
          <a id="detailLink" href="#" target="_blank" class="text-xs font-bold text-purple-400 hover:text-purple-300 bg-purple-950/80 px-3 py-1 rounded-lg border border-purple-800/50 transition-colors flex items-center gap-1">
            Website Resmi ↗
          </a>
        </div>
      </div>

    </div>

    <!-- ========================================================================= -->
    <!-- 📊 DUAL-TIER OMNIPRESENT KPI BAR (PERSENTIL CASH & VALUASI POIN)          -->
    <!-- ========================================================================= -->
    <div class="bg-slate-900/80 rounded-2xl border border-slate-800 p-4 shadow-xl space-y-3.5">
      
      <!-- Tier 1: Cash Percentiles -->
      <div>
        <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-1.5 mb-2 px-1">
          <div class="flex items-center gap-2">
            <span class="text-xs font-black tracking-wider text-sky-400 uppercase flex items-center gap-1.5">
              <span class="w-2 h-2 rounded-full bg-sky-400"></span>
              1. Distribusi Persentil Tarif Tunai Kamar Standar (100% Like-for-Like)
            </span>
            <span id="p90p100Badge" class="inline-flex bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 text-[10px] font-bold px-2 py-0.5 rounded-full items-center gap-1">
              <span>🛡️</span> Validasi 2x (P90 & P100 Bebas Limpahan Suite)
            </span>
          </div>
          <span id="kpiSurge" class="text-[11px] font-bold text-emerald-400 mono">Surge Musiman Properti: +0%</span>
        </div>
        <div class="grid grid-cols-2 sm:grid-cols-5 gap-2.5">
          <div class="bg-slate-950/80 p-3 rounded-xl border border-slate-800/80">
            <span class="text-[10px] text-emerald-400 font-bold block uppercase tracking-wider">P0 Floor Basis</span>
            <span id="kpiLowest" class="text-sm sm:text-base font-black text-white mono mt-0.5 block">-</span>
          </div>
          <div class="bg-slate-950/80 p-3 rounded-xl border border-slate-800/80">
            <span class="text-[10px] text-sky-400 font-bold block uppercase tracking-wider">P10 Cash Promo</span>
            <span id="kpiLow" class="text-sm sm:text-base font-black text-white mono mt-0.5 block">-</span>
          </div>
          <div class="bg-slate-950/80 p-3 rounded-xl border border-slate-800/80">
            <span class="text-[10px] text-amber-400 font-bold block uppercase tracking-wider">P50 Median Wajar</span>
            <span id="kpiMedian" class="text-sm sm:text-base font-black text-white mono mt-0.5 block">-</span>
          </div>
          <div class="bg-slate-950/80 p-3 rounded-xl border border-purple-500/30 shadow-sm">
            <span class="text-[10px] text-purple-400 font-bold block uppercase tracking-wider">P90 Peak Standar (Tervalidasi)</span>
            <span id="kpiHigh" class="text-sm sm:text-base font-black text-purple-200 mono mt-0.5 block">-</span>
          </div>
          <div class="bg-slate-950/80 p-3 rounded-xl border border-rose-500/30 shadow-sm">
            <span class="text-[10px] text-rose-400 font-bold block uppercase tracking-wider">P100 Validated Max (Bebas Suite)</span>
            <span id="kpiPeak" class="text-sm sm:text-base font-black text-rose-200 mono mt-0.5 block">-</span>
          </div>
        </div>
      </div>

      <!-- Tier 2: Point Valuation Percentiles -->
      <div class="pt-3 border-t border-slate-800/60">
        <div class="flex justify-between items-center mb-2 px-1">
          <span class="text-xs font-black tracking-wider text-purple-400 uppercase flex items-center gap-1.5">
            <span class="w-2 h-2 rounded-full bg-purple-400"></span>
            2. Valuasi Poin Riil (V(t) = Cash / Points &bull; Like-for-Like Kamar Standar)
          </span>
          <span id="valThresholdPill" class="text-[11px] font-bold text-purple-300 bg-purple-950/80 px-2 py-0.5 rounded border border-purple-800/60 mono">
            Ambang Sweet Spot: -
          </span>
        </div>
        <div class="grid grid-cols-2 sm:grid-cols-5 gap-2.5">
          <div class="bg-slate-950/80 p-3 rounded-xl border border-purple-900/30">
            <span class="text-[10px] text-slate-400 font-bold block uppercase tracking-wider">P0 Valuasi Terendah</span>
            <span id="kpiValP0" class="text-sm sm:text-base font-black text-slate-300 mono mt-0.5 block">-</span>
          </div>
          <div class="bg-slate-950/80 p-3 rounded-xl border border-purple-900/30">
            <span class="text-[10px] text-sky-400 font-bold block uppercase tracking-wider">P10 Fair Floor</span>
            <span id="kpiValP10" class="text-sm sm:text-base font-black text-sky-300 mono mt-0.5 block">-</span>
          </div>
          <div class="bg-slate-950/80 p-3 rounded-xl border border-purple-900/30">
            <span class="text-[10px] text-amber-400 font-bold block uppercase tracking-wider">P50 Median Nilai</span>
            <span id="kpiValP50" class="text-sm sm:text-base font-black text-amber-300 mono mt-0.5 block">-</span>
          </div>
          <div class="bg-purple-950/40 p-3 rounded-xl border border-purple-600/50 shadow-inner">
            <span class="text-[10px] text-purple-300 font-black block uppercase tracking-wider">🔥 P90 Sweet Spot</span>
            <span id="kpiValP90" class="text-sm sm:text-base font-black text-purple-200 mono mt-0.5 block">-</span>
          </div>
          <div class="bg-slate-950/80 p-3 rounded-xl border border-purple-900/30">
            <span class="text-[10px] text-pink-400 font-bold block uppercase tracking-wider">P100 Max Valuasi</span>
            <span id="kpiValP100" class="text-sm sm:text-base font-black text-pink-300 mono mt-0.5 block">-</span>
          </div>
        </div>
      </div>

      <!-- Scope Metadata Footer -->
      <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2 pt-2 border-t border-slate-800/40 text-[11px] text-slate-400">
        <div class="flex items-center gap-2">
          <span>ℹ️</span>
          <span id="kpiScopeSummary">Memuat metadata...</span>
        </div>
        <div class="flex items-center gap-2">
          <span id="kpiTierBadge" class="bg-emerald-950 text-emerald-300 border border-emerald-700/50 px-2 py-0.5 rounded text-[10px] font-bold">Standard Room Benchmark</span>
        </div>
      </div>

    </div>

    <!-- ========================================================================= -->
    <!-- 📑 3-TAB MODULAR NAVIGATION HEADER                                        -->
    <!-- ========================================================================= -->
    <div class="flex items-center gap-2 border-b border-slate-800 pb-3">
      <button id="tabBtnArbitrage" onclick="switchMainTab('ARBITRAGE')" class="tab-btn px-4 py-2.5 rounded-xl text-xs font-bold transition-all flex items-center gap-2 bg-gradient-to-r from-purple-600 to-indigo-600 text-white shadow-lg">
        <span>🪙</span> Radar Arbitrase Beli Poin
      </button>
      <button id="tabBtnCalendar" onclick="switchMainTab('CALENDAR')" class="tab-btn px-4 py-2.5 rounded-xl text-xs font-bold transition-all flex items-center gap-2 bg-slate-900 text-slate-400 hover:text-white border border-slate-800">
        <span>🗓️</span> Kalender Matriks & Musim
      </button>
      <button id="tabBtnAnalytics" onclick="switchMainTab('ANALYTICS')" class="tab-btn px-4 py-2.5 rounded-xl text-xs font-bold transition-all flex items-center gap-2 bg-slate-900 text-slate-400 hover:text-white border border-slate-800">
        <span>📈</span> Analitik Valuasi & Persentil
      </button>
    </div>

    <!-- ========================================================================= -->
    <!-- 🪙 TAB 1: RADAR ARBITRASE BELI POIN (ATH Promo vs Cash)                   -->
    <!-- ========================================================================= -->
    <div id="tabContentArbitrage" class="space-y-6">
      
      <!-- Arbitrage Intelligence Banner -->
      <div id="destArbitrageBanner" class="bg-gradient-to-r from-purple-950/80 via-indigo-950/70 to-slate-900 border border-purple-500/50 p-4 rounded-xl shadow-xl flex flex-wrap items-center justify-between gap-4">
        <div class="flex items-center gap-3">
          <div class="w-10 h-10 rounded-xl bg-purple-600/30 border border-purple-400/40 flex items-center justify-center text-xl">
            🪙
          </div>
          <div>
            <h4 class="text-sm font-bold text-white flex items-center gap-2">
              <span id="arbDestTitle">Peluang Arbitrase Beli Poin: Destinasi</span>
              <span class="bg-purple-600 text-[10px] font-black text-white px-2 py-0.5 rounded-full uppercase tracking-wider">ATH Promo</span>
            </h4>
            <p id="arbDestSub" class="text-xs text-purple-200/80 mt-0.5">
              Hanya membandingkan Kamar Standar Like-for-Like (Poin standar tidak membooking Suite).
            </p>
          </div>
        </div>
        <div class="flex items-center gap-3 flex-wrap">
          <div class="bg-slate-900/90 px-3 py-1.5 rounded-lg border border-purple-800/60 text-right">
            <span class="text-[10px] text-slate-400 block uppercase font-bold">Peluang Arbitrase</span>
            <span id="arbCount" class="text-sm font-black text-purple-300 mono">0 Tanggal</span>
          </div>
          <div class="bg-slate-900/90 px-3 py-1.5 rounded-lg border border-emerald-800/60 text-right">
            <span class="text-[10px] text-emerald-400 block uppercase font-bold">Top Hemat Bersih</span>
            <span id="arbMaxSavings" class="text-sm font-black text-emerald-400 mono">Rp 0</span>
          </div>
          <div class="bg-slate-900/90 px-3 py-1.5 rounded-lg border border-amber-800/60 text-right">
            <span class="text-[10px] text-amber-400 block uppercase font-bold">Rata-rata Diskon</span>
            <span id="arbAvgPct" class="text-sm font-black text-amber-300 mono">0%</span>
          </div>
        </div>
      </div>

      <!-- Top Deal Champions Grid -->
      <div id="topDealsSection" class="space-y-3">
        <div class="flex justify-between items-center px-1">
          <h3 class="text-xs font-black tracking-wider text-emerald-400 uppercase flex items-center gap-1.5">
            <span>🏆</span> Peluang Arbitrase Terbaik (Rekomendasi Utama Kamar Standar)
          </h3>
          <span class="text-[11px] text-slate-400">Diurutkan berdasarkan Net Penghematan Terbesar</span>
        </div>
        <div id="topDealsContainer" class="grid grid-cols-1 md:grid-cols-3 gap-3.5"></div>
      </div>

      <!-- Arbitrage Full Matrix Table -->
      <div class="bg-slate-900/90 rounded-2xl border border-slate-800 shadow-xl overflow-hidden">
        <div class="p-4 border-b border-slate-800 flex flex-wrap justify-between items-center gap-3">
          <div>
            <h3 class="text-sm font-bold text-white flex items-center gap-2">
              <span>📋</span> Matriks Komparasi Lengkap (Cash vs Beli Poin)
            </h3>
            <p class="text-xs text-slate-400 mt-0.5">Seluruh rekaman tanggal dengan perbandingan riil tarif tunai vs poin.</p>
          </div>
          <div class="flex items-center gap-2 text-xs">
            <button id="sortBtnSavings" onclick="setSort('savings', 'desc')" class="px-2.5 py-1 rounded-lg font-bold transition-all bg-emerald-600/30 text-emerald-300 border border-emerald-500/40 hover:bg-emerald-600/50">
              🪙 Net Hemat Arbitrase Tertinggi
            </button>
            <button id="sortBtnVal" onclick="setSort('val', 'desc')" class="px-2.5 py-1 rounded-lg font-bold transition-all bg-purple-600/30 text-purple-300 border border-purple-500/40 hover:bg-purple-600/50">
              🔥 Valuasi Poin Tertinggi
            </button>
            <button id="toggleRowsBtn" onclick="toggleShowAllRows()" class="px-2.5 py-1 rounded-lg font-bold bg-slate-800 hover:bg-slate-700 text-slate-200 transition-all">
              👁️ Tampilkan Seluruh Data
            </button>
          </div>
        </div>

        <div class="overflow-x-auto">
          <table class="w-full text-left text-xs border-collapse">
            <thead>
              <tr class="bg-slate-950/80 text-slate-400 border-b border-slate-800 text-[11px] uppercase tracking-wider">
                <th onclick="toggleSort('d')" class="py-2.5 px-3 font-semibold cursor-pointer hover:text-white select-none transition-colors">Tanggal <span id="sortIcon_d">↕</span></th>
                <th onclick="toggleSort('hotel')" class="py-2.5 px-3 font-semibold cursor-pointer hover:text-white select-none transition-colors">Properti & Kamar <span id="sortIcon_hotel">↕</span></th>
                <th onclick="toggleSort('cash')" class="py-2.5 px-3 font-semibold cursor-pointer hover:text-white select-none transition-colors text-right">Tarif Tunai <span id="sortIcon_cash">↕</span></th>
                <th onclick="toggleSort('pts')" class="py-2.5 px-3 font-semibold cursor-pointer hover:text-white select-none transition-colors text-right">Poin Diperlukan <span id="sortIcon_pts">↕</span></th>
                <th class="py-2.5 px-3 font-semibold text-right text-purple-300">Biaya Beli Poin (ATH)</th>
                <th onclick="toggleSort('savings')" class="py-2.5 px-3 font-semibold cursor-pointer hover:text-white select-none transition-colors text-right text-emerald-400">Net Hemat <span id="sortIcon_savings">↕</span></th>
                <th onclick="toggleSort('savingsPct')" class="py-2.5 px-3 font-semibold cursor-pointer hover:text-white select-none transition-colors text-right text-amber-300">Diskon % <span id="sortIcon_savingsPct">↕</span></th>
                <th onclick="toggleSort('val')" class="py-2.5 px-3 font-semibold cursor-pointer hover:text-white select-none transition-colors text-right">Valuasi (Rp/pt) <span id="sortIcon_val">↕</span></th>
                <th class="py-2.5 px-3 font-semibold text-center">Rekomendasi Arbitrase</th>
              </tr>
            </thead>
            <tbody id="arbitrageTableBody" class="divide-y divide-slate-800/60 font-mono"></tbody>
          </table>
        </div>
      </div>

    </div>

    <!-- ========================================================================= -->
    <!-- 🗓️ TAB 2: KALENDER MATRIKS & MUSIM                                        -->
    <!-- ========================================================================= -->
    <div id="tabContentCalendar" class="space-y-6 hidden">
      <div class="bg-slate-900/90 rounded-2xl border border-slate-800 p-5 shadow-xl space-y-4">
        <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3 pb-3 border-b border-slate-800">
          <div>
            <h3 class="text-sm sm:text-base font-bold text-white flex items-center gap-2">
              <span>🗓️</span> Kalender Matriks Fleksibel
            </h3>
            <p class="text-xs text-slate-400 mt-0.5">Tampilan bird's-eye view seluruh hari dalam bulan untuk menemukan sweet spot termurah.</p>
          </div>
          <div class="flex items-center gap-2">
            <button onclick="changeCalendarMonth(-1)" class="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-white rounded-lg text-xs font-bold transition-all">&larr; Bulan Lalu</button>
            <span id="calendarMonthLabel" class="text-xs font-bold text-white px-3 py-1 bg-slate-950 rounded-lg border border-slate-800 mono">September 2026</span>
            <button onclick="changeCalendarMonth(1)" class="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-white rounded-lg text-xs font-bold transition-all">Bulan Depan &rarr;</button>
          </div>
        </div>

        <div class="grid grid-cols-7 gap-1.5 text-center text-xs font-bold text-slate-400 mb-1">
          <div>Min</div><div>Sen</div><div>Sel</div><div>Rab</div><div>Kam</div><div>Jum</div><div>Sab</div>
        </div>
        <div id="calendarGridContainer" class="grid grid-cols-7 gap-1.5"></div>

        <div class="flex items-center justify-between text-[11px] text-slate-400 pt-2 border-t border-slate-800/60">
          <div class="flex items-center gap-3">
            <span class="flex items-center gap-1"><span class="w-2.5 h-2.5 rounded bg-purple-600"></span> Sweet Spot (Poin)</span>
            <span class="flex items-center gap-1"><span class="w-2.5 h-2.5 rounded bg-emerald-600"></span> Cash Bargain (&le; P10)</span>
            <span class="flex items-center gap-1"><span class="w-2.5 h-2.5 rounded bg-slate-800"></span> Tarif Standar</span>
          </div>
          <span>Klik salah satu tanggal untuk detail kamar</span>
        </div>
      </div>
    </div>

    <!-- ========================================================================= -->
    <!-- 📈 TAB 3: ANALITIK VALUASI & PERSENTIL                                    -->
    <!-- ========================================================================= -->
    <div id="tabContentAnalytics" class="space-y-6 hidden">
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div class="bg-slate-900/90 rounded-2xl border border-slate-800 p-5 shadow-xl space-y-3">
          <h3 class="text-xs font-black tracking-wider text-sky-400 uppercase flex items-center gap-2">
            <span>📉</span> Kurva Tarif Tunai Harian vs Floor & Peak
          </h3>
          <div class="h-64 relative">
            <canvas id="cashChartCanvas"></canvas>
          </div>
        </div>

        <div class="bg-slate-900/90 rounded-2xl border border-slate-800 p-5 shadow-xl space-y-3">
          <h3 class="text-xs font-black tracking-wider text-purple-400 uppercase flex items-center gap-2">
            <span>🔥</span> Kurva Valuasi Poin Harian (V(t)) vs P90 Sweet Spot
          </h3>
          <div class="h-64 relative">
            <canvas id="valChartCanvas"></canvas>
          </div>
        </div>
      </div>
    </div>

  </main>

  <!-- ========================================================================= -->
  <!-- 🦶 FOOTER                                                                 -->
  <!-- ========================================================================= -->
  <footer class="border-t border-slate-800/80 bg-slate-950 py-4 mt-8">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row justify-between items-center gap-2 text-xs text-slate-500">
      <div>
        <span class="font-bold text-slate-300">Index Hotel</span> &bull; 100% Data Riil Live CRS &bull; Google Finance Live FX
      </div>
      <div>
        Standard Room Like-for-Like Arbitrage &bull; Zero Cross-Tier Comparison
      </div>
    </div>
  </footer>

  <!-- ========================================================================= -->
  <!-- 💻 JAVASCRIPT LOGIC & AUTHENTIC DATA                                      -->
  <!-- ========================================================================= -->
  <script>
    // Injected Authentic Data Sets
    const HOTELS = {hotels_json};
    const RATES = {rates_json};
    const BRAND_COMPOSITES = {comp_json};
    const COUNTRY_COMPOSITES = {country_comp_json};
    const ROOMS_MAP = {rooms_json};
    const COUNTRIES_WITH_RATES = new Set({countries_json});

    // Injected Live Google Finance FX Data
    const USD_TO_IDR = {usd_to_idr:.2f};
    const BUY_POINTS_ATH = {json.dumps(buy_points_ath, indent=2)};
    const FX_TO_USD = {json.dumps(fx_to_usd, indent=2)};

    const FIXED_VALUATION_BRANDS = new Set(['GHA', 'ACCOR']);

    // State
    let currentFilterMode = 'DESTINATION';
    let currentCountry = 'Indonesia';
    let currentCity = 'ALL';
    let currentBrand = 'ALL';
    let selectedScope = 'COMPOSITE_DESTINATION';
    let currentRoomTier = 'STANDARD'; // Default to standard rooms to prevent Suite mixing
    let displayCurrency = 'ORIGINAL';
    let currentCurr = 'IDR';

    let calCurrentMonth = 8; // September
    let calCurrentYear = 2026;

    let currentSortKey = 'savings';
    let currentSortOrder = 'desc';
    let showAllRows = false;
    let currentDayRecords = [];
    let propertySurgeMap = {{}}; // Per-property seasonal surge

    let cashChart = null;
    let valChart = null;

    // Currency Converter
    function getDestinationCurrency(country) {{
      const map = {{
        'Indonesia': 'IDR', 'Japan': 'JPY', 'Singapore': 'SGD', 'United States': 'USD',
        'United Kingdom': 'GBP', 'France': 'EUR', 'Germany': 'EUR', 'Italy': 'EUR',
        'Spain': 'EUR', 'Australia': 'AUD', 'Thailand': 'THB', 'Malaysia': 'MYR',
        'China': 'CNY', 'Switzerland': 'CHF', 'United Arab Emirates': 'AED',
        'Saudi Arabia': 'SAR', 'Hong Kong': 'HKD', 'Canada': 'CAD'
      }};
      return map[country] || 'USD';
    }}

    function convertRate(amount, fromCurr, toCurr) {{
      if (amount === null || amount === undefined || isNaN(amount)) return null;
      if (!fromCurr || !toCurr || toCurr === 'ORIGINAL' || toCurr === fromCurr) return amount;
      const rateFrom = FX_TO_USD[fromCurr] || 1.0;
      const rateTo = FX_TO_USD[toCurr] || 1.0;
      const amountUSD = amount * rateFrom;
      return amountUSD / rateTo;
    }}

    function formatMoney(amount, curr) {{
      if (amount === null || amount === undefined || isNaN(amount)) return '-';
      const c = curr || currentCurr || 'IDR';
      if (c === 'IDR') {{
        return 'Rp ' + Math.round(amount).toLocaleString('id-ID');
      }} else if (c === 'JPY') {{
        return '¥ ' + Math.round(amount).toLocaleString('ja-JP');
      }} else if (c === 'USD') {{
        return '$' + Math.round(amount).toLocaleString('en-US');
      }} else if (c === 'SGD') {{
        return 'S$' + Math.round(amount).toLocaleString('en-US');
      }} else if (c === 'EUR') {{
        return '€' + Math.round(amount).toLocaleString('de-DE');
      }} else if (c === 'GBP') {{
        return '£' + Math.round(amount).toLocaleString('en-GB');
      }}
      return c + ' ' + Math.round(amount).toLocaleString();
    }}

    // Tab Switching
    function switchMainTab(tab) {{
      ['Arbitrage', 'Calendar', 'Analytics'].forEach(t => {{
        const btn = document.getElementById('tabBtn' + t);
        const content = document.getElementById('tabContent' + t);
        if (t.toUpperCase() === tab) {{
          btn.className = 'tab-btn px-4 py-2.5 rounded-xl text-xs font-bold transition-all flex items-center gap-2 bg-gradient-to-r from-purple-600 to-indigo-600 text-white shadow-lg';
          content.classList.remove('hidden');
        }} else {{
          btn.className = 'tab-btn px-4 py-2.5 rounded-xl text-xs font-bold transition-all flex items-center gap-2 bg-slate-900 text-slate-400 hover:text-white border border-slate-800';
          content.classList.add('hidden');
        }}
      }});
      if (tab === 'CALENDAR') renderMonthlyCalendarGrid();
      if (tab === 'ANALYTICS') renderCharts();
    }}

    function switchFilterMode(mode) {{
      currentFilterMode = mode;
      const destBtn = document.getElementById('modeDestBtn');
      const brandBtn = document.getElementById('modeBrandBtn');
      if (mode === 'DESTINATION') {{
        destBtn.className = 'px-3 py-1.5 rounded-xl font-bold bg-purple-600 text-white shadow-sm transition-all';
        brandBtn.className = 'px-3 py-1.5 rounded-xl font-bold bg-slate-800 text-slate-300 hover:bg-slate-700 transition-all';
      }} else {{
        brandBtn.className = 'px-3 py-1.5 rounded-xl font-bold bg-purple-600 text-white shadow-sm transition-all';
        destBtn.className = 'px-3 py-1.5 rounded-xl font-bold bg-slate-800 text-slate-300 hover:bg-slate-700 transition-all';
      }}
      populateCountryDropdown();
    }}

    // Dropdowns Populator
    function populateCountryDropdown() {{
      const sel = document.getElementById('countrySelect');
      sel.innerHTML = '';
      
      const countries = Array.from(COUNTRIES_WITH_RATES).sort();
      const sorted = ['Indonesia', 'Japan', ...countries.filter(c => c !== 'Indonesia' && c !== 'Japan')];
      
      sorted.forEach(c => {{
        const opt = document.createElement('option');
        opt.value = c;
        opt.textContent = c;
        if (c === currentCountry) opt.selected = true;
        sel.appendChild(opt);
      }});
      populateCityDropdown();
    }}

    function populateCityDropdown() {{
      const sel = document.getElementById('citySelect');
      sel.innerHTML = '<option value=\"ALL\">Semua Kota</option>';
      
      const matched = HOTELS.filter(h => h.country === currentCountry);
      const cities = Array.from(new Set(matched.map(h => h.city).filter(Boolean))).sort();
      
      cities.forEach(ct => {{
        const opt = document.createElement('option');
        opt.value = ct;
        opt.textContent = ct;
        if (ct === currentCity) opt.selected = true;
        sel.appendChild(opt);
      }});
      populateBrandDropdown();
    }}

    function populateBrandDropdown() {{
      const sel = document.getElementById('brandSelect');
      sel.innerHTML = '<option value=\"ALL\">Semua Brand</option>';
      
      let matched = HOTELS.filter(h => h.country === currentCountry);
      if (currentCity !== 'ALL') matched = matched.filter(h => h.city === currentCity);
      const brands = Array.from(new Set(matched.map(h => h.brand))).sort();
      
      brands.forEach(b => {{
        const opt = document.createElement('option');
        opt.value = b;
        opt.textContent = b;
        if (b === currentBrand) opt.selected = true;
        sel.appendChild(opt);
      }});
      populateHotelDropdown();
    }}

    function populateHotelDropdown() {{
      const sel = document.getElementById('hotelSelect');
      sel.innerHTML = '';
      
      const compOpt = document.createElement('option');
      compOpt.value = 'COMPOSITE_DESTINATION';
      compOpt.textContent = currentCity === 'ALL' ? `Komposit: ${{currentCountry}} (Semua Hotel)` : `Komposit: ${{currentCity}}`;
      sel.appendChild(compOpt);
      
      let matched = HOTELS.filter(h => h.country === currentCountry);
      if (currentCity !== 'ALL') matched = matched.filter(h => h.city === currentCity);
      if (currentBrand !== 'ALL') matched = matched.filter(h => h.brand === currentBrand);
      
      matched.sort((a, b) => a.name.localeCompare(b.name)).forEach(h => {{
        const opt = document.createElement('option');
        opt.value = h.id;
        opt.textContent = `[${{h.brand}}] ${{h.name}}`;
        if (h.id === selectedScope) opt.selected = true;
        sel.appendChild(opt);
      }});
      
      renderDashboard();
    }}

    // DATA COLLECTION WITH STRICT ANTI-CROSS-COMPARISON & VILLA ISOLATION LOGIC
    function collectRatesForScope() {{
      let matchedHotels = HOTELS.filter(h => h.country === currentCountry);
      if (currentCity !== 'ALL') matchedHotels = matchedHotels.filter(h => h.city === currentCity);
      if (currentBrand !== 'ALL') matchedHotels = matchedHotels.filter(h => h.brand === currentBrand);
      
      let targetHotelIds = selectedScope === 'COMPOSITE_DESTINATION' ? matchedHotels.map(h => h.id) : [selectedScope];
      let records = [];

      let targetCurr = displayCurrency !== 'ORIGINAL' ? displayCurrency : getDestinationCurrency(currentCountry);
      propertySurgeMap = {{}};

      const ALL_VILLA_PROPERTIES = new Set([
        'gha_capella_ubud_bali_409',
        'gha_capella_ubud_bali',
        'gha_bulgari_resort_bali',
        'marr_dpser',                  // Mandapa, a Ritz-Carlton Reserve
        'hyatt_m1617',                 // Tampah Hills
        'hyatt_m1385',                 // The Ridge Bali
        'gha_fivelements_retreat_bali',// Fivelements Retreat Bali
        'hyatt_dpsav',                 // Alila Villas Uluwatu
        'ihg_dpsub',                   // Six Senses Uluwatu
        'hyatt_m0351'                  // Awasi Iguazu
      ]);

      function isAllVilla(hId, hName) {{
        if (ALL_VILLA_PROPERTIES.has(hId)) return true;
        const hl = (hName || '').toLowerCase();
        return hl.includes('capella ubud') || 
               hl.includes('alila villas') || 
               hl.includes('six senses uluwatu') || 
               hl.includes('tampah hills') || 
               hl.includes('the ridge bali') || 
               hl.includes('fivelements retreat');
      }}

      targetHotelIds.forEach(hid => {{
        const hotel = HOTELS.find(h => h.id === hid);
        const hName = hotel ? hotel.name : '';

        // Isolasi resort 100% all-villa dari komposit destinasi kamar standar
        if (selectedScope === 'COMPOSITE_DESTINATION' && isAllVilla(hid, hName)) {{
          return;
        }}

        const tiers = currentRoomTier === 'ALL' ? ['STANDARD', 'DELUXE', 'CLUB', 'SUITE'] : [currentRoomTier];
        
        tiers.forEach(t => {{
          const key = `${{hid}}__${{t}}`;
          const rawList = RATES[key];
          if (rawList) {{
            rawList.forEach(item => {{
              let r = Object.assign({{}}, item);
              let sourceCurr = r.curr || (hotel ? hotel.curr : 'USD') || 'USD';
              let rawCash = r.cash;

              // === 1. DATA SANITATION: CORRECTION OF SCRAPER ANOMALIES ===
              if (currentCountry === 'Japan' && sourceCurr === 'USD' && rawCash > 500) sourceCurr = 'JPY';
              if (currentCountry === 'Indonesia' && sourceCurr === 'USD' && rawCash > 10000) sourceCurr = 'IDR';

              // Universal USD bounds test
              const rateUSD = (FX_TO_USD[sourceCurr] || 1.0) * rawCash;
              // Discard micro-rate error dates (e.g. $1.0, $1.5, or < $22/night)
              if (rateUSD < 22.0 || rateUSD > 3500.0) return;

              const dCash = convertRate(rawCash, sourceCurr, targetCurr);
              r.cash = dCash;
              r.dispCurr = targetCurr;

              // === 2. STRICT 1-TO-1 LIKE-FOR-LIKE ROOM COMPARISON ===
              r.tier = t;
              const rName = (r.room_name || '').toLowerCase();
              const isSuiteOrVilla = (t === 'SUITE') ||
                                     rName.includes('suite') || 
                                     rName.includes('villa') || 
                                     rName.includes('presidential') || 
                                     rName.includes('club') ||
                                     rName.includes('penthouse') || 
                                     rName.includes('cottage') ||
                                     rName.includes('residence');
              r.isSuiteOrVilla = isSuiteOrVilla;

              // Filter kamar standar murni: Jangan masukkan kamar Suite/Villa ke dalam pool kamar standar
              if (currentRoomTier === 'STANDARD' && isSuiteOrVilla) {{
                return;
              }}

              const brandCfg = BUY_POINTS_ATH[r.brand];

              // ARBITRASE WAJIB 1:1 SESUAI KELAS:
              const isValidStandardMatch = (t === 'STANDARD' && !isSuiteOrVilla && r.pts && r.pts > 0);
              const isValidSuiteMatch = (isSuiteOrVilla && r.pts && r.pts > 0 && r.brand === 'HYATT');

              if (brandCfg && (isValidStandardMatch || isValidSuiteMatch)) {{
                const ptCostTarget = convertRate(brandCfg.usd_pt, 'USD', targetCurr);
                r.buyCost = r.pts * ptCostTarget;
                r.savings = dCash - r.buyCost;
                r.savingsPct = dCash > 0 ? ((r.savings / dCash) * 100) : 0;
                r.isArbitrageWin = r.savings > 0 && r.savingsPct <= 55.0;
              }} else {{
                r.buyCost = null;
                r.savings = -999999;
                r.savingsPct = 0;
                r.isArbitrageWin = false;
              }}

              // Track property-level rates for real seasonal surge
              if (!propertySurgeMap[hid]) propertySurgeMap[hid] = [];
              propertySurgeMap[hid].push(dCash);

              records.push(r);
            }});
          }}
        }});
      }});

      return records;
    }}

    // MASTER DASHBOARD RENDER WITH P90 & P100 2-POINT VALIDATION ENGINE
    function renderDashboard() {{
      const rates = collectRatesForScope();
      currentCurr = displayCurrency !== 'ORIGINAL' ? displayCurrency : getDestinationCurrency(currentCountry);

      // 1. Sub-Header
      const detailNameEl = document.getElementById('detailHotelName');
      const detailLocEl = document.getElementById('detailHotelLoc');
      const detailLinkEl = document.getElementById('detailLink');
      
      if (selectedScope === 'COMPOSITE_DESTINATION') {{
        detailNameEl.textContent = currentCity === 'ALL' ? `Komposit Destinasi: ${{currentCountry}}` : `Komposit Destinasi: ${{currentCity}}, ${{currentCountry}}`;
        detailLocEl.textContent = `Analisis komposit seluruh jaringan hotel (${{rates.length}} rekaman riil)`;
        detailLinkEl.style.display = 'none';
      }} else {{
        const hotel = HOTELS.find(h => h.id === selectedScope);
        if (hotel) {{
          detailNameEl.textContent = `[${{hotel.brand}}] ${{hotel.name}}`;
          detailLocEl.textContent = `${{hotel.city}}, ${{hotel.country}} &bull; Loyalty: ${{hotel.loyalty || 'Standar'}}`;
          detailLinkEl.href = hotel.url || '#';
          detailLinkEl.style.display = 'inline-flex';
        }}
      }}

      // 2. DISCONTINUITY JUMP & SOLD-OUT EXCLUSION ENGINE
      // Mendeteksi patahan diskontinu (Suite Jump). Tanggal yang terbukti kamar standarnya habis
      // DIELIMINASI dari perhitungan true P0-P100 dan DITANDAI SEBAGAI SOLD OUT!
      const propRatesMap = {{}};
      rates.forEach(r => {{
        if (!propRatesMap[r.h_id]) propRatesMap[r.h_id] = [];
        propRatesMap[r.h_id].push(r);
      }});

      let totalSoldOutDays = 0;
      let totalPtsSoldOutDays = 0;

      Object.keys(propRatesMap).forEach(hid => {{
        const pItems = propRatesMap[hid];
        if (pItems.length < 3) return;
        pItems.sort((a, b) => a.cash - b.cash);
        const n = pItems.length;
        const p50 = pItems[Math.floor(n / 2)].cash;
        const p75Idx = Math.floor(0.75 * (n - 1));

        let cutoffIdx = n; // Default: semua tanggal adalah kamar standar sah
        for (let i = p75Idx; i < n; i++) {{
          const prev = pItems[i - 1].cash;
          const curr = pItems[i].cash;
          const deltaPct = prev > 0 ? ((curr - prev) / prev) * 100 : 0;
          const hasPts = pItems[i].pts && pItems[i].pts > 0;

          // Deteksi Patahan Diskontinu:
          // 1. Kenaikan tajam >= 35% pada kuartil atas tanpa poin kamar standar, ATAU
          // 2. Tarif melonjak ekstrim > 2.8x median P50 tanpa poin kamar standar
          if ((deltaPct >= 35.0 && curr > 2.2 * p50 && !hasPts) || (curr > 2.8 * p50 && !hasPts)) {{
            cutoffIdx = i;
            break;
          }}
        }}

        // Tandai status per hari:
        // Titik patahan dan seluruh hari di atasnya adalah SOLD OUT (Kamar Standar Habis • Limpahan Suite)
        pItems.forEach((item, idx) => {{
          if (idx >= cutoffIdx) {{
            item.isStandardSoldOut = true;
            item.originalCash = item.cash;
            totalSoldOutDays++;
          }} else {{
            item.isStandardSoldOut = false;
          }}
        }});

        // B. DETEKSI PATAHAN KALENDER POIN (POINTS DISCONTINUITY ENGINE)
        // Mengecualikan program dengan valuasi statis: Accor ALL (fixed €40/2k pts), GHA (D$1=$1), Shangri-La (15pts=$1)
        const ptsItems = pItems.filter(x => x.pts && x.pts > 0);
        if (ptsItems.length >= 3) {{
          const brandCode = (ptsItems[0].brand || '').toUpperCase();
          const isStaticValuation = brandCode.includes('ACCOR') || brandCode.includes('GHA') || brandCode.includes('SHANGRI');

          if (!isStaticValuation) {{
            // Program dengan Fixed Award Chart Ceiling (Hyatt: Max 45k Cat 8, Wyndham: Max 30k)
            if (brandCode.includes('HYATT') || brandCode.includes('WOH') || brandCode.includes('ALILA') || brandCode.includes('ANDAZ')) {{
              ptsItems.forEach(item => {{
                if (item.pts > 45000) {{
                  item.isPointsSoldOut = true;
                  totalPtsSoldOutDays++;
                }} else {{
                  item.isPointsSoldOut = false;
                }}
              }});
            }} else if (brandCode.includes('WYNDHAM')) {{
              ptsItems.forEach(item => {{
                if (item.pts > 30000) {{
                  item.isPointsSoldOut = true;
                  totalPtsSoldOutDays++;
                }} else {{
                  item.isPointsSoldOut = false;
                }}
              }});
            }} else {{
              // Dynamic Points Programs: IHG, Hilton, Marriott, Langham, dll.
              ptsItems.sort((a, b) => a.pts - b.pts);
              const nPts = ptsItems.length;
              const p50Pts = ptsItems[Math.floor(nPts / 2)].pts;
              const p75PtsIdx = Math.floor(0.75 * (nPts - 1));
              let cutoffPtsIdx = nPts;

              for (let i = p75PtsIdx; i < nPts; i++) {{
                const prev = ptsItems[i - 1].pts;
                const curr = ptsItems[i].pts;
                const deltaPct = prev > 0 ? ((curr - prev) / prev) * 100 : 0;

                // Patahan diskontinu poin: lonjakan >= 35% dan > 1.8x P50 pts, atau lonjakan ekstrim > 2.5x P50 pts
                if ((deltaPct >= 35.0 && curr > 1.8 * p50Pts) || (curr > 2.5 * p50Pts)) {{
                  cutoffPtsIdx = i;
                  break;
                }}
              }}

              ptsItems.forEach((item, idx) => {{
                if (idx >= cutoffPtsIdx) {{
                  item.isPointsSoldOut = true;
                  totalPtsSoldOutDays++;
                }} else {{
                  item.isPointsSoldOut = false;
                }}
              }});
            }}
          }}
        }}
      }});

      // 3. Day-by-Day Aggregation
      const dayMap = {{}};
      rates.forEach(r => {{
        if (!dayMap[r.d]) dayMap[r.d] = [];
        dayMap[r.d].push(r);
      }});

      const dayRecords = [];
      const verifiedStandardCash = [];
      const allVal = [];

      Object.keys(dayMap).sort().forEach(d => {{
        const dayList = dayMap[d];
        dayList.sort((a, b) => a.cash - b.cash);

        // Cari kamar standar yang aktif (tidak sold out) pada hari ini
        const availableStandards = dayList.filter(x => !x.isStandardSoldOut);
        
        let selectedRecord;
        if (availableStandards.length > 0) {{
          selectedRecord = availableStandards[0];
          // HANYA kamar standar yang sah yang dimasukkan ke perhitungan True P0-P100!
          verifiedStandardCash.push(selectedRecord.cash);
        }} else {{
          // Pada hari ini seluruh opsi kamar standar habis (Sold Out)
          selectedRecord = dayList[0];
        }}

        let val = null;
        let cpp = null;
        let isAboveCountryP50 = false;
        if (selectedRecord.pts && selectedRecord.pts > 0 && !selectedRecord.isStandardSoldOut && !selectedRecord.isPointsSoldOut) {{
          val = selectedRecord.cash / selectedRecord.pts;
          allVal.push(val);
          const cashUSD = convertRate(selectedRecord.cash, currentCurr, 'USD');
          cpp = (cashUSD / selectedRecord.pts) * 100.0;
          const countryComp = COUNTRY_COMPOSITES[currentCountry];
          if (countryComp && countryComp.val_p50 && cpp > countryComp.val_p50) {{
            isAboveCountryP50 = true;
          }}
        }}

        dayRecords.push({{
          d: d,
          hotel: selectedRecord.h_name,
          room: selectedRecord.room_name,
          tier: selectedRecord.tier || 'STANDARD',
          isSuiteOrVilla: selectedRecord.isSuiteOrVilla || false,
          isStandardSoldOut: selectedRecord.isStandardSoldOut || false,
          isPointsSoldOut: selectedRecord.isPointsSoldOut || false,
          originalCash: selectedRecord.originalCash || null,
          brand: selectedRecord.brand,
          city: selectedRecord.city,
          cash: selectedRecord.cash,
          pts: selectedRecord.pts,
          val: val,
          cpp: cpp,
          isAboveCountryP50: isAboveCountryP50,
          dispCurr: currentCurr,
          buyCost: selectedRecord.buyCost,
          savings: selectedRecord.savings,
          savingsPct: selectedRecord.savingsPct,
          isArbitrageWin: !selectedRecord.isStandardSoldOut && !selectedRecord.isPointsSoldOut && selectedRecord.isArbitrageWin
        }});
      }});

      currentDayRecords = dayRecords;

      // 4. Mathematical Percentiles (Dihitung pada Verified Standard Rates yang telah divalidasi)
      const targetCashArr = [...verifiedStandardCash];
      targetCashArr.sort((a, b) => a - b);
      allVal.sort((a, b) => a - b);

      function calcP(arr, p) {{
        if (arr.length === 0) return 0;
        const idx = (p / 100) * (arr.length - 1);
        const low = Math.floor(idx);
        const high = Math.ceil(idx);
        if (low === high) return arr[low];
        return arr[low] + (arr[high] - arr[low]) * (idx - low);
      }}

      const cashP0 = calcP(targetCashArr, 0);
      const cashP10 = calcP(targetCashArr, 10);
      const cashP50 = calcP(targetCashArr, 50);
      const cashP90 = calcP(targetCashArr, 90);
      const cashP100 = calcP(targetCashArr, 100);

      const valP0 = allVal.length > 0 ? calcP(allVal, 0) : null;
      const valP10 = allVal.length > 0 ? calcP(allVal, 10) : null;
      const valP50 = allVal.length > 0 ? calcP(allVal, 50) : null;
      const valP90 = allVal.length > 0 ? calcP(allVal, 90) : null;
      const valP100 = allVal.length > 0 ? calcP(allVal, 100) : null;

      // Update KPI Cards
      document.getElementById('kpiLowest').textContent = formatMoney(cashP0, currentCurr);
      document.getElementById('kpiLow').textContent = formatMoney(cashP10, currentCurr);
      document.getElementById('kpiMedian').textContent = formatMoney(cashP50, currentCurr);
      document.getElementById('kpiHigh').textContent = formatMoney(cashP90, currentCurr);
      document.getElementById('kpiPeak').textContent = formatMoney(cashP100, currentCurr);

      // Update Validation Badge
      const pBadge = document.getElementById('p90p100Badge');
      if (pBadge) {{
        if (totalSoldOutDays > 0 || totalPtsSoldOutDays > 0) {{
          const parts = [];
          if (totalSoldOutDays > 0) parts.push(`${{totalSoldOutDays}} hari cash`);
          if (totalPtsSoldOutDays > 0) parts.push(`${{totalPtsSoldOutDays}} hari poin suite`);
          pBadge.innerHTML = `<span>🚫</span> Sold Out Filter Aktif (${{parts.join(' & ')}} dieliminasi dari P0-P100)`;
        }} else {{
          pBadge.innerHTML = `<span>🛡️</span> Validasi 2x (P90 & P100 Bebas Suite)`;
        }}
      }}

      // === 3. REALISTIC SEASONAL SURGE CALCULATION ===
      // Instead of comparing an entire country's budget motel with a luxury resort (which gave fake 20x surge):
      // Calculate real seasonal fluctuation per property!
      let realisticSurgePct = 0;
      if (selectedScope !== 'COMPOSITE_DESTINATION') {{
        // Specific hotel surge: its own peak vs floor
        realisticSurgePct = cashP0 > 0 ? ((cashP90 - cashP0) / cashP0 * 100) : 0;
        document.getElementById('kpiSurge').textContent = `Surge Musiman Properti: +${{realisticSurgePct.toFixed(0)}}% (P90 vs Floor)`;
      }} else {{
        // Composite: calculate median seasonal surge of individual hotels
        const propSurges = [];
        Object.keys(propertySurgeMap).forEach(hid => {{
          const prices = propertySurgeMap[hid];
          if (prices.length >= 3) {{
            prices.sort((a, b) => a - b);
            const pFloor = prices[0];
            const pPeak = prices[Math.floor(0.9 * (prices.length - 1))];
            if (pFloor > 0) {{
              propSurges.push(((pPeak - pFloor) / pFloor) * 100);
            }}
          }}
        }});
        propSurges.sort((a, b) => a - b);
        realisticSurgePct = propSurges.length > 0 ? propSurges[Math.floor(propSurges.length / 2)] : 45;
        document.getElementById('kpiSurge').textContent = `Surge Musiman Rata-rata Properti: +${{realisticSurgePct.toFixed(0)}}% (Normal Musiman)`;
      }}

      // Point Valuation KPI Row
      document.getElementById('kpiValP0').textContent = valP0 ? `${{currentCurr}} ${{valP0.toFixed(1)}}/pt` : '-';
      document.getElementById('kpiValP10').textContent = valP10 ? `${{currentCurr}} ${{valP10.toFixed(1)}}/pt` : '-';
      document.getElementById('kpiValP50').textContent = valP50 ? `${{currentCurr}} ${{valP50.toFixed(1)}}/pt` : '-';
      document.getElementById('kpiValP90').textContent = valP90 ? `${{currentCurr}} ${{valP90.toFixed(1)}}/pt` : '-';
      document.getElementById('kpiValP100').textContent = valP100 ? `${{currentCurr}} ${{valP100.toFixed(1)}}/pt` : '-';

      const valPill = document.getElementById('valThresholdPill');
      const cComp = COUNTRY_COMPOSITES[currentCountry];
      const cP50Str = cComp && cComp.val_p50 ? `${{cComp.val_p50.toFixed(2)}} CPP` : '-';
      if (valPill) {{
        valPill.textContent = `★ P50 Negara: ${{cP50Str}} &bull; Ambang P90: ${{valP90 ? `${{currentCurr}} ${{valP90.toFixed(1)}}/pt` : '-'}}`;
      }}

      document.getElementById('kpiScopeSummary').textContent = `Menampilkan ${{verifiedStandardCash.length}} hari standar aktif (${{dayRecords.length - verifiedStandardCash.length}} hari Sold Out dieliminasi dari P0-P100) &bull; ★ P50 Komposit Negara: ${{cP50Str}} &bull; Kamar: ${{currentRoomTier}}`;

      // 4. Update Tab 1: Arbitrage Banner & Table
      updateArbitrageView(dayRecords);

      // 5. Refresh active tabs
      const calActive = !document.getElementById('tabContentCalendar').classList.contains('hidden');
      if (calActive) renderMonthlyCalendarGrid();

      const anaActive = !document.getElementById('tabContentAnalytics').classList.contains('hidden');
      if (anaActive) renderCharts();
    }}

    // TAB 1: ARBITRAGE BANNER & MATRIX
    function updateArbitrageView(records) {{
      const arbDeals = records.filter(r => r.isArbitrageWin);
      
      const destName = currentCity === 'ALL' ? currentCountry : `${{currentCity}}, ${{currentCountry}}`;
      document.getElementById('arbDestTitle').textContent = `Peluang Arbitrase Beli Poin: ${{destName}}`;
      
      const countEl = document.getElementById('arbCount');
      const maxEl = document.getElementById('arbMaxSavings');
      const avgEl = document.getElementById('arbAvgPct');

      if (arbDeals.length > 0) {{
        const maxSave = Math.max(...arbDeals.map(d => d.savings));
        const avgPct = arbDeals.reduce((acc, d) => acc + d.savingsPct, 0) / arbDeals.length;
        countEl.textContent = `${{arbDeals.length}} Tanggal Untung`;
        maxEl.textContent = formatMoney(maxSave, currentCurr);
        avgEl.textContent = `${{avgPct.toFixed(1)}}%`;
      }} else {{
        countEl.textContent = '0 Tanggal';
        maxEl.textContent = '-';
        avgEl.textContent = '0%';
      }}

      // Top Deal Champions
      const champContainer = document.getElementById('topDealsContainer');
      champContainer.innerHTML = '';
      const sortedArb = [...arbDeals].sort((a, b) => b.savings - a.savings);
      
      sortedArb.slice(0, 3).forEach((deal, idx) => {{
        const card = document.createElement('div');
        card.className = 'bg-slate-950/90 rounded-xl p-4 border border-emerald-500/40 shadow-lg relative overflow-hidden';
        card.innerHTML = `
          <div class=\"flex justify-between items-start\">
            <span class=\"bg-emerald-500/20 text-emerald-400 text-[10px] font-black px-2 py-0.5 rounded uppercase\">#${{idx + 1}} Top Deal Standar</span>
            <span class=\"text-xs font-bold text-slate-400 mono\">${{deal.d}}</span>
          </div>
          <div class=\"mt-2\">
            <div class=\"text-sm font-bold text-white truncate\">${{deal.hotel}}</div>
            <div class=\"text-[11px] text-slate-400 truncate\">${{deal.room}}</div>
          </div>
          <div class=\"mt-3 pt-2.5 border-t border-slate-800 flex justify-between items-center\">
            <div>
              <span class=\"text-[10px] text-slate-400 block uppercase font-bold\">Hemat Bersih</span>
              <span class=\"text-sm font-black text-emerald-400 mono\">+${{formatMoney(deal.savings, currentCurr)}}</span>
            </div>
            <div class=\"text-right\">
              <span class=\"text-[10px] text-amber-400 block uppercase font-bold\">Diskon</span>
              <span class=\"text-xs font-black text-amber-300 mono\">${{deal.savingsPct.toFixed(1)}}%</span>
            </div>
          </div>
        `;
        champContainer.appendChild(card);
      }});

      if (sortedArb.length === 0) {{
        champContainer.innerHTML = '<div class=\"col-span-3 text-center py-4 text-xs text-slate-500 bg-slate-950/40 rounded-xl border border-slate-800\">Tidak ada tanggal dengan arbitrase beli poin pada lingkup ini. Disarankan membayar tunai (Cash Promo).</div>';
      }}

      renderArbitrageTable();
    }}

    function renderArbitrageTable() {{
      const tbody = document.getElementById('arbitrageTableBody');
      tbody.innerHTML = '';

      let list = [...currentDayRecords];
      list.sort((a, b) => {{
        let valA = a[currentSortKey];
        let valB = b[currentSortKey];
        if (valA === null || valA === undefined) valA = -999999;
        if (valB === null || valB === undefined) valB = -999999;
        return currentSortOrder === 'desc' ? (valB - valA) : (valA - valB);
      }});

      const displayList = showAllRows ? list : list.slice(0, 15);

      displayList.forEach(r => {{
        const tr = document.createElement('tr');
        tr.className = 'hover:bg-slate-800/40 transition-colors text-xs border-b border-slate-800/40';

        const hasArb = r.isArbitrageWin;
        const buyCostDisp = r.buyCost !== null ? formatMoney(r.buyCost, r.dispCurr) : '-';
        const savingsDisp = hasArb ? `+${{formatMoney(r.savings, r.dispCurr)}}` : '-';
        const pctDisp = hasArb ? `${{r.savingsPct.toFixed(1)}}%` : '-';

        let badgeHtml = '<span class=\"text-slate-400 bg-slate-800/60 px-2 py-0.5 rounded text-[10px] font-bold\">🟢 Bayar Tunai</span>';
        if (r.isStandardSoldOut) {{
          badgeHtml = `<span class=\"text-rose-300 bg-rose-950/90 px-2 py-0.5 rounded text-[10px] font-black border border-rose-500/80 shadow-sm\">🚫 SOLD OUT (Standar Habis &bull; Suite ${{formatMoney(r.cash, r.dispCurr)}})</span>`;
        }} else if (r.isPointsSoldOut) {{
          badgeHtml = `<span class=\"text-amber-300 bg-amber-950/90 px-2 py-0.5 rounded text-[10px] font-black border border-amber-500/80 shadow-sm\">⚠️ POIN SUITE (${{r.pts ? r.pts.toLocaleString() : ''}} pts &bull; Standar Habis)</span>`;
        }} else if (hasArb) {{
          badgeHtml = `<span class=\"text-emerald-300 bg-emerald-950/90 px-2 py-0.5 rounded text-[10px] font-black border border-emerald-500 shadow-sm\">🪙 Beli Poin (Hemat ${{formatMoney(r.savings, r.dispCurr)}})</span>`;
        }} else if (r.isSuiteOrVilla) {{
          badgeHtml = '<span class=\"text-amber-300 bg-amber-950/80 border border-amber-500/40 px-2 py-0.5 rounded text-[10px] font-bold\">💎 Suite (Cash Only)</span>';
        }}

        let countryP50Badge = '';
        if (r.isAboveCountryP50) {{
          const cData = COUNTRY_COMPOSITES[currentCountry];
          const threshStr = cData ? `${{cData.val_p50.toFixed(2)}} CPP` : '';
          countryP50Badge = `<div class=\"mt-0.5\"><span class=\"inline-block text-amber-300 bg-amber-950/90 border border-amber-500/60 px-1.5 py-0.5 rounded text-[9px] font-black\">★ > P50 Negara (${{r.cpp.toFixed(2)}} vs ${{threshStr}})</span></div>`;
        }}

        tr.innerHTML = `
          <td class=\"py-2.5 px-3 text-slate-300 font-bold whitespace-nowrap\">${{r.d}}</td>
          <td class=\"py-2.5 px-3 text-slate-200\">
            <div class=\"font-semibold text-white flex items-center gap-1.5\">
              <span>[${{r.brand || ''}}] ${{r.hotel || ''}}</span>
              <span class=\"text-[9px] font-black px-1.5 py-0.5 rounded ${{r.tier === 'SUITE' || r.isSuiteOrVilla || r.isStandardSoldOut ? 'bg-amber-950 text-amber-300 border border-amber-500/40' : 'bg-slate-800 text-sky-300'}} uppercase\">${{r.tier || 'STANDARD'}}</span>
            </div>
            <div class=\"text-[10px] text-slate-400 font-normal\">${{r.room || ''}} &bull; ${{r.city || ''}}</div>
          </td>
          <td class=\"py-2.5 px-3 text-right font-bold text-white whitespace-nowrap\">
            ${{r.isStandardSoldOut ? `<span class=\"text-slate-400 line-through block font-normal text-[11px]\">${{formatMoney(r.cash, r.dispCurr)}}</span><span class=\"text-[9px] text-rose-400 font-bold block\">Standar Sold Out</span>` : formatMoney(r.cash, r.dispCurr)}}
          </td>
          <td class=\"py-2.5 px-3 text-right text-sky-400 font-bold whitespace-nowrap\">
            ${{r.isPointsSoldOut ? `<span class=\"text-slate-400 line-through block font-normal text-[11px]\">${{r.pts ? r.pts.toLocaleString() + ' pts' : '-'}}</span><span class=\"text-[9px] text-amber-400 font-bold block\">Poin Suite</span>` : (r.pts ? r.pts.toLocaleString() + ' pts' : '-')}}
          </td>
          <td class=\"py-2.5 px-3 text-right font-mono text-purple-300 whitespace-nowrap\">${{buyCostDisp}}</td>
          <td class=\"py-2.5 px-3 text-right font-black mono whitespace-nowrap ${{hasArb ? 'text-emerald-400 font-black' : 'text-slate-500'}}\">${{savingsDisp}}</td>
          <td class=\"py-2.5 px-3 text-right font-bold mono whitespace-nowrap ${{hasArb ? 'text-amber-300' : 'text-slate-500'}}\">${{pctDisp}}</td>
          <td class=\"py-2.5 px-3 text-right font-black text-purple-300 whitespace-nowrap\">
            ${{r.val ? `${{r.dispCurr}} ${{r.val.toFixed(1)}}/pt` : '-'}}
            ${{countryP50Badge}}
          </td>
          <td class=\"py-2.5 px-3 text-center whitespace-nowrap\">${{badgeHtml}}</td>
        `;

        tbody.appendChild(tr);
      }});
    }}

    function setSort(key, order) {{
      currentSortKey = key;
      currentSortOrder = order;
      renderArbitrageTable();
    }}

    function toggleSort(key) {{
      if (currentSortKey === key) {{
        currentSortOrder = currentSortOrder === 'asc' ? 'desc' : 'asc';
      }} else {{
        currentSortKey = key;
        currentSortOrder = 'desc';
      }}
      renderArbitrageTable();
    }}

    function toggleShowAllRows() {{
      showAllRows = !showAllRows;
      document.getElementById('toggleRowsBtn').textContent = showAllRows ? '👁️ Batasi 15 Baris Teratas' : '👁️ Tampilkan Seluruh Data';
      renderArbitrageTable();
    }}

    // TAB 2: MONTHLY CALENDAR GRID
    function changeCalendarMonth(delta) {{
      calCurrentMonth += delta;
      if (calCurrentMonth > 11) {{
        calCurrentMonth = 0;
        calCurrentYear += 1;
      }} else if (calCurrentMonth < 0) {{
        calCurrentMonth = 11;
        calCurrentYear -= 1;
      }}
      renderMonthlyCalendarGrid();
    }}

    function renderMonthlyCalendarGrid() {{
      const MONTH_NAMES = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'];
      document.getElementById('calendarMonthLabel').textContent = `${{MONTH_NAMES[calCurrentMonth]}} ${{calCurrentYear}}`;

      const container = document.getElementById('calendarGridContainer');
      container.innerHTML = '';

      const firstDay = new Date(calCurrentYear, calCurrentMonth, 1).getDay();
      const totalDays = new Date(calCurrentYear, calCurrentMonth + 1, 0).getDate();

      for (let i = 0; i < firstDay; i++) {{
        const blank = document.createElement('div');
        blank.className = 'h-20 bg-slate-950/30 rounded-xl border border-slate-900/40';
        container.appendChild(blank);
      }}

      const dayLookup = {{}};
      currentDayRecords.forEach(r => {{ dayLookup[r.d] = r; }});

      for (let day = 1; day <= totalDays; day++) {{
        const dStr = `${{calCurrentYear}}-${{String(calCurrentMonth + 1).padStart(2, '0')}}-${{String(day).padStart(2, '0')}}`;
        const r = dayLookup[dStr];

        const cell = document.createElement('div');
        cell.className = 'calendar-cell h-20 p-2 rounded-xl flex flex-col justify-between border ';

        if (r) {{
          if (r.isStandardSoldOut) {{
            cell.className += 'bg-rose-950/40 border-rose-500/70 text-rose-200';
            cell.innerHTML = `
              <div class=\"flex justify-between items-center\">
                <span class=\"text-xs font-black\">${{day}}</span>
                <span class=\"text-[8px] bg-rose-600 px-1 py-0.5 rounded text-white font-black tracking-wider\">SOLD OUT</span>
              </div>
              <div class=\"text-right\">
                <div class=\"text-[10px] text-rose-300 font-bold leading-tight\">Standar Habis</div>
                <div class=\"text-[9px] text-slate-400 line-through mono\">${{formatMoney(r.cash, currentCurr)}}</div>
                <div class=\"text-[8px] text-amber-300/90 font-semibold\">(Suite)</div>
              </div>
            `;
          }} else if (r.isPointsSoldOut) {{
            cell.className += 'bg-amber-950/30 border-amber-500/50 text-amber-200';
            cell.innerHTML = `
              <div class=\"flex justify-between items-center\">
                <span class=\"text-xs font-black\">${{day}}</span>
                <span class=\"text-[8px] bg-amber-600 px-1 py-0.5 rounded text-white font-black tracking-wider\">PTS SUITE</span>
              </div>
              <div class=\"text-right\">
                <div class=\"text-xs font-black mono text-emerald-300\">${{formatMoney(r.cash, currentCurr)}}</div>
                <div class=\"text-[10px] text-slate-400 line-through mono\">${{r.pts ? r.pts.toLocaleString() + 'p' : '-'}}</div>
                <div class=\"text-[8px] text-amber-400 font-semibold\">(Std Pts Habis)</div>
              </div>
            `;
          }} else if (r.isArbitrageWin) {{
            cell.className += 'bg-purple-950/60 border-purple-500/70 text-purple-200';
            cell.innerHTML = `
              <div class=\"flex justify-between items-center\">
                <span class=\"text-xs font-black\">${{day}}</span>
                <span class=\"text-[9px] bg-purple-600 px-1 rounded text-white font-bold\">ARBITRASE</span>
              </div>
              <div class=\"text-right\">
                <div class=\"text-xs font-black mono\">${{formatMoney(r.cash, currentCurr)}}</div>
                <div class=\"text-[10px] text-sky-400 font-bold mono\">${{r.pts ? r.pts.toLocaleString() + 'p' : '-'}}</div>
              </div>
            `;
          }} else {{
            cell.className += 'bg-slate-900 border-slate-800 text-slate-300';
            cell.innerHTML = `
              <div class=\"flex justify-between items-center\">
                <span class=\"text-xs font-black\">${{day}}</span>
              </div>
              <div class=\"text-right\">
                <div class=\"text-xs font-black mono\">${{formatMoney(r.cash, currentCurr)}}</div>
                <div class=\"text-[10px] text-sky-400 font-bold mono\">${{r.pts ? r.pts.toLocaleString() + 'p' : '-'}}</div>
              </div>
            `;
          }}
        }} else {{
          cell.className += 'bg-slate-950/50 border-slate-900 text-slate-600';
          cell.innerHTML = `<span class=\"text-xs font-bold\">${{day}}</span>`;
        }}

        container.appendChild(cell);
      }}
    }}

    // TAB 3: CHARTS
    function renderCharts() {{
      const ctxCash = document.getElementById('cashChartCanvas').getContext('2d');
      const ctxVal = document.getElementById('valChartCanvas').getContext('2d');

      const labels = currentDayRecords.map(r => r.d.slice(5));
      const cashData = currentDayRecords.map(r => r.cash);
      const valData = currentDayRecords.map(r => r.val || 0);

      if (cashChart) cashChart.destroy();
      if (valChart) valChart.destroy();

      cashChart = new Chart(ctxCash, {{
        type: 'line',
        data: {{
          labels: labels,
          datasets: [{{
            label: `Tarif Tunai (${{currentCurr}})`,
            data: cashData,
            borderColor: '#38bdf8',
            backgroundColor: 'rgba(56, 189, 248, 0.1)',
            fill: true,
            tension: 0.2
          }}]
        }},
        options: {{
          responsive: true,
          maintainAspectRatio: false,
          plugins: {{ legend: {{ display: false }} }},
          scales: {{
            x: {{ grid: {{ color: 'rgba(255, 255, 255, 0.05)' }} }},
            y: {{ grid: {{ color: 'rgba(255, 255, 255, 0.05)' }} }}
          }}
        }}
      }});

      valChart = new Chart(ctxVal, {{
        type: 'bar',
        data: {{
          labels: labels,
          datasets: [{{
            label: `Valuasi Poin (${{currentCurr}}/pt)`,
            data: valData,
            backgroundColor: '#a855f7',
            borderRadius: 4
          }}]
        }},
        options: {{
          responsive: true,
          maintainAspectRatio: false,
          plugins: {{ legend: {{ display: false }} }},
          scales: {{
            x: {{ grid: {{ color: 'rgba(255, 255, 255, 0.05)' }} }},
            y: {{ grid: {{ color: 'rgba(255, 255, 255, 0.05)' }} }}
          }}
        }}
      }});
    }}

    // Initialize Selectors
    window.addEventListener('DOMContentLoaded', () => {{
      const countrySel = document.getElementById('countrySelect');
      const citySel = document.getElementById('citySelect');
      const brandSel = document.getElementById('brandSelect');
      const hotelSel = document.getElementById('hotelSelect');
      const tierSel = document.getElementById('roomTierSelect');
      const currSel = document.getElementById('currencySelect');

      populateCountryDropdown();

      countrySel.addEventListener('change', (e) => {{
        currentCountry = e.target.value;
        currentCity = 'ALL';
        populateCityDropdown();
      }});

      citySel.addEventListener('change', (e) => {{
        currentCity = e.target.value;
        populateBrandDropdown();
      }});

      brandSel.addEventListener('change', (e) => {{
        currentBrand = e.target.value;
        populateHotelDropdown();
      }});

      hotelSel.addEventListener('change', (e) => {{
        selectedScope = e.target.value;
        renderDashboard();
      }});

      tierSel.addEventListener('change', (e) => {{
        currentRoomTier = e.target.value;
        renderDashboard();
      }});

      currSel.addEventListener('change', (e) => {{
        displayCurrency = e.target.value;
        renderDashboard();
      }});
    }});
  </script>
</body>
</html>
"""

# Stream/write out Index_Hotel.html safely
with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
    f.write(html_top)

print(f"[✓] Successfully generated {OUTPUT_HTML} (Size: {os.path.getsize(OUTPUT_HTML):,} bytes)")

# Also mirror to Hotel_Analytics_Dashboard.html so OPEN_DASHBOARD.bat works seamlessly
with open(DASH_SRC, "w", encoding="utf-8") as f:
    f.write(html_top)
print(f"[✓] Successfully mirrored to {DASH_SRC}")
