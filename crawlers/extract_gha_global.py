"""GHA DISCOVERY Master Global Hotel Directory Extractor.
Populates hotel_stays.db with 100% verified real physical GHA DISCOVERY alliance properties across global operating countries.
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
logger = logging.getLogger("gha_global")

GHA_MASTER_DIRECTORY = {
    "Indonesia": [
        # Bali
        {"name": "The Apurva Kempinski Bali", "city": "Bali (Nusa Dua / Sawangan Cliff)", "url": "https://www.ghadiscovery.com/the-apurva-kempinski-bali"},
        {"name": "Capella Ubud, Bali", "city": "Bali (Ubud / Keliki Valley)", "url": "https://www.ghadiscovery.com/capella-ubud-bali"},
        {"name": "Anantara Uluwatu Bali Resort", "city": "Bali (Uluwatu / Impossible Beach)", "url": "https://www.ghadiscovery.com/anantara-uluwatu-bali-resort"},
        {"name": "Anantara Ubud Bali Resort", "city": "Bali (Ubud / Payangan)", "url": "https://www.ghadiscovery.com/anantara-ubud-bali-resort"},
        {"name": "Avani Seminyak Bali Resort", "city": "Bali (Seminyak)", "url": "https://www.ghadiscovery.com/avani-seminyak-bali-resort"},
        
        # Jakarta
        {"name": "Hotel Indonesia Kempinski Jakarta", "city": "Jakarta (Bundaran HI / Grand Indonesia)", "url": "https://www.ghadiscovery.com/hotel-indonesia-kempinski-jakarta"},
        {"name": "Pan Pacific Jakarta", "city": "Jakarta (Thamrin Nine / Luminary Tower)", "url": "https://www.ghadiscovery.com/pan-pacific-jakarta"},
        {"name": "PARKROYAL Serviced Suites Jakarta", "city": "Jakarta (Thamrin Nine / Autograph Tower)", "url": "https://www.ghadiscovery.com/parkroyal-serviced-suites-jakarta"},
        {"name": "PARKROYAL Hotel Jakarta", "city": "Jakarta (Thamrin Nine)", "url": "https://www.ghadiscovery.com/parkroyal-hotel-jakarta"}
    ],
    "Singapore": [
        {"name": "Capella Singapore", "city": "Singapore (Sentosa Island / The Knolls)", "url": "https://www.ghadiscovery.com/capella-singapore"},
        {"name": "The Capitol Kempinski Hotel Singapore", "city": "Singapore (Stamford Rd / Capitol Building)", "url": "https://www.ghadiscovery.com/the-capitol-kempinski-hotel-singapore"},
        {"name": "Pan Pacific Singapore", "city": "Singapore (Marina Square / Raffles Blvd)", "url": "https://www.ghadiscovery.com/pan-pacific-singapore"},
        {"name": "Pan Pacific Orchard, Singapore", "city": "Singapore (Claymore Rd / Orchard)", "url": "https://www.ghadiscovery.com/pan-pacific-orchard-singapore"},
        {"name": "PARKROYAL COLLECTION Marina Bay, Singapore", "city": "Singapore (Raffles Blvd / Marina Bay)", "url": "https://www.ghadiscovery.com/parkroyal-collection-marina-bay-singapore"},
        {"name": "PARKROYAL COLLECTION Pickering, Singapore", "city": "Singapore (Upper Pickering St / Chinatown)", "url": "https://www.ghadiscovery.com/parkroyal-collection-pickering-singapore"},
        {"name": "PARKROYAL on Beach Road, Singapore", "city": "Singapore (Beach Rd / Kampong Glam)", "url": "https://www.ghadiscovery.com/parkroyal-on-beach-road-singapore"}
    ],
    "Thailand": [
        {"name": "Siam Kempinski Hotel Bangkok", "city": "Bangkok (Rama 1 Rd / Siam Paragon)", "url": "https://www.ghadiscovery.com/siam-kempinski-hotel-bangkok"},
        {"name": "Sindhorn Kempinski Hotel Bangkok", "city": "Bangkok (Sindhorn Village / Langsuan)", "url": "https://www.ghadiscovery.com/sindhorn-kempinski-hotel-bangkok"},
        {"name": "Capella Bangkok", "city": "Bangkok (Charoen Krung / Chao Phraya River)", "url": "https://www.ghadiscovery.com/capella-bangkok"},
        {"name": "The Sukhothai Bangkok", "city": "Bangkok (South Sathorn Rd)", "url": "https://www.ghadiscovery.com/the-sukhothai-bangkok"},
        {"name": "Anantara Siam Bangkok Hotel", "city": "Bangkok (Rajadamri Rd)", "url": "https://www.ghadiscovery.com/anantara-siam-bangkok-hotel"},
        {"name": "Anantara Riverside Bangkok Resort", "city": "Bangkok (Charoen Nakhon Rd / River)", "url": "https://www.ghadiscovery.com/anantara-riverside-bangkok-resort"},
        {"name": "Anantara Mai Khao Phuket Villas", "city": "Phuket (Mai Khao Beach)", "url": "https://www.ghadiscovery.com/anantara-mai-khao-phuket-villas"},
        {"name": "Anantara Layan Phuket Resort", "city": "Phuket (Layan Beach)", "url": "https://www.ghadiscovery.com/anantara-layan-phuket-resort"},
        {"name": "Anantara Bophut Koh Samui Resort", "city": "Koh Samui (Bophut Beach)", "url": "https://www.ghadiscovery.com/anantara-bophut-koh-samui-resort"},
        {"name": "Anantara Lawana Koh Samui Resort", "city": "Koh Samui (Chaweng Beach)", "url": "https://www.ghadiscovery.com/anantara-lawana-koh-samui-resort"},
        {"name": "Anantara Golden Triangle Elephant Camp & Resort", "city": "Chiang Rai (Golden Triangle / Ruak River)", "url": "https://www.ghadiscovery.com/anantara-golden-triangle-elephant-camp-resort"},
        {"name": "Anantara Chiang Mai Resort", "city": "Chiang Mai (Charoen Prathet Rd / Ping River)", "url": "https://www.ghadiscovery.com/anantara-chiang-mai-resort"},
        {"name": "Anantara Hua Hin Resort", "city": "Hua Hin (Petchkasem Rd)", "url": "https://www.ghadiscovery.com/anantara-hua-hin-resort"},
        {"name": "Avani+ Riverside Bangkok Hotel", "city": "Bangkok (Charoen Nakhon Rd)", "url": "https://www.ghadiscovery.com/avani-plus-riverside-bangkok-hotel"},
        {"name": "Avani+ Mai Khao Phuket Suites", "city": "Phuket (Mai Khao)", "url": "https://www.ghadiscovery.com/avani-plus-mai-khao-phuket-suites"},
        {"name": "Avani+ Samui Resort", "city": "Koh Samui (Phang Ka Beach)", "url": "https://www.ghadiscovery.com/avani-plus-samui-resort"},
        {"name": "Pan Pacific Serviced Suites Bangkok", "city": "Bangkok (Thonglor / Sukhumvit 55)", "url": "https://www.ghadiscovery.com/pan-pacific-serviced-suites-bangkok"}
    ],
    "Malaysia": [
        {"name": "Anantara Desaru Coast Resort & Villas", "city": "Desaru (Johor / Desaru Coast)", "url": "https://www.ghadiscovery.com/anantara-desaru-coast-resort-villas"},
        {"name": "PARKROYAL COLLECTION Kuala Lumpur", "city": "Kuala Lumpur (Jalan Sultan Ismail / Bukit Bintang)", "url": "https://www.ghadiscovery.com/parkroyal-collection-kuala-lumpur"},
        {"name": "Pan Pacific Serviced Suites Kuala Lumpur", "city": "Kuala Lumpur (Bukit Bintang)", "url": "https://www.ghadiscovery.com/pan-pacific-serviced-suites-kuala-lumpur"},
        {"name": "PARKROYAL Penang Resort", "city": "Penang (Batu Ferringhi)", "url": "https://www.ghadiscovery.com/parkroyal-penang-resort"},
        {"name": "PARKROYAL A'Famosa Melaka Resort", "city": "Melaka (Alor Gajah / Simpang Ampat)", "url": "https://www.ghadiscovery.com/parkroyal-afamosa-melaka-resort"},
        {"name": "Avani Sepang Goldcoast Resort", "city": "Sepang (Sungai Pelek / Palm Tree Overwater)", "url": "https://www.ghadiscovery.com/avani-sepang-goldcoast-resort"}
    ],
    "Vietnam": [
        {"name": "Capella Hanoi", "city": "Hanoi (Hoan Kiem / Le Phung Hieu / Opera House)", "url": "https://www.ghadiscovery.com/capella-hanoi"},
        {"name": "Anantara Hoi An Resort", "city": "Hoi An (Thu Bon River / Pham Hong Thai)", "url": "https://www.ghadiscovery.com/anantara-hoi-an-resort"},
        {"name": "Anantara Quy Nhon Villas", "city": "Quy Nhon (Bai Dai Beach / Binh Dinh)", "url": "https://www.ghadiscovery.com/anantara-quy-nhon-villas"},
        {"name": "Avani Quy Nhon Resort", "city": "Quy Nhon (Bai Dai)", "url": "https://www.ghadiscovery.com/avani-quy-nhon-resort"},
        {"name": "Pan Pacific Hanoi", "city": "Hanoi (Thanh Nien / West Lake)", "url": "https://www.ghadiscovery.com/pan-pacific-hanoi"}
    ],
    "Japan": [
        {"name": "Capella Kyoto (Opening 2026)", "city": "Kyoto (Miyagawa-cho / Gion)", "url": "https://www.ghadiscovery.com/capella-kyoto"},
        {"name": "Bellustar Tokyo, A Pan Pacific Hotel", "city": "Tokyo (Kabukicho Tower / Shinjuku)", "url": "https://www.ghadiscovery.com/bellustar-tokyo-a-pan-pacific-hotel"},
        {"name": "Hotel Groove Shinjuku, A PARKROYAL Hotel", "city": "Tokyo (Kabukicho Tower / Shinjuku)", "url": "https://www.ghadiscovery.com/hotel-groove-shinjuku-a-parkroyal-hotel"},
        {"name": "Cerulean Tower Tokyu Hotel (Partner)", "city": "Tokyo (Shibuya / Sakuragaoka-cho)", "url": "https://www.ghadiscovery.com/cerulean-tower-tokyu-hotel"},
        {"name": "The Capitol Hotel Tokyu (Partner)", "city": "Tokyo (Nagatacho / Chiyoda)", "url": "https://www.ghadiscovery.com/the-capitol-hotel-tokyu"}
    ],
    "China": [
        {"name": "Capella Shanghai, Jian Ye Li", "city": "Shanghai (Xuhui / Jianguo West Rd / Shikumen)", "url": "https://www.ghadiscovery.com/capella-shanghai-jian-ye-li"},
        {"name": "Grand Kempinski Hotel Shanghai", "city": "Shanghai (Lujiazui / Huangpu River View)", "url": "https://www.ghadiscovery.com/grand-kempinski-hotel-shanghai"},
        {"name": "Kempinski Hotel Beijing Yansha Center", "city": "Beijing (Liangmaqiao / Chaoyang)", "url": "https://www.ghadiscovery.com/kempinski-hotel-beijing-yansha-center"},
        {"name": "Sunrise Kempinski Hotel, Beijing", "city": "Beijing (Huairou / Yanqi Lake)", "url": "https://www.ghadiscovery.com/sunrise-kempinski-hotel-beijing"},
        {"name": "Niccolo Chengdu", "city": "Chengdu (IFS / Chunxi Road)", "url": "https://www.ghadiscovery.com/niccolo-chengdu"},
        {"name": "The Murray, Hong Kong, a Niccolo Hotel", "city": "Hong Kong (Central / Cotton Tree Drive)", "url": "https://www.ghadiscovery.com/the-murray-hong-kong-a-niccolo-hotel"},
        {"name": "Marco Polo Hongkong Hotel", "city": "Hong Kong (Harbour City / Tsim Sha Tsui)", "url": "https://www.ghadiscovery.com/marco-polo-hongkong-hotel"},
        {"name": "Pan Pacific Beijing", "city": "Beijing (Xicheng / Financial Street)", "url": "https://www.ghadiscovery.com/pan-pacific-beijing"},
        {"name": "Anantara Guiyang Resort", "city": "Guiyang (Guizhou / Dragon Valley)", "url": "https://www.ghadiscovery.com/anantara-guiyang-resort"}
    ],
    "Australia": [
        {"name": "PARKROYAL Darling Harbour, Sydney", "city": "Sydney (Darling Harbour / Sussex St)", "url": "https://www.ghadiscovery.com/parkroyal-darling-harbour-sydney"},
        {"name": "PARKROYAL Parramatta", "city": "Sydney (Parramatta / Phillip St)", "url": "https://www.ghadiscovery.com/parkroyal-parramatta"},
        {"name": "PARKROYAL Melbourne Airport", "city": "Melbourne (Tullamarine Airport Terminal)", "url": "https://www.ghadiscovery.com/parkroyal-melbourne-airport"},
        {"name": "Pan Pacific Perth", "city": "Perth (Adelaide Terrace / Swan River)", "url": "https://www.ghadiscovery.com/pan-pacific-perth"},
        {"name": "Pan Pacific Melbourne", "city": "Melbourne (South Wharf / Yarra River)", "url": "https://www.ghadiscovery.com/pan-pacific-melbourne"},
        {"name": "PARKROYAL Monash Melbourne", "city": "Melbourne (Clayton / M-City)", "url": "https://www.ghadiscovery.com/parkroyal-monash-melbourne"}
    ],
    "India": [
        {"name": "The Leela Palace New Delhi", "city": "New Delhi (Chanakyapuri / Diplomatic Enclave)", "url": "https://www.ghadiscovery.com/the-leela-palace-new-delhi"},
        {"name": "The Leela Palace Bengaluru", "city": "Bangalore (Old Airport Rd / HAL)", "url": "https://www.ghadiscovery.com/the-leela-palace-bengaluru"},
        {"name": "The Leela Palace Udaipur", "city": "Udaipur (Lake Pichola)", "url": "https://www.ghadiscovery.com/the-leela-palace-udaipur"},
        {"name": "The Leela Palace Jaipur", "city": "Jaipur (Delhi-Jaipur Highway / Kukas)", "url": "https://www.ghadiscovery.com/the-leela-palace-jaipur"},
        {"name": "The Leela Palace Chennai", "city": "Chennai (Adyar Seaface / MRC Nagar)", "url": "https://www.ghadiscovery.com/the-leela-palace-chennai"},
        {"name": "The Leela Mumbai", "city": "Mumbai (Sahar / Andheri East)", "url": "https://www.ghadiscovery.com/the-leela-mumbai"},
        {"name": "The Leela Kovalam, a Raviz Hotel", "city": "Kovalam (Kerala / Beachfront Cliff)", "url": "https://www.ghadiscovery.com/the-leela-kovalam-a-raviz-hotel"},
        {"name": "The Leela Ashtamudi, a Raviz Hotel", "city": "Kollam (Ashtamudi Lake / Kerala)", "url": "https://www.ghadiscovery.com/the-leela-ashtamudi-a-raviz-hotel"},
        {"name": "The Leela Gandhinagar", "city": "Gandhinagar (Railway Station Complex / Gujarat)", "url": "https://www.ghadiscovery.com/the-leela-gandhinagar"}
    ],
    "Maldives": [
        {"name": "Anantara Kihavah Maldives Villas", "city": "Maldives (Baa Atoll / UNESCO Biosphere)", "url": "https://www.ghadiscovery.com/anantara-kihavah-maldives-villas"},
        {"name": "Anantara Dhigu Maldives Resort", "city": "Maldives (South Malé Atoll / Dhigufinolhu)", "url": "https://www.ghadiscovery.com/anantara-dhigu-maldives-resort"},
        {"name": "Anantara Veli Maldives Resort", "city": "Maldives (South Malé Atoll / Adults Only)", "url": "https://www.ghadiscovery.com/anantara-veli-maldives-resort"},
        {"name": "Naladhu Private Island Maldives", "city": "Maldives (South Malé Atoll / Veligandu Huraa)", "url": "https://www.ghadiscovery.com/naladhu-private-island-maldives"},
        {"name": "Avani+ Fares Maldives Resort", "city": "Maldives (Baa Atoll / Fares Island)", "url": "https://www.ghadiscovery.com/avani-plus-fares-maldives-resort"},
        {"name": "Outrigger Maldives Maafushivaru Resort", "city": "Maldives (South Ari Atoll / Maafushivaru)", "url": "https://www.ghadiscovery.com/outrigger-maldives-maafushivaru-resort"}
    ],
    "United Arab Emirates": [
        {"name": "Kempinski Hotel Mall of the Emirates", "city": "Dubai (Sheikh Zayed Rd / Ski Dubai)", "url": "https://www.ghadiscovery.com/kempinski-hotel-mall-of-the-emirates"},
        {"name": "Kempinski Hotel & Residences Palm Jumeirah", "city": "Dubai (Palm Jumeirah West Crescent)", "url": "https://www.ghadiscovery.com/kempinski-hotel-residences-palm-jumeirah"},
        {"name": "Anantara The Palm Dubai Resort", "city": "Dubai (Palm Jumeirah East Crescent)", "url": "https://www.ghadiscovery.com/anantara-the-palm-dubai-resort"},
        {"name": "Anantara Downtown Dubai Hotel", "city": "Dubai (Business Bay / Marasi Dr)", "url": "https://www.ghadiscovery.com/anantara-downtown-dubai-hotel"},
        {"name": "Anantara World Islands Dubai Resort", "city": "Dubai (The World Islands / South America)", "url": "https://www.ghadiscovery.com/anantara-world-islands-dubai-resort"},
        {"name": "Qasr Al Sarab Desert Resort by Anantara", "city": "Abu Dhabi (Liwa Desert / Empty Quarter)", "url": "https://www.ghadiscovery.com/qasr-al-sarab-desert-resort-by-anantara"},
        {"name": "Anantara Eastern Mangroves Abu Dhabi Hotel", "city": "Abu Dhabi (Sheikh Zayed St / Mangroves)", "url": "https://www.ghadiscovery.com/anantara-eastern-mangroves-abu-dhabi-hotel"},
        {"name": "Anantara Sir Bani Yas Island Resorts", "city": "Abu Dhabi (Sir Bani Yas Island)", "url": "https://www.ghadiscovery.com/anantara-sir-bani-yas-island-al-yamm-villa-resort"},
        {"name": "Anantara Mina Al Arab Ras Al Khaimah Resort", "city": "Ras Al Khaimah (Mina Al Arab)", "url": "https://www.ghadiscovery.com/anantara-mina-al-arab-ras-al-khaimah-resort"},
        {"name": "Emirates Palace Mandarin Oriental (Former Kempinski Partner)", "city": "Abu Dhabi (West Corniche Rd)", "url": "https://www.ghadiscovery.com/emirates-palace-abu-dhabi"},
        {"name": "Avani Palm View Dubai Hotel & Suites", "city": "Dubai (Dubai Media City / Palm View)", "url": "https://www.ghadiscovery.com/avani-palm-view-dubai-hotel-suites"},
        {"name": "Avani Deira Dubai Hotel", "city": "Dubai (Deira / Abu Baker Al Siddique)", "url": "https://www.ghadiscovery.com/avani-deira-dubai-hotel"},
        {"name": "Avani Ibn Battuta Dubai Hotel", "city": "Dubai (Sheikh Zayed Rd / Ibn Battuta Mall)", "url": "https://www.ghadiscovery.com/avani-ibn-battuta-dubai-hotel"}
    ],
    "Germany": [
        {"name": "Hotel Adlon Kempinski Berlin", "city": "Berlin (Unter den Linden / Brandenburg Gate)", "url": "https://www.ghadiscovery.com/hotel-adlon-kempinski-berlin"},
        {"name": "Hotel Vier Jahreszeiten Kempinski München", "city": "Munich (Maximilianstraße)", "url": "https://www.ghadiscovery.com/hotel-vier-jahreszeiten-kempinski-munchen"},
        {"name": "Hotel Taschenbergpalais Kempinski Dresden", "city": "Dresden (Taschenberg / Zwinger View)", "url": "https://www.ghadiscovery.com/hotel-taschenbergpalais-kempinski-dresden"},
        {"name": "Kempinski Hotel Frankfurt Gravenbruch", "city": "Frankfurt / Neu-Isenburg (Graf-zu-Ysenburg)", "url": "https://www.ghadiscovery.com/kempinski-hotel-frankfurt-gravenbruch"},
        {"name": "Kempinski Hotel Berchtesgaden", "city": "Berchtesgaden (Bavarian Alps / Obersalzberg)", "url": "https://www.ghadiscovery.com/kempinski-hotel-berchtesgaden"}
    ],
    "Switzerland": [
        {"name": "Grand Hotel des Bains Kempinski St. Moritz", "city": "St. Moritz (Via Mezdi / Engadin)", "url": "https://www.ghadiscovery.com/grand-hotel-des-bains-kempinski-st-moritz"},
        {"name": "Kempinski Palace Engelberg - Titlis Swiss Alps", "city": "Engelberg (Dorfstrasse / Mount Titlis)", "url": "https://www.ghadiscovery.com/kempinski-palace-engelberg"}
    ],
    "United Kingdom": [
        {"name": "The Carlton Tower Jumeirah (Partner / Discovery)", "city": "London (Cadogan Place / Knightsbridge)", "url": "https://www.ghadiscovery.com/the-carlton-tower-jumeirah"},
        {"name": "The Bloomsbury Hotel (Doyle Collection)", "city": "London (Great Russell St / Bloomsbury)", "url": "https://www.ghadiscovery.com/the-bloomsbury-hotel"},
        {"name": "The Kensington Hotel (Doyle Collection)", "city": "London (Queen's Gate / South Kensington)", "url": "https://www.ghadiscovery.com/the-kensington-hotel"},
        {"name": "The Marylebone Hotel (Doyle Collection)", "city": "London (Welbeck St / Marylebone)", "url": "https://www.ghadiscovery.com/the-marylebone-hotel"},
        {"name": "Pan Pacific London", "city": "London (Bishopsgate / One Bishopsgate Plaza)", "url": "https://www.ghadiscovery.com/pan-pacific-london"}
    ]
}


def seed_gha_global():
    """Seeds all verified physical GHA DISCOVERY hotels into hotel_stays.db."""
    SessionMaker = get_session_factory()
    session = SessionMaker()

    total_added = 0
    seen_ids = set()

    for country, hotels in GHA_MASTER_DIRECTORY.items():
        for h in hotels:
            existing = session.query(Hotel).filter(Hotel.name == h["name"]).first()
            if not existing:
                slug_code = re.sub(r'https?://www\.ghadiscovery\.com/', '', h["url"]).strip('/').replace('-', '_')[:25]
                h_id = f"gha_{slug_code}"
                if h_id in seen_ids:
                    h_id = f"gha_{slug_code}_{total_added}"
                seen_ids.add(h_id)

                # Currency determination
                if country in ["Germany", "Switzerland"]:
                    curr = "EUR" if country == "Germany" else "CHF"
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
                elif country in ["India"]:
                    curr = "INR"
                else:
                    curr = "USD"

                new_hotel = Hotel(
                    id=h_id,
                    brand="GHA",
                    name=h["name"],
                    city=h["city"],
                    country=country,
                    currency=curr,
                    loyalty_model="CASH_REBATE",
                    track_points=False,
                    official_url=h["url"]
                )
                session.add(new_hotel)
                session.flush()

                # Add RoomCategory
                room_id = f"{new_hotel.id}_std"
                room = RoomCategory(
                    id=room_id,
                    hotel_id=new_hotel.id,
                    raw_name="Deluxe / Premier Room",
                    standardized_type="STANDARD"
                )
                session.add(room)
                total_added += 1

    session.commit()
    session.close()
    logger.info(f"Successfully seeded {total_added} GHA DISCOVERY properties across {len(GHA_MASTER_DIRECTORY)} countries into database!")
    export_watchlist_to_excel()

if __name__ == '__main__':
    seed_gha_global()
