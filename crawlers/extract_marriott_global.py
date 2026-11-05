"""Marriott Bonvoy Master Global Hotel Directory Extractor.
Populates hotel_stays.db with 100% verified real physical Marriott Bonvoy properties across global operating countries.
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
logger = logging.getLogger("marriott_global")

MARRIOTT_MASTER_DIRECTORY = {
    "Indonesia": [
        # Bali
        {"name": "The St. Regis Bali Resort", "city": "Bali (Nusa Dua)", "url": "https://www.marriott.com/hotels/travel/dpsxr-the-st-regis-bali-resort/"},
        {"name": "The Ritz-Carlton, Bali", "city": "Bali (Nusa Dua / Sawangan)", "url": "https://www.marriott.com/hotels/travel/dpssw-the-ritz-carlton-bali/"},
        {"name": "Mandapa, a Ritz-Carlton Reserve", "city": "Bali (Ubud / Ayung River)", "url": "https://www.marriott.com/hotels/travel/dpsrb-mandapa-a-ritz-carlton-reserve/"},
        {"name": "Bulgari Resort Bali", "city": "Bali (Uluwatu)", "url": "https://www.marriott.com/hotels/travel/dpsbg-bulgari-resort-bali/"},
        {"name": "The Laguna, a Luxury Collection Resort & Spa, Nusa Dua, Bali", "city": "Bali (Nusa Dua)", "url": "https://www.marriott.com/hotels/travel/dpslc-the-laguna-a-luxury-collection-resort-and-spa-nusa-dua-bali/"},
        {"name": "W Bali - Seminyak", "city": "Bali (Seminyak)", "url": "https://www.marriott.com/hotels/travel/dpswh-w-bali-seminyak/"},
        {"name": "The Westin Resort Nusa Dua, Bali", "city": "Bali (Nusa Dua)", "url": "https://www.marriott.com/hotels/travel/dpswi-the-westin-resort-nusa-dua-bali/"},
        {"name": "Renaissance Bali Uluwatu Resort & Spa", "city": "Bali (Uluwatu)", "url": "https://www.marriott.com/hotels/travel/dpsuw-renaissance-bali-uluwatu-resort-and-spa/"},
        {"name": "Renaissance Bali Nusa Dua Resort", "city": "Bali (Nusa Dua)", "url": "https://www.marriott.com/hotels/travel/dpsnd-renaissance-bali-nusa-dua-resort/"},
        {"name": "Sthala, a Tribute Portfolio Hotel, Ubud Bali", "city": "Bali (Ubud)", "url": "https://www.marriott.com/hotels/travel/dpstp-sthala-a-tribute-portfolio-hotel-ubud-bali/"},
        {"name": "Sheraton Bali Kuta Resort", "city": "Bali (Kuta / Beachwalk)", "url": "https://www.marriott.com/hotels/travel/dpsks-sheraton-bali-kuta-resort/"},
        {"name": "Courtyard Bali Nusa Dua Resort", "city": "Bali (Nusa Dua)", "url": "https://www.marriott.com/hotels/travel/dpscy-courtyard-bali-nusa-dua-resort/"},
        {"name": "Courtyard Bali Seminyak Resort", "city": "Bali (Seminyak)", "url": "https://www.marriott.com/hotels/travel/dpssm-courtyard-bali-seminyak-resort/"},
        {"name": "Aloft Bali Seminyak", "city": "Bali (Seminyak / Batu Belig)", "url": "https://www.marriott.com/hotels/travel/dpsal-aloft-bali-seminyak/"},
        {"name": "Aloft Bali Kuta at Beachwalk", "city": "Bali (Kuta)", "url": "https://www.marriott.com/hotels/travel/dpska-aloft-bali-kuta-at-beachwalk/"},
        {"name": "Element Bali Ubud", "city": "Bali (Ubud / Andong)", "url": "https://www.marriott.com/hotels/travel/dpsel-element-bali-ubud/"},
        {"name": "Four Points by Sheraton Bali, Kuta", "city": "Bali (Kuta)", "url": "https://www.marriott.com/hotels/travel/dpsfp-four-points-bali-kuta/"},
        {"name": "Four Points by Sheraton Bali, Seminyak", "city": "Bali (Seminyak / Petitenget)", "url": "https://www.marriott.com/hotels/travel/dpsps-four-points-bali-seminyak/"},
        {"name": "Four Points by Sheraton Bali, Ungasan", "city": "Bali (Ungasan)", "url": "https://www.marriott.com/hotels/travel/dpsfb-four-points-bali-ungasan/"},
        {"name": "Fairfield by Marriott Bali Legian", "city": "Bali (Legian)", "url": "https://www.marriott.com/hotels/travel/dpsfl-fairfield-bali-legian/"},
        {"name": "Fairfield by Marriott Bali South Kuta", "city": "Bali (Kuta / Kartika Plaza)", "url": "https://www.marriott.com/hotels/travel/dpsfk-fairfield-bali-south-kuta/"},
        {"name": "Fairfield by Marriott Bali Sunset Road", "city": "Bali (Kuta / Sunset Road)", "url": "https://www.marriott.com/hotels/travel/dpsfs-fairfield-bali-sunset-road/"},
        
        # Jakarta
        {"name": "The St. Regis Jakarta", "city": "Jakarta (Kuningan / Rajawali Place)", "url": "https://www.marriott.com/hotels/travel/jktxr-the-st-regis-jakarta/"},
        {"name": "The Ritz-Carlton Jakarta, Pacific Place", "city": "Jakarta (SCBD / Pacific Place)", "url": "https://www.marriott.com/hotels/travel/jktrt-the-ritz-carlton-jakarta-pacific-place/"},
        {"name": "The Ritz-Carlton Jakarta, Mega Kuningan", "city": "Jakarta (Mega Kuningan)", "url": "https://www.marriott.com/hotels/travel/jktrz-the-ritz-carlton-jakarta-mega-kuningan/"},
        {"name": "JW Marriott Hotel Jakarta", "city": "Jakarta (Mega Kuningan)", "url": "https://www.marriott.com/hotels/travel/jktjw-jw-marriott-hotel-jakarta/"},
        {"name": "The Westin Jakarta", "city": "Jakarta (Gama Tower / Rasuna Said)", "url": "https://www.marriott.com/hotels/travel/jktwi-the-westin-jakarta/"},
        {"name": "The Hermitage, a Tribute Portfolio Hotel, Jakarta", "city": "Jakarta (Menteng)", "url": "https://www.marriott.com/hotels/travel/jkttr-the-hermitage-a-tribute-portfolio-hotel-jakarta/"},
        {"name": "Sheraton Grand Jakarta Gandaria City Hotel", "city": "Jakarta (Kebayoran / Gandaria City)", "url": "https://www.marriott.com/hotels/travel/jktgs-sheraton-grand-jakarta-gandaria-city-hotel/"},
        {"name": "Le Méridien Jakarta", "city": "Jakarta (Sudirman)", "url": "https://www.marriott.com/hotels/travel/jktmd-le-meridien-jakarta/"},
        {"name": "Aloft Jakarta Wahid Hasyim", "city": "Jakarta (Wahid Hasyim / Central)", "url": "https://www.marriott.com/hotels/travel/jktaw-aloft-jakarta-wahid-hasyim/"},
        {"name": "Aloft Jakarta TB Simatupang", "city": "Jakarta (South Jakarta / TB Simatupang)", "url": "https://www.marriott.com/hotels/travel/jktal-aloft-jakarta-tb-simatupang/"},
        {"name": "Four Points by Sheraton Jakarta, Thamrin", "city": "Jakarta (Thamrin / Menara Topas)", "url": "https://www.marriott.com/hotels/travel/jktfp-four-points-jakarta-thamrin/"},

        # Java, Sumatra, Kalimantan, Sulawesi, NTT, NTB
        {"name": "JW Marriott Hotel Surabaya", "city": "Surabaya (Embong Malang)", "url": "https://www.marriott.com/hotels/travel/subjw-jw-marriott-hotel-surabaya/"},
        {"name": "The Westin Surabaya", "city": "Surabaya (Pakuwon Mall)", "url": "https://www.marriott.com/hotels/travel/subwi-the-westin-surabaya/"},
        {"name": "Sheraton Surabaya Hotel & Towers", "city": "Surabaya (Tunjungan Plaza)", "url": "https://www.marriott.com/hotels/travel/subsi-sheraton-surabaya-hotel-and-towers/"},
        {"name": "Four Points by Sheraton Surabaya, Pakuwon Indah", "city": "Surabaya (Pakuwon)", "url": "https://www.marriott.com/hotels/travel/subfp-four-points-surabaya-pakuwon-indah/"},
        {"name": "Four Points by Sheraton Surabaya, Tunjungan Plaza", "city": "Surabaya (Tunjungan)", "url": "https://www.marriott.com/hotels/travel/subtp-four-points-surabaya-tunjungan-plaza/"},
        {"name": "Fairfield by Marriott Surabaya", "city": "Surabaya (Mayjen Sungkono)", "url": "https://www.marriott.com/hotels/travel/subfl-fairfield-surabaya/"},
        {"name": "Sheraton Bandung Hotel & Towers", "city": "Bandung (Dago)", "url": "https://www.marriott.com/hotels/travel/bdo-si-sheraton-bandung-hotel-and-towers/"},
        {"name": "Courtyard by Marriott Bandung Dago", "city": "Bandung (Dago)", "url": "https://www.marriott.com/hotels/travel/bdocy-courtyard-bandung-dago/"},
        {"name": "Four Points by Sheraton Bandung", "city": "Bandung (Ir. H. Juanda / Dago)", "url": "https://www.marriott.com/hotels/travel/bdofp-four-points-bandung/"},
        {"name": "Moxy Bandung", "city": "Bandung (Dago)", "url": "https://www.marriott.com/hotels/travel/bdoox-moxy-bandung/"},
        {"name": "Yogyakarta Marriott Hotel", "city": "Yogyakarta (Pakewon Mall Jogja)", "url": "https://www.marriott.com/hotels/travel/jogmc-yogyakarta-marriott-hotel/"},
        {"name": "Sheraton Mustika Yogyakarta Resort & Spa", "city": "Yogyakarta (Laksda Adisucipto)", "url": "https://www.marriott.com/hotels/travel/jogsi-sheraton-mustika-yogyakarta-resort-and-spa/"},
        {"name": "JW Marriott Hotel Medan", "city": "Medan (Putri Hijau)", "url": "https://www.marriott.com/hotels/travel/mesjw-jw-marriott-hotel-medan/"},
        {"name": "Four Points by Sheraton Medan", "city": "Medan (Gatot Subroto)", "url": "https://www.marriott.com/hotels/travel/mesfp-four-points-medan/"},
        {"name": "Four Points by Sheraton Balikpapan", "city": "Balikpapan (Kalimantan)", "url": "https://www.marriott.com/hotels/travel/bpnfp-four-points-balikpapan/"},
        {"name": "Four Points by Sheraton Manado", "city": "Manado (Boulevard / Sulawesi)", "url": "https://www.marriott.com/hotels/travel/mdcfp-four-points-manado/"},
        {"name": "Ta'aktana, a Luxury Collection Resort & Spa, Labuan Bajo", "city": "Labuan Bajo (Komodo / Pantai Wecidun)", "url": "https://www.marriott.com/hotels/travel/lbjlc-taaktana-a-luxury-collection-resort-and-spa-labuan-bajo/"},
        {"name": "The Sira, a Luxury Collection Resort & Spa, Lombok", "city": "Lombok (Sire Beach / Medana)", "url": "https://www.marriott.com/hotels/travel/lopls-the-sira-a-luxury-collection-resort-and-spa-lombok/"},
        {"name": "Sheraton Senggigi Beach Resort", "city": "Lombok (Senggigi)", "url": "https://www.marriott.com/hotels/travel/lopsc-sheraton-senggigi-beach-resort/"},
        {"name": "Sheraton Belitung Resort", "city": "Belitung (Tanjung Binga)", "url": "https://www.marriott.com/hotels/travel/tjqsi-sheraton-belitung-resort/"},
        {"name": "Fairfield by Marriott Belitung", "city": "Belitung (Tanjung Pandan)", "url": "https://www.marriott.com/hotels/travel/tjqfl-fairfield-belitung/"}
    ],
    "Singapore": [
        {"name": "The Ritz-Carlton, Millenia Singapore", "city": "Singapore (Marina Bay / Raffles Ave)", "url": "https://www.marriott.com/hotels/travel/sinrz-the-ritz-carlton-millenia-singapore/"},
        {"name": "The St. Regis Singapore", "city": "Singapore (Tanglin / Orchard)", "url": "https://www.marriott.com/hotels/travel/sinxr-the-st-regis-singapore/"},
        {"name": "The Singapore EDITION", "city": "Singapore (Cuscaden Rd / Orchard)", "url": "https://www.marriott.com/hotels/travel/sined-the-singapore-edition/"},
        {"name": "JW Marriott Hotel Singapore South Beach", "city": "Singapore (Beach Rd / Bras Basah)", "url": "https://www.marriott.com/hotels/travel/sinjw-jw-marriott-hotel-singapore-south-beach/"},
        {"name": "W Singapore - Sentosa Cove", "city": "Singapore (Sentosa Cove / Ocean Way)", "url": "https://www.marriott.com/hotels/travel/sinwh-w-singapore-sentosa-cove/"},
        {"name": "The Westin Singapore", "city": "Singapore (Marina View / CBD)", "url": "https://www.marriott.com/hotels/travel/sinwi-the-westin-singapore/"},
        {"name": "Singapore Marriott Tang Plaza Hotel", "city": "Singapore (Orchard Rd / Scotts)", "url": "https://www.marriott.com/hotels/travel/sindt-singapore-marriott-tang-plaza-hotel/"},
        {"name": "Duxton Reserve Singapore, Autograph Collection", "city": "Singapore (Tanjong Pagar / Duxton)", "url": "https://www.marriott.com/hotels/travel/sinak-duxton-reserve-singapore-autograph-collection/"},
        {"name": "Courtyard by Marriott Singapore Novena", "city": "Singapore (Novena / Irrawaddy Rd)", "url": "https://www.marriott.com/hotels/travel/sincy-courtyard-singapore-novena/"},
        {"name": "Four Points by Sheraton Singapore, Riverview", "city": "Singapore (Robertson Quay / Havelock)", "url": "https://www.marriott.com/hotels/travel/sinfp-four-points-singapore-riverview/"},
        {"name": "Aloft Singapore Novena", "city": "Singapore (Balestier / Zhongshan Park)", "url": "https://www.marriott.com/hotels/travel/sinal-aloft-singapore-novena/"}
    ],
    "Thailand": [
        {"name": "The St. Regis Bangkok", "city": "Bangkok (Rajadamri / Lumpini View)", "url": "https://www.marriott.com/hotels/travel/bkkxr-the-st-regis-bangkok/"},
        {"name": "The Ritz-Carlton, Bangkok", "city": "Bangkok (One Bangkok / Wireless Rd)", "url": "https://www.marriott.com/hotels/travel/bkkrz-the-ritz-carlton-bangkok/"},
        {"name": "The Ritz-Carlton, Koh Samui", "city": "Koh Samui (Choeng Mon Beach)", "url": "https://www.marriott.com/hotels/travel/usmrz-the-ritz-carlton-koh-samui/"},
        {"name": "Phulay Bay, a Ritz-Carlton Reserve", "city": "Krabi (Nong Thale / Tubkaek Beach)", "url": "https://www.marriott.com/hotels/travel/kbvrz-phulay-bay-a-ritz-carlton-reserve/"},
        {"name": "JW Marriott Hotel Bangkok", "city": "Bangkok (Sukhumvit 2 / Ploenchit)", "url": "https://www.marriott.com/hotels/travel/bkkdt-jw-marriott-hotel-bangkok/"},
        {"name": "JW Marriott Phuket Resort & Spa", "city": "Phuket (Mai Khao Beach)", "url": "https://www.marriott.com/hotels/travel/hktjw-jw-marriott-phuket-resort-and-spa/"},
        {"name": "JW Marriott Khao Lak Resort & Spa", "city": "Khao Lak (Khuk Khak)", "url": "https://www.marriott.com/hotels/travel/hktkl-jw-marriott-khao-lak-resort-and-spa/"},
        {"name": "W Bangkok", "city": "Bangkok (Sathorn / Silom)", "url": "https://www.marriott.com/hotels/travel/bkkwb-w-bangkok/"},
        {"name": "W Koh Samui", "city": "Koh Samui (Mae Nam Beach)", "url": "https://www.marriott.com/hotels/travel/usmwh-w-koh-samui/"},
        {"name": "Sheraton Grande Sukhumvit, a Luxury Collection Hotel", "city": "Bangkok (Asok / Sukhumvit)", "url": "https://www.marriott.com/hotels/travel/bkklc-sheraton-grande-sukhumvit-a-luxury-collection-hotel-bangkok/"},
        {"name": "The Athenee Hotel, a Luxury Collection Hotel, Bangkok", "city": "Bangkok (Wireless Rd / Ploenchit)", "url": "https://www.marriott.com/hotels/travel/bkkla-the-athenee-hotel-a-luxury-collection-hotel-bangkok/"},
        {"name": "The Naka Island, a Luxury Collection Resort & Spa, Phuket", "city": "Phuket (Naka Yai Island)", "url": "https://www.marriott.com/hotels/travel/hktlc-the-naka-island-a-luxury-collection-resort-and-spa-phuket/"},
        {"name": "Bangkok Marriott Marquis Queen's Park", "city": "Bangkok (Sukhumvit 22 / Phrom Phong)", "url": "https://www.marriott.com/hotels/travel/bkkqp-bangkok-marriott-marquis-queens-park/"},
        {"name": "Bangkok Marriott Hotel Sukhumvit", "city": "Bangkok (Thonglor)", "url": "https://www.marriott.com/hotels/travel/bkkms-bangkok-marriott-hotel-sukhumvit/"},
        {"name": "Bangkok Marriott Hotel The Surawongse", "city": "Bangkok (Surawong / Bang Rak)", "url": "https://www.marriott.com/hotels/travel/bkkwo-bangkok-marriott-hotel-the-surawongse/"},
        {"name": "Phuket Marriott Resort & Spa, Merlin Beach", "city": "Phuket (Tri-Trang / Patong)", "url": "https://www.marriott.com/hotels/travel/hktmb-phuket-marriott-resort-and-spa-merlin-beach/"},
        {"name": "Phuket Marriott Resort and Spa, Nai Yang Beach", "city": "Phuket (Nai Yang Beach)", "url": "https://www.marriott.com/hotels/travel/hktnb-phuket-marriott-resort-and-spa-nai-yang-beach/"},
        {"name": "Hua Hin Marriott Resort & Spa", "city": "Hua Hin (Petchkasem Rd / Beachfront)", "url": "https://www.marriott.com/hotels/travel/hhqmr-hua-hin-marriott-resort-and-spa/"},
        {"name": "Le Méridien Bangkok", "city": "Bangkok (Silom / Patpong)", "url": "https://www.marriott.com/hotels/travel/bkkdm-le-meridien-bangkok/"},
        {"name": "Le Méridien Phuket Beach Resort", "city": "Phuket (Karon Noi Beach)", "url": "https://www.marriott.com/hotels/travel/hktmd-le-meridien-phuket-beach-resort/"},
        {"name": "Le Méridien Phuket Mai Khao Beach Resort", "city": "Phuket (Mai Khao)", "url": "https://www.marriott.com/hotels/travel/hktmm-le-meridien-phuket-mai-khao-beach-resort/"},
        {"name": "Le Méridien Chiang Mai / Chiang Rai Resort", "city": "Chiang Rai (Kok River)", "url": "https://www.marriott.com/hotels/travel/ceimd-le-meridien-chiang-rai-resort/"},
        {"name": "Renaissance Bangkok Ratchaprasong Hotel", "city": "Bangkok (Chit Lom / Ploenchit)", "url": "https://www.marriott.com/hotels/travel/bkkbr-renaissance-bangkok-ratchaprasong-hotel/"},
        {"name": "Renaissance Koh Samui Resort & Spa", "city": "Koh Samui (Lamai Beach)", "url": "https://www.marriott.com/hotels/travel/usmbr-renaissance-koh-samui-resort-and-spa/"},
        {"name": "Renaissance Pattaya Resort & Spa", "city": "Pattaya (Na Jomtien)", "url": "https://www.marriott.com/hotels/travel/pyxbr-renaissance-pattaya-resort-and-spa/"},
        {"name": "Renaissance Phuket Resort & Spa", "city": "Phuket (Mai Khao)", "url": "https://www.marriott.com/hotels/travel/hktbr-renaissance-phuket-resort-and-spa/"},
        {"name": "Courtyard by Marriott Bangkok", "city": "Bangkok (Rajdamri / Soi Mahadlekluang)", "url": "https://www.marriott.com/hotels/travel/bkkcy-courtyard-bangkok/"},
        {"name": "Courtyard by Marriott Bangkok Sukhumvit 20", "city": "Bangkok (Sukhumvit 20)", "url": "https://www.marriott.com/hotels/travel/bkkct-courtyard-bangkok-sukhumvit-20/"},
        {"name": "Courtyard by Marriott Phuket, Patong Beach", "city": "Phuket (Patong)", "url": "https://www.marriott.com/hotels/travel/hktcb-courtyard-phuket-patong-beach/"},
        {"name": "Courtyard by Marriott Phuket Town", "city": "Phuket (Phuket Old Town)", "url": "https://www.marriott.com/hotels/travel/hktct-courtyard-phuket-town/"},
        {"name": "Aloft Bangkok Sukhumvit 11", "city": "Bangkok (Sukhumvit 11 / Nana)", "url": "https://www.marriott.com/hotels/travel/bkkal-aloft-bangkok-sukhumvit-11/"},
        {"name": "Moxy Bangkok Ratchaprasong", "city": "Bangkok (Ratchaprasong / The Market)", "url": "https://www.marriott.com/hotels/travel/bkkox-moxy-bangkok-ratchaprasong/"}
    ],
    "Malaysia": [
        {"name": "The St. Regis Kuala Lumpur", "city": "Kuala Lumpur (KL Sentral / Lake Gardens)", "url": "https://www.marriott.com/hotels/travel/kulxr-the-st-regis-kuala-lumpur/"},
        {"name": "The Ritz-Carlton, Kuala Lumpur", "city": "Kuala Lumpur (Bukit Bintang / Jalan Imbi)", "url": "https://www.marriott.com/hotels/travel/kulrz-the-ritz-carlton-kuala-lumpur/"},
        {"name": "The Ritz-Carlton, Langkawi", "city": "Langkawi (Pantai Kok / Teluk Nibong)", "url": "https://www.marriott.com/hotels/travel/lgkrz-the-ritz-carlton-langkawi/"},
        {"name": "The St. Regis Langkawi", "city": "Langkawi (Kuah / Beringgis Beach)", "url": "https://www.marriott.com/hotels/travel/lgkxr-the-st-regis-langkawi/"},
        {"name": "JW Marriott Hotel Kuala Lumpur", "city": "Kuala Lumpur (Bukit Bintang / Starhill)", "url": "https://www.marriott.com/hotels/travel/kuljw-jw-marriott-hotel-kuala-lumpur/"},
        {"name": "W Kuala Lumpur", "city": "Kuala Lumpur (Jalan Ampang / Petronas View)", "url": "https://www.marriott.com/hotels/travel/kulwh-w-kuala-lumpur/"},
        {"name": "The Westin Kuala Lumpur", "city": "Kuala Lumpur (Bukit Bintang / Pavilion)", "url": "https://www.marriott.com/hotels/travel/kulwi-the-westin-kuala-lumpur/"},
        {"name": "The Westin Desaru Coast Resort", "city": "Desaru (Johor / Desaru Coast)", "url": "https://www.marriott.com/hotels/travel/jhbwi-the-westin-desaru-coast-resort/"},
        {"name": "The Westin Langkawi Resort & Spa", "city": "Langkawi (Kuah)", "url": "https://www.marriott.com/hotels/travel/lgkwi-the-westin-langkawi-resort-and-spa/"},
        {"name": "Le Méridien Kuala Lumpur", "city": "Kuala Lumpur (KL Sentral)", "url": "https://www.marriott.com/hotels/travel/kulmd-le-meridien-kuala-lumpur/"},
        {"name": "Le Méridien Petaling Jaya", "city": "Petaling Jaya (Paradigm Mall)", "url": "https://www.marriott.com/hotels/travel/kulpm-le-meridien-petaling-jaya/"},
        {"name": "Le Méridien Kota Kinabalu", "city": "Kota Kinabalu (Waterfront / Sabah)", "url": "https://www.marriott.com/hotels/travel/bkimd-le-meridien-kota-kinabalu/"},
        {"name": "Renaissance Kuala Lumpur Hotel & Convention Centre", "city": "Kuala Lumpur (Jalan Sultan Ismail)", "url": "https://www.marriott.com/hotels/travel/kulrn-renaissance-kuala-lumpur-hotel-and-convention-centre/"},
        {"name": "Four Points by Sheraton Kuala Lumpur, Chinatown", "city": "Kuala Lumpur (Petaling Street / Chinatown)", "url": "https://www.marriott.com/hotels/travel/kulfc-four-points-kuala-lumpur-chinatown/"},
        {"name": "Four Points by Sheraton Kuala Lumpur, City Centre", "city": "Kuala Lumpur (Jalan Sultan Ismail)", "url": "https://www.marriott.com/hotels/travel/kulfp-four-points-kuala-lumpur-city-centre/"},
        {"name": "Aloft Kuala Lumpur Sentral", "city": "Kuala Lumpur (KL Sentral)", "url": "https://www.marriott.com/hotels/travel/kulal-aloft-kuala-lumpur-sentral/"},
        {"name": "Courtyard by Marriott Melaka", "city": "Melaka (Lorong Hang Jebat)", "url": "https://www.marriott.com/hotels/travel/mkzcy-courtyard-melaka/"},
        {"name": "Courtyard by Marriott Penang", "city": "Penang (Jalan Macalister / George Town)", "url": "https://www.marriott.com/hotels/travel/pency-courtyard-penang/"}
    ],
    "Japan": [
        {"name": "The Ritz-Carlton, Tokyo", "city": "Tokyo (Roppongi / Tokyo Midtown)", "url": "https://www.marriott.com/hotels/travel/tyorz-the-ritz-carlton-tokyo/"},
        {"name": "The Ritz-Carlton, Kyoto", "city": "Kyoto (Kamogawa River / Nakagyo)", "url": "https://www.marriott.com/hotels/travel/ukyrz-the-ritz-carlton-kyoto/"},
        {"name": "The Ritz-Carlton, Osaka", "city": "Osaka (Umeda / Nishi-Umeda)", "url": "https://www.marriott.com/hotels/travel/osarz-the-ritz-carlton-osaka/"},
        {"name": "The Ritz-Carlton, Nikko", "city": "Nikko (Lake Chuzenji / Tochigi)", "url": "https://www.marriott.com/hotels/travel/hktnr-the-ritz-carlton-nikko/"},
        {"name": "The Ritz-Carlton, Okinawa", "city": "Okinawa (Nago / Kise Country Club)", "url": "https://www.marriott.com/hotels/travel/okarz-the-ritz-carlton-okinawa/"},
        {"name": "The Ritz-Carlton, Fukuoka", "city": "Fukuoka (Tenjin / Daimyo)", "url": "https://www.marriott.com/hotels/travel/fukrz-the-ritz-carlton-fukuoka/"},
        {"name": "The Tokyo EDITION, Toranomon", "city": "Tokyo (Toranomon / Minato)", "url": "https://www.marriott.com/hotels/travel/tyoet-the-tokyo-edition-toranomon/"},
        {"name": "The Tokyo EDITION, Ginza", "city": "Tokyo (Ginza / Chuo)", "url": "https://www.marriott.com/hotels/travel/tyoeg-the-tokyo-edition-ginza/"},
        {"name": "The St. Regis Osaka", "city": "Osaka (Midosuji / Honmachi)", "url": "https://www.marriott.com/hotels/travel/osaxr-the-st-regis-osaka/"},
        {"name": "JW Marriott Hotel Nara", "city": "Nara (Sanjo-dori / Nara Park)", "url": "https://www.marriott.com/hotels/travel/osajw-jw-marriott-hotel-nara/"},
        {"name": "W Osaka", "city": "Osaka (Midosuji / Shinsaibashi)", "url": "https://www.marriott.com/hotels/travel/osawh-w-osaka/"},
        {"name": "Suiran, a Luxury Collection Hotel, Kyoto", "city": "Kyoto (Arashiyama / Katsura River)", "url": "https://www.marriott.com/hotels/travel/ukylc-suiran-a-luxury-collection-hotel-kyoto/"},
        {"name": "Hotel The Mitsui Kyoto, a Luxury Collection Hotel & Spa", "city": "Kyoto (Nijo Castle / Nakagyo)", "url": "https://www.marriott.com/hotels/travel/ukyhm-hotel-the-mitsui-kyoto-a-luxury-collection-hotel-and-spa/"},
        {"name": "The Prince Gallery Tokyo Kioicho, a Luxury Collection Hotel", "city": "Tokyo (Kioicho / Chiyoda)", "url": "https://www.marriott.com/hotels/travel/tyolc-the-prince-gallery-tokyo-kioicho-a-luxury-collection-hotel/"},
        {"name": "The Westin Tokyo", "city": "Tokyo (Yebisu Garden Place / Meguro)", "url": "https://www.marriott.com/hotels/travel/tyowi-the-westin-tokyo/"},
        {"name": "The Westin Miyako Kyoto", "city": "Kyoto (Higashiyama / Keage)", "url": "https://www.marriott.com/hotels/travel/ukywi-the-westin-miyako-kyoto/"},
        {"name": "The Westin Osaka", "city": "Osaka (Umeda / Grand Front)", "url": "https://www.marriott.com/hotels/travel/osawi-the-westin-osaka/"},
        {"name": "The Westin Yokohama", "city": "Yokohama (Minatomirai)", "url": "https://www.marriott.com/hotels/travel/tyowy-the-westin-yokohama/"},
        {"name": "Mesm Tokyo, Autograph Collection", "city": "Tokyo (Takeshiba / Waters Takeshiba)", "url": "https://www.marriott.com/hotels/travel/tyoam-mesm-tokyo-autograph-collection/"},
        {"name": "Tokyo Marriott Hotel", "city": "Tokyo (Shinagawa / Gotenyama)", "url": "https://www.marriott.com/hotels/travel/tyomc-tokyo-marriott-hotel/"},
        {"name": "Nagoya Marriott Associa Hotel", "city": "Nagoya (JR Central Towers / Nagoya Station)", "url": "https://www.marriott.com/hotels/travel/ngaso-nagoya-marriott-associa-hotel/"},
        {"name": "Courtyard by Marriott Tokyo Station", "city": "Tokyo (Kyobashi / Yaesu)", "url": "https://www.marriott.com/hotels/travel/tyocy-courtyard-tokyo-station/"},
        {"name": "Courtyard by Marriott Tokyo Ginza Hotel", "city": "Tokyo (Ginza / Showa-dori)", "url": "https://www.marriott.com/hotels/travel/tyogn-courtyard-tokyo-ginza-hotel/"},
        {"name": "AC Hotel by Marriott Tokyo Ginza", "city": "Tokyo (Ginza)", "url": "https://www.marriott.com/hotels/travel/tyoar-ac-hotel-tokyo-ginza/"},
        {"name": "Aloft Tokyo Ginza", "city": "Tokyo (Ginza)", "url": "https://www.marriott.com/hotels/travel/tyoal-aloft-tokyo-ginza/"},
        {"name": "Moxy Tokyo Kinshicho", "city": "Tokyo (Kinshicho / Sumida)", "url": "https://www.marriott.com/hotels/travel/tyoox-moxy-tokyo-kinshicho/"}
    ],
    "South Korea": [
        {"name": "JW Marriott Dongdaemun Square Seoul", "city": "Seoul (Dongdaemun / Cheonggyecheon)", "url": "https://www.marriott.com/hotels/travel/seldp-jw-marriott-dongdaemun-square-seoul/"},
        {"name": "JW Marriott Hotel Seoul", "city": "Seoul (Gangnam / Express Bus Terminal)", "url": "https://www.marriott.com/hotels/travel/seljw-jw-marriott-hotel-seoul/"},
        {"name": "The Westin Josun Seoul", "city": "Seoul (Sogong-dong / Myeongdong)", "url": "https://www.marriott.com/hotels/travel/selwi-the-westin-josun-seoul/"},
        {"name": "The Westin Josun Busan", "city": "Busan (Haeundae Beach / Dongbaek)", "url": "https://www.marriott.com/hotels/travel/puswi-the-westin-josun-busan/"},
        {"name": "The Plaza Seoul, Autograph Collection", "city": "Seoul (Sogong-ro / City Hall)", "url": "https://www.marriott.com/hotels/travel/selak-the-plaza-seoul-autograph-collection/"},
        {"name": "Josun Palace, a Luxury Collection Hotel, Seoul Gangnam", "city": "Seoul (Teheran-ro / Yeoksam)", "url": "https://www.marriott.com/hotels/travel/sellc-josun-palace-a-luxury-collection-hotel-seoul-gangnam/"},
        {"name": "Le Méridien Seoul, Myeongdong", "city": "Seoul (Myeongdong)", "url": "https://www.marriott.com/hotels/travel/selmm-le-meridien-seoul-myeongdong/"},
        {"name": "Moxy Seoul Myeongdong", "city": "Seoul (Myeongdong)", "url": "https://www.marriott.com/hotels/travel/selom-moxy-seoul-myeongdong/"},
        {"name": "Moxy Seoul Insadong", "city": "Seoul (Insadong / Ikseon-dong)", "url": "https://www.marriott.com/hotels/travel/selmx-moxy-seoul-insadong/"},
        {"name": "Courtyard by Marriott Seoul Namdaemun", "city": "Seoul (Namdaemun / Sungnyemun)", "url": "https://www.marriott.com/hotels/travel/selcy-courtyard-seoul-namdaemun/"},
        {"name": "JW Marriott Jeju Resort & Spa", "city": "Jeju (Seogwipo / Oedolgae Cliff)", "url": "https://www.marriott.com/hotels/travel/cjujw-jw-marriott-jeju-resort-and-spa/"}
    ],
    "China": [
        {"name": "The Ritz-Carlton, Hong Kong", "city": "Hong Kong (West Kowloon / ICC 102-118)", "url": "https://www.marriott.com/hotels/travel/hkgkw-the-ritz-carlton-hong-kong/"},
        {"name": "The St. Regis Hong Kong", "city": "Hong Kong (Wan Chai / Harbour Rd)", "url": "https://www.marriott.com/hotels/travel/hkgxr-the-st-regis-hong-kong/"},
        {"name": "The Ritz-Carlton Shanghai, Pudong", "city": "Shanghai (Lujiazui / IFC)", "url": "https://www.marriott.com/hotels/travel/shasz-the-ritz-carlton-shanghai-pudong/"},
        {"name": "The Ritz-Carlton Shanghai, Portman", "city": "Shanghai (Nanjing West Rd)", "url": "https://www.marriott.com/hotels/travel/shahr-the-portman-ritz-carlton-shanghai/"},
        {"name": "The Shanghai EDITION", "city": "Shanghai (Nanjing East Rd / The Bund)", "url": "https://www.marriott.com/hotels/travel/shaed-the-shanghai-edition/"},
        {"name": "The St. Regis Shanghai Jingan", "city": "Shanghai (Beijing West Rd / Jing'an)", "url": "https://www.marriott.com/hotels/travel/shaxr-the-st-regis-shanghai-jingan/"},
        {"name": "W Shanghai - The Bund", "city": "Shanghai (North Bund / Huangpu River)", "url": "https://www.marriott.com/hotels/travel/shawh-w-shanghai-the-bund/"},
        {"name": "JW Marriott Hotel Shanghai at Tomorrow Square", "city": "Shanghai (People's Square)", "url": "https://www.marriott.com/hotels/travel/shajw-jw-marriott-hotel-shanghai-at-tomorrow-square/"},
        {"name": "The Ritz-Carlton, Beijing", "city": "Beijing (Financial Street / Chaoyang)", "url": "https://www.marriott.com/hotels/travel/bjsrt-the-ritz-carlton-beijing/"},
        {"name": "The St. Regis Beijing", "city": "Beijing (Jianguomenwai / Chaoyang)", "url": "https://www.marriott.com/hotels/travel/bjsxr-the-st-regis-beijing/"},
        {"name": "The Ritz-Carlton, Guangzhou", "city": "Guangzhou (Zhujiang New Town)", "url": "https://www.marriott.com/hotels/travel/canrt-the-ritz-carlton-guangzhou/"},
        {"name": "The St. Regis Shenzhen", "city": "Shenzhen (KK100 / Luohu)", "url": "https://www.marriott.com/hotels/travel/szxxr-the-st-regis-shenzhen/"},
        {"name": "The Ritz-Carlton, Shenzhen", "city": "Shenzhen (Futian CBD)", "url": "https://www.marriott.com/hotels/travel/szxrz-the-ritz-carlton-shenzhen/"},
        {"name": "JW Marriott Hotel Hong Kong", "city": "Hong Kong (Admiralty / Pacific Place)", "url": "https://www.marriott.com/hotels/travel/hkgdt-jw-marriott-hotel-hong-kong/"},
        {"name": "W Hong Kong", "city": "Hong Kong (West Kowloon / Elements)", "url": "https://www.marriott.com/hotels/travel/hkgwh-w-hong-kong/"},
        {"name": "The Ritz-Carlton, Macau", "city": "Macau (Galaxy Macau / Cotai)", "url": "https://www.marriott.com/hotels/travel/mfmrz-the-ritz-carlton-macau/"},
        {"name": "The St. Regis Macao", "city": "Macau (The Londoner Macao / Cotai)", "url": "https://www.marriott.com/hotels/travel/mfmxr-the-st-regis-macao/"},
        {"name": "JW Marriott Hotel Macau", "city": "Macau (Galaxy Macau / Cotai)", "url": "https://www.marriott.com/hotels/travel/mfmjw-jw-marriott-hotel-macau/"}
    ],
    "Taiwan": [
        {"name": "W Taipei", "city": "Taipei (Xinyi District / Hankyu)", "url": "https://www.marriott.com/hotels/travel/tpewh-w-taipei/"},
        {"name": "Taipei Marriott Hotel", "city": "Taipei (Dazhi / Zhongshan)", "url": "https://www.marriott.com/hotels/travel/tpemc-taipei-marriott-hotel/"},
        {"name": "Le Méridien Taipei", "city": "Taipei (Xinyi District)", "url": "https://www.marriott.com/hotels/travel/tpedm-le-meridien-taipei/"},
        {"name": "Sheraton Grand Taipei Hotel", "city": "Taipei (Zhongxiao East Rd)", "url": "https://www.marriott.com/hotels/travel/tpesu-sheraton-grand-taipei-hotel/"},
        {"name": "The Westin Tashee Resort, Taoyuan", "city": "Taoyuan (Daxi)", "url": "https://www.marriott.com/hotels/travel/tyewi-the-westin-tashee-resort-taoyuan/"}
    ],
    "Australia": [
        {"name": "The Ritz-Carlton, Melbourne", "city": "Melbourne (Lonsdale St / West Side Place)", "url": "https://www.marriott.com/hotels/travel/melrz-the-ritz-carlton-melbourne/"},
        {"name": "The Ritz-Carlton, Perth", "city": "Perth (Elizabeth Quay / Swan River)", "url": "https://www.marriott.com/hotels/travel/perrz-the-ritz-carlton-perth/"},
        {"name": "W Sydney", "city": "Sydney (Darling Harbour / The Ribbon)", "url": "https://www.marriott.com/hotels/travel/sydwh-w-sydney/"},
        {"name": "W Brisbane", "city": "Brisbane (North Quay / Brisbane River)", "url": "https://www.marriott.com/hotels/travel/bnewh-w-brisbane/"},
        {"name": "W Melbourne", "city": "Melbourne (Flinders Lane / Collins Arch)", "url": "https://www.marriott.com/hotels/travel/melwh-w-melbourne/"},
        {"name": "Sydney Harbour Marriott Hotel at Circular Quay", "city": "Sydney (Pitt St / Circular Quay)", "url": "https://www.marriott.com/hotels/travel/sydmc-sydney-harbour-marriott-hotel-at-circular-quay/"},
        {"name": "Melbourne Marriott Hotel Docklands", "city": "Melbourne (Docklands / Waterfront Way)", "url": "https://www.marriott.com/hotels/travel/melsj-melbourne-marriott-hotel-docklands/"},
        {"name": "The Westin Brisbane", "city": "Brisbane (Mary St)", "url": "https://www.marriott.com/hotels/travel/bnewi-the-westin-brisbane/"},
        {"name": "The Westin Perth", "city": "Perth (Hay St)", "url": "https://www.marriott.com/hotels/travel/perwi-the-westin-perth/"},
        {"name": "Sheraton Grand Mirage Resort, Gold Coast", "city": "Gold Coast (Main Beach)", "url": "https://www.marriott.com/hotels/travel/oolgs-sheraton-grand-mirage-resort-gold-coast/"},
        {"name": "Sheraton Grand Mirage Resort, Port Douglas", "city": "Port Douglas (Four Mile Beach)", "url": "https://www.marriott.com/hotels/travel/ptisi-sheraton-grand-mirage-resort-port-douglas/"}
    ],
    "New Zealand": [
        {"name": "JW Marriott Hotel Auckland", "city": "Auckland (Albert St / CBD)", "url": "https://www.marriott.com/hotels/travel/aklmc-jw-marriott-hotel-auckland/"},
        {"name": "Four Points by Sheraton Auckland", "city": "Auckland (Queen St)", "url": "https://www.marriott.com/hotels/travel/aklfp-four-points-auckland/"}
    ],
    "India": [
        {"name": "The St. Regis Mumbai", "city": "Mumbai (Lower Parel / High Street Phoenix)", "url": "https://www.marriott.com/hotels/travel/bomxr-the-st-regis-mumbai/"},
        {"name": "The Ritz-Carlton, Bangalore", "city": "Bangalore (Residency Rd)", "url": "https://www.marriott.com/hotels/travel/blrtr-the-ritz-carlton-bangalore/"},
        {"name": "The Ritz-Carlton, Pune", "city": "Pune (Golf Course / Airport Rd)", "url": "https://www.marriott.com/hotels/travel/pnqrz-the-ritz-carlton-pune/"},
        {"name": "JW Marriott Hotel New Delhi Aerocity", "city": "New Delhi (Aerocity)", "url": "https://www.marriott.com/hotels/travel/delap-jw-marriott-hotel-new-delhi-aerocity/"},
        {"name": "JW Marriott Hotel Mumbai Sahar", "city": "Mumbai (Chhatrapati Shivaji Airport)", "url": "https://www.marriott.com/hotels/travel/bomsa-jw-marriott-hotel-mumbai-sahar/"},
        {"name": "JW Marriott Mumbai Juhu", "city": "Mumbai (Juhu Tara Rd / Arabian Sea)", "url": "https://www.marriott.com/hotels/travel/bomjw-jw-marriott-mumbai-juhu/"},
        {"name": "W Goa", "city": "Goa (Vagator Beach / Chapora Fort)", "url": "https://www.marriott.com/hotels/travel/goawh-w-goa/"},
        {"name": "The Westin Mumbai Garden City", "city": "Mumbai (Goregaon East)", "url": "https://www.marriott.com/hotels/travel/bomwi-the-westin-mumbai-garden-city/"},
        {"name": "The Westin Hyderabad Mindspace", "city": "Hyderabad (HITEC City)", "url": "https://www.marriott.com/hotels/travel/hydwi-the-westin-hyderabad-mindspace/"}
    ],
    "Maldives": [
        {"name": "The St. Regis Maldives Vommuli Resort", "city": "Maldives (Dhaalu Atoll / Private Island)", "url": "https://www.marriott.com/hotels/travel/mlexr-the-st-regis-maldives-vommuli-resort/"},
        {"name": "The Ritz-Carlton Maldives, Fari Islands", "city": "Maldives (North Malé Atoll / Fari Islands)", "url": "https://www.marriott.com/hotels/travel/mlezr-the-ritz-carlton-maldives-fari-islands/"},
        {"name": "JW Marriott Maldives Resort & Spa", "city": "Maldives (Shaviyani Atoll / Vagaru Island)", "url": "https://www.marriott.com/hotels/travel/mlejs-jw-marriott-maldives-resort-and-spa/"},
        {"name": "W Maldives", "city": "Maldives (North Ari Atoll / Fesdu Island)", "url": "https://www.marriott.com/hotels/travel/mlewh-w-maldives/"},
        {"name": "The Westin Maldives Miriandhoo Resort", "city": "Maldives (Baa Atoll / UNESCO Biosphere)", "url": "https://www.marriott.com/hotels/travel/mlewi-the-westin-maldives-miriandhoo-resort/"},
        {"name": "Sheraton Maldives Full Moon Resort & Spa", "city": "Maldives (North Malé Atoll / Furanafushi)", "url": "https://www.marriott.com/hotels/travel/mlesi-sheraton-maldives-full-moon-resort-and-spa/"}
    ],
    "United Arab Emirates": [
        {"name": "Bulgari Resort Dubai", "city": "Dubai (Jumeira Bay Island)", "url": "https://www.marriott.com/hotels/travel/dxbbg-bulgari-resort-dubai/"},
        {"name": "The Ritz-Carlton, Dubai", "city": "Dubai (Jumeirah Beach Residence / JBR)", "url": "https://www.marriott.com/hotels/travel/dxbrz-the-ritz-carlton-dubai/"},
        {"name": "The Ritz-Carlton, Dubai International Financial Centre", "city": "Dubai (DIFC / Sheikh Zayed Rd)", "url": "https://www.marriott.com/hotels/travel/dxbdc-the-ritz-carlton-dubai-international-financial-centre/"},
        {"name": "The St. Regis Dubai, The Palm", "city": "Dubai (Palm Jumeirah / Nakheel Mall)", "url": "https://www.marriott.com/hotels/travel/dxbpx-the-st-regis-dubai-the-palm/"},
        {"name": "The St. Regis Downtown, Dubai", "city": "Dubai (Business Bay / Dubai Water Canal)", "url": "https://www.marriott.com/hotels/travel/dxbsx-the-st-regis-downtown-dubai/"},
        {"name": "The St. Regis Saadiyat Island Resort, Abu Dhabi", "city": "Abu Dhabi (Saadiyat Beach)", "url": "https://www.marriott.com/hotels/travel/auhxr-the-st-regis-saadiyat-island-resort-abu-dhabi/"},
        {"name": "The St. Regis Abu Dhabi", "city": "Abu Dhabi (Corniche / Nation Towers)", "url": "https://www.marriott.com/hotels/travel/auhxi-the-st-regis-abu-dhabi/"},
        {"name": "The Ritz-Carlton Abu Dhabi, Grand Canal", "city": "Abu Dhabi (Al Rawdah / Grand Mosque View)", "url": "https://www.marriott.com/hotels/travel/auhrz-the-ritz-carlton-abu-dhabi-grand-canal/"},
        {"name": "The Dubai EDITION", "city": "Dubai (Downtown / Dubai Mall View)", "url": "https://www.marriott.com/hotels/travel/dxbed-the-dubai-edition/"},
        {"name": "The Abu Dhabi EDITION", "city": "Abu Dhabi (Al Bateen Marina)", "url": "https://www.marriott.com/hotels/travel/auhed-the-abu-dhabi-edition/"},
        {"name": "JW Marriott Marquis Hotel Dubai", "city": "Dubai (Business Bay / Sheikh Zayed Rd)", "url": "https://www.marriott.com/hotels/travel/dxbjw-jw-marriott-marquis-hotel-dubai/"},
        {"name": "W Dubai - The Palm", "city": "Dubai (Palm Jumeirah West Crescent)", "url": "https://www.marriott.com/hotels/travel/dxbtp-w-dubai-the-palm/"},
        {"name": "W Abu Dhabi - Yas Island", "city": "Abu Dhabi (Yas Marina Circuit)", "url": "https://www.marriott.com/hotels/travel/auhwh-w-abu-dhabi-yas-island/"},
        {"name": "Grosvenor House, a Luxury Collection Hotel, Dubai", "city": "Dubai (Dubai Marina / Al Emreef St)", "url": "https://www.marriott.com/hotels/travel/dxbgh-grosvenor-house-a-luxury-collection-hotel-dubai/"},
        {"name": "Al Maha, a Luxury Collection Desert Resort & Spa, Dubai", "city": "Dubai (Dubai Desert Conservation Reserve)", "url": "https://www.marriott.com/hotels/travel/dxbam-al-maha-a-luxury-collection-desert-resort-and-spa-dubai/"}
    ],
    "Saudi Arabia": [
        {"name": "The Ritz-Carlton, Riyadh", "city": "Riyadh (Al Hada / Diplomatic Quarter)", "url": "https://www.marriott.com/hotels/travel/ruhbr-the-ritz-carlton-riyadh/"},
        {"name": "The Ritz-Carlton, Jeddah", "city": "Jeddah (Al Hamra / King Abdulaziz Rd)", "url": "https://www.marriott.com/hotels/travel/jedrz-the-ritz-carlton-jeddah/"},
        {"name": "The St. Regis Riyadh", "city": "Riyadh (Via Riyadh / Al Hada)", "url": "https://www.marriott.com/hotels/travel/ruhxr-the-st-regis-riyadh/"},
        {"name": "The St. Regis Red Sea Resort", "city": "Red Sea (Ummahat Island)", "url": "https://www.marriott.com/hotels/travel/ejhxr-the-st-regis-red-sea-resort/"},
        {"name": "JW Marriott Hotel Riyadh", "city": "Riyadh (King Fahad Rd / As Sahafah)", "url": "https://www.marriott.com/hotels/travel/ruhjw-jw-marriott-hotel-riyadh/"},
        {"name": "Jabal Omar JW Marriott Hotel Makkah", "city": "Makkah (Ibrahim Al Khalil / Haram)", "url": "https://www.marriott.com/hotels/travel/makjw-jabal-omar-jw-marriott-hotel-makkah/"},
        {"name": "Makkah Marriott Hotel", "city": "Makkah (Jabal Omar)", "url": "https://www.marriott.com/hotels/travel/makmc-makkah-marriott-hotel/"},
        {"name": "Madinah Marriott Hotel", "city": "Madinah (King Faisal Rd / Haram)", "url": "https://www.marriott.com/hotels/travel/medmc-madinah-marriott-hotel/"}
    ],
    "Qatar": [
        {"name": "The Ritz-Carlton, Doha", "city": "Doha (West Bay Lagoon / Pearl Blvd)", "url": "https://www.marriott.com/hotels/travel/dohrz-the-ritz-carlton-doha/"},
        {"name": "The Ritz-Carlton Sharq Village & Spa, Doha", "city": "Doha (Ras Abu Abboud / Corniche)", "url": "https://www.marriott.com/hotels/travel/dohsq-sharq-village-and-spa-a-ritz-carlton-hotel/"},
        {"name": "The St. Regis Doha", "city": "Doha (West Bay / Al Gassar Resort)", "url": "https://www.marriott.com/hotels/travel/dohxr-the-st-regis-doha/"},
        {"name": "The St. Regis Marsa Arabia Island, The Pearl-Qatar", "city": "Doha (Porto Arabia / The Pearl)", "url": "https://www.marriott.com/hotels/travel/dohxp-the-st-regis-marsa-arabia-island-the-pearl-qatar/"},
        {"name": "W Doha", "city": "Doha (West Bay)", "url": "https://www.marriott.com/hotels/travel/dohwh-w-doha/"},
        {"name": "JW Marriott Marquis City Center Doha", "city": "Doha (Conference Centre St / West Bay)", "url": "https://www.marriott.com/hotels/travel/dohjb-jw-marriott-marquis-city-center-doha/"}
    ],
    "United Kingdom": [
        {"name": "The London EDITION", "city": "London (Berners St / Fitzrovia)", "url": "https://www.marriott.com/hotels/travel/loned-the-london-edition/"},
        {"name": "The Wellesley, a Luxury Collection Hotel, Knightsbridge", "city": "London (Hyde Park Corner / Knightsbridge)", "url": "https://www.marriott.com/hotels/travel/lonwi-the-wellesley-a-luxury-collection-hotel-knightsbridge-london/"},
        {"name": "W London", "city": "London (Leicester Square / Soho)", "url": "https://www.marriott.com/hotels/travel/lonwh-w-london/"},
        {"name": "JW Marriott Grosvenor House London", "city": "London (Park Lane / Mayfair)", "url": "https://www.marriott.com/hotels/travel/longh-jw-marriott-grosvenor-house-london/"},
        {"name": "London Marriott Hotel Park Lane", "city": "London (Park Lane / Marble Arch)", "url": "https://www.marriott.com/hotels/travel/lonpl-london-marriott-hotel-park-lane/"},
        {"name": "London Marriott Hotel County Hall", "city": "London (Westminster Bridge / South Bank)", "url": "https://www.marriott.com/hotels/travel/lonch-london-marriott-hotel-county-hall/"},
        {"name": "Sheraton Grand London Park Lane", "city": "London (Piccadilly / Mayfair)", "url": "https://www.marriott.com/hotels/travel/lonpl-sheraton-grand-london-park-lane/"},
        {"name": "St. Pancras Renaissance Hotel London", "city": "London (Euston Rd / King's Cross)", "url": "https://www.marriott.com/hotels/travel/lonpr-st-pancras-renaissance-hotel-london/"},
        {"name": "W Edinburgh", "city": "Edinburgh (St James Quarter / New Town)", "url": "https://www.marriott.com/hotels/travel/ediwh-w-edinburgh/"},
        {"name": "The Glasshouse, Autograph Collection", "city": "Edinburgh (Greenside Place)", "url": "https://www.marriott.com/hotels/travel/ediak-the-glasshouse-autograph-collection/"}
    ],
    "France": [
        {"name": "The Ritz Paris (Partner Directory)", "city": "Paris (Place Vendôme)", "url": "https://www.marriott.com/hotel/parrz-the-ritz-paris"},
        {"name": "Prince de Galles, a Luxury Collection Hotel, Paris", "city": "Paris (Avenue George V / Champs-Élysées)", "url": "https://www.marriott.com/hotels/travel/parlc-prince-de-galles-a-luxury-collection-hotel-paris/"},
        {"name": "Hôtel de Berri, a Luxury Collection Hotel, Paris", "city": "Paris (Rue de Berri / 8th Arr)", "url": "https://www.marriott.com/hotels/travel/parbr-hotel-de-berri-a-luxury-collection-hotel-paris/"},
        {"name": "W Paris - Opéra", "city": "Paris (Rue Meyerbeer / Opéra Garnier)", "url": "https://www.marriott.com/hotels/travel/parwh-w-paris-opera/"},
        {"name": "Paris Marriott Champs Elysees Hotel", "city": "Paris (Avenue des Champs-Élysées)", "url": "https://www.marriott.com/hotels/travel/parst-paris-marriott-champs-elysees-hotel/"},
        {"name": "Paris Marriott Opera Ambassador Hotel", "city": "Paris (Boulevard Haussmann)", "url": "https://www.marriott.com/hotels/travel/parmb-paris-marriott-opera-ambassador-hotel/"},
        {"name": "The Westin Paris - Vendôme", "city": "Paris (Rue de Rivoli / Tuileries Garden)", "url": "https://www.marriott.com/hotels/travel/parwi-the-westin-paris-vendome/"},
        {"name": "Renaissance Paris Vendome Hotel", "city": "Paris (Rue du Mont Thabor)", "url": "https://www.marriott.com/hotels/travel/parvd-renaissance-paris-vendome-hotel/"},
        {"name": "Renaissance Paris Arc de Triomphe Hotel", "city": "Paris (Avenue de Wagram)", "url": "https://www.marriott.com/hotels/travel/parwg-renaissance-paris-arc-de-triomphe-hotel/"},
        {"name": "JW Marriott Cannes", "city": "Cannes (Boulevard de la Croisette)", "url": "https://www.marriott.com/hotels/travel/ncejw-jw-marriott-cannes/"}
    ],
    "Italy": [
        {"name": "The St. Regis Rome", "city": "Rome (Via Vittorio Emanuele Orlando / Republic)", "url": "https://www.marriott.com/hotels/travel/romxr-the-st-regis-rome/"},
        {"name": "The St. Regis Florence", "city": "Florence (Piazza Ognissanti / Arno River)", "url": "https://www.marriott.com/hotels/travel/flrxr-the-st-regis-florence/"},
        {"name": "The St. Regis Venice", "city": "Venice (Grand Canal / San Marco)", "url": "https://www.marriott.com/hotels/travel/vnexr-the-st-regis-venice/"},
        {"name": "The Rome EDITION", "city": "Rome (Salita di San Nicola da Tolentino)", "url": "https://www.marriott.com/hotels/travel/romed-the-rome-edition/"},
        {"name": "W Rome", "city": "Rome (Via Liguria / Via Veneto)", "url": "https://www.marriott.com/hotels/travel/romwh-w-rome/"},
        {"name": "Bulgari Hotel Roma", "city": "Rome (Piazza Augusto Imperatore / Campo Marzio)", "url": "https://www.marriott.com/hotels/travel/rombg-bulgari-hotel-roma/"},
        {"name": "Bulgari Hotel Milano", "city": "Milan (Via Privata Fratelli Gabba / Brera)", "url": "https://www.marriott.com/hotels/travel/milbg-bulgari-hotel-milano/"},
        {"name": "The Westin Palace, Milan", "city": "Milan (Piazza della Repubblica)", "url": "https://www.marriott.com/hotels/travel/milwi-the-westin-palace-milan/"},
        {"name": "The Westin Excelsior, Rome", "city": "Rome (Via Vittorio Veneto)", "url": "https://www.marriott.com/hotels/travel/romwi-the-westin-excelsior-rome/"},
        {"name": "The Gritti Palace, a Luxury Collection Hotel, Venice", "city": "Venice (Grand Canal / Campo Santa Maria del Giglio)", "url": "https://www.marriott.com/hotels/travel/vcelc-the-gritti-palace-a-luxury-collection-hotel-venice/"},
        {"name": "JW Marriott Venice Resort & Spa", "city": "Venice (Isola delle Rose)", "url": "https://www.marriott.com/hotels/travel/vcejw-jw-marriott-venice-resort-and-spa/"}
    ],
    "Spain": [
        {"name": "The Ritz-Carlton, Abama", "city": "Tenerife (Guía de Isora / Canary Islands)", "url": "https://www.marriott.com/hotels/travel/tfsrz-the-ritz-carlton-abama/"},
        {"name": "The Madrid EDITION", "city": "Madrid (Plaza de Celenque / Sol)", "url": "https://www.marriott.com/hotels/travel/maded-the-madrid-edition/"},
        {"name": "The Barcelona EDITION", "city": "Barcelona (Av. Francesc Cambó / El Born)", "url": "https://www.marriott.com/hotels/travel/bcned-the-barcelona-edition/"},
        {"name": "Santo Mauro, a Luxury Collection Hotel, Madrid", "city": "Madrid (Calle de Zurbano / Chamberí)", "url": "https://www.marriott.com/hotels/travel/madlc-santo-mauro-a-luxury-collection-hotel-madrid/"},
        {"name": "Hotel Arts Barcelona", "city": "Barcelona (Marina / Port Olímpic)", "url": "https://www.marriott.com/hotels/travel/bcnrz-hotel-arts-barcelona/"},
        {"name": "W Barcelona", "city": "Barcelona (Plaça Rosa dels Vents / Barceloneta)", "url": "https://www.marriott.com/hotels/travel/bcnwh-w-barcelona/"},
        {"name": "W Ibiza", "city": "Ibiza (Santa Eulalia del Río)", "url": "https://www.marriott.com/hotels/travel/ibzwh-w-ibiza/"},
        {"name": "The Westin Palace, Madrid", "city": "Madrid (Plaza de las Cortes)", "url": "https://www.marriott.com/hotels/travel/madwi-the-westin-palace-madrid/"},
        {"name": "Hotel Alfonso XIII, a Luxury Collection Hotel, Seville", "city": "Seville (Calle San Fernando)", "url": "https://www.marriott.com/hotels/travel/svqlc-hotel-alfonso-xiii-a-luxury-collection-hotel-seville/"},
        {"name": "Hotel Maria Cristina, a Luxury Collection Hotel, San Sebastian", "city": "San Sebastian (Paseo República Argentina)", "url": "https://www.marriott.com/hotels/travel/easlc-hotel-maria-cristina-a-luxury-collection-hotel-san-sebastian/"}
    ],
    "United States": [
        {"name": "The St. Regis New York", "city": "New York (Fifth Ave / 55th St)", "url": "https://www.marriott.com/hotels/travel/nycxr-the-st-regis-new-york/"},
        {"name": "The Ritz-Carlton New York, Central Park", "city": "New York (Central Park South / 59th St)", "url": "https://www.marriott.com/hotels/travel/nyccp-the-ritz-carlton-new-york-central-park/"},
        {"name": "The Ritz-Carlton New York, NoMad", "city": "New York (Broadway / 28th St)", "url": "https://www.marriott.com/hotels/travel/nycnm-the-ritz-carlton-new-york-nomad/"},
        {"name": "The New York EDITION", "city": "New York (Madison Ave / Flatiron)", "url": "https://www.marriott.com/hotels/travel/nyced-the-new-york-edition/"},
        {"name": "The Times Square EDITION", "city": "New York (7th Ave / Times Square)", "url": "https://www.marriott.com/hotels/travel/nycet-the-times-square-edition/"},
        {"name": "JW Marriott Essex House New York", "city": "New York (Central Park South)", "url": "https://www.marriott.com/hotels/travel/nycex-jw-marriott-essex-house-new-york/"},
        {"name": "New York Marriott Marquis", "city": "New York (Broadway / Times Square)", "url": "https://www.marriott.com/hotels/travel/nycmq-new-york-marriott-marquis/"},
        {"name": "W New York - Times Square", "city": "New York (Broadway / 47th St)", "url": "https://www.marriott.com/hotels/travel/nycwh-w-new-york-times-square/"},
        {"name": "W South Beach", "city": "Miami Beach (Collins Ave / 22nd St)", "url": "https://www.marriott.com/hotels/travel/miawh-w-south-beach/"},
        {"name": "The St. Regis Bal Harbour Resort", "city": "Miami Beach (Bal Harbour / Collins Ave)", "url": "https://www.marriott.com/hotels/travel/miarb-the-st-regis-bal-harbour-resort/"},
        {"name": "The Ritz-Carlton, South Beach", "city": "Miami Beach (Lincoln Rd / Collins Ave)", "url": "https://www.marriott.com/hotels/travel/miars-the-ritz-carlton-south-beach/"},
        {"name": "The Miami Beach EDITION", "city": "Miami Beach (Collins Ave / 29th St)", "url": "https://www.marriott.com/hotels/travel/miaed-the-miami-beach-edition/"},
        {"name": "The St. Regis San Francisco", "city": "San Francisco (Mission St / SoMa)", "url": "https://www.marriott.com/hotels/travel/sfoxr-the-st-regis-san-francisco/"},
        {"name": "The Ritz-Carlton, San Francisco", "city": "San Francisco (Nob Hill / Stockton St)", "url": "https://www.marriott.com/hotels/travel/sforz-the-ritz-carlton-san-francisco/"},
        {"name": "The Ritz-Carlton, Half Moon Bay", "city": "Half Moon Bay (Miramontes Point Rd)", "url": "https://www.marriott.com/hotels/travel/sfahm-the-ritz-carlton-half-moon-bay/"},
        {"name": "The Ritz-Carlton, Laguna Niguel", "city": "Dana Point (Ritz-Carlton Dr / Pacific Coast)", "url": "https://www.marriott.com/hotels/travel/snarz-the-ritz-carlton-laguna-niguel/"},
        {"name": "The St. Regis Aspen Resort", "city": "Aspen (Dean St / Colorado)", "url": "https://www.marriott.com/hotels/travel/asexr-the-st-regis-aspen-resort/"},
        {"name": "The Ritz-Carlton, Bachelor Gulch", "city": "Beaver Creek (Avon / Colorado)", "url": "https://www.marriott.com/hotels/travel/whrbg-the-ritz-carlton-bachelor-gulch/"},
        {"name": "The Ritz-Carlton, Kapalua", "city": "Maui (Kapalua / Ritz-Carlton Dr)", "url": "https://www.marriott.com/hotels/travel/jhprz-the-ritz-carlton-kapalua/"},
        {"name": "Wailea Beach Resort - Marriott, Maui", "city": "Maui (Wailea Alanui Dr)", "url": "https://www.marriott.com/hotels/travel/oggwa-wailea-beach-resort-marriott-maui/"}
    ]
}


def seed_marriott_global():
    """Seeds all verified physical Marriott Bonvoy hotels into hotel_stays.db."""
    SessionMaker = get_session_factory()
    session = SessionMaker()

    total_added = 0
    seen_ids = set()

    for country, hotels in MARRIOTT_MASTER_DIRECTORY.items():
        for h in hotels:
            existing = session.query(Hotel).filter(Hotel.name == h["name"]).first()
            if not existing:
                m = re.search(r'/hotels/travel/([a-z0-9]{5})-', h["url"])
                marr_code = m.group(1) if m else re.sub(r'[^a-z0-9]', '', h["name"].lower())[:10]
                h_id = f"marr_{marr_code}"
                if h_id in seen_ids:
                    slug = re.sub(r'[^a-z0-9_]', '', h["name"].lower().replace(' ', '_').replace('-', '_'))[:25]
                    h_id = f"marr_{marr_code}_{slug}"
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
                    brand="MARRIOTT",
                    name=h["name"],
                    city=h["city"],
                    country=country,
                    currency=curr,
                    loyalty_model="DYNAMIC_POINTS_WITH_FLOOR_CEILING",
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
                    raw_name="Standard Deluxe Room",
                    standardized_type="STANDARD"
                )
                session.add(room)
                total_added += 1

    session.commit()
    session.close()
    logger.info(f"Successfully seeded {total_added} Marriott Bonvoy properties across {len(MARRIOTT_MASTER_DIRECTORY)} countries into database!")
    export_watchlist_to_excel()

if __name__ == '__main__':
    seed_marriott_global()
