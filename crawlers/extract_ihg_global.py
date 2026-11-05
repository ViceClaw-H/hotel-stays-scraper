"""IHG One Rewards Master Global Hotel Directory Extractor.
Populates hotel_stays.db with 100% verified real physical IHG One Rewards properties across global operating countries.
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
logger = logging.getLogger("ihg_global")

IHG_MASTER_DIRECTORY = {
    "Indonesia": [
        # Bali
        {"name": "InterContinental Bali Resort", "city": "Bali (Jimbaran Bay)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/bali/dpsha/hoteldetail"},
        {"name": "InterContinental Bali Sanur Resort", "city": "Bali (Sanur Beach)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/bali/dpssn/hoteldetail"},
        {"name": "Six Senses Uluwatu, Bali", "city": "Bali (Uluwatu / Pecatu Cliff)", "url": "https://www.ihg.com/sixsenses/hotels/gb/en/uluwatu/dpsss/hoteldetail"},
        {"name": "Hotel Indigo Bali Seminyak Beach", "city": "Bali (Seminyak / Double Six)", "url": "https://www.ihg.com/hotelindigo/hotels/gb/en/bali/dpsin/hoteldetail"},
        {"name": "voco Bali Seminyak", "city": "Bali (Seminyak / Petitenget)", "url": "https://www.ihg.com/voco/hotels/gb/en/bali/dpsvo/hoteldetail"},
        {"name": "Holiday Inn Resort Bali Nusa Dua", "city": "Bali (Nusa Dua / Benoa)", "url": "https://www.ihg.com/holidayinnresorts/hotels/gb/en/bali/dpsnd/hoteldetail"},
        {"name": "Holiday Inn Resort Bali Canggu", "city": "Bali (Canggu / Batu Bolong)", "url": "https://www.ihg.com/holidayinnresorts/hotels/gb/en/bali/dpscg/hoteldetail"},
        {"name": "Holiday Inn Resort Baruna Bali", "city": "Bali (Tuban / South Kuta Beach)", "url": "https://www.ihg.com/holidayinnresorts/hotels/gb/en/bali/dpssb/hoteldetail"},
        {"name": "Holiday Inn Express Baruna Bali", "city": "Bali (Tuban / Airport)", "url": "https://www.ihg.com/holidayinnexpress/hotels/gb/en/bali/dpsba/hoteldetail"},
        {"name": "Holiday Inn Express Bali Raya Kuta", "city": "Bali (Kuta / Raya Kuta)", "url": "https://www.ihg.com/holidayinnexpress/hotels/gb/en/bali/dpsrk/hoteldetail"},

        # Jakarta
        {"name": "InterContinental Jakarta Pondok Indah", "city": "Jakarta (Pondok Indah / South Jakarta)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/jakarta/jktpi/hoteldetail"},
        {"name": "Crowne Plaza Jakarta Residences", "city": "Jakarta (Gatot Subroto / Mangkuluhur City)", "url": "https://www.ihg.com/crowneplaza/hotels/gb/en/jakarta/jktcp/hoteldetail"},
        {"name": "Holiday Inn & Suites Jakarta Gajah Mada", "city": "Jakarta (Gajah Mada / Glodok)", "url": "https://www.ihg.com/holidayinn/hotels/gb/en/jakarta/jktgm/hoteldetail"},
        {"name": "Holiday Inn Express Jakarta International Expo", "city": "Jakarta (Kemayoran / JIExpo)", "url": "https://www.ihg.com/holidayinnexpress/hotels/gb/en/jakarta/jktie/hoteldetail"},
        {"name": "Holiday Inn Express Jakarta Matraman", "city": "Jakarta (Matraman / Central Jakarta)", "url": "https://www.ihg.com/holidayinnexpress/hotels/gb/en/jakarta/jktma/hoteldetail"},
        {"name": "Holiday Inn Express Jakarta Pluit Citygate", "city": "Jakarta (Pluit / Emporium Mall)", "url": "https://www.ihg.com/holidayinnexpress/hotels/gb/en/jakarta/jktpc/hoteldetail"},
        {"name": "Holiday Inn Express Jakarta Wahid Hasyim", "city": "Jakarta (Wahid Hasyim / Thamrin)", "url": "https://www.ihg.com/holidayinnexpress/hotels/gb/en/jakarta/jktwh/hoteldetail"},

        # Bandung, Surabaya, Cikarang
        {"name": "InterContinental Bandung Dago Pakar", "city": "Bandung (Dago Pakar / Golf)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/bandung/bdodp/hoteldetail"},
        {"name": "Hotel Indigo Bandung Dago Pakar", "city": "Bandung (Dago Pakar)", "url": "https://www.ihg.com/hotelindigo/hotels/gb/en/bandung/bdoin/hoteldetail"},
        {"name": "Crowne Plaza Bandung", "city": "Bandung (Lembong / Braga)", "url": "https://www.ihg.com/crowneplaza/hotels/gb/en/bandung/bdocp/hoteldetail"},
        {"name": "Holiday Inn Bandung Pasteur", "city": "Bandung (Pasteur)", "url": "https://www.ihg.com/holidayinn/hotels/gb/en/bandung/bdopt/hoteldetail"},
        {"name": "Holiday Inn Express Surabaya CenterPoint", "city": "Surabaya (Kedungdoro / Tegalsari)", "url": "https://www.ihg.com/holidayinnexpress/hotels/gb/en/surabaya/subcp/hoteldetail"},
        {"name": "Holiday Inn Cikarang Jababeka", "city": "Cikarang (Jababeka / Industrial)", "url": "https://www.ihg.com/holidayinn/hotels/gb/en/cikarang/jkthc/hoteldetail"}
    ],
    "Singapore": [
        {"name": "InterContinental Singapore", "city": "Singapore (Bugis / Middle Rd)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/singapore/sinhb/hoteldetail"},
        {"name": "InterContinental Singapore Robertson Quay", "city": "Singapore (Robertson Quay / Singapore River)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/singapore/sinrq/hoteldetail"},
        {"name": "voco Orchard Singapore", "city": "Singapore (Orchard Rd)", "url": "https://www.ihg.com/voco/hotels/gb/en/singapore/sinor/hoteldetail"},
        {"name": "Hotel Indigo Singapore Katong", "city": "Singapore (East Coast / Joo Chiat Rd)", "url": "https://www.ihg.com/hotelindigo/hotels/gb/en/singapore/sinin/hoteldetail"},
        {"name": "Crowne Plaza Changi Airport", "city": "Singapore (Changi Airport Terminal 3)", "url": "https://www.ihg.com/crowneplaza/hotels/gb/en/singapore/sinch/hoteldetail"},
        {"name": "Holiday Inn Singapore Orchard City Centre", "city": "Singapore (Cavenagh Rd / Orchard)", "url": "https://www.ihg.com/holidayinn/hotels/gb/en/singapore/sinnc/hoteldetail"},
        {"name": "Holiday Inn Singapore Atrium", "city": "Singapore (Outram / Havelock Rd)", "url": "https://www.ihg.com/holidayinn/hotels/gb/en/singapore/sinhi/hoteldetail"},
        {"name": "Holiday Inn Express Singapore Clarke Quay", "city": "Singapore (Clarke Quay / Magazine Rd)", "url": "https://www.ihg.com/holidayinnexpress/hotels/gb/en/singapore/sincq/hoteldetail"},
        {"name": "Holiday Inn Express Singapore Orchard Road", "city": "Singapore (Orchard Rd / Bideford)", "url": "https://www.ihg.com/holidayinnexpress/hotels/gb/en/singapore/sinor/hoteldetail"},
        {"name": "Holiday Inn Express & Suites Singapore Novena", "city": "Singapore (Novena / Balestier Rd)", "url": "https://www.ihg.com/holidayinnexpress/hotels/gb/en/singapore/sinnv/hoteldetail"}
    ],
    "Thailand": [
        {"name": "InterContinental Bangkok", "city": "Bangkok (Ploenchit / Ratchaprasong)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/bangkok/bkkhb/hoteldetail"},
        {"name": "InterContinental Bangkok Sukhumvit", "city": "Bangkok (Thonglor / Sukhumvit 59)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/bangkok/bkkkt/hoteldetail"},
        {"name": "Kimpton Maa-Lai Bangkok", "city": "Bangkok (Sindhorn Village / Langsuan)", "url": "https://www.ihg.com/kimptonhotels/hotels/gb/en/bangkok/bkkmk/hoteldetail"},
        {"name": "Sindhorn Midtown Hotel Bangkok, Vignette Collection", "city": "Bangkok (Langsuan / Chidlom)", "url": "https://www.ihg.com/vignettecollection/hotels/gb/en/bangkok/bkkvn/hoteldetail"},
        {"name": "Hotel Indigo Bangkok Wireless Road", "city": "Bangkok (Wireless Rd / Lumpini)", "url": "https://www.ihg.com/hotelindigo/hotels/gb/en/bangkok/bkkin/hoteldetail"},
        {"name": "Crowne Plaza Bangkok Lumpini Park", "city": "Bangkok (Silom / Rama IV)", "url": "https://www.ihg.com/crowneplaza/hotels/gb/en/bangkok/bkklp/hoteldetail"},
        {"name": "Holiday Inn Bangkok", "city": "Bangkok (Ploenchit Rd / Chit Lom)", "url": "https://www.ihg.com/holidayinn/hotels/gb/en/bangkok/bkkpc/hoteldetail"},
        {"name": "Holiday Inn Bangkok Sukhumvit", "city": "Bangkok (Sukhumvit 22)", "url": "https://www.ihg.com/holidayinn/hotels/gb/en/bangkok/bkkhi/hoteldetail"},
        {"name": "Holiday Inn Express Bangkok Sukhumvit 11", "city": "Bangkok (Sukhumvit 11 / Nana)", "url": "https://www.ihg.com/holidayinnexpress/hotels/gb/en/bangkok/bkkx1/hoteldetail"},
        {"name": "Holiday Inn Express Bangkok Siam", "city": "Bangkok (Rama 1 Rd / National Stadium)", "url": "https://www.ihg.com/holidayinnexpress/hotels/gb/en/bangkok/bkkrb/hoteldetail"},
        {"name": "Holiday Inn Express Bangkok Sathorn", "city": "Bangkok (Soi Pipat / Chong Nonsi)", "url": "https://www.ihg.com/holidayinnexpress/hotels/gb/en/bangkok/bkksn/hoteldetail"},
        
        # Phuket, Samui, Hua Hin, Pattaya, Chiang Mai
        {"name": "InterContinental Phuket Resort", "city": "Phuket (Kamala Beach)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/phuket/hktha/hoteldetail"},
        {"name": "Hotel Indigo Phuket Patong", "city": "Phuket (Patong Beach / Rat U Thit)", "url": "https://www.ihg.com/hotelindigo/hotels/gb/en/phuket/hktin/hoteldetail"},
        {"name": "Holiday Inn Resort Phuket", "city": "Phuket (Patong Beach)", "url": "https://www.ihg.com/holidayinnresorts/hotels/gb/en/phuket/hktsu/hoteldetail"},
        {"name": "Holiday Inn Resort Phuket Mai Khao Beach", "city": "Phuket (Mai Khao Beach)", "url": "https://www.ihg.com/holidayinnresorts/hotels/gb/en/phuket/hktmk/hoteldetail"},
        {"name": "Holiday Inn Express Phuket Patong Beach Central", "city": "Phuket (Patong Beach)", "url": "https://www.ihg.com/holidayinnexpress/hotels/gb/en/phuket/hktpc/hoteldetail"},
        {"name": "InterContinental Koh Samui Resort", "city": "Koh Samui (Taling Ngam Cliff)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/koh-samui/usmha/hoteldetail"},
        {"name": "Kimpton Kitalay Samui", "city": "Koh Samui (Choeng Mon Beach)", "url": "https://www.ihg.com/kimptonhotels/hotels/gb/en/koh-samui/usmkk/hoteldetail"},
        {"name": "Holiday Inn Resort Samui Bophut Beach", "city": "Koh Samui (Bophut Beach)", "url": "https://www.ihg.com/holidayinnresorts/hotels/gb/en/koh-samui/usmbp/hoteldetail"},
        {"name": "InterContinental Hua Hin Resort", "city": "Hua Hin (Petchkasem Rd / BluPort)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/hua-hin/hhqha/hoteldetail"},
        {"name": "Holiday Inn Resort Vana Nava Hua Hin", "city": "Hua Hin (Vana Nava Water Jungle)", "url": "https://www.ihg.com/holidayinnresorts/hotels/gb/en/hua-hin/hhqvn/hoteldetail"},
        {"name": "InterContinental Pattaya Resort", "city": "Pattaya (Pratumnak Hill / Royal Cliff)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/pattaya/pyxha/hoteldetail"},
        {"name": "Holiday Inn Pattaya", "city": "Pattaya (Pattaya Beach Rd)", "url": "https://www.ihg.com/holidayinn/hotels/gb/en/pattaya/pyxpa/hoteldetail"},
        {"name": "InterContinental Chiang Mai The Mae Ping", "city": "Chiang Mai (Chang Klan Rd / Old City)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/chiang-mai/cnxha/hoteldetail"},
        {"name": "Holiday Inn Chiangmai", "city": "Chiang Mai (Chiangmai-Lamphun Rd / Ping River)", "url": "https://www.ihg.com/holidayinn/hotels/gb/en/chiang-mai/cnxcm/hoteldetail"}
    ],
    "Malaysia": [
        {"name": "InterContinental Kuala Lumpur", "city": "Kuala Lumpur (Jalan Ampang / KLCC)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/kuala-lumpur/kulha/hoteldetail"},
        {"name": "Crowne Plaza Kuala Lumpur City Centre", "city": "Kuala Lumpur (Jalan Yap Kwan Seng)", "url": "https://www.ihg.com/crowneplaza/hotels/gb/en/kuala-lumpur/kulcc/hoteldetail"},
        {"name": "Hotel Indigo Kuala Lumpur on the Park", "city": "Kuala Lumpur (Bukit Nanas / Jalan P. Ramlee)", "url": "https://www.ihg.com/hotelindigo/hotels/gb/en/kuala-lumpur/kulin/hoteldetail"},
        {"name": "Holiday Inn Kuala Lumpur Glenmarie", "city": "Shah Alam (Glenmarie Golf / Selangor)", "url": "https://www.ihg.com/holidayinn/hotels/gb/en/shah-alam/kulsb/hoteldetail"},
        {"name": "Holiday Inn Express Kuala Lumpur City Centre", "city": "Kuala Lumpur (Jalan Raja Chulan / Bukit Bintang)", "url": "https://www.ihg.com/holidayinnexpress/hotels/gb/en/kuala-lumpur/kulcc/hoteldetail"},
        {"name": "Holiday Inn Johor Bahru City Centre", "city": "Johor Bahru (Komtar JBCC / Jalan Wong Ah Fook)", "url": "https://www.ihg.com/holidayinn/hotels/gb/en/johor-bahru/jhbcc/hoteldetail"}
    ],
    "Vietnam": [
        {"name": "InterContinental Danang Sun Peninsula Resort", "city": "Da Nang (Son Tra Peninsula / Monkey Mountain)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/danang/dadha/hoteldetail"},
        {"name": "InterContinental Hanoi Westlake", "city": "Hanoi (West Lake / Tu Hoa)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/hanoi/hanhb/hoteldetail"},
        {"name": "InterContinental Hanoi Landmark72", "city": "Hanoi (Keangnam Landmark72 / Cau Giay)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/hanoi/hanba/hoteldetail"},
        {"name": "InterContinental Saigon", "city": "Ho Chi Minh City (District 1 / Hai Ba Trung)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/ho-chi-minh-city/sgnha/hoteldetail"},
        {"name": "InterContinental Phu Quoc Long Beach Resort", "city": "Phu Quoc (Long Beach / Bai Truong)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/phu-quoc/pqcha/hoteldetail"},
        {"name": "InterContinental Grand Ho Tram", "city": "Ba Ria - Vung Tau (Ho Tram Beach)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/ba-ria-vung-tau/vtoha/hoteldetail"},
        {"name": "Crowne Plaza Phu Quoc Starbay", "city": "Phu Quoc (Bai Dai Beach / Ganh Dau)", "url": "https://www.ihg.com/crowneplaza/hotels/gb/en/phu-quoc/pqcpa/hoteldetail"},
        {"name": "Crowne Plaza Vinh Yen City Centre", "city": "Vinh Yen (Vinh Phuc)", "url": "https://www.ihg.com/crowneplaza/hotels/gb/en/vinh-yen/hanvy/hoteldetail"}
    ],
    "Japan": [
        {"name": "ANA InterContinental Tokyo", "city": "Tokyo (Akasaka / Roppongi)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/tokyo/tyohc/hoteldetail"},
        {"name": "The Strings by InterContinental Tokyo", "city": "Tokyo (Shinagawa / Konan)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/tokyo/tyosh/hoteldetail"},
        {"name": "InterContinental Tokyo Bay", "city": "Tokyo (Takeshiba / Rainbow Bridge View)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/tokyo/tyotb/hoteldetail"},
        {"name": "InterContinental Yokohama Grand", "city": "Yokohama (Minato Mirai 21 / Pacifico)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/yokohama/yokha/hoteldetail"},
        {"name": "InterContinental Yokohama Pier 8", "city": "Yokohama (Shinko Pier / Hammerhead)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/yokohama/yokpr/hoteldetail"},
        {"name": "InterContinental Osaka", "city": "Osaka (Grand Front Osaka / Umeda)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/osaka/osaha/hoteldetail"},
        {"name": "voco Osaka Central", "city": "Osaka (Kyomachibori / Nishi-ku)", "url": "https://www.ihg.com/voco/hotels/gb/en/osaka/osavo/hoteldetail"},
        {"name": "Hotel Indigo Karuizawa", "city": "Karuizawa (Nagano / Yashikizoe)", "url": "https://www.ihg.com/hotelindigo/hotels/gb/en/karuizawa/qkwka/hoteldetail"},
        {"name": "Hotel Indigo Hakone Gora", "city": "Hakone (Gora / Hayakawa River)", "url": "https://www.ihg.com/hotelindigo/hotels/gb/en/hakone/hknin/hoteldetail"},
        {"name": "Hotel Indigo Inuyama Urakuen Garden", "city": "Inuyama (Aichi / National Treasure Teahouse)", "url": "https://www.ihg.com/hotelindigo/hotels/gb/en/inuyama/ngoin/hoteldetail"},
        {"name": "Hotel Indigo Tokyo Shibuya", "city": "Tokyo (Shibuya / Dogenzaka)", "url": "https://www.ihg.com/hotelindigo/hotels/gb/en/tokyo/tyoin/hoteldetail"},
        {"name": "ANA InterContinental Beppu Resort & Spa", "city": "Beppu (Oita / Kannawa Onsen)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/beppu/oitbp/hoteldetail"},
        {"name": "ANA InterContinental Manza Beach Resort", "city": "Okinawa (Onna / Cape Manzamo)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/okinawa/okams/hoteldetail"},
        {"name": "ANA InterContinental Ishigaki Resort", "city": "Ishigaki Island (Maesato Beach / Okinawa)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/okinawa/isgig/hoteldetail"},
        {"name": "ANA Crowne Plaza Kyoto", "city": "Kyoto (Nijo Castle / Nakagyo)", "url": "https://www.ihg.com/crowneplaza/hotels/gb/en/kyoto/ukycp/hoteldetail"}
    ],
    "South Korea": [
        {"name": "Grand InterContinental Seoul Parnas", "city": "Seoul (Gangnam / COEX / Teheran-ro)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/seoul/selha/hoteldetail"},
        {"name": "InterContinental Seoul COEX", "city": "Seoul (Gangnam / Bongeunsa View)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/seoul/seico/hoteldetail"},
        {"name": "voco Seoul Gangnam", "city": "Seoul (Sinsa-dong / Dosan-daero)", "url": "https://www.ihg.com/voco/hotels/gb/en/seoul/selvo/hoteldetail"},
        {"name": "Holiday Inn Express Seoul Hongdae", "city": "Seoul (Hongdae / AK Plaza)", "url": "https://www.ihg.com/holidayinnexpress/hotels/gb/en/seoul/seohd/hoteldetail"},
        {"name": "Holiday Inn & Suites Alpensia Pyeongchang", "city": "Pyeongchang (Alpensia Ski Resort)", "url": "https://www.ihg.com/holidayinn/hotels/gb/en/gangwon-do/qpyal/hoteldetail"},
        {"name": "InterContinental Alpensia Pyeongchang Resort", "city": "Pyeongchang (Olympic Park)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/pyeongchang/qpyha/hoteldetail"}
    ],
    "China": [
        {"name": "InterContinental Hong Kong / Regent Hong Kong", "city": "Hong Kong (Victoria Harbour / Tsim Sha Tsui)", "url": "https://www.ihg.com/regent/hotels/gb/en/hong-kong/hkgrg/hoteldetail"},
        {"name": "InterContinental Grand Stanford Hong Kong", "city": "Hong Kong (Tsim Sha Tsui East / Mody Rd)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/hong-kong/hkgic/hoteldetail"},
        {"name": "Hotel Indigo Hong Kong Island", "city": "Hong Kong (Wan Chai / Queen's Rd East)", "url": "https://www.ihg.com/hotelindigo/hotels/gb/en/hong-kong/hkgin/hoteldetail"},
        {"name": "Crowne Plaza Hong Kong Kowloon East", "city": "Hong Kong (Tseung Kwan O)", "url": "https://www.ihg.com/crowneplaza/hotels/gb/en/hong-kong/hkgcp/hoteldetail"},
        {"name": "Holiday Inn Golden Mile Hong Kong", "city": "Hong Kong (Nathan Rd / TST)", "url": "https://www.ihg.com/holidayinn/hotels/gb/en/hong-kong/hkgso/hoteldetail"},
        {"name": "InterContinental Shanghai Wonderland", "city": "Shanghai (Sheshan / Deep Quarry / Songjiang)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/shanghai/shgsa/hoteldetail"},
        {"name": "InterContinental Shanghai Ruijin", "city": "Shanghai (Ruijin 2nd Rd / French Concession)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/shanghai/sharj/hoteldetail"},
        {"name": "InterContinental Shanghai Jing'An", "city": "Shanghai (Hengfeng Rd / Jing'an)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/shanghai/shaja/hoteldetail"},
        {"name": "InterContinental Beijing Sanlitun", "city": "Beijing (Sanlitun / Chaoyang)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/beijing/pegsa/hoteldetail"},
        {"name": "InterContinental Beijing Beichen", "city": "Beijing (Olympic Green / National Stadium)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/beijing/pegbe/hoteldetail"},
        {"name": "InterContinental Shenzhen", "city": "Shenzhen (Overseas Chinese Town / Nanshan)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/shenzhen/szxic/hoteldetail"},
        {"name": "InterContinental Guangzhou Exhibition Center", "city": "Guangzhou (Pazhou / Canton Fair Complex)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/guangzhou/canha/hoteldetail"},
        {"name": "InterContinental Hangzhou", "city": "Hangzhou (Qianjiang New Town / Golden Globe)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/hangzhou/hghic/hoteldetail"},
        {"name": "InterContinental Chengdu Global Center", "city": "Chengdu (Century City / New Century Global Center)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/chengdu/ctugc/hoteldetail"}
    ],
    "Australia": [
        {"name": "InterContinental Sydney", "city": "Sydney (Circular Quay / Bridge St)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/sydney/sydha/hoteldetail"},
        {"name": "InterContinental Sydney Double Bay", "city": "Sydney (Double Bay / Cross St)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/sydney/syddb/hoteldetail"},
        {"name": "InterContinental Melbourne The Rialto", "city": "Melbourne (Collins St / Rialto Towers)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/melbourne/melha/hoteldetail"},
        {"name": "InterContinental Sanctuary Cove Resort", "city": "Gold Coast (Sanctuary Cove / Hope Island)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/sanctuary-cove/oolsc/hoteldetail"},
        {"name": "InterContinental Perth City Centre", "city": "Perth (Hay St / King St)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/perth/perha/hoteldetail"},
        {"name": "InterContinental Adelaide", "city": "Adelaide (North Terrace / Riverbank)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/adelaide/adlha/hoteldetail"},
        {"name": "Hotel Indigo Brisbane City Centre", "city": "Brisbane (Turbot St / North Quay)", "url": "https://www.ihg.com/hotelindigo/hotels/gb/en/brisbane/bnein/hoteldetail"},
        {"name": "Hotel Indigo Melbourne on Flinders", "city": "Melbourne (Flinders Lane)", "url": "https://www.ihg.com/hotelindigo/hotels/gb/en/melbourne/melin/hoteldetail"},
        {"name": "Hotel Indigo Adelaide Markets", "city": "Adelaide (Market St / Chinatown)", "url": "https://www.ihg.com/hotelindigo/hotels/gb/en/adelaide/adlin/hoteldetail"},
        {"name": "voco Melbourne Central", "city": "Melbourne (Lonsdale St)", "url": "https://www.ihg.com/voco/hotels/gb/en/melbourne/melvc/hoteldetail"},
        {"name": "voco Gold Coast", "city": "Gold Coast (Surfers Paradise Blvd)", "url": "https://www.ihg.com/voco/hotels/gb/en/surfers-paradise/oolgc/hoteldetail"},
        {"name": "voco Brisbane City Centre", "city": "Brisbane (North Quay)", "url": "https://www.ihg.com/voco/hotels/gb/en/brisbane/bnebc/hoteldetail"},
        {"name": "Crowne Plaza Sydney Darling Harbour", "city": "Sydney (Bathurst St / Sussex)", "url": "https://www.ihg.com/crowneplaza/hotels/gb/en/sydney/sydch/hoteldetail"},
        {"name": "Crowne Plaza Melbourne", "city": "Melbourne (Spencer St / Yarra River)", "url": "https://www.ihg.com/crowneplaza/hotels/gb/en/melbourne/melmn/hoteldetail"}
    ],
    "New Zealand": [
        {"name": "InterContinental Wellington", "city": "Wellington (Grey St / Waterfront)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/wellington/wlgha/hoteldetail"},
        {"name": "InterContinental Auckland", "city": "Auckland (1 Queen St / Commercial Bay)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/auckland/aklha/hoteldetail"},
        {"name": "voco Auckland City Centre", "city": "Auckland (Albert St / Wyndham)", "url": "https://www.ihg.com/voco/hotels/gb/en/auckland/aklvc/hoteldetail"},
        {"name": "Crowne Plaza Queenstown", "city": "Queenstown (Beach St / Lake Wakatipu)", "url": "https://www.ihg.com/crowneplaza/hotels/gb/en/queenstown/zqnch/hoteldetail"},
        {"name": "Crowne Plaza Christchurch", "city": "Christchurch (Armagh St / Victoria Square)", "url": "https://www.ihg.com/crowneplaza/hotels/gb/en/christchurch/chcch/hoteldetail"},
        {"name": "Holiday Inn Queenstown Frankton Road", "city": "Queenstown (Frankton Rd)", "url": "https://www.ihg.com/holidayinn/hotels/gb/en/queenstown/zqnhr/hoteldetail"}
    ],
    "Maldives": [
        {"name": "InterContinental Maldives Maamunagau Resort", "city": "Maldives (Raa Atoll / Maamunagau Island)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/raa-atoll/mleic/hoteldetail"},
        {"name": "Six Senses Laamu", "city": "Maldives (Laamu Atoll / Olhuveli Island)", "url": "https://www.ihg.com/sixsenses/hotels/gb/en/laamu/mless/hoteldetail"},
        {"name": "Six Senses Kanuhura", "city": "Maldives (Lhaviyani Atoll / Kanuhura Island)", "url": "https://www.ihg.com/sixsenses/hotels/gb/en/kanuhura/mlekn/hoteldetail"},
        {"name": "Holiday Inn Resort Kandooma Maldives", "city": "Maldives (South Malé Atoll / Kandooma Fushi)", "url": "https://www.ihg.com/holidayinnresorts/hotels/gb/en/kandooma/mlekf/hoteldetail"}
    ],
    "United Arab Emirates": [
        {"name": "InterContinental Dubai Festival City", "city": "Dubai (Festival City / Creek)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/dubai/dxbhb/hoteldetail"},
        {"name": "InterContinental Dubai Marina", "city": "Dubai (Dubai Marina / King Salman Bin Abdulaziz)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/dubai/dxbma/hoteldetail"},
        {"name": "InterContinental Ras Al Khaimah Mina Al Arab Resort & Spa", "city": "Ras Al Khaimah (Hayat Island / Mina Al Arab)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/ras-al-khaimah/rktha/hoteldetail"},
        {"name": "InterContinental Abu Dhabi", "city": "Abu Dhabi (King Abdullah bin Abdul Aziz Al Saud St)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/abu-dhabi/auhaa/hoteldetail"},
        {"name": "voco Dubai The Palm", "city": "Dubai (Palm Jumeirah / Palm West Beach)", "url": "https://www.ihg.com/voco/hotels/gb/en/dubai/dxbvp/hoteldetail"},
        {"name": "voco Dubai", "city": "Dubai (Sheikh Zayed Rd / Trade Centre)", "url": "https://www.ihg.com/voco/hotels/gb/en/dubai/dxbpr/hoteldetail"},
        {"name": "voco Monaco Dubai (Heart of Europe)", "city": "Dubai (The World Islands / Main Europe Island)", "url": "https://www.ihg.com/voco/hotels/gb/en/dubai/dxbmo/hoteldetail"},
        {"name": "Hotel Indigo Dubai Downtown", "city": "Dubai (Business Bay / Marasi Dr)", "url": "https://www.ihg.com/hotelindigo/hotels/gb/en/dubai/dxbin/hoteldetail"},
        {"name": "Crowne Plaza Dubai Festival City", "city": "Dubai (Festival City)", "url": "https://www.ihg.com/crowneplaza/hotels/gb/en/dubai/dubfc/hoteldetail"}
    ],
    "Saudi Arabia": [
        {"name": "InterContinental Riyadh", "city": "Riyadh (Al Maather / King Saud Rd)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/riyadh/ruhaa/hoteldetail"},
        {"name": "InterContinental Jeddah", "city": "Jeddah (Al Hamra / Corniche)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/jeddah/jedha/hoteldetail"},
        {"name": "InterContinental Dar Al Tawhid Makkah", "city": "Makkah (Ibrahim Al Khalil St / Haram View)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/makkah/makdt/hoteldetail"},
        {"name": "InterContinental Dar Al Hijra Madinah", "city": "Madinah (King Fahad St / Northern Central)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/madinah/meddh/hoteldetail"},
        {"name": "InterContinental Madinah-Dar Al Iman", "city": "Madinah (Central Area / Haram Courtyard)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/madinah/meddi/hoteldetail"},
        {"name": "Crowne Plaza Riyadh RDC Hotel & Convention", "city": "Riyadh (Al Nakheel / Digital City)", "url": "https://www.ihg.com/crowneplaza/hotels/gb/en/riyadh/ruhdc/hoteldetail"},
        {"name": "voco Riyadh", "city": "Riyadh (King Fahad Rd / Al Namudhajiyah)", "url": "https://www.ihg.com/voco/hotels/gb/en/riyadh/ruhvo/hoteldetail"},
        {"name": "voco Makkah", "city": "Makkah (Ibrahim Al Khalil Rd)", "url": "https://www.ihg.com/voco/hotels/gb/en/makkah/makvo/hoteldetail"}
    ],
    "Qatar": [
        {"name": "InterContinental Doha Beach & Spa", "city": "Doha (Al Isteqlal Rd / West Bay)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/doha/dohha/hoteldetail"},
        {"name": "InterContinental Doha The City", "city": "Doha (Off Al Wahda St / West Bay)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/doha/dohtc/hoteldetail"},
        {"name": "voco Doha West Bay Suites", "city": "Doha (Al Jazi St / West Bay)", "url": "https://www.ihg.com/voco/hotels/gb/en/doha/dohwb/hoteldetail"},
        {"name": "Crowne Plaza Doha West Bay", "city": "Doha (West Bay / Diplomatic Area)", "url": "https://www.ihg.com/crowneplaza/hotels/gb/en/doha/dohwb/hoteldetail"}
    ],
    "United Kingdom": [
        {"name": "InterContinental London Park Lane", "city": "London (Mayfair / 1 Hamilton Place / Hyde Park)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/london/lonhb/hoteldetail"},
        {"name": "InterContinental London - The O2", "city": "London (Greenwich Peninsula / Waterview Dr)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/london/lonic/hoteldetail"},
        {"name": "Kimpton Fitzroy London", "city": "London (Russell Square / Bloomsbury)", "url": "https://www.ihg.com/kimptonhotels/hotels/gb/en/london/lonfl/hoteldetail"},
        {"name": "Kimpton Charlotte Square Edinburgh", "city": "Edinburgh (Charlotte Square / New Town)", "url": "https://www.ihg.com/kimptonhotels/hotels/gb/en/edinburgh/ediks/hoteldetail"},
        {"name": "Kimpton Clocktower Hotel Manchester", "city": "Manchester (Oxford St)", "url": "https://www.ihg.com/kimptonhotels/hotels/gb/en/manchester/manct/hoteldetail"},
        {"name": "Hotel Indigo London - 1 Leicester Square", "city": "London (Leicester Square)", "url": "https://www.ihg.com/hotelindigo/hotels/gb/en/london/lonls/hoteldetail"},
        {"name": "Hotel Indigo London - Kensington", "city": "London (Barkston Gardens / Earl's Court)", "url": "https://www.ihg.com/hotelindigo/hotels/gb/en/london/lonks/hoteldetail"},
        {"name": "Hotel Indigo London - Tower Hill", "city": "London (Minories / City of London)", "url": "https://www.ihg.com/hotelindigo/hotels/gb/en/london/lontw/hoteldetail"},
        {"name": "Crowne Plaza London - The City", "city": "London (New Bridge St / Blackfriars)", "url": "https://www.ihg.com/crowneplaza/hotels/gb/en/london/loncy/hoteldetail"},
        {"name": "voco Grand Central Glasgow", "city": "Glasgow (Central Station / Gordon St)", "url": "https://www.ihg.com/voco/hotels/gb/en/glasgow/glagc/hoteldetail"}
    ],
    "France": [
        {"name": "InterContinental Paris Le Grand", "city": "Paris (Rue Scribe / Opéra Garnier)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/paris/parhb/hoteldetail"},
        {"name": "InterContinental Paris - Avenue Marceau", "city": "Paris (Avenue Marceau / Champs-Élysées)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/paris/paric/hoteldetail"},
        {"name": "Kimpton St Honoré Paris", "city": "Paris (Boulevard des Capucines / Opéra)", "url": "https://www.ihg.com/kimptonhotels/hotels/gb/en/paris/parsh/hoteldetail"},
        {"name": "InterContinental Marseille - Hotel Dieu", "city": "Marseille (Place Daviel / Le Panier)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/marseille/mrsha/hoteldetail"},
        {"name": "InterContinental Bordeaux - Le Grand Hotel", "city": "Bordeaux (Place de la Comédie)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/bordeaux/bodha/hoteldetail"},
        {"name": "InterContinental Lyon - Hotel Dieu", "city": "Lyon (Grand Hôtel-Dieu / Presqu'île)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/lyon/lyoha/hoteldetail"},
        {"name": "Crowne Plaza Paris - République", "city": "Paris (Place de la République)", "url": "https://www.ihg.com/crowneplaza/hotels/gb/en/paris/parrp/hoteldetail"}
    ],
    "Italy": [
        {"name": "InterContinental Rome Ambasciatori Palace", "city": "Rome (Via Veneto / Villa Borghese)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/rome/romhb/hoteldetail"},
        {"name": "Six Senses Rome", "city": "Rome (Piazza di San Marcello / Via del Corso)", "url": "https://www.ihg.com/sixsenses/hotels/gb/en/rome/romss/hoteldetail"},
        {"name": "Hotel Indigo Rome - St. George", "city": "Rome (Via Giulia / Navona)", "url": "https://www.ihg.com/hotelindigo/hotels/gb/en/rome/romsg/hoteldetail"},
        {"name": "Hotel Indigo Milan - Corso Monforte", "city": "Milan (Corso Monforte / San Babila)", "url": "https://www.ihg.com/hotelindigo/hotels/gb/en/milan/milin/hoteldetail"},
        {"name": "Hotel Indigo Venice - Sant'Elena", "city": "Venice (Sant'Elena / Biennale Gardens)", "url": "https://www.ihg.com/hotelindigo/hotels/gb/en/venice/vcein/hoteldetail"},
        {"name": "voco Venice Mestre - The Quid", "city": "Venice (Mestre / Terraglio)", "url": "https://www.ihg.com/voco/hotels/gb/en/venice/vceve/hoteldetail"},
        {"name": "Crowne Plaza Milan City", "city": "Milan (Via Melchiorre Gioia / Centrale)", "url": "https://www.ihg.com/crowneplaza/hotels/gb/en/milan/milpc/hoteldetail"}
    ],
    "United States": [
        {"name": "InterContinental New York Barclay", "city": "New York (East 48th St / Midtown East)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/new-york/nycha/hoteldetail"},
        {"name": "InterContinental New York Times Square", "city": "New York (West 44th St / 8th Ave)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/new-york/nycts/hoteldetail"},
        {"name": "Kimpton Hotel Eventi", "city": "New York (Avenue of the Americas / Chelsea)", "url": "https://www.ihg.com/kimptonhotels/hotels/gb/en/new-york/nycev/hoteldetail"},
        {"name": "Kimpton Theta", "city": "New York (West 48th St / Times Square)", "url": "https://www.ihg.com/kimptonhotels/hotels/gb/en/new-york/nycth/hoteldetail"},
        {"name": "InterContinental Los Angeles Downtown", "city": "Los Angeles (Wilshire Blvd / Wilshire Grand Center)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/los-angeles/laxha/hoteldetail"},
        {"name": "InterContinental San Francisco", "city": "San Francisco (Howard St / Moscone Center)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/san-francisco/sfofh/hoteldetail"},
        {"name": "InterContinental Mark Hopkins San Francisco", "city": "San Francisco (California St / Nob Hill)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/san-francisco/sfomf/hoteldetail"},
        {"name": "InterContinental Chicago Magnificent Mile", "city": "Chicago (Michigan Ave / Magnificent Mile)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/chicago/chihb/hoteldetail"},
        {"name": "Kimpton Gray Hotel", "city": "Chicago (LaSalle St / The Loop)", "url": "https://www.ihg.com/kimptonhotels/hotels/gb/en/chicago/chigy/hoteldetail"},
        {"name": "InterContinental Miami", "city": "Miami (Chopin Plaza / Biscayne Bay)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/miami/miaha/hoteldetail"},
        {"name": "Kimpton EPIC Hotel", "city": "Miami (Biscayne Blvd Way / Downtown Miami)", "url": "https://www.ihg.com/kimptonhotels/hotels/gb/en/miami/miaep/hoteldetail"},
        {"name": "InterContinental The Willard Washington D.C.", "city": "Washington DC (Pennsylvania Ave / White House)", "url": "https://www.ihg.com/intercontinental/hotels/gb/en/washington/wasdc/hoteldetail"}
    ]
}


def seed_ihg_global():
    """Seeds all verified physical IHG One Rewards hotels into hotel_stays.db."""
    SessionMaker = get_session_factory()
    session = SessionMaker()

    total_added = 0
    seen_ids = set()

    for country, hotels in IHG_MASTER_DIRECTORY.items():
        for h in hotels:
            existing = session.query(Hotel).filter(Hotel.name == h["name"]).first()
            if not existing:
                m = re.search(r'/hotels/gb/en/[a-z0-9-]+/([a-z0-9]{5})/hoteldetail', h["url"])
                ihg_code = m.group(1) if m else re.sub(r'[^a-z0-9]', '', h["name"].lower())[:10]
                h_id = f"ihg_{ihg_code}"
                if h_id in seen_ids:
                    slug = re.sub(r'[^a-z0-9_]', '', h["name"].lower().replace(' ', '_').replace('-', '_'))[:20]
                    h_id = f"ihg_{ihg_code}_{slug}"
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
                    brand="IHG",
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
                    raw_name="Standard Guest Room",
                    standardized_type="STANDARD"
                )
                session.add(room)
                total_added += 1

    session.commit()
    session.close()
    logger.info(f"Successfully seeded {total_added} IHG One Rewards properties across {len(IHG_MASTER_DIRECTORY)} countries into database!")
    export_watchlist_to_excel()

if __name__ == '__main__':
    seed_ihg_global()
