"""Database connection and session handling."""
import os
from pathlib import Path
from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker, scoped_session
from .models import Base

# Default SQLite database path in local project directory
DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "hotel_stays.db"

def get_engine(db_url_or_engine = None):
    if isinstance(db_url_or_engine, Engine):
        return db_url_or_engine
    if db_url_or_engine is None:
        db_url_or_engine = os.environ.get("HOTEL_DB_URL", f"sqlite:///{DEFAULT_DB_PATH}")
    
    connect_args = {"check_same_thread": False, "timeout": 60} if str(db_url_or_engine).startswith("sqlite") else {}
    return create_engine(str(db_url_or_engine), connect_args=connect_args, echo=False)

def init_db(engine_or_url=None):
    """Create all tables defined in models and install evidence security triggers."""
    engine = get_engine(engine_or_url)
    Base.metadata.create_all(bind=engine)
    
    # Install strict security triggers for SQLite databases
    if str(engine.url).startswith("sqlite"):
        with engine.connect() as conn:
            from sqlalchemy import text
            conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS enforce_award_evidence_insert
                BEFORE INSERT ON rate_records
                FOR EACH ROW
                WHEN (NEW.award_available = 1 OR (NEW.points_required IS NOT NULL AND NEW.points_required > 0))
                     AND (NEW.evidence_file IS NULL OR NEW.source_payload_hash IS NULL OR LENGTH(NEW.source_payload_hash) < 32)
                BEGIN
                    SELECT RAISE(ABORT, 'Database Security Gate Rejected: Award rates (award_available=1 or points_required>0) MANDATE official CRS evidence_file and SHA-256 source_payload_hash.');
                END;
            """))
            conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS enforce_award_evidence_update
                BEFORE UPDATE ON rate_records
                FOR EACH ROW
                WHEN (NEW.award_available = 1 OR (NEW.points_required IS NOT NULL AND NEW.points_required > 0))
                     AND (NEW.evidence_file IS NULL OR NEW.source_payload_hash IS NULL OR LENGTH(NEW.source_payload_hash) < 32)
                BEGIN
                    SELECT RAISE(ABORT, 'Database Security Gate Rejected: Award rates (award_available=1 or points_required>0) MANDATE official CRS evidence_file and SHA-256 source_payload_hash.');
                END;
            """))
            conn.commit()
    return engine

def get_session_factory(engine_or_url=None):
    engine = get_engine(engine_or_url)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_scoped_session(engine_or_url=None):
    return scoped_session(get_session_factory(engine_or_url))
