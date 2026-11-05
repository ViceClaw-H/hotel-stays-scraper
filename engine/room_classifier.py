"""Room classification engine.
Categorizes authentic hotel room types from CRS into 4 clean standard tiers:
1. STANDARD (Classic, Superior, Standard Room)
2. DELUXE (Deluxe, Premium, Corner, Ocean/Pool/City View)
3. CLUB (Executive, Club Lounge, Regency Club, Club InterContinental)
4. SUITE (Junior Suite, 1-Bedroom Suite, Villa, Presidential)
"""
from typing import Dict, Any

ROOM_TIERS = {
    "STANDARD": {
        "label": "Standard & Classic",
        "description": "Kamar dasar/standar (Superior, Classic, Standard).",
    },
    "DELUXE": {
        "label": "Deluxe & View Room",
        "description": "Kamar lebih luas dengan pemandangan (Ocean/Pool/City View).",
    },
    "CLUB": {
        "label": "Executive & Club Lounge",
        "description": "Akses Executive Lounge (Sarapan gratis, afternoon tea, cocktails).",
    },
    "SUITE": {
        "label": "Suite & Luxury Villa",
        "description": "Ruang tamu terpisah, Suite Mewah & Private Pool Villa.",
    },
}

def classify_room_name(raw_name: str) -> str:
    """Classify raw hotel room name string into one of the 4 standard room tiers."""
    lower = raw_name.lower().strip()
    
    # Check for Suite / Villa / Penthouse / Presidential
    if any(k in lower for k in ["suite", "villa", "penthouse", "bungalow", "residence", "presidential", "ambassador", "overwater"]):
        return "SUITE"
        
    # Check for Executive / Club Lounge Access
    if any(k in lower for k in ["club", "executive lounge", "lounge access", "club intercontinental", "executive floor", "regency club"]):
        return "CLUB"
        
    # Check for Deluxe / Premium / View
    if any(k in lower for k in ["deluxe", "premium", "ocean view", "sea view", "pool view", "bay view", "harbour view", "corner", "grand deluxe"]):
        return "DELUXE"
        
    # Default to STANDARD
    return "STANDARD"
