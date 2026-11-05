"""Single source of truth for the rate_records contract (schema v2).

Rules that used to live only in Python (and so could be skipped by raw SQL) are enforced here by the
database itself with CHECK constraints and triggers:

  * cash_rate is NULL when the source gave no fully-taxed cash price - never a 0.0 placeholder.
  * points_required is NULL when there are no points - never 0.
  * a cash price must carry a real 3-letter currency taken from the source response.
  * every row must carry at least one price (cash or points).
  * every row must name the room it prices (room_name) and its tier (room_class), so a Standard
    cash rate can never be silently compared with a Suite cash rate.
  * every row states how strong its evidence is (evidence_grade): RAW (verbatim response bytes),
    SUMMARY (a harvester-written summary of a response) or UNVERIFIED.
"""
import sqlite3

from engine.chain_policy import CHAIN_POLICIES

SCHEMA_VERSION = 2

ROOM_CLASSES = ("STANDARD", "DELUXE", "CLUB", "SUITE", "UNKNOWN")
EVIDENCE_GRADES = ("RAW", "SUMMARY", "UNVERIFIED")

HOTELS_DDL = """
CREATE TABLE IF NOT EXISTS hotels (
    id VARCHAR(64) NOT NULL,
    brand VARCHAR(32) NOT NULL,
    name VARCHAR(255) NOT NULL,
    city VARCHAR(128) NOT NULL,
    country VARCHAR(64) NOT NULL,
    currency VARCHAR(3) NOT NULL,
    loyalty_model VARCHAR(32) NOT NULL,
    award_category VARCHAR(64),
    track_points BOOLEAN NOT NULL,
    official_url VARCHAR(512),
    created_at DATETIME,
    PRIMARY KEY (id)
)"""

ROOM_CATEGORIES_DDL = """
CREATE TABLE IF NOT EXISTS room_categories (
    id VARCHAR(96) NOT NULL,
    hotel_id VARCHAR(64) NOT NULL,
    raw_name VARCHAR(255) NOT NULL,
    standardized_type VARCHAR(32) NOT NULL,
    max_occupancy INTEGER,
    PRIMARY KEY (id),
    FOREIGN KEY(hotel_id) REFERENCES hotels (id) ON DELETE CASCADE
)"""

EVIDENCE_REGISTRY_DDL = """
CREATE TABLE IF NOT EXISTS evidence_registry (
    id TEXT PRIMARY KEY,
    evidence_file TEXT NOT NULL UNIQUE,
    sha256_hash TEXT NOT NULL,
    file_bytes_size INTEGER NOT NULL,
    source_url TEXT NOT NULL,
    source_type TEXT NOT NULL,
    has_award_data INTEGER NOT NULL DEFAULT 0,
    award_points_min INTEGER,
    award_points_max INTEGER,
    verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)"""

RATE_RECORDS_COLUMNS = (
    "id", "room_id", "stay_date", "cash_rate", "points_required", "award_available", "scraped_at",
    "notes", "source_url", "source_type", "source_payload_hash", "observed_at", "raw_currency",
    "raw_amount", "tax_inclusive", "evidence_file", "room_name", "room_class", "evidence_grade",
)


def rate_records_ddl(table="rate_records"):
    return f"""
CREATE TABLE {table} (
    id INTEGER NOT NULL,
    room_id VARCHAR(96) NOT NULL,
    stay_date DATE NOT NULL,
    cash_rate FLOAT,
    points_required INTEGER,
    award_available BOOLEAN NOT NULL,
    scraped_at DATETIME,
    notes VARCHAR(255),
    source_url VARCHAR(512),
    source_type VARCHAR(32),
    source_payload_hash VARCHAR(64),
    observed_at DATETIME,
    raw_currency VARCHAR(3),
    raw_amount FLOAT,
    tax_inclusive BOOLEAN DEFAULT 1,
    evidence_file VARCHAR(255),
    room_name TEXT NOT NULL,
    room_class VARCHAR(16) NOT NULL,
    evidence_grade VARCHAR(12) NOT NULL DEFAULT 'UNVERIFIED',
    PRIMARY KEY (id),
    CONSTRAINT uq_room_stay_date UNIQUE (room_id, stay_date),
    FOREIGN KEY(room_id) REFERENCES room_categories (id) ON DELETE CASCADE,
    CONSTRAINT ck_cash_positive CHECK (cash_rate IS NULL OR cash_rate > 0),
    CONSTRAINT ck_points_positive CHECK (points_required IS NULL OR points_required > 0),
    CONSTRAINT ck_has_price CHECK (cash_rate IS NOT NULL OR points_required IS NOT NULL),
    CONSTRAINT ck_cash_has_currency CHECK (cash_rate IS NULL OR (raw_currency IS NOT NULL AND length(raw_currency) = 3)),
    CONSTRAINT ck_room_class CHECK (room_class IN ('STANDARD','DELUXE','CLUB','SUITE','UNKNOWN')),
    CONSTRAINT ck_grade CHECK (evidence_grade IN ('RAW','SUMMARY','UNVERIFIED'))
)"""


