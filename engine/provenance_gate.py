"""Strict Provenance Ingestion Gate for Hotel Rate Records.
Enforces 100% Real Live Data Mandate.
Rejects any procedural, multiplier-based, estimated, or unverified rate records.
Enforces strict official domain allowlist and mandatory raw CRS payload hashing.
"""
import hashlib
import re
from datetime import datetime
from typing import Dict, Any, Optional
from urllib.parse import urlparse

ALLOWED_SOURCE_TYPES = {
    "OFFICIAL_CRS_API",
    "OFFICIAL_SHANGRILA_CRS",
    "OFFICIAL_LANGHAM_SYNXIS",
    "OFFICIAL_SYNXIS_CRS",
    "OFFICIAL_WYNDHAM_BWS_API",
    "OFFICIAL_IHG_CRS",
    "OFFICIAL_MARRIOTT_CRS",
    "OFFICIAL_ACCOR_CRS",
    "OFFICIAL_HILTON_CRS",
    "OFFICIAL_GHA_CRS",
    "OFFICIAL_HYATT_CRS",
    # Source types the harvesters actually write. They were missing from this list, so the gate
    # would have rejected ~34% of the rows already in the database.
    "OFFICIAL_WYNDHAM_CRS",
    "OFFICIAL_HYATT_AVAIL_DAYS",
    "OFFICIAL_HYATT_CASH_BENCHMARK",
    "OFFICIAL_BESTWESTERN_BFF",
    "OFFICIAL_BESTWESTERN_CRS",
    "OFFICIAL_RADISSON_CRS",
    "OFFICIAL_SWISSBEL_CRS",
}

ALLOWED_OFFICIAL_DOMAINS = [
    "shangri-la.com",
    "langhamhotels.com",
    "cordishotels.com",
    "eatonworkshop.com",
    "yingnflo.com",
    "brilliantbylangham.com",
    "synxis.com",
    "chelseatoronto.com",
    "hyatt.com",
    "marriott.com",
    "hilton.com",
    "ihg.com",
    "accor.com",
    "wyndhamhotels.com",
    "ghadiscovery.com",
    "bestwestern.com",
    "bwhhotels.com",
    "radissonhotels.com",
    "swiss-belhotel.com",
    "hotelchamp.io",
    "hotelchamp.com"
]

FORBIDDEN_KEYWORDS = [
    "synthetic",
    "estimated",
    "multiplier",
    "fake",
    "benchmark formula",
    "procedural",
    "placeholder"
]

class ProvenanceViolationError(ValueError):
    """Raised when a rate record violates the 100% Real Live Data Mandate."""
    pass


