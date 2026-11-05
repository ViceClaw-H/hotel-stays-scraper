import os
import sys
import time
import json
import sqlite3
import hashlib
import re
import asyncio
from datetime import datetime, timedelta
from urllib.parse import quote
from playwright.async_api import async_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

WORKSPACE_DIR = os.environ.get("HOTEL_WORKSPACE_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(WORKSPACE_DIR)

# Off by default -- flip via `ihg_ui_calendar_crawler.DEBUG_TRACE = True`
# before calling harvest_single_hotel in a standalone diagnostic script. Never
# enabled by the production pipeline itself, so it can't spam a real run's log.
DEBUG_TRACE = False

DB_PATH = os.path.join(WORKSPACE_DIR, "hotel_stays.db")
EVIDENCE_CAL_DIR = os.path.join(WORKSPACE_DIR, "evidence", "ihg", "calendar")
os.makedirs(EVIDENCE_CAL_DIR, exist_ok=True)
FAILURE_SHOT_DIR = os.path.join(WORKSPACE_DIR, "evidence", "ihg", "failure_screenshots")
os.makedirs(FAILURE_SHOT_DIR, exist_ok=True)


class BrowserDeadError(Exception):
    """Raised when the page/context/browser died mid-operation (e.g. crashed,
    got closed) rather than genuinely determining the hotel has no rooms.
    Previously this was swallowed by harvest_single_hotel's blanket except
    and returned the same (0,0,0,0) as a real 'not found' result, so once a
    tab died every remaining hotel in that pass got silently reported as
    VERIFIED UNAVAILABLE with zero actual check performed. Callers must catch
    this separately and recreate the page/browser rather than record it as
    a real outcome."""
    pass


_BROWSER_DEAD_MARKERS = ("has been closed", "Target closed", "Target crashed")

_BLOCKED_RESOURCE_TYPES = ("image", "font", "media")
_BLOCKED_URL_KEYWORDS = (
    "adrum", "appdynamics", "analytics", "doubleclick", "googletagmanager",
    "google-analytics", "adobedtm", "tealium", "facebook.net", "hotjar",
    "clarity.ms", "optimizely",
)


async def block_heavy_resources(context):
    """IHG's find-hotels app ships 19+ JS chunks plus images/fonts/analytics
    on every single navigation. None of that renders the calendar we actually
    need -- blocking it cuts real page weight instead of trying to make a
    full human-grade page load faster through timing tricks."""
    async def _handler(route):
        req = route.request
        url = req.url.lower()
        if req.resource_type in _BLOCKED_RESOURCE_TYPES or any(k in url for k in _BLOCKED_URL_KEYWORDS):
            await route.abort()
        else:
            await route.continue_()
    await context.route("**/*", _handler)

DESTINATION_REGIONS = {
    "Indonesia": [
        "Indonesia", "Jakarta, Indonesia", "Bali, Indonesia", "Bandung, Indonesia", "Surabaya, Indonesia", 
        "Cikarang, Indonesia", "Semarang, Indonesia", "Bintan, Indonesia", "Batam, Indonesia", 
        "Labuan Bajo, Indonesia", "Yogyakarta, Indonesia", "Solo, Indonesia", "Medan, Indonesia", "Lombok, Indonesia"
    ],
    "Singapore": [
        "Singapore"
    ],
    "Thailand": [
        "Bangkok, Thailand", "Phuket, Thailand", "Pattaya, Thailand", "Koh Samui, Thailand",
        "Chiang Mai, Thailand", "Hua Hin, Thailand", "Krabi, Thailand", "Rayong, Thailand", 
        "Khao Yai, Thailand", "Phang Nga, Thailand", "Khao Lak, Thailand", "Chiang Rai, Thailand"
    ],
    "Japan": [
        "Tokyo, Japan", "Osaka, Japan", "Kyoto, Japan", "Okinawa, Japan", "Sapporo, Japan",
        "Nagoya, Japan", "Fukuoka, Japan", "Yokohama, Japan", "Sendai, Japan", "Karuizawa, Japan", 
        "Beppu, Japan", "Niigata, Japan", "Kumamoto, Japan", "Hakone, Japan", "Hiroshima, Japan", 
        "Nagasaki, Japan", "Kobe, Japan", "Takayama, Japan", "Appi Kogen, Japan"
    ],
    "Malaysia": [
        "Kuala Lumpur, Malaysia", "Penang, Malaysia", "Johor Bahru, Malaysia", "Kota Kinabalu, Malaysia", "Malacca, Malaysia"
    ],
    "Vietnam": [
        "Vietnam", "Hanoi, Vietnam", "Ho Chi Minh City, Vietnam", "Da Nang, Vietnam", "Phu Quoc, Vietnam", 
        "Nha Trang, Vietnam", "Halong Bay, Vietnam", "Hoi An, Vietnam", "Hue, Vietnam", 
        "Quy Nhon, Vietnam", "Vung Tau, Vietnam", "Sapa, Vietnam", "Can Tho, Vietnam"
    ],
    "Australia": [
        "Sydney, Australia", "Melbourne, Australia", "Brisbane, Australia", "Perth, Australia",
        "Adelaide, Australia", "Gold Coast, Australia", "Cairns, Australia", "Canberra, Australia", 
        "Hobart, Australia", "Darwin, Australia", "Hayman Island, Australia"
    ],
    "United Kingdom": [
        "London, United Kingdom", "Manchester, United Kingdom", "Edinburgh, United Kingdom",
        "Birmingham, United Kingdom", "Glasgow, United Kingdom", "Liverpool, United Kingdom", 
        "Leeds, United Kingdom", "Oxford, United Kingdom", "Cambridge, United Kingdom", 
        "Cardiff, United Kingdom", "Belfast, United Kingdom", "York, United Kingdom", "Bath, United Kingdom"
    ],
    "France": [
        "Paris, France", "Nice, France", "Lyon, France", "Marseille, France", "Bordeaux, France", 
        "Cannes, France", "Strasbourg, France", "Toulouse, France", "Lille, France"
    ],
    "Germany": [
        "Frankfurt, Germany", "Munich, Germany", "Berlin, Germany", "Hamburg, Germany",
        "Cologne, Germany", "Dusseldorf, Germany", "Stuttgart, Germany", "Leipzig, Germany", 
        "Dresden, Germany", "Nuremberg, Germany", "Hannover, Germany"
    ],
    "United Arab Emirates": [
        "Dubai, United Arab Emirates", "Abu Dhabi, United Arab Emirates", "Ras Al Khaimah, United Arab Emirates", "Sharjah, United Arab Emirates"
    ],
    "Saudi Arabia": [
        "Riyadh, Saudi Arabia", "Jeddah, Saudi Arabia", "Makkah, Saudi Arabia", "Madinah, Saudi Arabia", 
        "Al Khobar, Saudi Arabia", "Dammam, Saudi Arabia", "Taif, Saudi Arabia", "AlUla, Saudi Arabia", "Abha, Saudi Arabia"
    ],
    "Qatar": [
        "Doha, Qatar"
    ],
    "Hong Kong": [
        "Hong Kong SAR", "Hong Kong", "Kowloon, Hong Kong"
    ],
    "Taiwan": [
        "Taipei, Taiwan", "Kaohsiung, Taiwan", "Taichung, Taiwan", "Tainan, Taiwan", "Chiayi, Taiwan"
    ],
    "South Korea": [
        "Seoul, South Korea", "Busan, South Korea", "Incheon, South Korea", "Pyeongchang, South Korea"
    ],
    "New Zealand": [
        "Auckland, New Zealand", "Wellington, New Zealand", "Christchurch, New Zealand", "Queenstown, New Zealand", "Rotorua, New Zealand"
    ],
    "Maldives": [
        "Maldives", "Male, Maldives"
    ],
    "Netherlands": [
        "Amsterdam, Netherlands", "Rotterdam, Netherlands", "The Hague, Netherlands", "Utrecht, Netherlands", "Eindhoven, Netherlands"
    ],
    "Spain": [
        "Madrid, Spain", "Barcelona, Spain", "Seville, Spain", "Valencia, Spain", "Malaga, Spain", "Mallorca, Spain", "Ibiza, Spain"
    ],
    "Italy": [
        "Rome, Italy", "Milan, Italy", "Venice, Italy", "Florence, Italy", "Naples, Italy", "Bologna, Italy", "Turin, Italy"
    ],
    "Switzerland": [
        "Geneva, Switzerland", "Zurich, Switzerland", "Lucerne, Switzerland", "Basel, Switzerland", "Bern, Switzerland", "Lugano, Switzerland"
    ],
    "Austria": [
        "Vienna, Austria", "Salzburg, Austria", "Innsbruck, Austria", "Graz, Austria"
    ],
    "Turkey": [
        "Istanbul, Turkey", "Antalya, Turkey", "Bodrum, Turkey", "Ankara, Turkey", "Izmir, Turkey", "Cappadocia, Turkey"
    ],
    "Mexico": [
        "Cancun, Mexico", "Mexico City, Mexico", "Los Cabos, Mexico", "Puerto Vallarta, Mexico", "Guadalajara, Mexico", "Monterrey, Mexico", "Puebla, Mexico", "Riviera Maya, Mexico"
    ],
    "Canada": [
        "Toronto, Canada", "Vancouver, Canada", "Montreal, Canada", "Calgary, Canada", "Ottawa, Canada", "Edmonton, Canada", "Quebec City, Canada", "Victoria, Canada", "Niagara Falls, Canada", "Whistler, Canada"
    ],
    "United States": [
        "New York, NY", "Los Angeles, CA", "Chicago, IL", "Miami, FL", "San Francisco, CA", "Las Vegas, NV", 
        "Orlando, FL", "Washington, DC", "Boston, MA", "Seattle, WA", "Dallas, TX", "Houston, TX", 
        "Atlanta, GA", "Denver, CO", "Honolulu, HI", "Maui, HI", "Phoenix, AZ", "San Diego, CA", 
        "Philadelphia, PA", "Nashville, TN", "Austin, TX", "New Orleans, LA", "San Antonio, TX", "Portland, OR"
    ]
}
COUNTRY_CURRENCY_MAP = {
    "United States": "USD", "Canada": "CAD", "United Kingdom": "GBP",
    "Japan": "JPY", "Australia": "AUD", "New Zealand": "NZD",
    "Indonesia": "IDR", "Malaysia": "MYR", "Singapore": "SGD",
    "Thailand": "THB", "Vietnam": "VND", "China": "CNY",
    "Mainland China": "CNY", "Hong Kong": "HKD", "Taiwan": "TWD",
    "South Korea": "KRW", "France": "EUR", "Germany": "EUR",
    "Italy": "EUR", "Spain": "EUR", "Netherlands": "EUR",
    "Switzerland": "CHF", "United Arab Emirates": "AED",
    "Saudi Arabia": "SAR", "Qatar": "QAR", "Mexico": "MXN",
    "Brazil": "BRL", "India": "INR"
}

def parse_price_val(val_str):
    if not val_str:
        return None
    val_str = str(val_str).strip()
    m_k = re.search(r'([0-9]+(?:\.[0-9]+)?)\s*([kKmM])?', val_str.replace(',', ''))
    if m_k:
        num = float(m_k.group(1))
        unit = m_k.group(2)
        if unit in ('k', 'K'):
            num *= 1000
        elif unit in ('m', 'M'):
            num *= 1000000
        return num
    return None

async def capture_failure(page, mnemonic, reason):
    """Record WHY and WHERE a hotel didn't come back as a full success: the
    exact URL the page was sitting on, one screenshot (overwritten on a
    repeat failure -- one file per hotel, not an accumulating pile), and a
    one-line cause printed to the log. Called on every non-full-success exit
    (UNOPENED, PARTIAL, 0-BYTE, DELISTED, BOOK-ON-HOTEL-SITE, FAIL-FAST,
    watchdog abandonment, dead-tab recovery) per direct instruction
    2026-09-17: failures must say why or at least where they got stuck.

    page.screenshot()'s own `timeout=` is a real Playwright-enforced client
    -side bound (unlike page.evaluate()/locator.count(), which have none --
    see the clean_overlays/enable_tax_inclusive notes above), so this is
    safe to call even on a page that's mid-wedge: it raises cleanly instead
    of hanging, and `except Exception` (not bare `except:`) lets a genuine
    watchdog cancellation still propagate through it.
    """
    url = "?"
    try:
        url = page.url
    except Exception:
        pass
    shot_path = os.path.join(FAILURE_SHOT_DIR, f"{mnemonic}.png")
    try:
        await page.screenshot(path=shot_path, timeout=4000)
    except Exception:
        shot_path = None
    shot_note = shot_path if shot_path else "unavailable (page unresponsive)"
    print(f"      ↳ [DIAG] {mnemonic}: {reason} | url={url} | screenshot={shot_note}")
    return url, shot_path


async def hotel_site_only(page, mnemonic):
    """Return the matched label if this hotel's search card offers only
    "Book on Hotel Site", else "".

    IHG lists some properties it does not sell through its own CRS and hands
    booking off to the hotel's website, so the card carries that link instead
    of a rate and a Browse Dates button. There is no IHG calendar behind it.

    Scoped to THIS hotel's card (the card containing a link to its mnemonic),
    never the whole page -- a radius search renders many hotels' cards and a
    page-wide text match would skip a perfectly bookable hotel because some
    unrelated neighbour in the results list is off-CRS.
    """
    try:
        return await page.evaluate(
            """(mn) => {
                const re = /book\\s+(on|at|through|via)\\s+(the\\s+)?hotel(\\u2019s|'s)?\\s*(web)?\\s*site/i;
                const link = document.querySelector(`a[href*="${mn}" i]`);
                let card = link;
                for (let i = 0; i < 6 && card; i++) {
                    const t = (card.innerText || '');
                    const m = t.match(re);
                    if (m) return m[0];
                    card = card.parentElement;
                }
                return '';
            }""",
            mnemonic,
        )
    except Exception:
        return ""


async def clean_overlays(page):
    try:
        await page.evaluate("""() => {
            const ids = ['onetrust-consent-sdk', 'consent-fixed-bottom', 'truste-consent-buttons', 'gigyaLoginModalScreen', 'uhf_countryLanguagePushDown', 'uhf_countryLanguagePushDownContainer'];
            ids.forEach(id => {
                const el = document.getElementById(id);
                if (el) el.remove();
            });
            document.querySelectorAll('.p-dialog-mask, .ihg-modal-mask-default').forEach(m => {
                if (m.style.display === 'none') m.remove();
            });
        }""")
    # Must be `except Exception`, not bare `except:`. page.evaluate() has no
    # timeout of its own, and this runs 3+ times per hotel (right after every
    # goto, plus the top of both the Money and Points passes) -- the hottest
    # possible place for the outer 300s watchdog's cancellation to land. A
    # bare except catches CancelledError too and silently discards it, which
    # defeats the watchdog entirely: live-reproduced 2026-09-17, a hotel that
    # should have been abandoned at 300s instead ran 3006s (BIOBL) and 622s
    # (AUSLN) because the cancel signal kept getting eaten right here.
    except Exception:
        pass

async def enable_tax_inclusive(page):
    # Kept as a JS click deliberately. The real-mouse-click conversion is the
    # right fix for the View Prices button (a JS click there left the page
    # stuck 28s), but applying it to in-calendar controls regressed them:
    # this code path produced 96% points coverage and a median 254 dates per
    # hotel before the conversion, and 0 points after.
    try:
        await page.evaluate("""() => {
            const cb = document.querySelector('[data-testid="taxesfeescheckbox"], [data-testid="taxesfeeslabel"], #inclusive-tax-label');
            if (cb) {
                const container = document.querySelector('[data-testid="taxesfeescheckbox"]');
                if (container && container.getAttribute('aria-checked') === 'false') {
                    cb.click();
                }
            }
        }""")
    # See clean_overlays' comment above -- same reasoning, same fix.
    except Exception:
        pass

async def discover_destination_hotels(page, country_name):
    regions = DESTINATION_REGIONS.get(country_name, [country_name])
    print(f"\n🔍 [LIVE REGIONAL DISCOVERY] Searching {len(regions)} region(s) for '{country_name}'...")
    
    all_hotels_dict = {}
    now = datetime.now()
    cur_d = now.day
    cur_m = (now.month - 1) % 12
    cur_y = now.year

    for reg in regions:
        search_url = f"https://www.ihg.com/hotels/us/en/find-hotels/hotel-search?fromRedirect=true&qBrs=6c.hi.ex.sb.ul.ic.cp.cw.in.vn.cv.rs.ki.kd.ma.sp.va.re.vx.nd.sx.we.lx.rn.nu.ge.fa&qSrt=sAV&qDest={reg}&qErm=false&qRms=1&qAdlt=1&qChld=0&qCiD={cur_d}&qCiMy={cur_m:02d}{cur_y}&qCoD={cur_d+1}&qCoMy={cur_m:02d}{cur_y}&qAAR=6CBARC&qRad=200&qRdU=km"
        print(f"  • Querying region: {reg}...")
        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(4)
            await clean_overlays(page)

            for _ in range(12):
                await page.mouse.wheel(0, 1500)
                await asyncio.sleep(0.6)

            hotels = await page.evaluate("""() => {
                const list = [];
                const links = document.querySelectorAll('button[aria-describedby*="hotel-card-title-"], a[aria-describedby*="hotel-card-title-"], [data-testid*="selectHotelSID_"], [data-slnm-ihg*="selectHotelSID_"]');
                
                for (const el of links) {
                    let code = '';
                    const descId = el.getAttribute('aria-describedby') || '';
                    const testId = el.getAttribute('data-testid') || el.getAttribute('data-slnm-ihg') || '';
                    
                    let m = descId.match(/hotel-card-title-([A-Za-z0-9]+)/);
                    if (m) code = m[1].toUpperCase();
                    if (!code) {
                        let m2 = testId.match(/selectHotelSID_([A-Za-z0-9]+)/);
                        if (m2) code = m2[1].toUpperCase();
                    }
                    if (!code) continue;

                    let p = el.parentElement;
                    while (p && p !== document.body) {
                        if (p.querySelector('.brand-name, .hotel-name') || (p.id && p.id.includes(code))) {
                            break;
                        }
                        p = p.parentElement;
                    }

                    let name = '';
                    let address = '';
                    if (p) {
                        const nameEl = p.querySelector('.brand-name, .hotel-name, h3, h2');
                        if (nameEl) name = nameEl.innerText.trim();
                        const addrEl = p.querySelector('.hotel-address, .address, [data-testid="hotelAddress"]');
                        if (addrEl) address = addrEl.innerText.trim();
                    }

                    list.push({
                        mnemonic: code,
                        name: name || ('IHG Hotel ' + code),
                        address: address
                    });
                }
                return list;
            }""")

            for h in hotels:
                c_code = h["mnemonic"]
                if c_code not in all_hotels_dict:
                    all_hotels_dict[c_code] = h
        except Exception as e:
            print(f"    [-] Error on region {reg}: {e}")

    hotel_catalog = list(all_hotels_dict.values())
    print(f"✅ Total Discovered: {len(hotel_catalog)} LIVE properties for '{country_name}'.")

    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL;")
    c = conn.cursor()
    
    for h in hotel_catalog:
        m = h["mnemonic"]
        hid = f"ihg_{m.lower()}"
        hname = h["name"] if h["name"] else f"IHG Hotel {m}"
        haddr = h["address"]
        city = haddr.split(",")[0].strip() if haddr and "," in haddr else country_name
        now = datetime.now()
        cimy = f"{now.month-1:02d}{now.year}"
        cid = f"{now.day:02d}"
        comy = cimy
        cod = f"{now.day+1:02d}"
        official_url = f"https://www.ihg.com/hotels/us/en/find-hotels/select-roomrate?qDest={quote(hname)}&qPt=CASH&qCiD={cid}&qCoD={cod}&qCiMy={cimy}&qCoMy={comy}&qAdlt=1&qChld=0&qRms=1&qAAR=6CBARC&qSlH={m}"
        
        c.execute("""
            INSERT OR REPLACE INTO hotels (
                id, brand, name, city, country, currency, loyalty_model, track_points, official_url, created_at
            ) VALUES (?, 'IHG', ?, ?, ?, 'USD', 'DYNAMIC_AWARD', 1, ?, datetime('now'))
        """, (hid, hname, city, country_name, official_url))

    conn.commit()
    conn.close()
    return hotel_catalog

async def harvest_single_hotel(page, hotel, country_name, months_count, db_lock, worker_id, total_hotels, progress_counter, is_retry=False, timeout_seconds=60):
    """No date-guessing, no text-parsing, no negative-signal branching --
    2026-09-17 rewrite per direct instruction: navigate straight to the
    hotel's own page, press View Prices (auto-fills its own default date,
    right or wrong doesn't matter), then poll a flat timeout for the
    Flexible Dates calendar to mount. If it doesn't within timeout_seconds,
    it's UNOPENED and this hotel moves on -- Pass 2 re-checks it later with
    its own (shorter) timeout, rather than this function trying to figure
    out *why* it failed."""
    mnemonic = hotel["mnemonic"]
    hid = f"ihg_{mnemonic.lower()}"
    hname = hotel["name"]
    official_url = hotel.get("official_url")

    t0 = time.time()
    try:
        mounted = False

        if not official_url:
            progress_counter[0] += 1
            curr_idx = progress_counter[0]
            print(f"  [W{worker_id}] [{curr_idx:02d}/{total_hotels:02d}] ⚠️ [NO URL] {mnemonic} ({hname}) -> no official_url on file, skipping ({time.time()-t0:.1f}s)")
            return 0, 0, 0, 0

        await page.goto(official_url, wait_until="domcontentloaded", timeout=45000)
        await clean_overlays(page)

        # Delisted properties (live-confirmed: BBDTX, BIOBS) no longer have a
        # hoteldetail page -- IHG silently redirects to the generic /explore
        # homepage. That page has its own search widget whose button matches
        # the same selectors below, so without this check we click it, think
        # we succeeded, and then burn the full 60s timeout waiting for a
        # calendar that can never appear. Bail in ~3s instead.
        if "hoteldetail" in official_url and "hoteldetail" not in page.url:
            progress_counter[0] += 1
            curr_idx = progress_counter[0]
            print(f"  [W{worker_id}] [{curr_idx:02d}/{total_hotels:02d}] 🗑️ [DELISTED] {mnemonic} ({hname}) -> hoteldetail page gone, redirected to {page.url.split('?')[0]} ({time.time()-t0:.1f}s)")
            await capture_failure(page, mnemonic, f"redirected away from hoteldetail to {page.url.split('?')[0]}")
            # -1 (not 0) so callers can tell "provably gone" from "nothing found
            # this time". A hotel whose page 404s to /explore cannot recover on
            # retry, and Pass 2 was spending ~81s each re-testing them.
            # This is trustworthy in a way UNOPENED never was: it's IHG's own
            # SERVER deciding to redirect, not our client racing Angular's
            # hydration. Confirmed live 2026-09-17 -- every DELISTED redirect
            # observed lands on a specific, hotel-named alternate URL
            # (ALEMN -> /alexandria-minnesota, BKXSD -> /brookings-south-
            # dakota, etc.), never a generic error page, which is what a
            # deliberate URL-scheme change looks like, not a glitch. -1 stays
            # excluded from Pass 2. Contrast with BOOK ON HOTEL SITE below,
            # which IS a client-side text match and does get re-verified.
            return -1, 0, 0, 0

        # Real simulated click, not a JS-evaluated el.click(): live-tested
        # 2026-09-17 -- a JS click on this exact button left the page stuck
        # 28s with zero rendered content (heavy Akamai bot-sensor traffic,
        # no real data call), while an identical real mouse click resolved
        # to a working page in 6s.
        # View Prices is an Angular-hydrated component: wait_until=
        # "domcontentloaded" only means the raw HTML parsed, not that
        # Angular has bootstrapped and inserted this button yet. A single
        # instant count()==0 check right after goto used to fall straight
        # through to UNOPENED with zero retry -- live-confirmed 2026-09-17
        # on AUSLN, which printed UNOPENED in 1.5s while the identical page
        # loaded normally, button and all, when opened fresh seconds later.
        # 10 of 23 UNOPENED results in that run (43%) were under 10s, all
        # consistent with this same hydration race rather than a genuinely
        # closed/unbookable hotel. Poll briefly instead of one instant check.
        view_prices_clicked = False
        selectors = (
            'button.search-button.brand-text.brand-border',
            'button:has-text("View Prices"), button:has-text("View prices")',
        )
        for _ in range(16):  # up to ~8s, 0.5s steps
            for sel in selectors:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0:
                        await loc.scroll_into_view_if_needed()
                        await loc.click(force=True, timeout=5000)
                        view_prices_clicked = True
                        break
                except Exception:
                    continue
            if view_prices_clicked:
                break
            await asyncio.sleep(0.5)

        if view_prices_clicked:
            # Root-caused live 2026-09-17: clicking View Prices kicks off
            # IHG's own internal navigation (hoteldetail -> select-roomrate),
            # which is still in flight for a few seconds after the click
            # resolves. A page.evaluate() during that window throws
            # "Execution context was destroyed" -- a normal, expected event,
            # not a real failure. Letting that exception propagate (the old
            # code did) aborted the whole hotel immediately AND left the
            # in-flight navigation to finish on its own later, which then
            # collided with and corrupted the *next* hotel's page.goto(),
            # cascading into a long run of false UNOPENED results. Treat it
            # as "not ready yet" and keep polling instead.
            # Two possible landings, both valid:
            #  1. select-roomrate  -> the Flexible Dates CTA appears
            #  2. hotel-search     -> the hotel's card shows "No rooms
            #     available for selected dates" plus a Browse Dates button,
            #     which opens the same calendar directly. IHG sends us here
            #     whenever the auto-filled date has no availability, which is
            #     common -- missing this second path is what made every such
            #     hotel burn the full timeout and report a false UNOPENED.
            #     IHG renders two copies of that button (desktop + a hidden
            #     mobile one), so match :visible -- clicking the hidden copy
            #     fails with "Element is not visible" even with force=True.
            for _ in range(int(timeout_seconds / 0.5)):
                try:
                    cta_exists = await page.evaluate("""() => {
                        const btn = document.querySelector('app-flex-dates-cta button, #flexible-dates-cta button, button[aria-labelledby="flexible-dates-cta"], #flexible-dates-cta');
                        return !!btn;
                    }""")
                except Exception:
                    cta_exists = False
                if cta_exists:
                    mounted = True
                    break

                if "hotel-search" in page.url:
                    # A property IHG lists but does not sell through its own
                    # CRS shows "Book on Hotel Site" where the rate and the
                    # Browse Dates button would be -- it hands booking off to
                    # the hotel's own website. There is no IHG calendar behind
                    # it, so waiting is pointless: without this the hotel
                    # burns the full timeout and is then retried in Pass 2 for
                    # another ~50s, twice, for a rate that cannot exist.
                    off_crs = await hotel_site_only(page, mnemonic)
                    if off_crs:
                        progress_counter[0] += 1
                        curr_idx = progress_counter[0]
                        print(f"  [W{worker_id}] [{curr_idx:02d}/{total_hotels:02d}] 🏨 [BOOK ON HOTEL SITE] {mnemonic} ({hname}) -> not sold via IHG CRS, matched {off_crs!r} ({time.time()-t0:.1f}s)")
                        await capture_failure(page, mnemonic, f"card shows {off_crs!r} -- not sold via IHG CRS")
                        # -2, NOT -1: unlike DELISTED (a server-side redirect,
                        # provably true), this is a client-side text match on
                        # a rendered card -- the same class of heuristic that
                        # produced false UNOPENED verdicts elsewhere this
                        # session (hydration races, CDP stalls). We can't
                        # actually vouch for this the way we can for DELISTED,
                        # so it stays in Pass 2 for a second look instead of
                        # being treated as settled.
                        return -2, 0, 0, 0

                    try:
                        browse_btn = page.locator(
                            f'div:has(a[href*="{mnemonic}" i]) button[data-testid="browseDates"]:visible'
                        ).first
                        if await browse_btn.count() > 0:
                            await browse_btn.click(force=True, timeout=5000)
                            await asyncio.sleep(2)
                            mounted = True
                            break
                    except Exception:
                        pass

                await asyncio.sleep(0.5)
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass

        if not mounted:
            progress_counter[0] += 1
            curr_idx = progress_counter[0]
            print(f"  [W{worker_id}] [{curr_idx:02d}/{total_hotels:02d}] 🔒 [UNOPENED / RESIDENCE / NO CRS] {mnemonic} ({hname}) -> Unlisted/No Rooms ({time.time()-t0:.1f}s)")
            if not view_prices_clicked:
                unopened_reason = "View Prices button never appeared/clickable within the 8s hydration poll"
            else:
                unopened_reason = f"View Prices clicked, but no flexible-dates CTA or Browse Dates button mounted within {timeout_seconds}s"
            await capture_failure(page, mnemonic, unopened_reason)
            return 0, 0, 0, 0

        async def scrape_mode(mode_name):
            await clean_overlays(page)

            # Payment mode must be switched BEFORE the calendar opens: the
            # toggles live on the room-rate page underneath, so once the
            # calendar modal is up a click lands on the dialog instead and
            # the mode silently stays on Money (verified 2026-09-17 --
            # aria-pressed never flipped, and every hotel scraped that way
            # returned "N Cash / 0 Points").
            # Money renders pre-selected (aria-pressed="true") by default, so
            # the Money pass was clicking an already-active toggle and paying
            # its full 1.5s settle sleep before Check Prices was even reached
            # -- live-observed 2026-09-17 as the crawler visibly sitting on
            # the room-rate page before pressing it. Only click (and only pay
            # the sleep) when the mode isn't already active.
            if mode_name == "Points":
                btn_pts = page.locator('[data-testid="btnPoints"]')
                if await btn_pts.is_visible() and await btn_pts.get_attribute("aria-pressed") != "true":
                    await btn_pts.click(force=True)
                    await asyncio.sleep(1.5)
            elif mode_name == "Money":
                btn_mny = page.locator('[data-testid="btnMoney"]')
                if await btn_mny.is_visible() and await btn_mny.get_attribute("aria-pressed") != "true":
                    await btn_mny.click(force=True)
                    await asyncio.sleep(1.5)

            # Entering via Browse Dates (the hotel-search path) already leaves
            # the calendar open -- clicking a CTA again would just close it.
            try:
                # Must test VISIBILITY, not mere presence: after the Money pass
                # closes the modal the calendar cells stay in the DOM hidden, so
                # a presence-only check made the Points pass believe the calendar
                # was already open, skip re-opening it, and scrape nothing --
                # every hotel harvested today came back "N Cash / 0 Points" while
                # hotels done hours earlier had 198/198.
                already_open = await page.evaluate(
                    """() => Array.from(document.querySelectorAll('[data-testid="calendarDate"]'))
                             .some(n => n.offsetParent !== null)"""
                )
            except Exception:
                already_open = False

            if not already_open:
                cta = page.locator("app-flex-dates-cta button, #flexible-dates-cta button, button[aria-labelledby='flexible-dates-cta'], #flexible-dates-cta, button:has-text('Flexible Dates'), a:has-text('Flexible Dates')").first
                try:
                    await cta.wait_for(state="attached", timeout=6000)
                    await cta.scroll_into_view_if_needed()
                    await cta.click(force=True)
                    await asyncio.sleep(1.5)
                except:
                    # Real clicks at each fallback tier, not JS el.click() -- see the
                    # note above the card-link click for why (28s stuck page vs 6s
                    # working page on an identical button, live-tested 2026-09-17).
                    clicked = False
                    for sel in (
                        'app-flex-dates-cta button, #flexible-dates-cta button, button[aria-labelledby="flexible-dates-cta"]',
                        '#flexible-dates-cta, app-flex-dates-cta',
                        'a:has-text("Flexible Dates"), button:has-text("Flexible Dates"), span:has-text("Flexible Dates")',
                    ):
                        try:
                            loc = page.locator(sel).first
                            if await loc.count() > 0:
                                await loc.click(force=True, timeout=3000)
                                clicked = True
                                break
                        except Exception:
                            continue
                    if not clicked:
                        # Root cause of today's mass PARTIAL rate, confirmed
                        # by direct instrumented replay 2026-09-17: for a
                        # hotel that reaches its calendar via the hotel-search
                        # / Browse Dates path, the Money pass's own modal-close
                        # (below, unconditional, every pass) leaves the page
                        # back on hotel-search's card list. The three tiers
                        # above only know app-flex-dates-cta -- the CTA that
                        # exists on select-roomrate -- so they can never
                        # re-open a hotel-search page's calendar, and every
                        # such hotel's Points pass silently returned {} here.
                        # Re-click this hotel's own Browse Dates button, same
                        # selector already proven correct in the initial
                        # mount-detection phase.
                        try:
                            browse_btn = page.locator(
                                f'div:has(a[href*="{mnemonic}" i]) button[data-testid="browseDates"]:visible'
                            ).first
                            if await browse_btn.count() > 0:
                                await browse_btn.click(force=True, timeout=5000)
                                await asyncio.sleep(2)
                                clicked = True
                        except Exception:
                            pass
                    if not clicked:
                        return {}, None
                    await asyncio.sleep(1.5)

            # Fallback for reaching reward pricing when the Money/Points toggle
            # isn't usable -- notably the Browse Dates path, where the toggle
            # lives on the room-rate page we never landed on, so those hotels
            # came back cash-only. The calendar modal carries its own rate
            # selector: a label ("Best Available applied") plus an "edit" link
            # opening a list that includes "Reward Nights".
            # Only used when the toggle didn't already get us there, so the
            # working 198/198 path is left untouched.
            if mode_name == "Points":
                try:
                    label = page.locator('[data-testid="calendarRateTypeLabel"]').first
                    current = (await label.inner_text()) if await label.count() > 0 else ""
                    if "reward" not in current.lower():
                        await page.locator('button:has(span:text-is("edit"))').first.click(force=True, timeout=5000)
                        await asyncio.sleep(1.0)
                        await page.locator('li:has-text("Reward Nights")').first.click(force=True, timeout=5000)
                        await asyncio.sleep(3.0)
                except Exception:
                    pass

            await enable_tax_inclusive(page)
            await asyncio.sleep(0.4)

            rates = {}
            detected_curr = None

            for step in range(months_count):
                # Wait up to 10s for prices to render -- but stop as soon as the
                # month has clearly finished rendering, which is true either when
                # prices appear OR when day cells exist and every one of them is
                # struck through (a fully unavailable month). Without that second
                # condition an empty month burned the whole 10s, six times, twice
                # (Money + Points) -- about 83s per hotel on properties that turn
                # out to have no availability at all, which is the common case.
                # Pagination itself is unchanged, so a hotel that only opens in a
                # later month is still found.
                for _ in range(20):
                    has_rendered_prices = await page.evaluate("""() => {
                        const prices = Array.from(document.querySelectorAll('[data-testid="calendarPrice"]'));
                        return prices.some(p => p.innerText && p.innerText.trim().length > 0);
                    }""")
                    if has_rendered_prices:
                        break
                    await asyncio.sleep(0.5)

                cards = await page.evaluate("""() => {
                    const items = [];
                    const nodes = document.querySelectorAll('[data-testid="calendarDate"]');
                    for (const n of nodes) {
                        const d = n.getAttribute('data-date');
                        const pEl = n.querySelector('[data-testid="calendarPrice"]');
                        const srOnly = n.querySelector('.sr-only') ? n.querySelector('.sr-only').innerText.trim() : '';
                        const isStrike = n.classList.contains('ui-ihg-calendar-strike-through');
                        if (d) {
                            items.push({
                                date: d,
                                priceText: pEl ? pEl.innerText.trim() : '',
                                srOnly: srOnly,
                                isStrike: isStrike
                            });
                        }
                    }
                    return items;
                }""")

                for c in cards:
                    if c["isStrike"]:
                        continue
                    d_str = c["date"]
                    sr = c["srOnly"]
                    p_txt = c["priceText"]

                    if mode_name == "Money":
                        m = re.search(r'([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*([A-Z]{3})\s+per night', sr)
                        hcountry = hotel.get("country", "")
                        prop_curr = COUNTRY_CURRENCY_MAP.get(hcountry) or hotel.get("currency") or "USD"
                        if m:
                            val = float(m.group(1).replace(',', ''))
                            curr = m.group(2)
                            rates[d_str] = {"amount": val, "currency": curr}
                            detected_curr = curr
                        elif p_txt:
                            val = parse_price_val(p_txt)
                            if val and val > 0:
                                if val > 10000 and prop_curr in ("USD", "GBP", "EUR", "AUD", "CAD"):
                                    curr = "IDR"
                                else:
                                    curr = prop_curr
                                rates[d_str] = {"amount": val, "currency": curr}
                                if not detected_curr:
                                    detected_curr = curr
                    else: # Points
                        m = re.search(r'([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?(?:[kK])?)\s*points?\s+per night', sr, re.IGNORECASE)
                        if m:
                            raw_pts = m.group(1).replace(',', '').upper()
                            if 'K' in raw_pts:
                                val = float(raw_pts.replace('K', '')) * 1000
                            else:
                                val = float(raw_pts)
                            rates[d_str] = int(val)
                        elif p_txt:
                            val = parse_price_val(p_txt)
                            if val and val > 0:
                                if val < 500:
                                    val = val * 1000
                                rates[d_str] = int(val)

                if step < months_count - 1:
                    old_first_date = cards[0]["date"] if cards else ""
                    # Real click, not JS el.click() -- this fires up to months_count-1
                    # times per hotel (every successful harvest), so it's the
                    # highest-frequency click site in the whole crawler; see the
                    # 28s-stuck-vs-6s-working note above for why that matters.
                    # JS click, same reasoning as enable_tax_inclusive: this is
                    # the implementation that produced a median 254 dates per
                    # hotel. document.querySelector returns the first DOM match,
                    # which is the visible control; the Playwright .first
                    # equivalent resolved to a hidden duplicate and silently
                    # broke the month loop after one view (45 dates vs 196).
                    next_clicked = await page.evaluate("""() => {
                        const nextBtn = document.querySelector('button.p-datepicker-next-button, button[aria-label="Next month"]');
                        if (nextBtn && nextBtn.style.visibility !== 'hidden' && !nextBtn.disabled) {
                            nextBtn.click();
                            return true;
                        }
                        return false;
                    }""")
                    if next_clicked:
                        for _ in range(10):
                            await asyncio.sleep(0.3)
                            new_first = await page.evaluate("() => document.querySelector('[data-testid=\"calendarDate\"]')?.getAttribute('data-date') || ''")
                            if new_first and new_first != old_first_date:
                                break
                    else:
                        break

            await page.evaluate("""() => {
                const closeBtn = document.querySelector('[data-testid="racs-close-btn"], .p-dialog-close-button, app-calendar-close-icon');
                if (closeBtn) closeBtn.click();
                document.querySelectorAll('.p-dialog-mask, .ihg-modal-mask-default').forEach(m => m.remove());
            }""")
            await asyncio.sleep(1.0)
            await clean_overlays(page)
            return rates, detected_curr

        money_rates, detected_curr = await scrape_mode("Money")
        points_rates, _ = await scrape_mode("Points")

        all_dates = sorted(set(list(money_rates.keys()) + list(points_rates.keys())))
        
        progress_counter[0] += 1
        curr_idx = progress_counter[0]

        if not all_dates:
            print(f"  [W{worker_id}] [{curr_idx:02d}/{total_hotels:02d}] ⏩ [0-BYTE / NO DATES] {mnemonic} ({hname}) -> Skipped ({time.time()-t0:.1f}s)")
            await capture_failure(page, mnemonic, "calendar mounted, but neither Money nor Points pass found any dates on the grid")
            return 0, 0, 0, 0

        # Partial (Cash or Points empty) used to return here WITHOUT saving --
        # whatever was actually found (e.g. 195 real cash-rate observations)
        # was thrown away, not persisted, leaving only the mnemonic in
        # retry_hotels for a Pass 2 that might be hours away for a large
        # country, or might never run at all if this process gets stopped
        # first (it happened, repeatedly, this session). The save path below
        # already handles a one-sided result correctly -- it's the exact
        # shape thousands of pre-existing cash-only rows in the DB already
        # have -- so just fall through into it instead of discarding. The
        # caller's own retry_hotels logic (m_cnt>0 and p_cnt>0 required to
        # skip Pass 2) still queues a genuine retry for whichever side is
        # missing; the only change is that Pass 1's real findings survive
        # even if this process dies before that retry ever runs.
        effective_curr = detected_curr or COUNTRY_CURRENCY_MAP.get(hotel.get("country", "")) or hotel.get("currency") or "USD"
        rates_list = []
        for d in all_dates:
            m_info = money_rates.get(d)
            c_val = m_info["amount"] if m_info else None
            c_curr = m_info["currency"] if m_info else effective_curr
            p_val = points_rates.get(d)
            cpp = None
            if c_val and p_val and p_val > 0:
                cpp = round((c_val / p_val) * 100, 4)

            rates_list.append({
                "stay_date": d,
                "cash_rate": c_val,
                "currency": c_curr,
                "points_required": p_val,
                "cents_per_point": cpp
            })

        combined_payload = {
            "hotel_id": hid,
            "hotel_name": hname,
            "mnemonic": mnemonic,
            "city": hotel.get("address", country_name),
            "country": country_name,
            "currency": effective_curr,
            "source_url": page.url,
            "tax_inclusive": True,
            "total_dates": len(all_dates),
            "total_money_dates": len(money_rates),
            "total_points_dates": len(points_rates),
            "rates": rates_list
        }

        ev_filename = f"ihg_{mnemonic}_ui_calendar.json"
        ev_rel_path = f"evidence/ihg/calendar/{ev_filename}"
        ev_abs_path = os.path.join(EVIDENCE_CAL_DIR, ev_filename)

        raw_json = json.dumps(combined_payload, indent=2, ensure_ascii=False)
        raw_bytes = raw_json.encode("utf-8")
        with open(ev_abs_path, "wb") as ef:
            ef.write(raw_bytes)

        file_hash = hashlib.sha256(raw_bytes).hexdigest()
        file_bytes = len(raw_bytes)

        async with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=60)
            conn.execute("PRAGMA journal_mode=WAL;")
            c = conn.cursor()

            pts_values = [p for p in points_rates.values() if p]
            c.execute("""
                INSERT OR REPLACE INTO evidence_registry (
                    evidence_file, source_url, source_type, sha256_hash, file_bytes_size,
                    has_award_data, award_points_min, award_points_max, verified_at
                ) VALUES (?, ?, 'OFFICIAL_IHG_CRS', ?, ?, ?, ?, ?, datetime('now'))
            """, (
                ev_rel_path,
                page.url,
                file_hash,
                file_bytes,
                1 if pts_values else 0,
                min(pts_values) if pts_values else None,
                max(pts_values) if pts_values else None,
            ))

            room_id = f"{hid}_STD"
            c.execute("""
                INSERT OR REPLACE INTO room_categories (
                    id, hotel_id, raw_name, standardized_type, max_occupancy
                ) VALUES (?, ?, 'Standard Room (Lowest Base Calendar)', 'STANDARD', 2)
            """, (room_id, hid))

            c.execute("DELETE FROM rate_records WHERE room_id = ?", (room_id,))

            final_url = page.url
            for item in rates_list:
                d_str = item["stay_date"]
                c_amt = item["cash_rate"]
                p_amt = item["points_required"]
                cur = item["currency"]

                if c_amt is None or c_amt <= 0:
                    continue

                c.execute("""
                    INSERT OR REPLACE INTO rate_records (
                        room_id, stay_date, cash_rate, points_required,
                        award_available, scraped_at, notes, source_url,
                        source_type, source_payload_hash, observed_at,
                        raw_currency, raw_amount, tax_inclusive, evidence_file
                    ) VALUES (?, ?, ?, ?, ?, datetime('now'), 'IHG Web UI Calendar Grid (Tax-Inclusive)', ?, 'OFFICIAL_IHG_CRS', ?, datetime('now'), ?, ?, 1, ?)
                """, (
                    room_id,
                    d_str,
                    c_amt,
                    p_amt,
                    1 if p_amt else 0,
                    final_url,
                    file_hash,
                    cur,
                    c_amt,
                    ev_rel_path
                ))

            conn.commit()
            conn.close()

        dur = time.time() - t0
        is_partial = len(money_rates) == 0 or len(points_rates) == 0
        tag = "🔁 [PARTIAL -- SAVED, still needs a retry for the missing side]" if is_partial else "🌟 [HARVESTED]"
        print(f"  [W{worker_id}] [{curr_idx:02d}/{total_hotels:02d}] {tag} {mnemonic} ({hname}): {len(money_rates)} Cash / {len(points_rates)} Points dates ({dur:.1f}s) -> {ev_filename}")
        if is_partial:
            empty_side = "Money/Cash" if len(money_rates) == 0 else "Points"
            await capture_failure(page, mnemonic, f"{empty_side} pass returned 0 dates ({len(money_rates)} Cash / {len(points_rates)} Points)")
        return len(rates_list), 1, len(money_rates), len(points_rates)

    except Exception as e:
        if any(marker in str(e) for marker in _BROWSER_DEAD_MARKERS):
            raise BrowserDeadError(f"{mnemonic}: {e}") from e
        progress_counter[0] += 1
        curr_idx = progress_counter[0]
        print(f"  [W{worker_id}] [{curr_idx:02d}/{total_hotels:02d}] ⏩ [FAIL-FAST SKIP] {mnemonic} ({hname}): {e} ({time.time()-t0:.1f}s)")
        await capture_failure(page, mnemonic, f"unhandled exception: {type(e).__name__}: {e}")
        return 0, 0, 0, 0