RATE_RECORDS_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_rate_records_source_type ON rate_records(source_type)",
    "CREATE INDEX IF NOT EXISTS idx_room_date ON rate_records (room_id, stay_date)",
    "CREATE INDEX IF NOT EXISTS ix_rate_records_room_id ON rate_records (room_id)",
    "CREATE INDEX IF NOT EXISTS ix_rate_records_stay_date ON rate_records (stay_date)",
)

# These four triggers already existed in the delivered DB; they are re-created verbatim because
# dropping the table drops them.
RATE_RECORDS_TRIGGERS = (
    """CREATE TRIGGER enforce_evidence_parity_insert
    BEFORE INSERT ON rate_records
    FOR EACH ROW
    WHEN NEW.evidence_file IS NOT NULL
    BEGIN
        SELECT RAISE(ABORT, 'Cryptographic Gate Rejected: evidence_file not registered in evidence_registry or SHA-256 hash mismatch.')
        WHERE NOT EXISTS (
            SELECT 1 FROM evidence_registry
            WHERE evidence_file = NEW.evidence_file
              AND sha256_hash = NEW.source_payload_hash
        );
    END""",
    """CREATE TRIGGER enforce_evidence_parity_update
    BEFORE UPDATE ON rate_records
    FOR EACH ROW
    WHEN NEW.evidence_file IS NOT NULL
    BEGIN
        SELECT RAISE(ABORT, 'Cryptographic Gate Rejected: evidence_file not registered in evidence_registry or SHA-256 hash mismatch.')
        WHERE NOT EXISTS (
            SELECT 1 FROM evidence_registry
            WHERE evidence_file = NEW.evidence_file
              AND sha256_hash = NEW.source_payload_hash
        );
    END""",
    """CREATE TRIGGER enforce_award_evidence_strict_insert
    BEFORE INSERT ON rate_records
    FOR EACH ROW
    WHEN NEW.award_available = 1 OR (NEW.points_required IS NOT NULL AND NEW.points_required > 0)
    BEGIN
        SELECT RAISE(ABORT, 'Cryptographic Gate Rejected: Award rows MANDATE an official CRS evidence file with verified has_award_data=1 in evidence_registry.')
        WHERE NOT EXISTS (
            SELECT 1 FROM evidence_registry
            WHERE evidence_file = NEW.evidence_file
              AND sha256_hash = NEW.source_payload_hash
              AND has_award_data = 1
        );
    END""",
    """CREATE TRIGGER enforce_award_evidence_strict_update
    BEFORE UPDATE ON rate_records
    FOR EACH ROW
    WHEN NEW.award_available = 1 OR (NEW.points_required IS NOT NULL AND NEW.points_required > 0)
    BEGIN
        SELECT RAISE(ABORT, 'Cryptographic Gate Rejected: Award rows MANDATE an official CRS evidence file with verified has_award_data=1 in evidence_registry.')
        WHERE NOT EXISTS (
            SELECT 1 FROM evidence_registry
            WHERE evidence_file = NEW.evidence_file
              AND sha256_hash = NEW.source_payload_hash
              AND has_award_data = 1
        );
    END""",
)

