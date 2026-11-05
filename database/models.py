"""Database models for Hotel Price Floor & Ceiling Database."""
from datetime import datetime, date, timezone
from typing import Optional, List
from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    CheckConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def utc_now():
    return datetime.now(timezone.utc)


class Hotel(Base):
    """Hotel property record across 9 major chains."""
    __tablename__ = "hotels"

    id = Column(String(64), primary_key=True)  # e.g., "hyatt_grand_hyatt_tokyo"
    brand = Column(String(32), nullable=False, index=True)  # HYATT, MARRIOTT, HILTON, IHG, WYNDHAM, ACCOR, GHA, SHANGRI_LA, LANGHAM
    name = Column(String(255), nullable=False)
    city = Column(String(128), nullable=False, index=True)
    country = Column(String(64), nullable=False)
    currency = Column(String(3), nullable=False, default="USD")
    
    # Loyalty model details
    loyalty_model = Column(String(32), nullable=False)  # FIXED_CHART, DYNAMIC_AWARD, FIXED_REBATE
    award_category = Column(String(64), nullable=True)  # "Category 6", "15,000 Pts", "N/A"
    track_points = Column(Boolean, nullable=False, default=True)
    official_url = Column(String(512), nullable=True)  # Direct official URL to brand property page
    
    created_at = Column(DateTime, default=utc_now)

    # Relationships
    rooms = relationship("RoomCategory", back_populates="hotel", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Hotel id={self.id} brand={self.brand} name={self.name} city={self.city}>"


class RoomCategory(Base):
    """Room category classification per hotel (Standard baseline vs Suites)."""
    __tablename__ = "room_categories"

    id = Column(String(96), primary_key=True)  # e.g., "hyatt_grand_hyatt_tokyo_standard_king"
    hotel_id = Column(String(64), ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False, index=True)
    raw_name = Column(String(255), nullable=False)
    standardized_type = Column(String(32), nullable=False, default="STANDARD")  # STANDARD, DELUXE, PREMIUM, SUITE
    max_occupancy = Column(Integer, default=2)

    # Relationships
    hotel = relationship("Hotel", back_populates="rooms")
    rates = relationship("RateRecord", back_populates="room", cascade="all, delete-orphan")
    baseline = relationship("PropertyBaseline", back_populates="room", uselist=False, cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<RoomCategory id={self.id} hotel_id={self.hotel_id} type={self.standardized_type}>"


class RateRecord(Base):
    """Daily cash rate and award points snapshot for a specific stay date with verified provenance."""
    __tablename__ = "rate_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    room_id = Column(String(96), ForeignKey("room_categories.id", ondelete="CASCADE"), nullable=False, index=True)
    stay_date = Column(Date, nullable=False, index=True)
    
    # FULLY TAXED final price for the stay, or NULL when the source gave no all-in cash price.
    # Never 0.0 - the database rejects it (ck_cash_positive). See docs/DATA_CONTRACT.md.
    cash_rate = Column(Float, nullable=True)
    points_required = Column(Integer, nullable=True)  # Required award points (null for cash-only chains)
    award_available = Column(Boolean, nullable=False, default=True)
    
    # Mandatory Provenance Metadata
    source_url = Column(String(512), nullable=True)  # Official CRS endpoint / Booking URL
    source_type = Column(String(32), nullable=True)  # OFFICIAL_CRS_API, OFFICIAL_SHANGRILA_CRS, OFFICIAL_SYNXIS_CRS, etc.
    source_payload_hash = Column(String(64), nullable=True)  # SHA-256 cryptographic payload hash
    observed_at = Column(DateTime, default=utc_now)
    raw_currency = Column(String(3), nullable=True)  # ISO code from the source response; required when cash_rate is set (no default: a default is how mislabelled currencies happen)
    raw_amount = Column(Float, nullable=True)
    tax_inclusive = Column(Boolean, nullable=True)  # 1 = verified all-in, 0 = source says excluded, NULL = unknown / no cash
    room_name = Column(String, nullable=False)      # verbatim room type the price belongs to
    room_class = Column(String(16), nullable=False)  # STANDARD | DELUXE | CLUB | SUITE | UNKNOWN (derived from room_name)
    evidence_grade = Column(String(12), nullable=False, default="UNVERIFIED")  # RAW | SUMMARY | UNVERIFIED

    scraped_at = Column(DateTime, default=utc_now)
    notes = Column(String(255), nullable=True)
    evidence_file = Column(String(255), nullable=True)

    # Relationships
    room = relationship("RoomCategory", back_populates="rates")

    __table_args__ = (
        UniqueConstraint("room_id", "stay_date", name="uq_room_stay_date"),
        Index("idx_room_date", "room_id", "stay_date"),
        # Mirrors engine/schema.py - the contract must hold for a freshly created database too.
        CheckConstraint("cash_rate IS NULL OR cash_rate > 0", name="ck_cash_positive"),
        CheckConstraint("points_required IS NULL OR points_required > 0", name="ck_points_positive"),
        CheckConstraint("cash_rate IS NOT NULL OR points_required IS NOT NULL", name="ck_has_price"),
        CheckConstraint("cash_rate IS NULL OR (raw_currency IS NOT NULL AND length(raw_currency) = 3)", name="ck_cash_has_currency"),
        CheckConstraint("room_class IN ('STANDARD','DELUXE','CLUB','SUITE','UNKNOWN')", name="ck_room_class"),
        CheckConstraint("evidence_grade IN ('RAW','SUMMARY','UNVERIFIED')", name="ck_grade"),
    )

    def __repr__(self) -> str:
        return f"<RateRecord room={self.room_id} date={self.stay_date} cash={self.cash_rate} pts={self.points_required} hash={self.source_payload_hash[:8] if self.source_payload_hash else 'N/A'}>"



class PropertyBaseline(Base):
    """Calculated Floor (100% baseline) and Ceiling metrics for each room."""
    __tablename__ = "property_baselines"

    room_id = Column(String(96), ForeignKey("room_categories.id", ondelete="CASCADE"), primary_key=True)
    
    cash_floor_100pct = Column(Float, nullable=False)  # The absolute lowest observed cash rate = 100%
    cash_ceiling_highest = Column(Float, nullable=False)  # The highest observed cash rate
    ceiling_surge_pct = Column(Float, nullable=False)  # (Ceiling / Floor) * 100%
    avg_cash_rate = Column(Float, nullable=False)
    
    points_floor = Column(Integer, nullable=True)
    points_ceiling = Column(Integer, nullable=True)
    
    sample_count = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationships
    room = relationship("RoomCategory", back_populates="baseline")

    def __repr__(self) -> str:
        return (
            f"<PropertyBaseline room={self.room_id} "
            f"Floor=${self.cash_floor_100pct:.2f} (100%) "
            f"Ceiling=${self.cash_ceiling_highest:.2f} ({self.ceiling_surge_pct:.1f}%)>"
        )
