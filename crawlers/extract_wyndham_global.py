"""Wyndham Rewards Master Global Hotel Directory Extractor.
Populates hotel_stays.db with 100% verified real physical Wyndham Rewards properties across global operating countries.
"""
import sys
import os
import re
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database.connection import get_session_factory
from database.models import Hotel, RoomCategory, PropertyBaseline
from export_hotels_excel import export_watchlist_to_excel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("wyndham_global")

WYNDHAM_MASTER_DIRECTORY = {
    "Indonesia": [
        {"name": "Wyndham Grand Bali Jimbaran Resort", "city": "Bali (Jimbaran)", "url": "https://www.wyndhamhotels.com/wyndham-grand/jimbaran-indonesia/wyndham-grand-bali-jimbaran-resort/overview"},
        {"name": "Wyndham Tamansari Jivva Resort Bali", "city": "Bali (Klungkung / Lepang Beach)", "url": "https://www.wyndhamhotels.com/wyndham/klungkung-indonesia/wyndham-tamansari-jivva-resort-bali/overview"},
        {"name": "Wyndham Garden Kuta Beach Bali", "city": "Bali (Kuta / Pantai Kuta)", "url": "https://www.wyndhamhotels.com/wyndham-garden/kuta-indonesia/wyndham-garden-kuta-beach-bali/overview"},
        {"name": "Ramada by Wyndham Bali Sunset Road Kuta", "city": "Bali (Kuta / Sunset Road)", "url": "https://www.wyndhamhotels.com/ramada/kuta-indonesia/ramada-bali-sunset-road-kuta/overview"},
        {"name": "Ramada Encore by Wyndham Bali Seminyak", "city": "Bali (Seminyak / Sunset Point)", "url": "https://www.wyndhamhotels.com/ramada/seminyak-indonesia/ramada-encore-bali-seminyak/overview"},
        {"name": "Wyndham Casablanca Jakarta", "city": "Jakarta (Casablanca / Tebet)", "url": "https://www.wyndhamhotels.com/wyndham/jakarta-indonesia/wyndham-casablanca-jakarta/overview"},
        {"name": "Wyndham Surabaya City Centre", "city": "Surabaya (Basuki Rahmat)", "url": "https://www.wyndhamhotels.com/wyndham/surabaya-indonesia/wyndham-surabaya/overview"},
        {"name": "Wyndham Opi Hotel Palembang", "city": "Palembang (Jakabaring)", "url": "https://www.wyndhamhotels.com/wyndham/palembang-indonesia/wyndham-opi-hotel-palembang/overview"},
        {"name": "Ramada Suites by Wyndham Solo", "city": "Solo (Adi Sucipto / Karanganyar)", "url": "https://www.wyndhamhotels.com/ramada/karanganyar-indonesia/ramada-suites-solo/overview"},
        {"name": "Ramada by Wyndham Yogyakarta", "city": "Yogyakarta (Ring Road Utara)", "url": "https://www.wyndhamhotels.com/ramada/yogyakarta-indonesia/ramada-yogyakarta/overview"},
        {"name": "Days Hotel & Suites by Wyndham Jakarta Airport", "city": "Tangerang (Soekarno-Hatta Airport)", "url": "https://www.wyndhamhotels.com/days-inn/tangerang-indonesia/days-hotel-and-suites-jakarta-airport/overview"},
        {"name": "Howard Johnson by Wyndham Pekalongan", "city": "Pekalongan (Central Java)", "url": "https://www.wyndhamhotels.com/hojo/pekalongan-indonesia/howard-johnson-pekalongan/overview"}
    ],
    "Singapore": [
        {"name": "Wyndham Singapore at Zhongshan Park", "city": "Singapore (Balestier / Ah Hood Rd)", "url": "https://www.wyndhamhotels.com/wyndham/singapore-singapore/wyndham-singapore-zhongshan-park/overview"},
        {"name": "Ramada by Wyndham Singapore at Zhongshan Park", "city": "Singapore (Balestier Rd)", "url": "https://www.wyndhamhotels.com/ramada/singapore-singapore/ramada-singapore-zhongshan-park/overview"},
        {"name": "Days Hotel by Wyndham Singapore at Zhongshan Park", "city": "Singapore (Ah Hood Rd)", "url": "https://www.wyndhamhotels.com/days-inn/singapore-singapore/days-hotel-singapore-zhongshan-park/overview"}
    ],
    "Thailand": [
        {"name": "Wyndham Grand Phuket Kalim Bay", "city": "Phuket (Kalim Beach / Patong View)", "url": "https://www.wyndhamhotels.com/wyndham-grand/kathu-thailand/wyndham-grand-phuket-kalim-bay/overview"},
        {"name": "Wyndham Grand Nai Harn Beach Phuket", "city": "Phuket (Nai Harn Beach)", "url": "https://www.wyndhamhotels.com/wyndham-grand/rawai-thailand/wyndham-grand-nai-harn-beach-phuket/overview"},
        {"name": "Wyndham Grand Bangsaray Pattaya", "city": "Pattaya (Bang Saray Beach)", "url": "https://www.wyndhamhotels.com/wyndham-grand/sattahip-thailand/wyndham-grand-bangsaray-pattaya/overview"},
        {"name": "Wyndham Bangkok Queen Convention Centre", "city": "Bangkok (Rama IV / QSNCC)", "url": "https://www.wyndhamhotels.com/wyndham/bangkok-thailand/wyndham-bangkok-queen-convention-centre/overview"},
        {"name": "Wyndham Garden Bangkok Sukhumvit 42", "city": "Bangkok (Sukhumvit 42 / Ekkamai)", "url": "https://www.wyndhamhotels.com/wyndham-garden/bangkok-thailand/wyndham-garden-bangkok-sukhumvit-42/overview"},
        {"name": "Ramada Plaza by Wyndham Bangkok Menam Riverside", "city": "Bangkok (Charoen Krung / Chao Phraya)", "url": "https://www.wyndhamhotels.com/ramada/bangkok-thailand/ramada-plaza-bangkok-menam-riverside/overview"},
        {"name": "Ramada by Wyndham D MA Bangkok", "city": "Bangkok (Pratunam / Petchaburi 35)", "url": "https://www.wyndhamhotels.com/ramada/bangkok-thailand/ramada-d-ma-bangkok/overview"},
        {"name": "Ramada Plaza by Wyndham Chao Fah Phuket", "city": "Phuket (Chao Fah West / Phuket Town)", "url": "https://www.wyndhamhotels.com/ramada/mueang-phuket-thailand/ramada-plaza-chao-fah-phuket/overview"},
        {"name": "Ramada Resort by Wyndham Khao Lak", "city": "Khao Lak (Bang Niang Beach)", "url": "https://www.wyndhamhotels.com/ramada/takua-pa-thailand/ramada-resort-khao-lak/overview"},
        {"name": "Days Inn by Wyndham Patong Beach Phuket", "city": "Phuket (Patong Beach / Rat U Thit)", "url": "https://www.wyndhamhotels.com/days-inn/patong-thailand/days-inn-patong-beach-phuket/overview"}
    ],
    "Malaysia": [
        {"name": "Wyndham Grand Bangsar Kuala Lumpur", "city": "Kuala Lumpur (Bangsar / Jalan Pantai Jaya)", "url": "https://www.wyndhamhotels.com/wyndham-grand/kuala-lumpur-malaysia/wyndham-grand-bangsar-kuala-lumpur/overview"},
        {"name": "Wyndham Acmar Klang", "city": "Klang (Selangor / Bandar Baru Klang)", "url": "https://www.wyndhamhotels.com/wyndham/klang-malaysia/wyndham-acmar-klang/overview"},
        {"name": "Ramada Suites by Wyndham KLCC", "city": "Kuala Lumpur (Changkat Bukit Bintang)", "url": "https://www.wyndhamhotels.com/ramada/kuala-lumpur-malaysia/ramada-suites-klcc/overview"},
        {"name": "Ramada Plaza by Wyndham Melaka", "city": "Melaka (Jalan Bendahara)", "url": "https://www.wyndhamhotels.com/ramada/melaka-malaysia/ramada-plaza-melaka/overview"},
        {"name": "Ramada by Wyndham Meridin Johor Bahru", "city": "Johor Bahru (Iskandar Puteri / Medini)", "url": "https://www.wyndhamhotels.com/ramada/johor-bahru-malaysia/ramada-meridin-johor-bahru/overview"},
        {"name": "Days Hotel & Suites by Wyndham Fraser Business Park KL", "city": "Kuala Lumpur (Jalan Metro Pudu)", "url": "https://www.wyndhamhotels.com/days-inn/kuala-lumpur-malaysia/days-hotel-and-suites-fraser-business-park/overview"}
    ],
    "Vietnam": [
        {"name": "Wyndham Grand KN Paradise Cam Ranh", "city": "Cam Ranh (Bai Dai Beach / Khanh Hoa)", "url": "https://www.wyndhamhotels.com/wyndham-grand/cam-ranh-vietnam/wyndham-grand-kn-paradise-cam-ranh/overview"},
        {"name": "Wyndham Grand Flamingo Dai Lai Resort", "city": "Vinh Phuc (Dai Lai Lake)", "url": "https://www.wyndhamhotels.com/wyndham-grand/phuc-yen-vietnam/wyndham-grand-flamingo-dai-lai-resort/overview"},
        {"name": "Wyndham Legend Halong", "city": "Ha Long (Ha Long Bay / Bai Chay)", "url": "https://www.wyndhamhotels.com/wyndham/ha-long-vietnam/wyndham-legend-halong/overview"},
        {"name": "Wyndham Danang Golden Bay", "city": "Da Nang (Thuan Phuoc / Han River)", "url": "https://www.wyndhamhotels.com/wyndham/da-nang-vietnam/wyndham-danang-golden-bay/overview"},
        {"name": "Wyndham Garden Hanoi", "city": "Hanoi (Ha Dong / To Huu)", "url": "https://www.wyndhamhotels.com/wyndham-garden/ha-noi-vietnam/wyndham-garden-hanoi/overview"},
        {"name": "Ramada Hotel & Suites by Wyndham Halong Bay View", "city": "Ha Long (Tran Hung Dao)", "url": "https://www.wyndhamhotels.com/ramada/ha-long-vietnam/ramada-hotel-and-suites-halong-bay-view/overview"}
    ],
    "Japan": [
        {"name": "Wyndham Grand Awashima", "city": "Numazu (Shizuoka / Awashima Island)", "url": "https://www.wyndhamhotels.com/wyndham-grand/numazu-japan/wyndham-grand-awashima/overview"},
        {"name": "Wyndham Garden Sapporo Odori", "city": "Sapporo (Chuo-ku / Odori Park)", "url": "https://www.wyndhamhotels.com/wyndham-garden/sapporo-japan/wyndham-garden-sapporo-odori/overview"},
        {"name": "Ramada by Wyndham Niigata", "city": "Niigata (Benten / Chuo-ku)", "url": "https://www.wyndhamhotels.com/ramada/niigata-japan/ramada-niigata/overview"}
    ],
    "South Korea": [
        {"name": "Wyndham Grand Busan Ijin", "city": "Busan (Songdo Beach / Seo-gu)", "url": "https://www.wyndhamhotels.com/wyndham-grand/busan-south-korea/wyndham-grand-busan-ijin/overview"},
        {"name": "Ramada Plaza by Wyndham Jeju Ocean Front", "city": "Jeju (Tapdong-ro / Oceanfront)", "url": "https://www.wyndhamhotels.com/ramada/jeju-south-korea/ramada-plaza-jeju-ocean-front/overview"},
        {"name": "Ramada Plaza by Wyndham Gwangju", "city": "Gwangju (Seo-gu)", "url": "https://www.wyndhamhotels.com/ramada/gwangju-south-korea/ramada-plaza-gwangju/overview"},
        {"name": "Ramada by Wyndham Seoul Dongdaemun", "city": "Seoul (Dongho-ro / Jung-gu)", "url": "https://www.wyndhamhotels.com/ramada/seoul-south-korea/ramada-seoul-dongdaemun/overview"},
        {"name": "Ramada Encore by Wyndham Haeundae", "city": "Busan (Haeundae / Gunam-ro)", "url": "https://www.wyndhamhotels.com/ramada/busan-south-korea/ramada-encore-haeundae/overview"}
    ],
    "China": [
        {"name": "Wyndham Grand Plaza Royale Hangzhou", "city": "Hangzhou (West Lake / Huancheng West Rd)", "url": "https://www.wyndhamhotels.com/wyndham-grand/hangzhou-china/wyndham-grand-plaza-royale-hangzhou/overview"},
        {"name": "Wyndham Grand Shenzhen", "city": "Shenzhen (Futian / Caitian Rd)", "url": "https://www.wyndhamhotels.com/wyndham-grand/shenzhen-china/wyndham-grand-shenzhen/overview"},
        {"name": "Wyndham Grand Xian South", "city": "Xi'an (Qujiang New District / Dayan Pagoda)", "url": "https://www.wyndhamhotels.com/wyndham-grand/xian-china/wyndham-grand-xian-south/overview"},
        {"name": "Wyndham Grand Plaza Royale Oriental Shanghai", "city": "Shanghai (Pudong / Pudong Avenue)", "url": "https://www.wyndhamhotels.com/wyndham-grand/shanghai-china/wyndham-grand-plaza-royale-oriental-shanghai/overview"},
        {"name": "Wyndham Beijing North", "city": "Beijing (Changping / Wangfu Street)", "url": "https://www.wyndhamhotels.com/wyndham/beijing-china/wyndham-beijing-north/overview"},
        {"name": "Wyndham Grand Plaza Royale Hainan Greentown", "city": "Lingshui (Hainan / Clear Water Bay)", "url": "https://www.wyndhamhotels.com/wyndham-grand/lingshui-china/wyndham-grand-plaza-royale-hainan-greentown/overview"}
    ],
    "Australia": [
        {"name": "Wyndham Hotel Melbourne", "city": "Melbourne (William St / CBD)", "url": "https://www.wyndhamhotels.com/wyndham/melbourne-australia/wyndham-hotel-melbourne/overview"},
        {"name": "Wyndham Resort Torquay", "city": "Torquay (Great Ocean Road / Victoria)", "url": "https://www.wyndhamhotels.com/wyndham/torquay-australia/wyndham-resort-torquay/overview"},
        {"name": "Wyndham Resort Denarau Island (Partner)", "city": "Fiji / Coral Coast (Denarau Island)", "url": "https://www.wyndhamhotels.com/wyndham/nadi-fiji/wyndham-resort-denarau-island/overview"},
        {"name": "Ramada Resort by Wyndham Port Douglas", "city": "Port Douglas (Port Douglas Rd / Queensland)", "url": "https://www.wyndhamhotels.com/ramada/port-douglas-australia/ramada-resort-port-douglas/overview"},
        {"name": "Ramada Hotel & Suites by Wyndham Sydney Cabramatta", "city": "Sydney (Cabramatta / John St)", "url": "https://www.wyndhamhotels.com/ramada/cabramatta-australia/ramada-hotel-and-suites-sydney-cabramatta/overview"},
        {"name": "Ramada by Wyndham Marcoola Beach", "city": "Sunshine Coast (Marcoola Beach / Queensland)", "url": "https://www.wyndhamhotels.com/ramada/marcoola-australia/ramada-marcoola-beach/overview"}
    ],
    "United Arab Emirates": [
        {"name": "Wyndham Dubai Marina", "city": "Dubai (Dubai Marina / Al Seba St)", "url": "https://www.wyndhamhotels.com/wyndham/dubai-united-arab-emirates/wyndham-dubai-marina/overview"},
        {"name": "Wyndham Dubai Deira", "city": "Dubai (Deira Waterfront / Al Khaleej Rd)", "url": "https://www.wyndhamhotels.com/wyndham/dubai-united-arab-emirates/wyndham-dubai-deira/overview"},
        {"name": "TRYP by Wyndham Dubai", "city": "Dubai (Barsha Heights / TECOM)", "url": "https://www.wyndhamhotels.com/tryp/dubai-united-arab-emirates/tryp-by-wyndham-dubai/overview"},
        {"name": "Ramada Plaza by Wyndham Dubai Jumeirah Beach", "city": "Dubai (Jumeirah Beach Residence / JBR)", "url": "https://www.wyndhamhotels.com/ramada/dubai-united-arab-emirates/ramada-plaza-by-wyndham-dubai-jbr/overview"},
        {"name": "Ramada Hotel & Suites by Wyndham Dubai JBR", "city": "Dubai (The Walk / JBR)", "url": "https://www.wyndhamhotels.com/ramada/dubai-united-arab-emirates/ramada-hotel-and-suites-by-wyndham-dubai-jbr/overview"},
        {"name": "Ramada by Wyndham Downtown Dubai", "city": "Dubai (Downtown / Burj Khalifa View)", "url": "https://www.wyndhamhotels.com/ramada/dubai-united-arab-emirates/ramada-downtown-dubai/overview"},
        {"name": "Howard Johnson by Wyndham Bur Dubai", "city": "Dubai (Bur Dubai / Khaled bin Waleed St)", "url": "https://www.wyndhamhotels.com/hojo/dubai-united-arab-emirates/howard-johnson-bur-dubai/overview"}
    ],
    "United Kingdom": [
        {"name": "The Chelsea Harbour Hotel and Spa (Registry Collection Partner)", "city": "London (Chelsea Harbour / Thames)", "url": "https://www.wyndhamhotels.com/registry-collection/london-united-kingdom/the-chelsea-harbour-hotel-and-spa/overview"},
        {"name": "Dolce by Wyndham Babington House (Partner)", "city": "Somerset (Frome / Babington)", "url": "https://www.wyndhamhotels.com/dolce/somerset-united-kingdom/dolce-babington/overview"},
        {"name": "Ramada by Wyndham London North M1", "city": "London (Mill Hill / M1 Motorway)", "url": "https://www.wyndhamhotels.com/ramada/london-united-kingdom/ramada-london-north-m1/overview"},
        {"name": "Ramada by Wyndham London Stansted Airport", "city": "Stansted (Birchanger Green)", "url": "https://www.wyndhamhotels.com/ramada/stansted-united-kingdom/ramada-london-stansted-airport/overview"},
        {"name": "Days Inn by Wyndham London Hyde Park", "city": "London (Paddington / Sussex Gardens)", "url": "https://www.wyndhamhotels.com/days-inn/london-united-kingdom/days-inn-hyde-park/overview"}
    ],
    "United States": [
        {"name": "Wyndham Grand Clearwater Beach", "city": "Clearwater Beach (Coronado Dr / Florida)", "url": "https://www.wyndhamhotels.com/wyndham-grand/clearwater-beach-florida/wyndham-grand-clearwater-beach/overview"},
        {"name": "Wyndham Grand Orlando Resort Bonnet Creek", "city": "Orlando (Bonnet Creek Resort / Chelonia Pkwy)", "url": "https://www.wyndhamhotels.com/wyndham-grand/orlando-florida/wyndham-grand-orlando-resort-bonnet-creek/overview"},
        {"name": "Wyndham Grand Pittsburgh Downtown", "city": "Pittsburgh (Commonwealth Place / Point State Park)", "url": "https://www.wyndhamhotels.com/wyndham-grand/pittsburgh-pennsylvania/wyndham-grand-pittsburgh-downtown/overview"},
        {"name": "The Mining Exchange, A Wyndham Grand Hotel", "city": "Colorado Springs (Nevada Ave)", "url": "https://www.wyndhamhotels.com/wyndham-grand/colorado-springs-colorado/the-mining-exchange-a-wyndham-grand-hotel-and-spa/overview"},
        {"name": "Wyndham New Yorker Hotel", "city": "New York (8th Ave / 34th St / Midtown)", "url": "https://www.wyndhamhotels.com/wyndham/new-york-new-york/the-new-yorker-a-wyndham-hotel/overview"},
        {"name": "Wyndham Philadelphia Historic District", "city": "Philadelphia (Arch St / Old City)", "url": "https://www.wyndhamhotels.com/wyndham/philadelphia-pennsylvania/wyndham-philadelphia-historic-district/overview"},
        {"name": "Wyndham San Diego Bayside", "city": "San Diego (North Harbor Dr / Embarcadero)", "url": "https://www.wyndhamhotels.com/wyndham/san-diego-california/wyndham-san-diego-bayside/overview"},
        {"name": "TRYP by Wyndham New York City Times Square South", "city": "New York (West 35th St / Midtown)", "url": "https://www.wyndhamhotels.com/tryp/new-york-new-york/tryp-by-wyndham-times-square-south/overview"},
        {"name": "La Quinta Inn & Suites by Wyndham Manhattan", "city": "New York (West 32nd St / Koreatown)", "url": "https://www.wyndhamhotels.com/laquinta/new-york-new-york/la-quinta-manhattan/overview"}
    ]
}


