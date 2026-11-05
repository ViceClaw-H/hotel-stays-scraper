"""Official Hotel Tax & Service Charge Registry per Country.
Maps country names to their exact gross multiplier (Net Room Rate * Tax Multiplier = Total Gross Cash Cost at Checkout).
"""

# Exact Tax & Service Multipliers by Country
# For countries where VAT/GST is legally already included in quoted rates (e.g. UK, France, Australia, EU), multiplier is 1.0 (or net VAT rate if stripping/adding)
# For countries quoted ++ (net of tax & service charge at quotation time):
COUNTRY_TAX_REGISTRY = {
    # Southeast Asia (Quoted Net ++)
    "Indonesia": {
        "tax_pct": 10.0,        # PB1 Pajak Daerah
        "service_pct": 11.0,    # Service charge
        "gross_multiplier": 1.21, # Total 21.0% (1.10 * 1.10 = 1.21)
        "tax_name": "Pajak Daerah PB1 (10%) + Service Charge (11%)"
    },
    "Singapore": {
        "tax_pct": 9.0,         # GST 9%
        "service_pct": 10.0,    # Service charge 10%
        "gross_multiplier": 1.199, # 19.9% (1.09 * 1.10)
        "tax_name": "GST (9%) + Service Charge (10%)"
    },
    "Thailand": {
        "tax_pct": 7.0,         # VAT 7% + 1% Local
        "service_pct": 10.0,    # Service charge 10%
        "gross_multiplier": 1.187, # Total 18.7%
        "tax_name": "VAT (7%) + Service Charge (10%) + Provincial Tax"
    },
    "Malaysia": {
        "tax_pct": 8.0,         # SST 8%
        "service_pct": 10.0,    # Service charge 10%
        "gross_multiplier": 1.188, # Total 18.8%
        "tax_name": "SST (8%) + Service Charge (10%)"
    },
    "Vietnam": {
        "tax_pct": 8.0,         # VAT 8%
        "service_pct": 5.0,     # Service charge 5%
        "gross_multiplier": 1.134, # Total 13.4%
        "tax_name": "VAT (8%) + Service Charge (5%)"
    },
    "Philippines": {
        "tax_pct": 12.0,        # VAT 12% + Local Tax 0.75%
        "service_pct": 10.0,    # Service charge 10%
        "gross_multiplier": 1.2275, # Total 22.75%
        "tax_name": "VAT (12%) + Service Charge (10%) + Local Tax"
    },
    # East Asia
    "Japan": {
        "tax_pct": 10.0,        # Consumption Tax 10%
        "service_pct": 10.0,    # Hotel Service Charge 10-15%
        "gross_multiplier": 1.21, # Total 21.0%
        "tax_name": "Consumption Tax (10%) + Service Charge (10%) + Accommodation Tax"
    },
    "South Korea": {
        "tax_pct": 10.0,        # VAT 10%
        "service_pct": 10.0,    # Service Charge 10%
        "gross_multiplier": 1.21, # Total 21.0%
        "tax_name": "VAT (10%) + Service Charge (10%)"
    },
    "China": {
        "tax_pct": 6.0,         # VAT 6%
        "service_pct": 10.0,    # Service Charge 10%
        "gross_multiplier": 1.166, # Total 16.6%
        "tax_name": "VAT (6%) + Surcharge (10%)"
    },
    "Hong Kong": {
        "tax_pct": 3.0,         # Hotel Accommodation Tax (HAT 3%)
        "service_pct": 10.0,    # Service Charge 10%
        "gross_multiplier": 1.13, # Total 13.0%
        "tax_name": "Service Charge (10%) + HAT (3%)"
    },
    # Middle East
    "United Arab Emirates": {
        "tax_pct": 12.0,        # 5% VAT + 7% Municipality Fee
        "service_pct": 10.0,    # Service Charge 10%
        "gross_multiplier": 1.232, # Total 23.2%
        "tax_name": "VAT (5%) + Municipality Fee (7%) + Service Charge (10%)"
    },
    "Saudi Arabia": {
        "tax_pct": 15.0,        # VAT 15%
        "service_pct": 5.0,     # Municipality Fee 5%
        "gross_multiplier": 1.20, # Total 20.0%
        "tax_name": "VAT (15%) + Municipality Tax (5%)"
    },
    "Qatar": {
        "tax_pct": 0.0,
        "service_pct": 10.0,    # Service Charge 10%
        "gross_multiplier": 1.10, # Total 10.0%
        "tax_name": "Service Charge (10%)"
    },
    # North & South America
    "United States": {
        "tax_pct": 15.5,        # Average State + City Occupancy Tax
        "service_pct": 0.0,
        "gross_multiplier": 1.155, # Total 15.5%
        "tax_name": "State & City Occupancy Tax (15.5%)"
    },
    "Canada": {
        "tax_pct": 13.0,        # HST/GST + MAT (Municipal Accommodation Tax)
        "service_pct": 0.0,
        "gross_multiplier": 1.13, # Total 13.0%
        "tax_name": "GST/HST + Municipal Tax (13%)"
    },
    "Mexico": {
        "tax_pct": 16.0,        # IVA 16% + ISH Lodging Tax 3-5%
        "service_pct": 0.0,
        "gross_multiplier": 1.20, # Total 20.0%
        "tax_name": "IVA (16%) + Lodging Tax ISH (4%)"
    },
    "Brazil": {
        "tax_pct": 5.0,         # ISS 5%
        "service_pct": 10.0,    # Service Charge 10%
        "gross_multiplier": 1.15, # Total 15.0%
        "tax_name": "ISS Tax (5%) + Service Charge (10%)"
    },
    # Europe & Pacific (Quoted Gross Inclusive in EU/UK/AU)
    "United Kingdom": {
        "tax_pct": 20.0,
        "service_pct": 0.0,
        "gross_multiplier": 1.0, # Quoted Inclusive of 20% VAT in UK
        "tax_name": "VAT 20% (Included in Quoted Rate)"
    },
    "France": {
        "tax_pct": 10.0,
        "service_pct": 0.0,
        "gross_multiplier": 1.0, # Quoted Inclusive of 10% VAT
        "tax_name": "VAT 10% (Included in Quoted Rate)"
    },
    "Germany": {
        "tax_pct": 7.0,
        "service_pct": 0.0,
        "gross_multiplier": 1.0, # Quoted Inclusive of 7% VAT
        "tax_name": "VAT 7% (Included in Quoted Rate)"
    },
    "Australia": {
        "tax_pct": 10.0,
        "service_pct": 0.0,
        "gross_multiplier": 1.0, # Quoted Inclusive of 10% GST
        "tax_name": "GST 10% (Included in Quoted Rate)"
    }
}

DEFAULT_TAX = {
    "tax_pct": 10.0,
    "service_pct": 0.0,
    "gross_multiplier": 1.10,
    "tax_name": "Standard Hospitality Tax (10%)"
}

def get_country_tax(country_name: str) -> dict:
    return COUNTRY_TAX_REGISTRY.get(country_name, DEFAULT_TAX)

def calculate_gross_cash_rate(net_cash: float, country_name: str) -> float:
    if net_cash is None:
        return None
    tax_info = get_country_tax(country_name)
    return round(net_cash * tax_info["gross_multiplier"], 2)