# One row per (source, hotel): the DB - not a JSON file - remembers what happened to every hotel,
# why, where it got stuck, and when it is worth trying again.
HARVEST_STATUS_DDL = """
CREATE TABLE IF NOT EXISTS harvest_status (
    source TEXT NOT NULL,
    hotel_id TEXT NOT NULL,
    status TEXT NOT NULL,          -- OK | PARTIAL | NO_AVAILABILITY | INACTIVE | DUPLICATE | FAILED
    reason TEXT,                   -- machine code, e.g. HTTP_425_CHANNEL, REDIRECT_TO_SEARCH, TIMEOUT
    detail TEXT,                   -- verbatim error text returned by the source
    url TEXT,                      -- the URL where it got stuck
    grid_id TEXT,
    dates_ok INTEGER,
    dates_total INTEGER,
    horizon_last_ok TEXT,          -- last stay date that returned a price (booking horizon)
    attempts INTEGER NOT NULL DEFAULT 1,
    last_attempt_at TEXT NOT NULL,
    retry_after TEXT,              -- ISO date; NULL = do not retry automatically
    PRIMARY KEY (source, hotel_id)
)"""

CHAIN_POLICY_REGISTRY_DDL = """
CREATE TABLE IF NOT EXISTS chain_policy_registry (
    chain TEXT PRIMARY KEY,
    location_scope TEXT NOT NULL CHECK (location_scope IN ('REDEMPTION_REQUIRED', 'BOOKABLE_ONLY')),
    rationale TEXT NOT NULL
)"""

LOCATION_OBSERVATIONS_DDL = """
CREATE TABLE IF NOT EXISTS location_observations (
    id TEXT PRIMARY KEY,
    hotel_id TEXT NOT NULL REFERENCES hotels(id) ON DELETE CASCADE,
    chain TEXT NOT NULL REFERENCES chain_policy_registry(chain),
    policy_mode TEXT NOT NULL CHECK (policy_mode IN ('REDEMPTION_REQUIRED', 'BOOKABLE_ONLY')),
    status TEXT NOT NULL CHECK (status IN (
        'IN_SCOPE_REDEEMABLE', 'IN_SCOPE_BOOKABLE', 'REDEEMABLE_SOLD_OUT_IN_TEST_WINDOW',
        'CASH_SOLD_OUT_IN_TEST_WINDOW', 'OUT_OF_SCOPE_PARTNER_NONREDEEMABLE', 'UNKNOWN_ELIGIBILITY'
    )),
    cash_search_attempted INTEGER NOT NULL CHECK (cash_search_attempted IN (0, 1)),
    cash_bookable INTEGER NOT NULL CHECK (cash_bookable IN (0, 1)),
    award_search_attempted INTEGER NOT NULL CHECK (award_search_attempted IN (0, 1)),
    full_points_bookable INTEGER NOT NULL CHECK (full_points_bookable IN (0, 1)),
    partner_nonredeemable_confirmed INTEGER NOT NULL CHECK (partner_nonredeemable_confirmed IN (0, 1)),
    source_url TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_payload_hash TEXT NOT NULL,
    evidence_file TEXT NOT NULL,
    evidence_grade TEXT NOT NULL CHECK (evidence_grade IN ('RAW', 'SUMMARY')),
    observed_at TEXT NOT NULL,
    notes TEXT
)"""

LOCATION_OBSERVATIONS_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_location_observations_hotel_observed ON location_observations(hotel_id, observed_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_location_observations_status ON location_observations(status)",
)

CURRENT_USABLE_LOCATION_ELIGIBILITY_VIEW = """
CREATE VIEW current_usable_location_eligibility AS
SELECT lo.*
FROM current_location_eligibility lo
WHERE NOT EXISTS (
    SELECT 1
    FROM harvest_status hs
    WHERE hs.hotel_id = lo.hotel_id
      AND hs.source = 'SHANGRILA'
      AND hs.status = 'INACTIVE'
)"""

