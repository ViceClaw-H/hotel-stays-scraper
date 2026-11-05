> **Salinan GitHub dari All_Hotel_Stays_Scraper_v9f_r5.** Kode, katalog, dan snapshot `hotel_stays.db` disertakan. Runtime `portable_python`, cookie/browser profile, serta rekaman request yang memuat token tidak disertakan. Arsip ZIP asli tidak diubah.
>
> Untuk salinan GitHub, pasang Python lalu jalankan `python -m pip install -r requirements.txt`. Gunakan `python cli.py <subcommand>`; peluncur `.bat` yang mengharuskan `portable_python` memerlukan runtime lokal dari paket asli. API key bawaan Accor/IHG dan session ID IHG sudah dikeluarkan dari kode. Bila diperlukan, atur `ACCOR_API_KEY`, `IHG_API_KEY`, dan `IHG_SESSION_ID` sebagai environment variable lokal sebelum menjalankan scraper. Jangan commit cookie atau kredensial.
>
> Publikasi repositori ini bukan validasi kelengkapan katalog, tarif, atau keberhasilan scraping semua jaringan. Petunjuk edisi portable di bawah berasal dari paket asli.

# Antigravity Unified Hotel Harvester & Rate Intelligence Engine
### Portable Windows Edition (Golden Standard Schema v2)

A comprehensive hotel rate benchmarking database and analytics system built to harvest, verify, and analyze room rates (Cash Floors & Ceilings, Award Points, and Points Arbitrage Valuations) across **12 global hotel chains**.

---

## ⚠️ WAJIB DIBACA SEBELUM MENJALANKAN SCRAPER

**Baca [`00_START_HERE_WAJIB_DIBACA.txt`](00_START_HERE_WAJIB_DIBACA.txt) secara lengkap sebelum menjalankan file `.bat` apa pun.** Gunakan `REGENERATE_ALL_COOKIES.bat` untuk memperbarui sesi protected chain saat run pertama, IP berubah, sesi kedaluwarsa, atau setelah 403/captcha/challenge anti-bot. Regenerasi dilakukan manual agar scraper tidak tertahan oleh challenge browser.

---

## 🏛️ Project Architecture & Data Contract

1. **Authentic CRS / IBE Evidence**: Every recorded price originates directly from official hotel booking engines or CRS GraphQL/REST endpoints.
2. **Cryptographic Provenance Gate**: Every scrape saves the raw server response as an evidence file (`evidence/<chain>/raw/`), indexed in `evidence_registry` with a SHA-256 hash.
3. **Fail-Closed Evidence Integrity**:
   - **Layer 1 (Byte Parity)**: Verifies that every stored rate record has its exact raw evidence file on disk with matching SHA-256 hash.
   - **Layer 2 (Value Replay)**: Deterministically re-derives cash rates, points required, currency, and room classes from raw evidence using chain extractors (`engine/extractors/<chain>.py`).
4. **Standardized Room Classes**: Room types are strictly normalized into standard tiers (`STANDARD`, `SUITE`, `DELUXE`) in `room_categories` to prevent artificial cross-tier price distortions.
5. **Gross All-in Pricing**: Cash rates reflect final payable prices including regional statutory lodging taxes and mandatory service charges.

---

## 🏨 The 12 Supported Hotel Chains

| Brand | Loyalty Model | Points DB? | Pricing Mechanics |
| :--- | :--- | :---: | :--- |
| **World of Hyatt** | Fixed Chart (Cat 1–8) | **Yes** | Fixed point redemption categories with peak/off-peak pricing. |
| **Wyndham Rewards** | Flat Tiers (7.5k / 15k / 30k) | **Yes** | Fixed point cost per bedroom regardless of cash surge. |
| **Hilton Honors** | Dynamic with Tier Caps | **Yes** | Standard room rewards capped per property tier. |
| **Marriott Bonvoy** | Dynamic (Soft Bounds) | **Yes** | Dynamic points floating with cash rates within seasonal bands. |
| **IHG One Rewards** | Dynamic (Cash-Pegged) | **Yes** | Dynamic points closely correlated with revenue rates. |
| **Best Western (BWH)**| Dynamic | **Yes** | Revenue-linked point redemptions across 26 global hubs. |
| **Radisson Rewards** | Dynamic Cash-Pegged | **Yes** | Points pegged to cash value across EMEA & APAC portfolio. |
| **Swiss-Belhotel** | Direct Member Discount | **No (Cash Only)**| SBEC member discount rates tracked across 365-day calendar. |
| **Accor (ALL)** | Fixed Rebate (€40 / 2k pts) | **No (Cash Only)**| Direct currency voucher; tracked for cash floor and ceiling. |
| **GHA DISCOVERY** | Fixed Rebate (1 D$ = $1 USD)| **No (Cash Only)**| Direct folio cash credit; tracked for cash floor and ceiling. |
| **Shangri-La Circle** | Fixed Rebate (15 pts = $1)| **No (Cash Only)**| Revenue redemption; tracked for cash floor and ceiling. |
| **Brilliant by Langham**| Fixed Rebate | **No (Cash Only)**| Revenue-based room credits; tracked for cash floor and ceiling. |

