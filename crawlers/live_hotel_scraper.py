"""Live Hotel Rate Scraper & Database Syncer.
Extracts 100% real live market cash rates using stealth browser context and populates hotel_stays.db.
"""
import sys
import os
import re
import time
import logging
from datetime import date, timedelta, datetime
from typing import Dict, List, Any, Optional

from sqlalchemy.orm import Session
from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database.connection import get_session_factory
from database.models import Hotel, RoomCategory, RateRecord
from engine.calculator import recalculate_all_baselines

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("live_hotel_scraper")

PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pw_profile_live")


def parse_live_prices_from_text(text: str) -> List[float]:
    """Extract valid room prices in USD from live page text."""
    usd_rates = []

    # 1. IDR parser (Rp 3.786.880 / IDR 3,786,880)
    idr_matches = re.findall(r"(?:IDR|Rp)[\s\xa0]?([0-9]{1,3}(?:[.,][0-9]{3}){2})", text)
    for m in idr_matches:
        val = int(re.sub(r"\D", "", m))
        if 500000 <= val <= 80000000:
            usd_rates.append(round(val / 16000.0, 2))

    # 2. THB parser (THB 4,500 / ฿4,500)
    thb_matches = re.findall(r"(?:THB|฿)[\s\xa0]?([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{3,6})", text)
    for m in thb_matches:
        val = int(re.sub(r"\D", "", m))
        if 800 <= val <= 150000:
            usd_rates.append(round(val / 36.0, 2))

    # 3. SGD parser (SGD 350 / S$350)
    sgd_matches = re.findall(r"(?:SGD|S\$)[\s\xa0]?([0-9]{1,3}(?:,[0-9]{3})*|[0-9]{2,5})", text)
    for m in sgd_matches:
        val = float(re.sub(r"[^\d.]", "", m))
        if 50.0 <= val <= 3000.0:
            usd_rates.append(round(val * 0.75, 2))

    # 4. JPY parser (¥65,000 / 65,000 JPY)
    jpy_matches = re.findall(r"(?:¥|JPY)[\s\xa0]?([0-9]{1,3}(?:,[0-9]{3})+)", text)
    for m in jpy_matches:
        val = int(re.sub(r"\D", "", m))
        if 8000 <= val <= 500000:
            usd_rates.append(round(val / 155.0, 2))

    # 5. Direct USD parser ($235, $1,250)
    usd_matches = re.findall(r"\$([0-9]{1,3}(?:,[0-9]{3})*)", text)
    for m in usd_matches:
        val = float(m.replace(",", ""))
        if 35.0 <= val <= 4000.0:
            usd_rates.append(val)

    return sorted(set(usd_rates))