# These triggers replicate the policy decision in SQLite.  This means direct SQL cannot claim a
# redeemable Wyndham result from a Cash + Points-only or untested observation.
LOCATION_POLICY_TRIGGERS = (
    """CREATE TRIGGER IF NOT EXISTS prevent_chain_policy_update
    BEFORE UPDATE ON chain_policy_registry
    BEGIN SELECT RAISE(ABORT, 'Chain policy registry is code-managed and immutable in the database.'); END""",
    """CREATE TRIGGER IF NOT EXISTS prevent_chain_policy_delete
    BEFORE DELETE ON chain_policy_registry
    BEGIN SELECT RAISE(ABORT, 'Chain policy registry is code-managed and immutable in the database.'); END""",
    """CREATE TRIGGER IF NOT EXISTS enforce_location_policy_insert
    BEFORE INSERT ON location_observations
    BEGIN
        SELECT RAISE(ABORT, 'Location policy rejected: chain must match the hotel brand.')
          WHERE NEW.chain != (SELECT brand FROM hotels WHERE id = NEW.hotel_id);
        SELECT RAISE(ABORT, 'Location policy rejected: policy mode does not match central registry.')
          WHERE NEW.policy_mode != (SELECT location_scope FROM chain_policy_registry WHERE chain = NEW.chain);
        SELECT RAISE(ABORT, 'Location policy rejected: evidence parity failed.')
          WHERE NOT EXISTS (SELECT 1 FROM evidence_registry WHERE evidence_file = NEW.evidence_file AND sha256_hash = NEW.source_payload_hash);
        SELECT RAISE(ABORT, 'Location policy rejected: contradictory partner and award facts.')
          WHERE NEW.full_points_bookable = 1 AND NEW.partner_nonredeemable_confirmed = 1;
        SELECT RAISE(ABORT, 'Location policy rejected: status does not follow observed facts.')
          WHERE NEW.status != CASE
            WHEN NEW.policy_mode = 'REDEMPTION_REQUIRED' AND NEW.full_points_bookable = 1 THEN 'IN_SCOPE_REDEEMABLE'
            WHEN NEW.policy_mode = 'REDEMPTION_REQUIRED' AND NEW.partner_nonredeemable_confirmed = 1 THEN 'OUT_OF_SCOPE_PARTNER_NONREDEEMABLE'
            WHEN NEW.policy_mode = 'REDEMPTION_REQUIRED' AND NEW.award_search_attempted = 1 THEN 'REDEEMABLE_SOLD_OUT_IN_TEST_WINDOW'
            WHEN NEW.policy_mode = 'REDEMPTION_REQUIRED' THEN 'UNKNOWN_ELIGIBILITY'
            WHEN NEW.cash_bookable = 1 THEN 'IN_SCOPE_BOOKABLE'
            WHEN NEW.cash_search_attempted = 1 THEN 'CASH_SOLD_OUT_IN_TEST_WINDOW'
            ELSE 'UNKNOWN_ELIGIBILITY'
          END;
    END""",
    """CREATE TRIGGER IF NOT EXISTS enforce_location_policy_update
    BEFORE UPDATE ON location_observations
    BEGIN
        SELECT RAISE(ABORT, 'Location policy rejected: chain must match the hotel brand.')
          WHERE NEW.chain != (SELECT brand FROM hotels WHERE id = NEW.hotel_id);
        SELECT RAISE(ABORT, 'Location policy rejected: policy mode does not match central registry.')
          WHERE NEW.policy_mode != (SELECT location_scope FROM chain_policy_registry WHERE chain = NEW.chain);
        SELECT RAISE(ABORT, 'Location policy rejected: status does not follow observed facts.')
          WHERE NEW.status != CASE
            WHEN NEW.policy_mode = 'REDEMPTION_REQUIRED' AND NEW.full_points_bookable = 1 THEN 'IN_SCOPE_REDEEMABLE'
            WHEN NEW.policy_mode = 'REDEMPTION_REQUIRED' AND NEW.partner_nonredeemable_confirmed = 1 THEN 'OUT_OF_SCOPE_PARTNER_NONREDEEMABLE'
            WHEN NEW.policy_mode = 'REDEMPTION_REQUIRED' AND NEW.award_search_attempted = 1 THEN 'REDEEMABLE_SOLD_OUT_IN_TEST_WINDOW'
            WHEN NEW.policy_mode = 'REDEMPTION_REQUIRED' THEN 'UNKNOWN_ELIGIBILITY'
            WHEN NEW.cash_bookable = 1 THEN 'IN_SCOPE_BOOKABLE'
            WHEN NEW.cash_search_attempted = 1 THEN 'CASH_SOLD_OUT_IN_TEST_WINDOW'
            ELSE 'UNKNOWN_ELIGIBILITY'
          END;
    END""",
)