---

## 🚀 Getting Started on a Clean Windows PC

This package includes a standalone **Portable Python 3.13** runtime. No Python, pip, or system path configuration is required.

### 1. Environment Verification
Double-click:
```bat
1_SETUP_NEW_PC.bat
```
This utility automatically:
- Confirms the bundled Portable Python runtime is functional.
- Detects your system browser (Microsoft Edge pre-installed on Windows 10/11, or Google Chrome).
- Runs the cryptographic evidence verifier to confirm database integrity.

### 2. Master Harvester Menu
Double-click:
```bat
RUN_MENU.bat
```
The interactive menu allows you to:
- Run individual chain harvesters (`[1]` to `[12]`).
- Launch interactive anti-bot cookie generators for protected chains (`[H]`, `[M]`, `[R]`, `[B]`).
- Run the cryptographic evidence audit (`[V]`).
- Run all chains concurrently (`[P]`) or sequentially (`[A]`).
- Emergency stop running scrapers (`[S]`).

### 3. Individual Chain Launchers
You can also run any harvester directly via its batch launcher:
- `run_swissbel.bat` - Swiss-Belhotel International (Official Hotelchamp IBE API)
- `run_bestwestern.bat` - Best Western (GraphQL BFF 12-Month Stratified Grid)
- `run_ihg.bat` - IHG One Rewards (Official CRS Calendar API)
- `run_wyndham.bat` - Wyndham Rewards (Stream Availability Engine)
- `run_radisson.bat` - Radisson Hotel Group
- `run_accor.bat` - Accor ALL PriceCalendar GraphQL
- `run_hyatt.bat` - World of Hyatt Availability Calendar
- `run_hilton.bat` - Hilton Honors CRS
- `run_marriott.bat` - Marriott Bonvoy Phoenix GraphQL
- `run_shangrila.bat` - Shangri-La Circle CRS
- `run_langham.bat` - Brilliant by Langham SynXis
- `run_gha.bat` - GHA DISCOVERY CRS

---

## 🛡️ Anti-Bot Protection & Interactive Cookie Generation

Chains protected by Akamai Bot Manager, Cloudflare, or DataDome (Hilton, Marriott, Radisson, Best Western) require a valid browser session token tied to your IP. 

To refresh tokens without manual devtools inspection:
1. Run `GENERATE_HILTON_COOKIES.bat`, `GENERATE_MARRIOTT_COOKIES.bat`, `GENERATE_RADISSON_COOKIES.bat`, or `GENERATE_BESTWESTERN_COOKIES.bat`.
2. A real browser window opens automatically and navigates to the official site.
3. Solve any visual challenge if presented. The script automatically detects the clearance tokens, saves the clean session to `crawlers/pw_<chain>_session/`, and closes cleanly.

---

## 💻 Command Line Interface (`cli.py`)

Run commands using the bundled Python:
```cmd
portable_python\python.exe cli.py <subcommand>
```
*(Or use standard `python cli.py <subcommand>` if Python is installed in PATH).*

### Available Subcommands:

| Subcommand | Description | Example |
| :--- | :--- | :--- |
| `stats` | Global inventory summary of hotels, rates, and room tiers | `python cli.py stats` |
| `verify` | Layer 1 byte-parity & Layer 2 value replay evidence audit | `python cli.py verify` |
| `audit` | Comprehensive provenance and real-data consistency check | `python cli.py audit` |
| `brands` | Overview of all 12 chains, loyalty models, and currencies | `python cli.py brands` |
| `percentiles` | 5-tier empirical percentiles (P0 floor to P100 peak ceiling) | `python cli.py percentiles --hotel Bali` |
| `baselines` | Empirical baseline valuations per property | `python cli.py baselines --brand WYNDHAM` |
| `build` | Recompiles analytics dashboards with latest rates | `python cli.py build` |
| `serve` | Starts local HTTP web server to view dashboards | `python cli.py serve --port 8000` |

---

## 📊 Analytics Dashboards

- `Index_Hotel.html` / `Hotel_Analytics_Dashboard.html`: Master interactive rate intelligence matrix featuring daily prices, percentiles, surge detection, and sweet-spot redemptions across all cataloged properties.
- `Points_Arbitrage_Report.html`: Points-to-cash valuation arbitrage report comparing redemption values against median market fair value ($P_{50}$).
- Launchers:
  - `00_BUKA_INDEX.bat` - Opens the main dashboard in your default browser.
  - `01_POINTS_ARBITRAGE.bat` - Opens the points arbitrage report.
  - `02_RUN_HOTEL_TODAY.bat` - Recompiles and updates daily dashboard analytics.

