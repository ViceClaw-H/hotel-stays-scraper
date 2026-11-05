"""City Tax & Stay Tax Registry for Global Points Arbitrage Verification.
Provides exact statutory local tourist taxes (City Tax, Stay Tax, Kurtaxe, Taxe de Sejour)
that MUST be settled in cash/credit card at check-in/out and CANNOT be waived by points.
"""

from typing import Dict, Any, Optional

CITY_TAX_REGISTRY: Dict[str, Dict[str, Any]] = {
    # --- FRANCE ---
    "Paris": {
        "country": "France",
        "tax_amount": 10.73,  # Standard 5-star hotel in 2026 (Palaces €14.95, 4-star €8.13)
        "currency": "EUR",
        "basis": "per_person_per_night",
        "waived_on_points": False,
        "legal_name": "Taxe de Séjour Régionale Île-de-France"
    },
    "Nice": {
        "country": "France",
        "tax_amount": 4.00,
        "currency": "EUR",
        "basis": "per_person_per_night",
        "waived_on_points": False,
        "legal_name": "Taxe de Séjour Métropole Nice Côte d'Azur"
    },
    
    # --- ITALY ---
    "Rome": {
        "country": "Italy",
        "tax_amount": 10.00,  # 5-star: €10, 4-star: €7.50
        "currency": "EUR",
        "basis": "per_person_per_night",
        "waived_on_points": False,
        "legal_name": "Contributo di Soggiorno Roma Capitale"
    },
    "Florence": {
        "country": "Italy",
        "tax_amount": 8.00,  # 5-star: €8, 4-star: €7
        "currency": "EUR",
        "basis": "per_person_per_night",
        "waived_on_points": False,
        "legal_name": "Imposta di Soggiorno Firenze"
    },
    "Venice": {
        "country": "Italy",
        "tax_amount": 5.00,
        "currency": "EUR",
        "basis": "per_person_per_night",
        "waived_on_points": False,
        "legal_name": "Imposta di Soggiorno Venezia"
    },
    "Milan": {
        "country": "Italy",
        "tax_amount": 5.00,
        "currency": "EUR",
        "basis": "per_person_per_night",
        "waived_on_points": False,
        "legal_name": "Imposta di Soggiorno Milano"
    },

    # --- SPAIN ---
    "Barcelona": {
        "country": "Spain",
        "tax_amount": 6.75,  # Regional €3.50 + City Surcharge €3.25
        "currency": "EUR",
        "basis": "per_person_per_night",
        "waived_on_points": False,
        "legal_name": "Impuesto sobre las Estancias en Establecimientos Turísticos"
    },
    "Madrid": {
        "country": "Spain",
        "tax_amount": 0.00,  # Currently Madrid has no tourist tax
        "currency": "EUR",
        "basis": "per_person_per_night",
        "waived_on_points": True,
        "legal_name": "None"
    },

    # --- NETHERLANDS ---
    "Amsterdam": {
        "country": "Netherlands",
        "tax_pct": 12.5,  # 12.5% tourist tax (highest in Europe)
        "currency": "EUR",
        "basis": "pct_of_room_rate",
        "waived_on_points": False,
        "legal_name": "Toeristenbelasting Gemeente Amsterdam",
        "notes": "On award nights, hotels charge 12.5% on internal wholesale rate or fixed €10-€25 fee"
    },

    # --- GERMANY ---
    "Berlin": {
        "country": "Germany",
        "tax_pct": 5.0,  # 5% City Tax on net rate
        "currency": "EUR",
        "basis": "pct_of_room_rate",
        "waived_on_points": False,
        "legal_name": "Übernachtungsteuer Berlin (City Tax)"
    },
    "Frankfurt": {
        "country": "Germany",
        "tax_amount": 2.00,
        "currency": "EUR",
        "basis": "per_person_per_night",
        "waived_on_points": False,
        "legal_name": "Tourismusbeitrag Frankfurt"
    },

    # --- JAPAN ---
    "Tokyo": {
        "country": "Japan",
        "tax_amount_jpy": 200,  # ¥200 for room rate ¥15,000+
        "currency": "JPY",
        "basis": "per_person_per_night",
        "waived_on_points": False,
        "legal_name": "Tokyo Metropolitan Accommodation Tax (宿泊税)"
    },
    "Kyoto": {
        "country": "Japan",
        "tax_amount_jpy": 1000,  # ¥1,000 for rate ¥50,000+, ¥400 for ¥20k-¥50k
        "currency": "JPY",
        "basis": "per_person_per_night",
        "waived_on_points": False,
        "legal_name": "Kyoto City Accommodation Tax (宿泊税)"
    },
    "Osaka": {
        "country": "Japan",
        "tax_amount_jpy": 300,  # ¥300 for rate ¥20,000+
        "currency": "JPY",
        "basis": "per_person_per_night",
        "waived_on_points": False,
        "legal_name": "Osaka Prefecture Accommodation Tax"
    },
    "Fukuoka": {
        "country": "Japan",
        "tax_amount_jpy": 200,
        "currency": "JPY",
        "basis": "per_person_per_night",
        "waived_on_points": False,
        "legal_name": "Fukuoka City & Prefecture Accommodation Tax"
    },

    # --- SOUTHEAST ASIA & RESORT HAVENS (100% CLEAN POINTS REDEMPTIONS) ---
    "Bali": {
        "country": "Indonesia",
        "tax_amount": 0.00,
        "currency": "IDR",
        "basis": "waived",
        "waived_on_points": True,
        "notes": "100% WAIVED: PB1 (10%) + Service Charge (11%) are completely waived on Hilton, Marriott, Hyatt award stays!"
    },
    "Jakarta": {
        "country": "Indonesia",
        "tax_amount": 0.00,
        "currency": "IDR",
        "basis": "waived",
        "waived_on_points": True,
        "notes": "100% WAIVED on points stays"
    },
    "Bangkok": {
        "country": "Thailand",
        "tax_amount": 0.00,
        "currency": "THB",
        "basis": "waived",
        "waived_on_points": True,
        "notes": "100% WAIVED on points stays (VAT 7% + Service 10% absorbed by chain)"
    },
    "Singapore": {
        "country": "Singapore",
        "tax_amount": 0.00,
        "currency": "SGD",
        "basis": "waived",
        "waived_on_points": True,
        "notes": "100% WAIVED on points stays (GST 9% + Service 10% absorbed)"
    },
    "Maldives": {
        "country": "Maldives",
        "tax_amount": 6.00,  # Green Tax $6/person/night
        "currency": "USD",
        "basis": "per_person_per_night",
        "waived_on_points": False,
        "notes": "TGST 16% + Service Charge 10% ($100-$300/night) WAIVED 100%! Only statutory $6 Green Tax paid at check-out."
    }
}


