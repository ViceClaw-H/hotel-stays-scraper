"""Batch Scraper for Full 365-Day Price Calendars on Overseas Flagship Hotels.
Pulls 365 continuous days directly from Accor PriceCalendar GraphQL API for:
- Singapore (Raffles Singapore, Swissôtel The Stamford, Fairmont, Pullman Hill St)
- France (Le Royal Monceau Raffles Paris, Pullman Paris Tour Eiffel, Sofitel Le Scribe)
- Japan (Swissôtel Nankai Osaka, Pullman Tokyo Tamachi, Mercure Kyoto)
- Australia (Sofitel Sydney Darling Harbour, Novotel Sydney, Pullman Melbourne)
- United Kingdom (Raffles London at The OWO, Sofitel London St James, Novotel London)
- UAE (Raffles The Palm Dubai, Sofitel Dubai Downtown)
- Thailand (Sofitel Bangkok Sukhumvit, Pullman Bangkok King Power)
"""
import sys
import os
import sqlite3
import time
import logging
from datetime import date, timedelta
from curl_cffi import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from crawlers.scrape_accor_365days_calendar import scrape_hotel_365_days
from build_dashboard import build_interactive_dashboard

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("overseas_365_sync")

OVERSEAS_TARGETS = [
    # Singapore
    {"code": "A5E1", "db_id": "accor_a5e1", "name": "Raffles Singapore", "curr": "SGD", "market": "SG"},
    {"code": "A5D3", "db_id": "accor_a5d3", "name": "Swissôtel The Stamford Singapore", "curr": "SGD", "market": "SG"},
    {"code": "B5L7", "db_id": "accor_b5l7", "name": "Pullman Singapore Hill Street", "curr": "SGD", "market": "SG"},
    
    # France (Paris)
    {"code": "A5D5", "db_id": "accor_a5d5", "name": "Le Royal Monceau - Raffles Paris", "curr": "EUR", "market": "FR"},
    {"code": "7229", "db_id": "accor_7229", "name": "Pullman Paris Tour Eiffel", "curr": "EUR", "market": "FR"},
    
    # Japan
    {"code": "A5F5", "db_id": "accor_a5f5", "name": "Swissôtel Nankai Osaka", "curr": "JPY", "market": "JP"},
    {"code": "B137", "db_id": "accor_b137", "name": "Pullman Tokyo Tamachi", "curr": "JPY", "market": "JP"},
    
    # Australia
    {"code": "B1D9", "db_id": "accor_b1d9", "name": "Sofitel Sydney Darling Harbour", "curr": "AUD", "market": "AU"},
    {"code": "3023", "db_id": "accor_3023", "name": "Novotel Sydney on Darling Harbour", "curr": "AUD", "market": "AU"},
    
    # United Kingdom
    {"code": "B1C0", "db_id": "accor_b1c0", "name": "Raffles London at The OWO", "curr": "GBP", "market": "GB"},
    {"code": "3144", "db_id": "accor_3144", "name": "Sofitel London St James", "curr": "GBP", "market": "GB"},
    
    # UAE
    {"code": "B8Y0", "db_id": "accor_b8y0", "name": "Raffles The Palm Dubai", "curr": "AED", "market": "AE"},
    
    # Thailand
    {"code": "5213", "db_id": "accor_5213", "name": "Sofitel Bangkok Sukhumvit", "curr": "THB", "market": "TH"}
]

def run_overseas_sync():
    logger.info(f"Starting 365-day calendar sync for {len(OVERSEAS_TARGETS)} overseas flagship properties...")
    
    success = 0
    for idx, t in enumerate(OVERSEAS_TARGETS, 1):
        logger.info(f"[{idx}/{len(OVERSEAS_TARGETS)}] Scraping 365 days for: {t['name']} ({t['curr']})...")
        try:
            cnt = scrape_hotel_365_days(
                hotel_code=t["code"],
                hotel_db_id=t["db_id"],
                hotel_name=t["name"],
                currency=t["curr"],
                country_market=t["market"]
            )
            logger.info(f"  -> Successfully inserted {cnt} daily rate records for {t['name']}.")
            success += 1
        except Exception as e:
            logger.error(f"  -> Error scraping {t['name']}: {e}")
        time.sleep(1)

    logger.info(f"Completed overseas calendar sync: {success}/{len(OVERSEAS_TARGETS)} hotels updated.")
    
    # Rebuild dashboard
    logger.info("Rebuilding master dashboard with new overseas 365-day stock curves...")
    build_interactive_dashboard()
    logger.info("Master dashboard rebuilt successfully.")

if __name__ == '__main__':
    run_overseas_sync()