def load_unpriced_hotels_from_catalog(country_name):
    """Already-catalogued IHG hotels for this country that have never gotten a
    single OFFICIAL_IHG_CRS rate record -- reuses the existing catalog row
    (name/city) instead of re-running live discovery. Mnemonic is recovered
    from hotels.id, which discover_destination_hotels always writes as
    'ihg_{mnemonic.lower()}'."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    rows = c.execute(
        """
        SELECT h.id, h.name, h.city, h.official_url
        FROM hotels h
        WHERE h.brand = 'IHG' AND h.country = ?
          AND h.id NOT IN (
              SELECT DISTINCT rc.hotel_id
              FROM room_categories rc
              JOIN rate_records rr ON rr.room_id = rc.id
              WHERE rr.source_type = 'OFFICIAL_IHG_CRS'
          )
        ORDER BY h.id
        """,
        (country_name,),
    ).fetchall()
    conn.close()

    unpriced = []
    for hid, name, city, official_url in rows:
        if not hid.startswith("ihg_"):
            continue
        mnemonic = hid[len("ihg_"):].upper()
        unpriced.append({"mnemonic": mnemonic, "name": name, "address": city, "official_url": official_url})
    return unpriced


async def run_parallel_destination_pipeline(country_name, num_workers=4, months_count=6, limit=None, only_mnemonics=None):
    print("==================================================================")
    print(f"🌍 IHG DETERMINISTIC PARALLEL HARVESTER: {country_name}")
    print(f"   Workers: {num_workers} Tabs | Horizon: {months_count} Months | Two-Pass Deterministic Retry")
    if limit:
        print(f"   Limit: first {limit} discovered propert(y/ies) only (test mode)")
    if only_mnemonics:
        print(f"   Restricted to {len(only_mnemonics)} specific mnemonic(s) from the existing catalog")
    print("==================================================================\n")

    # Uses Playwright's own bundled Chromium (a separate binary from the user's
    # installed Google Chrome, isolated profile per launch) instead of hijacking
    # the system Chrome over the DevTools Protocol. The old approach force-killed
    # every running chrome.exe first (subprocess.run(["taskkill", "/f", ...])) to
    # dodge Chrome's single-instance lock, which also closed the user's own
    # unrelated Chrome windows. Launching Playwright's own browser sidesteps that
    # lock entirely, so it needs no taskkill and never touches the user's browser.
    t_pipeline_start = time.time()
    total_rates_ingested = 0
    total_evidence_files = 0
    browser = None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context()
            await block_heavy_resources(context)
            disc_page = await context.new_page()

            # Step 1: hotel list -- either live multi-region discovery, or (when
            # only_mnemonics is given) the already-catalogued-but-unpriced hotels
            # for this country, pulled straight from the DB with no re-discovery.
            if only_mnemonics is not None:
                catalog = only_mnemonics
                print(f"[*] Using {len(catalog)} already-catalogued unpriced propert(y/ies) for {country_name} (no live discovery).")
            else:
                catalog = await discover_destination_hotels(disc_page, country_name)
            if not catalog:
                print("[-] No properties to harvest.")
                return

            if limit:
                catalog = catalog[:limit]
                print(f"[*] Limited to first {len(catalog)} propert(y/ies) for this test run.")

            # Setup Queue & Workers for Pass 1
            queue = asyncio.Queue()
            for h in catalog:
                await queue.put(h)

            total_hotels = len(catalog)
            progress_counter = [0]
            db_lock = asyncio.Lock()
            retry_hotels = []
            # mnemonic -> True when Pass 1 called it DELISTED or BOOK ON
            # HOTEL SITE (r_count == -1, previously excluded from Pass 2
            # entirely as "provably settled"). Both are heuristics -- a URL
            # -redirect check, a text match -- and this same session already
            # found several "confirmed" negatives that were actually wrong
            # (AUSLN's UNOPENED, a plain hydration race). Re-testing a truly
            # dead page costs ~2s, so there's no real cost to checking, and
            # it directly measures how often our own classification is
            # wrong instead of just trusting it.
            pass1_neg_verdict = {}

            # Create worker tabs (Pass 1)
            actual_workers = min(num_workers, total_hotels)
            worker_pages = [await context.new_page() for _ in range(actual_workers)]
            print(f"\n🚀 [PASS 1] Launching {len(worker_pages)} parallel worker tabs for {total_hotels} properties...")

            async def worker_loop(w_id, page):
                nonlocal total_rates_ingested, total_evidence_files
                while not queue.empty():
                    try:
                        h = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    try:
                        # Hard watchdog. Playwright calls like locator.count()
                        # and page.evaluate() have no implicit timeout, so a
                        # wedged page blocks its worker forever -- observed
                        # 2026-09-17: the run froze at 126/128 with CPU flat at
                        # 137.3s and no log output for 40 minutes. The internal
                        # per-guess timeouts cannot catch that because they
                        # never get to run. Cap the whole hotel instead.
                        r_count, ev_count, m_cnt, p_cnt = await asyncio.wait_for(
                            harvest_single_hotel(
                                page, h, country_name, months_count, db_lock, w_id, total_hotels, progress_counter, is_retry=False, timeout_seconds=60
                            ),
                            timeout=300,
                        )
                    except asyncio.TimeoutError:
                        print(f"  [W{w_id}] [!] {h['mnemonic']} exceeded the 300s watchdog -- abandoning this hotel, recreating tab, continuing.")
                        await capture_failure(page, h['mnemonic'], "exceeded the 300s watchdog -- page stopped responding to evaluate()/count() calls")
                        try:
                            await page.close()
                        except:
                            pass
                        try:
                            page = await context.new_page()
                        except Exception:
                            queue.task_done()
                            break
                        retry_hotels.append(h)
                        queue.task_done()
                        continue
                    except BrowserDeadError as e:
                        print(f"  [W{w_id}] [!] Tab died ({e}) -- recreating and requeueing {h['mnemonic']} rather than recording a false result.")
                        await capture_failure(page, h['mnemonic'], f"tab/browser died: {e}")
                        try:
                            await page.close()
                        except:
                            pass
                        try:
                            page = await context.new_page()
                        except Exception as relaunch_err:
                            print(f"  [W{w_id}] [!] Could not recreate a tab ({relaunch_err}); this worker is stopping, its remaining queue share goes to Pass 2.")
                            retry_hotels.append(h)
                            queue.task_done()
                            break
                        await queue.put(h)
                        queue.task_done()
                        continue
                    if r_count > 0 and m_cnt > 0 and p_cnt > 0:
                        total_rates_ingested += r_count
                        total_evidence_files += ev_count
                    elif r_count == -1:
                        pass  # DELISTED: a real server-side redirect, provably settled -- don't retry
                    else:
                        # -2 (BOOK ON HOTEL SITE, a heuristic text match) and
                        # every 0/partial result all get a second look.
                        if r_count == -2:
                            pass1_neg_verdict[h['mnemonic']] = "BOOK ON HOTEL SITE"
                        retry_hotels.append(h)
                    queue.task_done()
                    # Deliberate pacing between hotels -- IHG's WAF flagged this
                    # session for behaving like a burst/DDoS pattern (thousands
                    # of rapid requests with no gaps). This keeps each worker's
                    # own cadence human-scale regardless of how many workers run
                    # concurrently.
                    await asyncio.sleep(1.5)

            # Run Pass 1 concurrently
            tasks = [asyncio.create_task(worker_loop(i + 1, worker_pages[i])) for i in range(len(worker_pages))]
            await asyncio.gather(*tasks)

            # Pass 2: same queue/worker pattern as Pass 1, but 2 workers and a
            # shorter 50s timeout (vs Pass 1's 60s) -- per direct instruction:
            # a hotel that times out in Pass 1 just moves to the next hotel,
            # not a different phase; only after the whole country finishes
            # does Pass 2 come back and re-check everything Pass 1 missed.
            if retry_hotels:
                print(f"\n🔁 [PASS 2: RETRY] Re-testing {len(retry_hotels)} unharvested/partial properties -- 2 workers, 50s timeout...")
                for wp in worker_pages:
                    try:
                        if not wp.is_closed():
                            await wp.close()
                    except:
                        pass

                retry_queue = asyncio.Queue()
                for h in retry_hotels:
                    await retry_queue.put(h)
                retry_progress = [0]
                num_pass2_workers = min(2, len(retry_hotels))

                try:
                    retry_pages = [await context.new_page() for _ in range(num_pass2_workers)]
                except Exception:
                    browser = await p.chromium.launch(
                        headless=False,
                        args=["--disable-blink-features=AutomationControlled"],
                    )
                    context = await browser.new_context()
                    await block_heavy_resources(context)
                    retry_pages = [await context.new_page() for _ in range(num_pass2_workers)]

                async def retry_worker_loop(w_id, page):
                    nonlocal total_rates_ingested, total_evidence_files
                    while not retry_queue.empty():
                        try:
                            h = retry_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                        try:
                            r_count, ev_count, m_cnt, p_cnt = await asyncio.wait_for(
                                harvest_single_hotel(
                                    page, h, country_name, months_count, db_lock, w_id, len(retry_hotels), retry_progress, is_retry=True, timeout_seconds=50
                                ),
                                timeout=300,
                            )
                        except asyncio.TimeoutError:
                            print(f"  [W{w_id}] [!] {h['mnemonic']} exceeded the 300s watchdog in Pass 2 -- abandoning, not recording a result.")
                            await capture_failure(page, h['mnemonic'], "exceeded the 300s watchdog in Pass 2 -- page stopped responding to evaluate()/count() calls")
                            try:
                                await page.close()
                            except:
                                pass
                            try:
                                page = await context.new_page()
                            except Exception:
                                retry_queue.task_done()
                                break
                            retry_queue.task_done()
                            continue
                        except BrowserDeadError as e:
                            print(f"  [W{w_id}] [!] Tab died in Pass 2 ({e}) -- recreating and requeueing {h['mnemonic']}.")
                            await capture_failure(page, h['mnemonic'], f"tab/browser died in Pass 2: {e}")
                            try:
                                await page.close()
                            except:
                                pass
                            try:
                                page = await context.new_page()
                            except Exception as relaunch_err:
                                print(f"  [W{w_id}] [!] Could not recreate a tab ({relaunch_err}); this worker is stopping, {h['mnemonic']} left honestly unchecked.")
                                retry_queue.task_done()
                                break
                            await retry_queue.put(h)
                            retry_queue.task_done()
                            continue
                        pass1_tag = pass1_neg_verdict.get(h['mnemonic'])
                        if r_count > 0 and (m_cnt > 0 or p_cnt > 0):
                            total_rates_ingested += r_count
                            total_evidence_files += ev_count
                            if pass1_tag:
                                # The method's own weakness, caught in the act:
                                # Pass 1 called this settled (r_count == -2) and
                                # excluded it entirely under the old logic --
                                # here it demonstrably had real, bookable rates.
                                print(f"  [PASS-1 WAS WRONG] ⚠️ {h['mnemonic']} ({h['name']}): Pass 1 classified this as {pass1_tag}, but Pass 2 recovered {m_cnt} Cash / {p_cnt} Points rates. The {pass1_tag} check has a real false-positive rate.")
                            else:
                                print(f"  [RECOVERED] ✅ Successfully recovered {h['mnemonic']} ({h['name']}): {m_cnt} Cash / {p_cnt} Points rates!")
                        elif pass1_tag and r_count == -2:
                            print(f"  [PASS-1 CONFIRMED] ✅ {h['mnemonic']} ({h['name']}): still shows {pass1_tag} on a second look -- verdict holds up.")
                        elif pass1_tag:
                            print(f"  [PASS-1 UNCERTAIN] ❓ {h['mnemonic']} ({h['name']}): was {pass1_tag} in Pass 1, but Pass 2 saw something else entirely (r_count={r_count}) and still found no rates. Worth a manual look.")
                        else:
                            # State what was observed, not what it implies. The
                            # old wording ("VERIFIED UNAVAILABLE ... genuinely
                            # closed / sold out / coming soon") asserted a
                            # conclusion nothing here establishes: finding no
                            # bookable dates in a 6-month window is not proof a
                            # hotel is closed, and no verification step runs.
                            print(f"  [NO DATES FOUND] 🔒 {h['mnemonic']} ({h['name']}): no bookable dates in the {months_count}-month window after 2 passes. Not confirmation the hotel is closed.")
                        retry_queue.task_done()
                        await asyncio.sleep(1.5)  # same deliberate pacing as Pass 1

                retry_tasks = [asyncio.create_task(retry_worker_loop(i + 1, retry_pages[i])) for i in range(len(retry_pages))]
                await asyncio.gather(*retry_tasks)

            await browser.close()
            browser = None
    finally:
        if browser is not None:
            try:
                await browser.close()
            except:
                pass

    dur_total = time.time() - t_pipeline_start
    print("\n==================================================================")
    print(f"🏁 IHG {country_name.upper()} DETERMINISTIC HARVESTING COMPLETED")
    print(f"   • Total Discovered Properties         : {len(catalog)}")
    print(f"   • Successfully Harvested Properties   : {total_evidence_files}/{len(catalog)}")
    print(f"   • Total Authentic Rate Records        : {total_rates_ingested:,}")
    print(f"   • Total Execution Time                : {dur_total:.1f}s ({dur_total/60:.2f} mins)")
    print(f"   • Effective Speed                     : {dur_total/max(1,len(catalog)):.2f}s / property")
    print("==================================================================")

async def run_all_global_pipeline(num_workers=8, months_count=6):
    all_countries = list(DESTINATION_REGIONS.keys())
    print("==================================================================")
    print(f"🌍 IHG GLOBAL 8-WORKER AUTONOMOUS HARVESTING PIPELINE")
    print(f"   Total Countries: {len(all_countries)} | Workers: {num_workers} | Horizon: {months_count} Months")
    print("==================================================================\n")

    for idx, c_name in enumerate(all_countries, 1):
        print(f"\n>>>>>>>> [{idx:02d}/{len(all_countries):02d}] STARTING COUNTRY: {c_name.upper()} <<<<<<<<")
        try:
            await run_parallel_destination_pipeline(country_name=c_name, num_workers=num_workers, months_count=months_count)
        except Exception as err:
            print(f"[-] Error processing country {c_name}: {err}")
        await asyncio.sleep(2.0)

def main():
    country_arg = "Japan"
    workers_arg = 8
    months_arg = 6
    run_all = False
    limit_arg = None
    fill_unpriced = False

    if len(sys.argv) > 1:
        for a in sys.argv[1:]:
            if a == "--all":
                run_all = True
            elif a == "--fill-unpriced":
                fill_unpriced = True
            elif a.startswith("--country="):
                country_arg = a.split("=")[1]
            elif a.startswith("--workers="):
                try:
                    workers_arg = int(a.split("=")[1])
                except:
                    pass
            elif a.startswith("--months="):
                try:
                    months_arg = int(a.split("=")[1])
                except:
                    pass
            elif a.startswith("--limit="):
                try:
                    limit_arg = int(a.split("=")[1])
                except:
                    pass

    if run_all:
        asyncio.run(run_all_global_pipeline(num_workers=workers_arg, months_count=months_arg))
    else:
        only_mnemonics = load_unpriced_hotels_from_catalog(country_arg) if fill_unpriced else None
        asyncio.run(run_parallel_destination_pipeline(
            country_name=country_arg, num_workers=workers_arg, months_count=months_arg,
            limit=limit_arg, only_mnemonics=only_mnemonics
        ))

if __name__ == "__main__":
    main()