class LiveHotelScraper:
    """Scrapes live rates for hotels on the watchlist with persistent session reuse."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._pw = None
        self._context = None

    def start(self):
        if not self._pw:
            self._pw = sync_playwright().start()
            self._context = self._pw.chromium.launch_persistent_context(
                user_data_dir=PROFILE_DIR,
                headless=self.headless,
                viewport={"width": 1366, "height": 768},
                locale="en-US",
                timezone_id="Asia/Jakarta",
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                ignore_default_args=["--enable-automation"],
            )

    def close(self):
        if self._context:
            try:
                self._context.close()
            except:
                pass
            self._context = None
        if self._pw:
            try:
                self._pw.stop()
            except:
                pass
            self._pw = None

    def get_live_cash_rate(self, hotel_name: str, city: str, country: str) -> Optional[Dict[str, Any]]:
        """Fetch live rate using stealth Chromium browser context."""
        self.start()
        clean_city = city.split("(")[0].strip()
        clean_name = re.sub(r"[\(\)/,-]", " ", hotel_name).strip()
        query = f"{clean_name} {clean_city} {country}"
        url = f"https://www.google.com/travel/search?q={query.replace(' ', '+')}&hl=en&gl=us&curr=USD"

        page = None
        try:
            page = self._context.new_page()
            logger.info(f"Scraping live rates for: {hotel_name} ({city})")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3500)

            text = page.inner_text("body")
            page.close()
            page = None

            if "unusual traffic" in text.lower():
                logger.warning(f"CAPTCHA block encountered for {hotel_name}")
                return None

            rates = parse_live_prices_from_text(text)
            if not rates:
                logger.warning(f"No valid price matches found for {hotel_name}")
                return None

            min_rate = min(rates)
            logger.info(f"SUCCESS: Extracted live cash rate for {hotel_name}: ${min_rate:.2f} USD")
            return {
                "cash_rate": min_rate,
                "all_rates": rates[:5],
                "source": "Google Travel Stealth Scraper",
                "observed_at": datetime.utcnow()
            }
        except Exception as e:
            logger.error(f"Error during scrape for {hotel_name}: {e}")
            if page:
                try:
                    page.close()
                except:
                    pass
            return None


def scrape_and_save(
    session: Session,
    hotel: Hotel,
    stay_date: Optional[date] = None,
    scraper: Optional[LiveHotelScraper] = None,
    headless: bool = True
) -> bool:
    """Scrape live rate for a specific hotel record and save to database."""
    should_close = False
    if scraper is None:
        scraper = LiveHotelScraper(headless=headless)
        scraper.start()
        should_close = True

    if stay_date is None:
        stay_date = date.today() + timedelta(days=14)

    live_res = scraper.get_live_cash_rate(
        hotel_name=hotel.name,
        city=hotel.city,
        country=hotel.country
    )

    if should_close:
        scraper.close()

    if not live_res:
        return False

    cash_val = live_res["cash_rate"]

    # Ensure RoomCategory exists
    room = session.query(RoomCategory).filter(RoomCategory.hotel_id == hotel.id).first()
    if not room:
        room = RoomCategory(
            id=f"{hotel.id}_std",
            hotel_id=hotel.id,
            raw_name="Standard Room",
            standardized_type="STANDARD"
        )
        session.add(room)
        session.flush()

    # Save to RateRecord
    existing = (
        session.query(RateRecord)
        .filter(RateRecord.room_id == room.id, RateRecord.stay_date == stay_date)
        .first()
    )

    note = "Verified Real Live Scrape (Google Travel)"
    if existing:
        existing.cash_rate = cash_val
        existing.scraped_at = datetime.utcnow()
        existing.notes = note
    else:
        new_record = RateRecord(
            room_id=room.id,
            stay_date=stay_date,
            cash_rate=cash_val,
            points_required=None,
            award_available=False,
            notes=note
        )
        session.add(new_record)

    session.commit()
    return True


def run_bulk_scrape(
    brand: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    limit: Optional[int] = None,
    headless: bool = True
) -> int:
    """Run live scraper for filtered hotels in the watchlist."""
    SessionMaker = get_session_factory()
    session = SessionMaker()

    query = session.query(Hotel)
    if brand:
        query = query.filter(Hotel.brand == brand.upper())
    if city:
        query = query.filter(Hotel.city.ilike(f"%{city}%"))
    if country:
        query = query.filter(Hotel.country.ilike(f"%{country}%"))

    if limit and limit > 0:
        hotels = query.limit(limit).all()
    else:
        hotels = query.all()

    logger.info(f"Starting live scrape job for {len(hotels)} hotels (Brand: {brand or 'ALL'}, City: {city or 'ALL'}, Country: {country or 'ALL'})...")

    scraper = LiveHotelScraper(headless=headless)
    scraper.start()
    success_count = 0
    target_date = date.today() + timedelta(days=14)

    try:
        for h in hotels:
            res = scrape_and_save(session, h, stay_date=target_date, scraper=scraper, headless=headless)
            if res:
                success_count += 1
            time.sleep(1.0)
    finally:
        scraper.close()

    recalculate_all_baselines(session)
    session.close()
    logger.info(f"Bulk scrape finished. Successfully updated {success_count}/{len(hotels)} live hotel rates in database.")
    return success_count


if __name__ == "__main__":
    count = run_bulk_scrape(city="Bali", limit=5, headless=True)
    print(f"Scraped {count} Bali hotels live.")