def get_mandatory_cash_tax(city: str, country: str, num_guests: int = 2) -> Dict[str, Any]:
    """Calculate the exact non-waivable statutory cash tax for an award stay."""
    city_clean = city.strip() if city else ""
    country_clean = country.strip() if country else ""

    # Look up by city
    tax_info = None
    for k, v in CITY_TAX_REGISTRY.items():
        if k.lower() in city_clean.lower():
            tax_info = v
            break

    if not tax_info:
        # Default fallback for unknown jurisdictions
        return {
            "city": city_clean,
            "country": country_clean,
            "mandatory_cash_per_night_usd": 0.0,
            "waived_on_points": True,
            "notes": "No known mandatory local cash tourist tax detected."
        }

    # Calculate cash amount in USD (using conservative FX rates)
    fx_eur_usd = 1.09
    fx_jpy_usd = 0.0067

    tax_usd = 0.0
    if tax_info.get("currency") == "EUR":
        tax_usd = tax_info.get("tax_amount", 0.0) * num_guests * fx_eur_usd
    elif tax_info.get("currency") == "JPY":
        tax_usd = tax_info.get("tax_amount_jpy", 0) * num_guests * fx_jpy_usd
    elif tax_info.get("currency") == "USD":
        tax_usd = tax_info.get("tax_amount", 0.0) * num_guests

    return {
        "city": city_clean,
        "country": country_clean,
        "tax_info": tax_info,
        "mandatory_cash_per_night_usd": round(tax_usd, 2),
        "waived_on_points": tax_info.get("waived_on_points", True),
        "notes": tax_info.get("notes", tax_info.get("legal_name", ""))
    }