---

## Cek 1 hotel per rantai (baru)

`CHECK_ONE_HOTEL.bat swissbel` menjalankan skrip rantai itu untuk SATU hotel di salinan sementara (database dan folder bukti Anda tidak
disentuh), lalu memeriksa hasilnya: apakah ada baris, audit bukti kriptografis, dan audit kejujuran
(`engine/honesty_audit.py`): bukti yang diubah skrip, harga yang bukan harga berpajak, mata uang kosong, harga terlalu seragam, rasio
pajak yang sama di banyak hotel. Verdict: PASS / WARN / FAIL / NO ROWS. `CHECK_ONE_HOTEL.bat all` mengecek semua rantai
(Hilton, Marriott, Hyatt, Radisson, GHA membuka jendela Chrome). `CHECK_ONE_HOTEL.bat --list` menampilkan daftarnya.

## Perubahan di versi ini
- **Swiss-Belhotel**: pajak tidak lagi ditebak. Harga hanya ditulis bila endpoint pajak hotel itu sendiri menyatakan tidak ada pajak tambahan; bukti adalah salinan respons server apa adanya.
- **Best Western**: tidak lagi memakai harga sebelum pajak sebagai harga berpajak.
- **Radisson** dan **GHA**: scraper harga (Chrome sistem, tanpa cookie) dengan parser murni dan bukti asli.
- Placeholder 'Global*' di tabel hotels diganti 'Unknown'.
- Paket ini tidak membawa data hasil (evidence kosong, rate_records kosong).
- Belum dibuat ulang: Accor, Hilton, Langham, Marriott masih punya mata uang bawaan di kode (EUR/USD) bila server tidak menyebut mata uang; gunakan `CHECK_ONE_HOTEL.bat <rantai>`.

## v9d - perbaikan dari hasil run di PC lain (2026-11-03)
Penyebab yang ditemukan dari LAPORAN_PROBLEM + kejadian.csv, dan perbaikannya:
- **Peluncur utama (RUN_ALL_PARALLEL) memanggil skrip lama**: GHA -> gha_master_crawler (ModuleNotFoundError 'database'), Swiss-Belhotel -> skrip daftar hotel saja,
  Langham -> skrip lama (kurs IDR karangan, hotel 'Global'). Kini memanggil gha_harvester, swissbel_harvester, langham_harvester; skrip Langham lama dihapus.
- **Folder data/, database/, hotel_engine.py tidak ikut di ZIP** -> Hyatt gagal (data/hyatt_official_directory.json hilang). Dikembalikan.
- **IHG diblokir (49 HTTP 403 beruntun, 116 dari 7.413 hotel)**: enam worker, 4 req/dtk, dan 11 rantai lain berbagi satu IP. Kini default 3 worker, 1,5 req/dtk,
  jeda pemulihan 30 dtk / 90 dtk / 5 mnt / 15 mnt, peluncur menjeda 12 dtk antar rantai, dan IHG keluar dengan kode 2 bila berhenti dini.
- **Status "DONE OK" menyesatkan**: kode keluar 2 kini tampil sebagai PARSIAL, dan logs/_RINGKASAN_AKHIR.txt dibuat di akhir.
- **Radisson: 862 dari 876 hotel 'dilewati HTTP 500'**: setelah browser tertutup di hotel ke-14, semua kegagalan navigasi diberi label palsu "HTTP 500". Kini browser dibuka ulang
  (maks 5x), kegagalan navigasi dilaporkan apa adanya, berhenti setelah 8 hotel berturut-turut tanpa jawaban, dan keluar dengan kode 2 bila parsial.
- **GHA: 15 hotel pertama 'tanpa tarif publik'**: extractor hanya menerima kode tarif DAILY, padahal Rotana memakai RAFL/RFLEX dan Anantara S14BFXBE (dicek live). Bila kamar
  tidak punya tarif DAILY, dipakai tarif publik (bukan member) termurah dan kodenya ditulis di kolom catatan.
- **Best Western (jalur kamar buatan Anda)**: kini mengambil rencana tarif publik TERMURAH yang status pajaknya dinyatakan server, melewati tarif khusus anggota. Status "sudah termasuk pajak"
  tetap berasal dari flag server `taxIncluded` yang belum terbukti terhadap halaman checkout.
- `--no-sandbox` dihapus dari browser_tools (menurunkan keamanan browser). Cookie anti-bot Radisson dikosongkan.
- `tools/fix_legacy_langham_hotels.py`: merapikan hotel Langham 'Global'/mata uang pengisi di database lama (laporan dulu, `--apply` membuat cadangan). Baris harga tidak diubah.
- Tes: 84 lulus.

