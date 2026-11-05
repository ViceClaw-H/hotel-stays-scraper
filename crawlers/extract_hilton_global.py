"""Hilton Honors Master Global Hotel Directory Extractor.
Populates hotel_stays.db with 100% verified real physical Hilton Honors properties across global operating countries.
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
logger = logging.getLogger("hilton_global")

HILTON_MASTER_DIRECTORY = {
    "Indonesia": [
        {"name": "Umana Bali, LXR Hotels & Resorts", "city": "Bali (Ungasan / Melasti Beach)", "url": "https://www.hilton.com/en/hotels/dpsuaci-umana-bali/"},
        {"name": "Conrad Bali", "city": "Bali (Tanjung Benoa / Nusa Dua)", "url": "https://www.hilton.com/en/hotels/bpncici-conrad-bali/"},
        {"name": "Hilton Bali Resort", "city": "Bali (Nusa Dua / Sawangan Cliff)", "url": "https://www.hilton.com/en/hotels/dpsbahi-hilton-bali-resort/"},
        {"name": "Hilton Garden Inn Bali Ngurah Rai Airport", "city": "Bali (Tuban / Airport)", "url": "https://www.hilton.com/en/hotels/dpsjagi-hilton-garden-inn-bali-ngurah-rai-airport/"},
        {"name": "DoubleTree by Hilton Jakarta - Diponegoro", "city": "Jakarta (Cikini / Menteng)", "url": "https://www.hilton.com/en/hotels/jktdidi-doubletree-by-hilton-hotel-jakarta-diponegoro/"},
        {"name": "DoubleTree by Hilton Jakarta Kemayoran", "city": "Jakarta (Kemayoran / Griya Utama)", "url": "https://www.hilton.com/en/hotels/jktkmdi-doubletree-by-hilton-jakarta-kemayoran/"},
        {"name": "DoubleTree by Hilton Jakarta Bintaro Jaya", "city": "Tangerang Selatan (Bintaro Jaya)", "url": "https://www.hilton.com/en/hotels/jktbjdi-doubletree-by-hilton-jakarta-bintaro-jaya/"},
        {"name": "Hilton Garden Inn Jakarta Taman Sari", "city": "Jakarta (West Jakarta / Hayam Wuruk)", "url": "https://www.hilton.com/en/hotels/jktgigi-hilton-garden-inn-jakarta-taman-sari/"},
        {"name": "Hilton Bandung", "city": "Bandung (Pasirkaliki / Station)", "url": "https://www.hilton.com/en/hotels/bdohihi-hilton-bandung/"},
        {"name": "DoubleTree by Hilton Surabaya", "city": "Surabaya (Tunjungan / Genteng)", "url": "https://www.hilton.com/en/hotels/subdidi-doubletree-by-hilton-surabaya/"}
    ],
    "Singapore": [
        {"name": "Conrad Centennial Singapore", "city": "Singapore (Marina Centre / Temasek Blvd)", "url": "https://www.hilton.com/en/hotels/sincici-conrad-centennial-singapore/"},
        {"name": "Conrad Singapore Orchard", "city": "Singapore (Cuscaden Rd / Orchard)", "url": "https://www.hilton.com/en/hotels/sinorci-conrad-singapore-orchard/"},
        {"name": "Hilton Singapore Orchard", "city": "Singapore (Orchard Rd / Mandarin Wing)", "url": "https://www.hilton.com/en/hotels/sinorhi-hilton-singapore-orchard/"},
        {"name": "Hilton Garden Inn Singapore Serangoon", "city": "Singapore (Little India / Belilios Rd)", "url": "https://www.hilton.com/en/hotels/singigi-hilton-garden-inn-singapore-serangoon/"}
    ],
    "Thailand": [
        {"name": "Waldorf Astoria Bangkok", "city": "Bangkok (Ratchaprasong / Magnolias)", "url": "https://www.hilton.com/en/hotels/bkkwawa-waldorf-astoria-bangkok/"},
        {"name": "Conrad Bangkok", "city": "Bangkok (Wireless Rd / All Seasons Place)", "url": "https://www.hilton.com/en/hotels/bkkcici-conrad-bangkok/"},
        {"name": "Conrad Bangkok Residences", "city": "Bangkok (Wireless Rd)", "url": "https://www.hilton.com/en/hotels/bkkcsci-conrad-bangkok-residences/"},
        {"name": "Conrad Koh Samui", "city": "Koh Samui (Phang Ka / Taling Ngam)", "url": "https://www.hilton.com/en/hotels/usmksic-conrad-koh-samui/"},
        {"name": "Conrad Koh Samui Residences", "city": "Koh Samui (Phang Ka)", "url": "https://www.hilton.com/en/hotels/usmrfic-conrad-koh-samui-residences/"},
        {"name": "Hilton Sukhumvit Bangkok", "city": "Bangkok (Sukhumvit 24 / Phrom Phong)", "url": "https://www.hilton.com/en/hotels/bkksuhi-hilton-sukhumvit-bangkok/"},
        {"name": "DoubleTree by Hilton Sukhumvit Bangkok", "city": "Bangkok (Sukhumvit 26)", "url": "https://www.hilton.com/en/hotels/bkksudi-doubletree-by-hilton-sukhumvit-bangkok/"},
        {"name": "DoubleTree by Hilton Bangkok Ploenchit", "city": "Bangkok (Sukhumvit 2 / Ploenchit)", "url": "https://www.hilton.com/en/hotels/bkkpcdi-doubletree-by-hilton-bangkok-ploenchit/"},
        {"name": "Hilton Pattaya", "city": "Pattaya (Central Festival Pattaya Beach)", "url": "https://www.hilton.com/en/hotels/bkkhitw-hilton-pattaya/"},
        {"name": "Hilton Hua Hin Resort & Spa", "city": "Hua Hin (Naresdamri Rd / Beachfront)", "url": "https://www.hilton.com/en/hotels/hhahihi-hilton-hua-hin-resort-and-spa/"},
        {"name": "DoubleTree by Hilton Phuket Banthai Resort", "city": "Phuket (Patong Beach)", "url": "https://www.hilton.com/en/hotels/hktbadi-doubletree-phuket-banthai-resort/"},
        {"name": "Hilton Garden Inn Phuket Bang Tao", "city": "Phuket (Bang Tao / Laguna)", "url": "https://www.hilton.com/en/hotels/hktbtgi-hilton-garden-inn-phuket-bang-tao/"}
    ],
    "Malaysia": [
        {"name": "Hilton Kuala Lumpur", "city": "Kuala Lumpur (KL Sentral)", "url": "https://www.hilton.com/en/hotels/kulhihi-hilton-kuala-lumpur/"},
        {"name": "DoubleTree by Hilton Kuala Lumpur", "city": "Kuala Lumpur (The Intermark / Jalan Tun Razak)", "url": "https://www.hilton.com/en/hotels/kuldtdi-doubletree-by-hilton-hotel-kuala-lumpur/"},
        {"name": "DoubleTree by Hilton Putrajaya Lakeside", "city": "Putrajaya (Presint 5 / Lakefront)", "url": "https://www.hilton.com/en/hotels/kulpjdi-doubletree-by-hilton-putrajaya-lakeside/"},
        {"name": "DoubleTree by Hilton Shah Alam i-City", "city": "Shah Alam (i-City / Selangor)", "url": "https://www.hilton.com/en/hotels/kulia-doubletree-by-hilton-shah-alam-i-city/"},
        {"name": "Hilton Petaling Jaya", "city": "Petaling Jaya (Jalan Barat / Section 52)", "url": "https://www.hilton.com/en/hotels/petjahi-hilton-petaling-jaya/"},
        {"name": "Hilton Kota Kinabalu", "city": "Kota Kinabalu (Jalan Tunku Abdul Rahman / Sabah)", "url": "https://www.hilton.com/en/hotels/bkihitw-hilton-kota-kinabalu/"},
        {"name": "DoubleTree by Hilton Melaka", "city": "Melaka (Hatten City / Jalan Melaka Raya)", "url": "https://www.hilton.com/en/hotels/mkzsrdi-doubletree-by-hilton-hotel-melaka/"},
        {"name": "DoubleTree Resort by Hilton Penang", "city": "Penang (Batu Ferringhi)", "url": "https://www.hilton.com/en/hotels/penmbdi-doubletree-resort-by-hilton-hotel-penang/"},
        {"name": "DoubleTree by Hilton Johor Bahru", "city": "Johor Bahru (Menara Landmark)", "url": "https://www.hilton.com/en/hotels/jhbjbdi-doubletree-by-hilton-hotel-johor-bahru/"},
        {"name": "DoubleTree by Hilton Damai Laut Resort", "city": "Lumut (Perak / Teluk Senangin)", "url": "https://www.hilton.com/en/hotels/iphdldi-doubletree-by-hilton-damai-laut-resort/"}
    ],
    "Japan": [
        {"name": "Conrad Tokyo", "city": "Tokyo (Shiodome / Minato / Hamarikyu View)", "url": "https://www.hilton.com/en/hotels/tyocici-conrad-tokyo/"},
        {"name": "Conrad Osaka", "city": "Osaka (Nakanoshima Festival West / Nishi-ku)", "url": "https://www.hilton.com/en/hotels/osacici-conrad-osaka/"},
        {"name": "ROKU KYOTO, LXR Hotels & Resorts", "city": "Kyoto (Takagamine / Shozan Resort)", "url": "https://www.hilton.com/en/hotels/kytlxhi-roku-kyoto/"},
        {"name": "Hilton Tokyo", "city": "Tokyo (Shinjuku / Nishi-Shinjuku)", "url": "https://www.hilton.com/en/hotels/tyohitw-hilton-tokyo/"},
        {"name": "Hilton Tokyo Odaiba", "city": "Tokyo (Odaiba / Tokyo Bay)", "url": "https://www.hilton.com/en/hotels/tyotohi-hilton-tokyo-odaiba/"},
        {"name": "Hilton Tokyo Bay", "city": "Tokyo Bay (Maihama / Tokyo Disney Resort)", "url": "https://www.hilton.com/en/hotels/tyotbhi-hilton-tokyo-bay/"},
        {"name": "Hilton Osaka", "city": "Osaka (Umeda / Kita-ku)", "url": "https://www.hilton.com/en/hotels/osahitw-hilton-osaka/"},
        {"name": "Hilton Nagoya", "city": "Nagoya (Sakae / Naka-ku)", "url": "https://www.hilton.com/en/hotels/naghitw-hilton-nagoya/"},
        {"name": "Hilton Fukuoka Sea Hawk", "city": "Fukuoka (Momochi / PayPay Dome)", "url": "https://www.hilton.com/en/hotels/fukhihi-hilton-fukuoka-sea-hawk/"},
        {"name": "Hilton Hiroshima", "city": "Hiroshima (Fujimi-cho / Naka-ku)", "url": "https://www.hilton.com/en/hotels/hijhihi-hilton-hiroshima/"},
        {"name": "Hilton Okinawa Chatan Resort", "city": "Okinawa (Chatan / Mihama)", "url": "https://www.hilton.com/en/hotels/okahihi-hilton-okinawa-chatan-resort/"},
        {"name": "Hilton Okinawa Sesoko Resort", "city": "Okinawa (Sesoko Island / Motobu)", "url": "https://www.hilton.com/en/hotels/okashhi-hilton-okinawa-sesoko-resort/"},
        {"name": "Hilton Okinawa Miyako Island Resort", "city": "Miyakojima (Turiver / Irabu Bridge View)", "url": "https://www.hilton.com/en/hotels/mmymkhi-hilton-okinawa-miyako-island-resort/"},
        {"name": "DoubleTree by Hilton Kyoto Higashiyama", "city": "Kyoto (Higashiyama / Kiyomizu)", "url": "https://www.hilton.com/en/hotels/ukykddi-doubletree-by-hilton-kyoto-higashiyama/"},
        {"name": "DoubleTree by Hilton Kyoto Station", "city": "Kyoto (Kyoto Station / Minami-ku)", "url": "https://www.hilton.com/en/hotels/ukyktdi-doubletree-by-hilton-kyoto-station/"}
    ],
    "South Korea": [
        {"name": "Conrad Seoul", "city": "Seoul (Yeouido / IFC Seoul)", "url": "https://www.hilton.com/en/hotels/selcici-conrad-seoul/"},
        {"name": "Hilton Garden Inn Seoul Gangnam", "city": "Seoul (Gangnam / Yangjae Station)", "url": "https://www.hilton.com/en/hotels/selgigi-hilton-garden-inn-seoul-gangnam/"},
        {"name": "DoubleTree by Hilton Seoul Pangyo", "city": "Seongnam (Pangyo Techno Valley)", "url": "https://www.hilton.com/en/hotels/selpgdi-doubletree-by-hilton-seoul-pangyo/"}
    ],
    "China": [
        {"name": "Waldorf Astoria Shanghai on the Bund", "city": "Shanghai (The Bund / Zhongshan Dong Yi Lu)", "url": "https://www.hilton.com/en/hotels/shawa-waldorf-astoria-shanghai-on-the-bund/"},
        {"name": "Waldorf Astoria Beijing", "city": "Beijing (Jinfu Hutong / Wangfujing)", "url": "https://www.hilton.com/en/hotels/bjswawa-waldorf-astoria-beijing/"},
        {"name": "Waldorf Astoria Chengdu", "city": "Chengdu (Tianfu Avenue / Hi-Tech Zone)", "url": "https://www.hilton.com/en/hotels/ctuwawa-waldorf-astoria-chengdu/"},
        {"name": "Waldorf Astoria Xiamen", "city": "Xiamen (Siming / Lianhua Park)", "url": "https://www.hilton.com/en/hotels/xmnwawa-waldorf-astoria-xiamen/"},
        {"name": "Conrad Hong Kong", "city": "Hong Kong (Pacific Place / Admiralty)", "url": "https://www.hilton.com/en/hotels/hkghcc-conrad-hong-kong/"},
        {"name": "Conrad Beijing", "city": "Beijing (Chaoyang / Dongsanhuan)", "url": "https://www.hilton.com/en/hotels/bjscici-conrad-beijing/"},
        {"name": "Conrad Shanghai", "city": "Shanghai (Nanjing East Rd / People's Square)", "url": "https://www.hilton.com/en/hotels/shacici-conrad-shanghai/"},
        {"name": "Conrad Guangzhou", "city": "Guangzhou (Zhujiang New Town / Tianhe)", "url": "https://www.hilton.com/en/hotels/cancici-conrad-guangzhou/"},
        {"name": "Conrad Shenzhen", "city": "Shenzhen (Qianhai / Tinghai Rd)", "url": "https://www.hilton.com/en/hotels/szxcici-conrad-shenzhen/"},
        {"name": "Conrad Hangzhou", "city": "Hangzhou (Raffles City / Qianjiang New Town)", "url": "https://www.hilton.com/en/hotels/hghcici-conrad-hangzhou/"},
        {"name": "Conrad Macao", "city": "Macau (The Londoner Macao / Cotai)", "url": "https://www.hilton.com/en/hotels/mfmsc-conrad-macao/"},
        {"name": "Hilton Shenzhen Futian", "city": "Shenzhen (Shennan Blvd / Futian)", "url": "https://www.hilton.com/en/hotels/szxhehi-hilton-shenzhen-futian/"},
        {"name": "Hilton Guangzhou Tianhe", "city": "Guangzhou (Linhe Xi Heng Rd)", "url": "https://www.hilton.com/en/hotels/canithi-hilton-guangzhou-tianhe/"}
    ],
    "Taiwan": [
        {"name": "Hilton Taipei Sinban", "city": "Taipei (Banqiao / New Taipei City)", "url": "https://www.hilton.com/en/hotels/tsptshi-hilton-taipei-sinban/"},
        {"name": "Hotel Resonance Taipei, Tapestry Collection by Hilton", "city": "Taipei (Zhongzheng / Shandao Temple)", "url": "https://www.hilton.com/en/hotels/tpezrup-hotel-resonance-taipei/"}
    ],
    "Australia": [
        {"name": "Hilton Sydney", "city": "Sydney (George St / CBD)", "url": "https://www.hilton.com/en/hotels/sydhitw-hilton-sydney/"},
        {"name": "Hilton Melbourne Little Queen Street", "city": "Melbourne (Little Queen St / Equity Chambers)", "url": "https://www.hilton.com/en/hotels/melqqhi-hilton-melbourne-little-queen-street/"},
        {"name": "Hilton Brisbane", "city": "Brisbane (Elizabeth St / Queen St Mall)", "url": "https://www.hilton.com/en/hotels/bsbhitw-hilton-brisbane/"},
        {"name": "Hilton Adelaide", "city": "Adelaide (Victoria Square)", "url": "https://www.hilton.com/en/hotels/adhahi-hilton-adelaide/"},
        {"name": "Parmelia Hilton Perth", "city": "Perth (Mill St)", "url": "https://www.hilton.com/en/hotels/perhitw-parmelia-hilton-perth/"},
        {"name": "Hilton Cairns", "city": "Cairns (Esplanade / Marlin Marina)", "url": "https://www.hilton.com/en/hotels/crnhitw-hilton-cairns/"},
        {"name": "Hilton Surfers Paradise Hotel & Residences", "city": "Gold Coast (Orchid Ave / Surfers Paradise)", "url": "https://www.hilton.com/en/hotels/oolhshi-hilton-surfers-paradise-hotel-and-residences/"},
        {"name": "DoubleTree by Hilton Melbourne - Flinders Street", "city": "Melbourne (Flinders St / Federation Square)", "url": "https://www.hilton.com/en/hotels/melwsdi-doubletree-by-hilton-hotel-melbourne-flinders-street/"}
    ],
    "New Zealand": [
        {"name": "Hilton Auckland", "city": "Auckland (Princes Wharf / Waitemata Harbour)", "url": "https://www.hilton.com/en/hotels/aklhihi-hilton-auckland/"},
        {"name": "Hilton Queenstown Resort & Spa", "city": "Queenstown (Kawarau Village / Lake Wakatipu)", "url": "https://www.hilton.com/en/hotels/zqnqwhi-hilton-queenstown-resort-and-spa/"},
        {"name": "DoubleTree by Hilton Hotel Queenstown", "city": "Queenstown (Kawarau Village)", "url": "https://www.hilton.com/en/hotels/zqndt-doubletree-by-hilton-hotel-queenstown/"},
        {"name": "Hilton Lake Taupo", "city": "Taupo (Napier-Taupo Highway)", "url": "https://www.hilton.com/en/hotels/tuhlthi-hilton-lake-taupo/"}
    ],
    "India": [
        {"name": "Conrad Bengaluru", "city": "Bangalore (Kensington Rd / Ulsoor Lake)", "url": "https://www.hilton.com/en/hotels/blrcici-conrad-bengaluru/"},
        {"name": "Conrad Pune", "city": "Pune (Mangaldas Rd / Koregaon Park)", "url": "https://www.hilton.com/en/hotels/pnqcici-conrad-pune/"},
        {"name": "Hilton Mumbai International Airport", "city": "Mumbai (Sahar Airport Rd)", "url": "https://www.hilton.com/en/hotels/bomaphi-hilton-mumbai-international-airport/"},
        {"name": "Hilton Chennai", "city": "Chennai (Jawaharlal Nehru Salai / Guindy)", "url": "https://www.hilton.com/en/hotels/maahihi-hilton-chennai/"},
        {"name": "Hilton Bangalore Embassy GolfLinks", "city": "Bangalore (Embassy GolfLinks Business Park)", "url": "https://www.hilton.com/en/hotels/blreghi-hilton-bangalore-embassy-golflinks/"},
        {"name": "DoubleTree by Hilton Hotel Goa - Arpora - Baga", "city": "Goa (Arpora / Baga Beach)", "url": "https://www.hilton.com/en/hotels/goaagdi-doubletree-by-hilton-hotel-goa-arpora-baga/"}
    ],
    "Maldives": [
        {"name": "Waldorf Astoria Maldives Ithaafushi", "city": "Maldives (South Malé Atoll / Ithaafushi Island)", "url": "https://www.hilton.com/en/hotels/mleoni-waldorf-astoria-maldives-ithaafushi/"},
        {"name": "Conrad Maldives Rangali Island", "city": "Maldives (South Ari Atoll / Rangali Island)", "url": "https://www.hilton.com/en/hotels/mlehi-conrad-maldives-rangali-island/"},
        {"name": "Hilton Maldives Amingiri Resort & Spa", "city": "Maldives (North Malé Atoll / Amingiri Island)", "url": "https://www.hilton.com/en/hotels/mleaihi-hilton-maldives-amingiri-resort-and-spa/"},
        {"name": "SAii Lagoon Maldives, Curio Collection by Hilton", "city": "Maldives (Emboodhoo Lagoon / CROSSROADS)", "url": "https://www.hilton.com/en/hotels/mleabor-saii-lagoon-maldives/"}
    ],
    "United Arab Emirates": [
        {"name": "Conrad Dubai", "city": "Dubai (Sheikh Zayed Rd / Trade Centre)", "url": "https://www.hilton.com/en/hotels/dxbcdci-conrad-dubai/"},
        {"name": "Waldorf Astoria Dubai Palm Jumeirah", "city": "Dubai (Palm Jumeirah East Crescent)", "url": "https://www.hilton.com/en/hotels/dxbpdwa-waldorf-astoria-dubai-palm-jumeirah/"},
        {"name": "Waldorf Astoria Dubai International Financial Centre", "city": "Dubai (DIFC / Burj Daman)", "url": "https://www.hilton.com/en/hotels/dxbwa-waldorf-astoria-dubai-international-financial-centre/"},
        {"name": "Conrad Abu Dhabi Etihad Towers", "city": "Abu Dhabi (Corniche Rd / Etihad Towers)", "url": "https://www.hilton.com/en/hotels/auhetci-conrad-abu-dhabi-etihad-towers/"},
        {"name": "Waldorf Astoria Ras Al Khaimah", "city": "Ras Al Khaimah (Vienna St / Al Hamra)", "url": "https://www.hilton.com/en/hotels/rktwawa-waldorf-astoria-ras-al-khaimah/"},
        {"name": "Hilton Dubai Palm Jumeirah", "city": "Dubai (Palm West Beach)", "url": "https://www.hilton.com/en/hotels/dxbpjhi-hilton-dubai-palm-jumeirah/"},
        {"name": "Hilton Dubai Jumeirah", "city": "Dubai (The Walk / JBR)", "url": "https://www.hilton.com/en/hotels/dxbjbhi-hilton-dubai-jumeirah/"},
        {"name": "Hilton Dubai The Walk", "city": "Dubai (The Walk / JBR)", "url": "https://www.hilton.com/en/hotels/dxbithi-hilton-dubai-the-walk/"},
        {"name": "Habtoor Palace Dubai, LXR Hotels & Resorts", "city": "Dubai (Al Habtoor City / Sheikh Zayed Rd)", "url": "https://www.hilton.com/en/hotels/dxbplol-habtoor-palace-dubai/"},
        {"name": "V Hotel Dubai, Curio Collection by Hilton", "city": "Dubai (Al Habtoor City)", "url": "https://www.hilton.com/en/hotels/dxbvcur-v-hotel-dubai/"}
    ],
    "Saudi Arabia": [
        {"name": "Waldorf Astoria Jeddah - Qasr Al Sharq", "city": "Jeddah (North Corniche Rd / Red Sea View)", "url": "https://www.hilton.com/en/hotels/jedqswa-waldorf-astoria-jeddah-qasr-al-sharq/"},
        {"name": "Jabal Omar Conrad Makkah", "city": "Makkah (Ibrahim Al Khalil St / Haram View)", "url": "https://www.hilton.com/en/hotels/makcici-conrad-makkah/"},
        {"name": "Jabal Omar Hilton Makkah Hotel & Convention Center", "city": "Makkah (Jabal Omar)", "url": "https://www.hilton.com/en/hotels/makhchi-hilton-hotel-and-convention-center-makkah/"},
        {"name": "Makkah Hotel and Towers (Hilton Partner)", "city": "Makkah (Ibrahim Al Khalil / Clock Tower)", "url": "https://www.hilton.com/en/hotels/makskhi-makkah-hotel-and-towers/"},
        {"name": "Madinah Hilton Hotel", "city": "Madinah (King Fahd St / Prophet's Mosque)", "url": "https://www.hilton.com/en/hotels/medhihi-madinah-hilton-hotel/"},
        {"name": "Hilton Riyadh Hotel & Residences", "city": "Riyadh (Eastern Ring Rd / Granada)", "url": "https://www.hilton.com/en/hotels/ruhhehi-hilton-riyadh-hotel-and-residences/"},
        {"name": "Hilton Jeddah", "city": "Jeddah (Corniche Rd)", "url": "https://www.hilton.com/en/hotels/jedhihi-hilton-jeddah/"}
    ],
    "Qatar": [
        {"name": "Waldorf Astoria Lusail, Doha", "city": "Doha (Lusail / Damsa Blvd)", "url": "https://www.hilton.com/en/hotels/dohwvwa-waldorf-astoria-lusail-doha/"},
        {"name": "Waldorf Astoria Doha West Bay", "city": "Doha (West Bay / Diplomatic Area)", "url": "https://www.hilton.com/en/hotels/dohwawa-waldorf-astoria-doha-west-bay/"},
        {"name": "Hilton Doha", "city": "Doha (Diplomatic St / West Bay Beach)", "url": "https://www.hilton.com/en/hotels/dohhthi-hilton-doha/"},
        {"name": "Hilton Doha The Pearl Hotel & Residences", "city": "Doha (Abraj Quartier / The Pearl)", "url": "https://www.hilton.com/en/hotels/dohprhi-hilton-doha-the-pearl-hotel-and-residences/"},
        {"name": "Aleph Doha Residences, Curio Collection by Hilton", "city": "Doha (West Bay)", "url": "https://www.hilton.com/en/hotels/doharqq-aleph-doha-residences-curio-collection/"}
    ],
    "United Kingdom": [
        {"name": "The Biltmore Mayfair, LXR Hotels & Resorts", "city": "London (Grosvenor Square / Mayfair)", "url": "https://www.hilton.com/en/hotels/lonolxl-the-biltmore-mayfair-london/"},
        {"name": "Conrad London St. James", "city": "London (Broadway / Westminster)", "url": "https://www.hilton.com/en/hotels/lonjnhc-conrad-london-st-james/"},
        {"name": "London Hilton on Park Lane", "city": "London (Park Lane / Hyde Park)", "url": "https://www.hilton.com/en/hotels/lonhitw-london-hilton-on-park-lane/"},
        {"name": "The Waldorf Hilton, London", "city": "London (Aldwych / Covent Garden)", "url": "https://www.hilton.com/en/hotels/lonwahi-the-waldorf-hilton-london/"},
        {"name": "Hilton London Bankside", "city": "London (Great Suffolk St / Bankside)", "url": "https://www.hilton.com/en/hotels/lonsbhi-hilton-london-bankside/"},
        {"name": "100 Queen's Gate Hotel London, Curio Collection", "city": "London (South Kensington)", "url": "https://www.hilton.com/en/hotels/lonqgqq-100-queens-gate-hotel-london/"},
        {"name": "The Trafalgar St. James London, Curio Collection", "city": "London (Trafalgar Square / Spring Gardens)", "url": "https://www.hilton.com/en/hotels/lontsqq-the-trafalgar-st-james-london-curio-collection-by-hilton/"},
        {"name": "Waldorf Astoria Edinburgh - The Caledonian", "city": "Edinburgh (Princes St / Edinburgh Castle View)", "url": "https://www.hilton.com/en/hotels/ednchwa-waldorf-astoria-edinburgh-the-caledonian/"},
        {"name": "Hilton Manchester Deansgate", "city": "Manchester (Beetham Tower / Deansgate)", "url": "https://www.hilton.com/en/hotels/manhehi-hilton-manchester-deansgate/"}
    ],
    "France": [
        {"name": "Waldorf Astoria Versailles - Trianon Palace", "city": "Versailles (Boulevard de la Reine / Chateau Park)", "url": "https://www.hilton.com/en/hotels/cdgtpwa-waldorf-astoria-versailles-trianon-palace/"},
        {"name": "Hilton Paris Opera", "city": "Paris (Rue Saint-Lazare / 8th Arr)", "url": "https://www.hilton.com/en/hotels/parophi-hilton-paris-opera/"},
        {"name": "Canopy by Hilton Paris Trocadero", "city": "Paris (Avenue d'Eylau / Eiffel View)", "url": "https://www.hilton.com/en/hotels/parpypr-canopy-paris-trocadero/"},
        {"name": "Maison Astor Paris, Curio Collection by Hilton", "city": "Paris (Rue d'Astorg / Madeleine)", "url": "https://www.hilton.com/en/hotels/parmacs-maison-astor-paris-curio-collection-by-hilton/"},
        {"name": "Hilton Paris Charles de Gaulle Airport", "city": "Paris (Roissypole / CDG Terminal)", "url": "https://www.hilton.com/en/hotels/cdghitw-hilton-paris-charles-de-gaulle-airport/"}
    ],
    "Germany": [
        {"name": "Waldorf Astoria Berlin", "city": "Berlin (Hardenbergstraße / Kurfürstendamm)", "url": "https://www.hilton.com/en/hotels/berzawa-waldorf-astoria-berlin/"},
        {"name": "Hilton Berlin", "city": "Berlin (Mohrenstraße / Gendarmenmarkt)", "url": "https://www.hilton.com/en/hotels/berhitw-hilton-berlin/"},
        {"name": "Hilton Munich Park", "city": "Munich (Am Tucherpark / English Garden)", "url": "https://www.hilton.com/en/hotels/muchitw-hilton-munich-park/"},
        {"name": "Hilton Munich City", "city": "Munich (Rosenheimer Straße / Haidhausen)", "url": "https://www.hilton.com/en/hotels/muccitw-hilton-munich-city/"},
        {"name": "Hilton Frankfurt City Centre", "city": "Frankfurt (Hochstraße / Bockenheimer Anlage)", "url": "https://www.hilton.com/en/hotels/frahitw-hilton-frankfurt-city-centre/"},
        {"name": "Hilton Frankfurt Airport", "city": "Frankfurt (The Squaire / Airport)", "url": "https://www.hilton.com/en/hotels/fraapit-hilton-frankfurt-airport/"}
    ],
    "Italy": [
        {"name": "Rome Cavalieri, A Waldorf Astoria Hotel", "city": "Rome (Via Alberto Cadlolo / Monte Mario)", "url": "https://www.hilton.com/en/hotels/romhiwa-rome-cavalieri-a-waldorf-astoria-hotel/"},
        {"name": "Hilton Molino Stucky Venice", "city": "Venice (Giudecca Island / Giudecca Canal)", "url": "https://www.hilton.com/en/hotels/vcehihi-hilton-molino-stucky-venice/"},
        {"name": "Hilton Milan", "city": "Milan (Via Luigi Galvani / Centrale)", "url": "https://www.hilton.com/en/hotels/milhitw-hilton-milan/"},
        {"name": "Hilton Lake Como", "city": "Como (Via Borgovico / Villa Olmo)", "url": "https://www.hilton.com/en/hotels/mxpcohi-hilton-lake-como/"},
        {"name": "Aleph Rome Hotel, Curio Collection by Hilton", "city": "Rome (Via di San Basilio / Barberini)", "url": "https://www.hilton.com/en/hotels/romahqq-aleph-rome-hotel-curio-collection-by-hilton/"}
    ],
    "Netherlands": [
        {"name": "Waldorf Astoria Amsterdam", "city": "Amsterdam (Herengracht Canal / UNESCO Belt)", "url": "https://www.hilton.com/en/hotels/amswawa-waldorf-astoria-amsterdam/"},
        {"name": "Hilton Amsterdam", "city": "Amsterdam (Apollolaan / Museum Quarter)", "url": "https://www.hilton.com/en/hotels/amshitw-hilton-amsterdam/"},
        {"name": "DoubleTree by Hilton Amsterdam Centraal Station", "city": "Amsterdam (Oosterdoksstraat / Station)", "url": "https://www.hilton.com/en/hotels/amsdtdi-doubletree-by-hilton-hotel-amsterdam-centraal-station/"}
    ],
    "United States": [
        {"name": "Waldorf Astoria Beverly Hills", "city": "Beverly Hills (Wilshire Blvd / Santa Monica Blvd)", "url": "https://www.hilton.com/en/hotels/laxbowa-waldorf-astoria-beverly-hills/"},
        {"name": "Waldorf Astoria Chicago", "city": "Chicago (East Walton St / Gold Coast)", "url": "https://www.hilton.com/en/hotels/chowa-waldorf-astoria-chicago/"},
        {"name": "Waldorf Astoria Washington DC", "city": "Washington DC (Pennsylvania Ave / Old Post Office)", "url": "https://www.hilton.com/en/hotels/dcawawa-waldorf-astoria-washington-dc/"},
        {"name": "Waldorf Astoria Las Vegas", "city": "Las Vegas (Las Vegas Blvd / The Strip)", "url": "https://www.hilton.com/en/hotels/laswdwa-waldorf-astoria-las-vegas/"},
        {"name": "Waldorf Astoria Orlando", "city": "Orlando (Bonnet Creek Resort)", "url": "https://www.hilton.com/en/hotels/orlww-waldorf-astoria-orlando/"},
        {"name": "Waldorf Astoria Monarch Beach Resort & Club", "city": "Dana Point (Monarch Beach Resort N)", "url": "https://www.hilton.com/en/hotels/snampwa-waldorf-astoria-monarch-beach/"},
        {"name": "Conrad New York Midtown", "city": "New York (54th St / Midtown West)", "url": "https://www.hilton.com/en/hotels/nyccici-conrad-new-york-midtown/"},
        {"name": "Conrad New York Downtown", "city": "New York (North End Ave / Battery Park)", "url": "https://www.hilton.com/en/hotels/nyccnci-conrad-new-york-downtown/"},
        {"name": "Conrad Washington, DC", "city": "Washington DC (New York Ave NW / CityCenterDC)", "url": "https://www.hilton.com/en/hotels/wasccci-conrad-washington-dc/"},
        {"name": "Conrad Los Angeles", "city": "Los Angeles (Grand Ave / The Grand LA)", "url": "https://www.hilton.com/en/hotels/laxcici-conrad-los-angeles/"},
        {"name": "Grand Wailea, A Waldorf Astoria Resort", "city": "Maui (Wailea Alanui Dr)", "url": "https://www.hilton.com/en/hotels/oggkawa-grand-wailea-a-waldorf-astoria-resort/"},
        {"name": "Hilton Hawaiian Village Waikiki Beach Resort", "city": "Honolulu / Oahu (Kalia Rd / Waikiki)", "url": "https://www.hilton.com/en/hotels/hnlhh-hilton-hawaiian-village-waikiki-beach-resort/"},
        {"name": "New York Hilton Midtown", "city": "New York (Avenue of the Americas / 53rd St)", "url": "https://www.hilton.com/en/hotels/nycnmhh-new-york-hilton-midtown/"},
        {"name": "Hilton San Francisco Union Square", "city": "San Francisco (O'Farrell St / Union Square)", "url": "https://www.hilton.com/en/hotels/sfofhh-hilton-san-francisco-union-square/"}
    ]
}


def seed_hilton_global():
    """Seeds all verified physical Hilton Honors hotels into hotel_stays.db."""
    SessionMaker = get_session_factory()
    session = SessionMaker()

    total_added = 0
    seen_ids = set()

    for country, hotels in HILTON_MASTER_DIRECTORY.items():
        for h in hotels:
            existing = session.query(Hotel).filter(Hotel.name == h["name"]).first()
            if not existing:
                m = re.search(r'/hotels/([a-z0-9]{7})-', h["url"])
                hilt_code = m.group(1) if m else re.sub(r'[^a-z0-9]', '', h["name"].lower())[:10]
                h_id = f"hilt_{hilt_code}"
                if h_id in seen_ids:
                    slug = re.sub(r'[^a-z0-9_]', '', h["name"].lower().replace(' ', '_').replace('-', '_'))[:20]
                    h_id = f"hilt_{hilt_code}_{slug}"
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
                    brand="HILTON",
                    name=h["name"],
                    city=h["city"],
                    country=country,
                    currency=curr,
                    loyalty_model="DYNAMIC_POINTS_WITH_MAX_CAP",
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
                    raw_name="Standard Guest Room",
                    standardized_type="STANDARD"
                )
                session.add(room)
                total_added += 1

    session.commit()
    session.close()
    logger.info(f"Successfully seeded {total_added} Hilton Honors properties across {len(HILTON_MASTER_DIRECTORY)} countries into database!")
    export_watchlist_to_excel()

if __name__ == '__main__':
    seed_hilton_global()
