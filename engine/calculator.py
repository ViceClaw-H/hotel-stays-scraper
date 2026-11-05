"""Calculation engine for Hotel Price Floors, Ceilings, Surge Indexes, and Points Arbitrage."""
from datetime import datetime, date, timezone
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from database.models import Hotel, RoomCategory, RateRecord, PropertyBaseline


def recalculate_room_baseline(session: Session, room_id: str) -> Optional[PropertyBaseline]:
    """Calculate and persist the 100% floor, ceiling, and stats for a given room."""
    rates = (
        session.query(RateRecord)
        .filter(RateRecord.room_id == room_id)
        .order_by(RateRecord.stay_date.asc())
        .all()
    )

    if not rates:
        return None

    cash_values = [r.cash_rate for r in rates if r.cash_rate is not None]
    if not cash_values:
        return None

    cash_floor = min(cash_values)
    cash_ceiling = max(cash_values)
    avg_cash = sum(cash_values) / len(cash_values)
    
    # Ceiling as percentage of floor (e.g. $300 / $100 * 100 = 300.0%)
    ceiling_surge_pct = (cash_ceiling / cash_floor * 100.0) if cash_floor > 0 else 100.0

    points_values = [r.points_required for r in rates if r.points_required is not None]
    pts_floor = min(points_values) if points_values else None
    pts_ceiling = max(points_values) if points_values else None

    baseline = session.query(PropertyBaseline).filter(PropertyBaseline.room_id == room_id).first()
    if not baseline:
        baseline = PropertyBaseline(room_id=room_id)
        session.add(baseline)

    baseline.cash_floor_100pct = round(cash_floor, 2)
    baseline.cash_ceiling_highest = round(cash_ceiling, 2)
    baseline.ceiling_surge_pct = round(ceiling_surge_pct, 1)
    baseline.avg_cash_rate = round(avg_cash, 2)
    baseline.points_floor = pts_floor
    baseline.points_ceiling = pts_ceiling
    baseline.sample_count = len(rates)
    baseline.updated_at = datetime.now(timezone.utc)

    session.commit()
    return baseline


def recalculate_all_baselines(session: Session) -> int:
    """Recalculate baselines for all rooms in the database in a single fast bulk query."""
    stats = session.query(
        RateRecord.room_id,
        func.min(RateRecord.cash_rate).label("min_cash"),
        func.max(RateRecord.cash_rate).label("max_cash"),
        func.avg(RateRecord.cash_rate).label("avg_cash"),
        func.min(RateRecord.points_required).label("min_pts"),
        func.max(RateRecord.points_required).label("max_pts"),
        func.count(RateRecord.id).label("cnt")
    ).filter(RateRecord.cash_rate.isnot(None)).group_by(RateRecord.room_id).all()

    existing_baselines = {b.room_id: b for b in session.query(PropertyBaseline).all()}
    count = 0
    now = datetime.now(timezone.utc)

    for row in stats:
        rid, min_c, max_c, avg_c, min_p, max_p, cnt = row
        if not min_c or min_c <= 0:
            continue
        surge_pct = round((max_c / min_c * 100.0), 1)

        b = existing_baselines.get(rid)
        if not b:
            b = PropertyBaseline(room_id=rid)
            session.add(b)
        
        b.cash_floor_100pct = round(min_c, 2)
        b.cash_ceiling_highest = round(max_c, 2)
        b.ceiling_surge_pct = surge_pct
        b.avg_cash_rate = round(avg_c, 2) if avg_c else round(min_c, 2)
        b.points_floor = int(min_p) if min_p is not None else None
        b.points_ceiling = int(max_p) if max_p is not None else None
        b.sample_count = cnt
        b.updated_at = now
        count += 1

    session.commit()
    return count


def analyze_rates(
    session: Session,
    hotel_id: Optional[str] = None,
    brand: Optional[str] = None,
    city: Optional[str] = None,
    min_surge_pct: Optional[float] = None,
    arbitrage_only: bool = False,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """
    Query rates and compute real-time surge metrics against the 100% floor.
    """
    query = (
        session.query(RateRecord, RoomCategory, Hotel, PropertyBaseline)
        .join(RoomCategory, RateRecord.room_id == RoomCategory.id)
        .join(Hotel, RoomCategory.hotel_id == Hotel.id)
        .join(PropertyBaseline, RoomCategory.id == PropertyBaseline.room_id)
    )

    if hotel_id:
        query = query.filter(Hotel.id == hotel_id)
    if brand:
        query = query.filter(Hotel.brand == brand.upper())
    if city:
        query = query.filter(Hotel.city.ilike(f"%{city}%"))
    if start_date:
        query = query.filter(RateRecord.stay_date >= start_date)
    if end_date:
        query = query.filter(RateRecord.stay_date <= end_date)

    results = []
    for rate, room, hotel, baseline in query.order_by(RateRecord.stay_date.asc(), Hotel.name.asc()).all():
        floor = baseline.cash_floor_100pct
        cash = rate.cash_rate
        if cash is None:
            continue   # points-only row (no fully-taxed cash price): nothing to compare against a cash floor

        # Surge percentage (Floor = 100%)
        surge_pct = round((cash / floor * 100.0), 1) if floor > 0 else 100.0
        surge_multiplier = round(cash / floor, 2) if floor > 0 else 1.0

        # Points Cent-per-Point (CPP) calculation
        pts = rate.points_required
        # Cents-per-point is only meaningful when cash is in USD; native-currency amounts are not converted here.
        cpp = round((cash / pts * 100.0), 2) if (pts and pts > 0 and (rate.raw_currency in (None, "USD"))) else None

        # Arbitrage classification
        # For fixed chart chains (Hyatt, Wyndham) or high cash surge with standard points:
        is_arbitrage = False
        deal_rating = "PAY_CASH"  # Default when near floor

        if surge_pct <= 125.0:
            deal_rating = "FLOOR_CASH (Best for Cash)"
        elif surge_pct < 175.0:
            deal_rating = "MODERATE_SURGE"
        elif surge_pct < 250.0:
            deal_rating = "HIGH_SURGE"
            if pts and rate.award_available:
                is_arbitrage = True
                deal_rating = "HIGH_POINTS_VALUE 🎯"
        else:
            deal_rating = "PEAK_CEILING"
            if pts and rate.award_available:
                is_arbitrage = True
                deal_rating = "EXTREME_POINTS_ARBITRAGE 🔥"

        if min_surge_pct and surge_pct < min_surge_pct:
            continue
        if arbitrage_only and not is_arbitrage:
            continue

        results.append({
            "hotel_id": hotel.id,
            "hotel_name": hotel.name,
            "brand": hotel.brand,
            "city": hotel.city,
            "country": hotel.country,
            "currency": hotel.currency,
            "room_id": room.id,
            "room_name": room.raw_name,
            "room_type": room.standardized_type,
            "stay_date": rate.stay_date,
            "cash_rate": cash,
            "cash_floor_100pct": floor,
            "cash_ceiling_highest": baseline.cash_ceiling_highest,
            "surge_pct": surge_pct,  # e.g., 250.0%
            "surge_multiplier": surge_multiplier,  # e.g., 2.5x
            "points_required": pts,
            "award_available": rate.award_available,
            "cents_per_point": cpp,
            "deal_rating": deal_rating,
            "is_arbitrage": is_arbitrage,
            "loyalty_model": hotel.loyalty_model,
            "award_category": hotel.award_category,
        })

    return results