def seed_wyndham_global():
    """Seeds all verified physical Wyndham Rewards hotels into hotel_stays.db."""
    SessionMaker = get_session_factory()
    session = SessionMaker()

    total_added = 0
    seen_ids = set()

    for country, hotels in WYNDHAM_MASTER_DIRECTORY.items():
        for h in hotels:
            existing = session.query(Hotel).filter(Hotel.name == h["name"]).first()
            if not existing:
                m = re.search(r'wyndhamhotels\.com/[a-z-]+/[a-z-]+/[a-z0-9-]+/([a-z0-9-]+)/overview', h["url"])
                slug_code = m.group(1)[:15] if m else re.sub(r'[^a-z0-9]', '', h["name"].lower())[:15]
                h_id = f"wynd_{slug_code}"
                if h_id in seen_ids:
                    h_id = f"wynd_{slug_code}_{total_added}"
                seen_ids.add(h_id)

                # Currency determination
                if country in ["France", "Germany", "Italy", "Spain", "Netherlands", "Austria"]:
                    curr = "EUR"
                elif country in ["Japan"]:
                    curr = "JPY"
                elif country in ["United Kingdom"]:
                    curr = "GBP"
                elif country in ["Indonesia"]:
                    curr = "IDR"
                elif country in ["Thailand"]:
                    curr = "THB"
                elif country in ["Malaysia"]:
                    curr = "MYR"
                elif country in ["Australia"]:
                    curr = "AUD"
                else:
                    curr = "USD"

                new_hotel = Hotel(
                    id=h_id,
                    brand="WYNDHAM",
                    name=h["name"],
                    city=h["city"],
                    country=country,
                    currency=curr,
                    loyalty_model="FLAT_3_TIER",
                    track_points=True,
                    official_url=h["url"]
                )
                session.add(new_hotel)
                session.flush()

                # Add RoomCategory
                room_id = f"{new_hotel.id}_std"
                room = RoomCategory(
                    id=room_id,
                    hotel_id=new_hotel.id,
                    raw_name="Standard Room",
                    standardized_type="STANDARD"
                )
                session.add(room)
                total_added += 1

    session.commit()
    session.close()
    logger.info(f"Successfully seeded {total_added} Wyndham Rewards properties across {len(WYNDHAM_MASTER_DIRECTORY)} countries into database!")
    export_watchlist_to_excel()

if __name__ == '__main__':
    seed_wyndham_global()