# ---------------------------------------------------------------------------------------------
# Row-level rules (schema v2). Used by engine.rate_writer for every row of every harvester.
# ---------------------------------------------------------------------------------------------
_ISO_CCY = re.compile(r"^[A-Z]{3}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MAJOR_CCY = {"USD", "EUR", "GBP", "CAD", "AUD", "CHF", "NZD", "SGD"}
# A nightly price above this in a major currency is almost certainly a local-currency amount
# (e.g. IDR shown as USD). Such rows are REJECTED for review - never relabelled or rescaled.
MAX_PLAUSIBLE_MAJOR_CCY_NIGHT = 50_000


def check_row(stay_date, cash_rate, currency, points_required, room_name, today=None):
    """Return None if the row obeys the contract, else a short machine-readable reason code."""
    if not isinstance(stay_date, str) or not _DATE_RE.match(stay_date):
        return "BAD_DATE"
    try:
        d = datetime.strptime(stay_date, "%Y-%m-%d").date()
    except ValueError:
        return "BAD_DATE"
    if d < (today or datetime.now().date()):
        return "PAST_DATE"
    if not room_name or not str(room_name).strip():
        return "NO_ROOM_NAME"
    if cash_rate is not None:
        try:
            c = float(cash_rate)
        except (TypeError, ValueError):
            return "BAD_CASH"
        if not c > 0:
            return "BAD_CASH"          # 0.0 is never a price; use None
        if not currency or not _ISO_CCY.match(str(currency).upper()):
            return "NO_CURRENCY"       # currency must come from the source response
        if str(currency).upper() in _MAJOR_CCY and c > MAX_PLAUSIBLE_MAJOR_CCY_NIGHT:
            return "IMPLAUSIBLE_MAGNITUDE"
    if points_required is not None:
        try:
            if int(points_required) <= 0:
                return "BAD_POINTS"    # 0 is never a points price; use None
        except (TypeError, ValueError):
            return "BAD_POINTS"
    if cash_rate is None and points_required is None:
        return "NO_PRICE"
    return None


def check_batch_source(source_url, source_type, notes=None):
    """Batch-level rules: official https domain, allowed source type, no synthetic keywords."""
    if source_type not in ALLOWED_SOURCE_TYPES:
        raise ProvenanceViolationError(f"source_type '{source_type}' is not an allowed official source type.")
    if not source_url or not source_url.startswith("https://"):
        raise ProvenanceViolationError(f"source_url must be https, got '{source_url}'.")
    host = (urlparse(source_url).hostname or "").lower()
    if not any(host == dom or host.endswith("." + dom) for dom in ALLOWED_OFFICIAL_DOMAINS):
        raise ProvenanceViolationError(f"domain '{host}' is not an allowed official brand domain.")
    if notes:
        low = notes.lower()
        for kw in FORBIDDEN_KEYWORDS:
            if kw in low:
                raise ProvenanceViolationError(f"notes contain forbidden synthetic keyword '{kw}'.")

def validate_and_hash_rate_record(
    room_id: str,
    stay_date_str: str,
    raw_amount: float,
    raw_currency: str,
    source_url: str,
    source_type: str,
    raw_payload_str: Optional[str] = None,
    evidence_file: Optional[str] = None,
    cash_rate_idr: Optional[float] = None,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """Validates that a rate record meets all strict provenance requirements before database entry.
    
    Requires:
    1. Valid room_id and YYYY-MM-DD stay_date.
    2. Real positive raw_amount and 3-letter ISO raw_currency.
    3. Official source_url from verified brand domain allowlist.
    4. Allowed official CRS source_type.
    5. Mandatory unmodified raw evidence file on disk (or raw payload string) whose SHA-256 hash is computed.
    6. No forbidden synthetic keywords.
    """
    import os
    
    # 1. Check required fields
    if not room_id or not room_id.strip():
        raise ProvenanceViolationError("Ingestion rejected: room_id is required.")
    
    if not stay_date_str or not re.match(r"^\d{4}-\d{2}-\d{2}$", stay_date_str):
        raise ProvenanceViolationError(f"Ingestion rejected: Invalid stay_date format '{stay_date_str}'. Expected YYYY-MM-DD.")
        
    if raw_amount is None or raw_amount <= 0:
        raise ProvenanceViolationError(f"Ingestion rejected: Non-positive rate amount '{raw_amount}'. Rates must be positive real currency values.")
        
    if not raw_currency or len(raw_currency) != 3:
        raise ProvenanceViolationError(f"Ingestion rejected: Invalid ISO currency code '{raw_currency}'.")

    # 2. Strict Official Domain Whitelist Validation
    if not source_url or not source_url.startswith("https://"):
        raise ProvenanceViolationError(f"Ingestion rejected: source_url must be a valid secure HTTPS URL. Got '{source_url}'.")
    
    parsed = urlparse(source_url)
    hostname = parsed.hostname.lower() if parsed.hostname else ""
    
    if not any(hostname == d or hostname.endswith("." + d) for d in ALLOWED_OFFICIAL_DOMAINS):
        raise ProvenanceViolationError(
            f"Ingestion rejected: Domain '{hostname}' is not in the allowed official brand domains: {ALLOWED_OFFICIAL_DOMAINS}."
        )

    # 3. Check source type whitelist
    if source_type not in ALLOWED_SOURCE_TYPES:
        raise ProvenanceViolationError(
            f"Ingestion rejected: source_type '{source_type}' is not recognized. "
            f"Must be one of official CRS source types: {list(ALLOWED_SOURCE_TYPES)}."
        )

    # 4. Mandatory Raw Evidence Payload or File
    if evidence_file:
        norm_ev_path = evidence_file.replace("\\", "/")
        if not os.path.exists(norm_ev_path):
            raise ProvenanceViolationError(f"Ingestion rejected: Evidence file '{norm_ev_path}' does not exist on disk.")
        with open(norm_ev_path, "rb") as ef:
            file_bytes = ef.read()
        if len(file_bytes) < 10:
            raise ProvenanceViolationError(f"Ingestion rejected: Evidence file '{norm_ev_path}' is empty or corrupt.")
        payload_hash = hashlib.sha256(file_bytes).hexdigest()
        stored_evidence_file = norm_ev_path
    elif raw_payload_str and len(raw_payload_str.strip()) >= 10:
        payload_hash = hashlib.sha256(raw_payload_str.encode("utf-8")).hexdigest()
        stored_evidence_file = None
    else:
        raise ProvenanceViolationError(
            "Ingestion rejected: Either a valid evidence_file on disk or raw_payload_str is mandatory for authentic provenance."
        )

    # 5. Check for forbidden synthetic / procedural keywords in notes
    if notes:
        n_low = notes.lower()
        for kw in FORBIDDEN_KEYWORDS:
            if kw in n_low:
                raise ProvenanceViolationError(
                    f"Ingestion rejected: Note contains forbidden synthetic keyword '{kw}': '{notes}'. "
                    "Synthetic / estimated data is strictly forbidden by repository rules."
                )

    # Enforce Zero Synthetic: Cash rate in database is 100% strictly the raw empirical CRS amount in native currency
    final_cash_rate = float(raw_amount)

    return {
        "room_id": room_id,
        "stay_date": stay_date_str,
        "cash_rate": final_cash_rate,
        "raw_amount": float(raw_amount),
        "raw_currency": raw_currency.upper(),
        "source_url": source_url,
        "source_type": source_type,
        "source_payload_hash": payload_hash,
        "evidence_file": stored_evidence_file,
        "observed_at": datetime.now(),
        "tax_inclusive": True,
        "notes": notes
    }