QUARANTINE_EXTRA_COLUMNS = ("quarantine_reason TEXT", "quarantined_at TEXT")


def create_quarantine_table(conn):
    """rate_records_quarantine: same columns as rate_records, no constraints, plus why/when.

    Rows that are provably not what they claim to be are moved here (never deleted) so they stay
    inspectable and can be re-scraped."""
    conn.execute("DROP TABLE IF EXISTS rate_records_quarantine")
    conn.execute("CREATE TABLE rate_records_quarantine AS SELECT * FROM rate_records WHERE 0")
    for col in QUARANTINE_EXTRA_COLUMNS:
        conn.execute(f"ALTER TABLE rate_records_quarantine ADD COLUMN {col}")


def create_full_schema(conn: sqlite3.Connection):
    """Create the complete v2 schema in an empty database (tests, fresh installs)."""
    for ddl in (HOTELS_DDL, ROOM_CATEGORIES_DDL, EVIDENCE_REGISTRY_DDL):
        conn.execute(ddl)
    conn.execute(rate_records_ddl("rate_records"))
    for ddl in RATE_RECORDS_INDEXES:
        conn.execute(ddl)
    for ddl in RATE_RECORDS_TRIGGERS:
        conn.execute(ddl)
    conn.execute(HARVEST_STATUS_DDL)
    ensure_location_schema(conn, commit=False)
    conn.commit()


def ensure_location_schema(conn: sqlite3.Connection, *, commit: bool = True):
    """Install and verify the code-managed location-policy storage on an existing v2 database."""
    conn.execute(CHAIN_POLICY_REGISTRY_DDL)
    expected = {key: (value.location_scope.value, value.rationale) for key, value in CHAIN_POLICIES.items()}
    for chain, (scope, rationale) in expected.items():
        conn.execute("INSERT OR IGNORE INTO chain_policy_registry (chain, location_scope, rationale) VALUES (?,?,?)",
                     (chain, scope, rationale))
    actual = dict(conn.execute("SELECT chain, location_scope FROM chain_policy_registry"))
    mismatch = {chain: (scope, actual.get(chain)) for chain, (scope, _) in expected.items()
                if actual.get(chain) != scope}
    if mismatch:
        raise RuntimeError(f"chain_policy_registry differs from engine.chain_policy: {mismatch}")
    conn.execute(LOCATION_OBSERVATIONS_DDL)
    for ddl in LOCATION_OBSERVATIONS_INDEXES:
        conn.execute(ddl)
    for ddl in LOCATION_POLICY_TRIGGERS:
        conn.execute(ddl)
    conn.execute("""CREATE VIEW IF NOT EXISTS current_location_eligibility AS
        SELECT lo.* FROM location_observations lo
        WHERE lo.observed_at = (
            SELECT MAX(newer.observed_at) FROM location_observations newer WHERE newer.hotel_id = lo.hotel_id
        )""")
    # The official location search establishes discovery.  A stronger later CRS answer that says
    # HOTEL_CLOSED must win for the usable universe, while the discovery observation remains in
    # history for audit.
    conn.execute("DROP VIEW IF EXISTS current_usable_location_eligibility")
    conn.execute(CURRENT_USABLE_LOCATION_ELIGIBILITY_VIEW)
    if commit:
        conn.commit()


def schema_version(conn: sqlite3.Connection) -> int:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(rate_records)")}
    return 2 if {"room_name", "room_class", "evidence_grade"} <= cols else 1


def require_v2(conn: sqlite3.Connection, who: str = "this harvester") -> None:
    """Stop BEFORE any live request if the database cannot store what would be fetched.

    A harvester run against a schema-v1 database fetches real data from the site, then fails every
    write - wasting requests (and risking a block) for nothing."""
    if schema_version(conn) < 2:
        raise SystemExit(
            f"[!] {who}: the database is still schema v1 (no room_name / room_class / evidence_grade columns), "
            "so nothing fetched could be stored. Refusing to spend live requests.\n"
            "    Run first:  python scripts/migrate_contract_v2.py --db hotel_stays.db"
        )
