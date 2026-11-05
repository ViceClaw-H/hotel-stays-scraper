"""Points Arbitrage & Point Valuation Wave Engine."""
from typing import List, Dict, Any, Optional
from datetime import date
import logging

from database.models import RateRecord, RoomCategory, Hotel, PropertyBaseline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("arbitrage_engine")

# Industry standard baseline benchmark valuations (Cents Per Point / CPP)
LOYALTY_BENCHMARKS = {
    "HYATT": {"name": "World of Hyatt", "baseline_cpp": 1.70, "fixed_chart": True},
    "MARRIOTT": {"name": "Marriott Bonvoy", "baseline_cpp": 0.84, "fixed_chart": False},
    "HILTON": {"name": "Hilton Honors", "baseline_cpp": 0.55, "fixed_chart": False},
    "IHG": {"name": "IHG One Rewards", "baseline_cpp": 0.58, "fixed_chart": False},
    "WYNDHAM": {"name": "Wyndham Rewards", "baseline_cpp": 0.90, "fixed_chart": True},
    "ACCOR": {"name": "ALL (Accor Live Limitless)", "baseline_cpp": 2.17, "fixed_chart": False, "rebate_fixed": True},
    "GHA": {"name": "GHA DISCOVERY", "baseline_cpp": 100.0, "fixed_chart": False, "rebate_fixed": True},  # 1 D$ = 1 USD
    "SHANGRI_LA": {"name": "Shangri-La Circle", "baseline_cpp": 6.67, "fixed_chart": False, "rebate_fixed": True},  # 15 pts = 1 USD
    "LANGHAM": {"name": "The Langham (1865/Brilliant)", "baseline_cpp": 1.00, "fixed_chart": False, "rebate_fixed": True},
}


def calculate_realized_cpp(cash_rate_with_tax: float, points_required: Optional[int], currency: Optional[str] = "USD") -> Optional[float]:
    """Calculate Realized Cents-Per-Point (CPP) redemption value: (Total Cash / Points) * 100.

    Only defined for USD cash: the benchmarks are USD cents and no FX table exists, so a native-currency
    amount (KRW, CNY, IDR...) divided by points would be meaningless. Returns None for any other currency."""
    if currency not in (None, "USD"):
        return None
    if not points_required or points_required <= 0 or not cash_rate_with_tax or cash_rate_with_tax <= 0:
        return None
    return round((cash_rate_with_tax / points_required) * 100.0, 2)


def generate_valuation_wave(rates: List[RateRecord], brand: str) -> List[Dict[str, Any]]:
    """Generate daily Point Valuation Wave timeseries with Arbitrage Flags."""
    benchmark = LOYALTY_BENCHMARKS.get(brand, {}).get("baseline_cpp", 1.0)
    wave = []

    for r in sorted(rates, key=lambda x: x.stay_date):
        cpp = calculate_realized_cpp(r.cash_rate, r.points_required, r.raw_currency)
        arbitrage_multiplier = round(cpp / benchmark, 2) if cpp and benchmark > 0 else None
        
        # High value arbitrage: Realized CPP is at least 30% higher than benchmark
        is_sweet_spot = (arbitrage_multiplier >= 1.30) if arbitrage_multiplier else False

        wave.append({
            "stay_date": r.stay_date.isoformat() if isinstance(r.stay_date, date) else str(r.stay_date),
            "cash_rate": round(r.cash_rate, 2) if r.cash_rate is not None else None,
            "points_required": r.points_required,
            "realized_cpp": cpp,
            "benchmark_cpp": benchmark,
            "arbitrage_multiplier": arbitrage_multiplier,
            "is_sweet_spot": is_sweet_spot,
            "award_available": r.award_available
        })

    return wave


def scan_top_arbitrage_opportunities(session, min_cpp: Optional[float] = None) -> List[Dict[str, Any]]:
    """Scan and rank all properties for the highest point valuation redemption opportunities."""
    opportunities = []
    
    # Query standard rooms with rates and baselines
    standard_rooms = session.query(RoomCategory).filter(RoomCategory.standardized_type == "STANDARD").all()

    for room in standard_rooms:
        hotel = room.hotel
        if not hotel:
            continue

        rates = session.query(RateRecord).filter(
            RateRecord.room_id == room.id,
            RateRecord.points_required.isnot(None),
            RateRecord.points_required > 0,
            RateRecord.award_available == True
        ).all()

        if not rates:
            continue

        benchmark = LOYALTY_BENCHMARKS.get(hotel.brand, {}).get("baseline_cpp", 1.0)

        for r in rates:
            cpp = calculate_realized_cpp(r.cash_rate, r.points_required, r.raw_currency)
            if not cpp:
                continue

            threshold = min_cpp if min_cpp is not None else (benchmark * 1.25)
            if cpp >= threshold:
                opportunities.append({
                    "hotel_id": hotel.id,
                    "hotel_name": hotel.name,
                    "brand": hotel.brand,
                    "city": hotel.city,
                    "country": hotel.country,
                    "currency": hotel.currency,
                    "stay_date": r.stay_date.isoformat() if isinstance(r.stay_date, date) else str(r.stay_date),
                    "cash_rate": round(r.cash_rate, 2) if r.cash_rate is not None else None,
                    "points_required": r.points_required,
                    "realized_cpp": cpp,
                    "benchmark_cpp": benchmark,
                    "arbitrage_ratio": round(cpp / benchmark, 2),
                    "official_url": hotel.official_url
                })

    # Sort by highest realized CPP
    opportunities.sort(key=lambda x: x["realized_cpp"], reverse=True)
    return opportunities
