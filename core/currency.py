"""
All Hotel Stays - Core Currency & FX Engine
Standardized Dual-Currency Converter conforming to Antigravity Master SOP:
"100 USD (Rp 1.817.700)" format, preserving raw currency while converting to IDR.
"""

import json
import os
import urllib.request
import re
from typing import Dict, Tuple, Optional

class CurrencyEngine:
    def __init__(self, base_dir: str = None):
        if base_dir is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.base_dir = base_dir
        self.fx_rates_path = os.path.join(base_dir, "live_fx_rates_usd.json")
        self.rates: Dict[str, float] = self._load_fx_rates()

    def _load_fx_rates(self) -> Dict[str, float]:
        if os.path.exists(self.fx_rates_path):
            try:
                with open(self.fx_rates_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        # Fallback benchmark rates if file unreadable
        return {
            "USD": 1.0,
            "IDR": 17924.0,
            "EUR": 0.895,
            "SGD": 1.28,
            "JPY": 158.5,
            "THB": 33.6,
            "GBP": 0.756
        }

    def convert_to_idr(self, amount: float, from_currency: str) -> float:
        from_currency = from_currency.upper().strip()
        if from_currency == "IDR":
            return float(amount)
        
        idr_per_usd = self.rates.get("IDR", 17924.0)
        from_rate = self.rates.get(from_currency)
        if not from_rate or from_rate <= 0:
            return float(amount)
        
        # rates are relative to 1 USD
        usd_amount = float(amount) / from_rate
        return usd_amount * idr_per_usd

    def format_dual_currency(self, amount: float, currency: str) -> str:
        """
        SOP Antigravity Format:
        [Amount] [Currency] (Rp [Converted IDR])
        Example: "100 USD (Rp 1.817.700)" or "15.000 JPY (Rp 1.710.000)"
        """
        currency = currency.upper().strip()
        if currency == "IDR":
            return f"Rp {int(amount):,}".replace(",", ".")
        
        idr_val = self.convert_to_idr(amount, currency)
        formatted_idr = f"Rp {int(round(idr_val)):,}".replace(",", ".")
        
        if amount == int(amount):
            amt_str = f"{int(amount):,}".replace(",", ".")
        else:
            amt_str = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            
        return f"{amt_str} {currency} ({formatted_idr})"

# Singleton helper
_default_engine = None

def get_currency_engine() -> CurrencyEngine:
    global _default_engine
    if _default_engine is None:
        _default_engine = CurrencyEngine()
    return _default_engine

def format_dual(amount: float, currency: str) -> str:
    return get_currency_engine().format_dual_currency(amount, currency)
