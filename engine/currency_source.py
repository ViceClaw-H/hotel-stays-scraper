# -*- coding: utf-8 -*-
"""Currency taken FROM the source text, never assumed.

`currency_from_text("IDR 1,318,750")` -> "IDR"; `"€66"` -> "EUR"; `"$66"` -> None (a bare "$" is USD, SGD, AUD ... - ambiguous).
A caller that gets None must SKIP the price (and count it) instead of falling back to a default currency.
"""
import re
from typing import Optional

ISO = {
    "IDR", "USD", "EUR", "GBP", "SGD", "JPY", "CNY", "MYR", "THB", "AUD", "CAD", "HKD", "KRW", "CHF", "INR", "VND", "AED", "SAR",
    "QAR", "TWD", "NZD", "MXN", "BRL", "ZAR", "PHP", "TRY", "SEK", "NOK", "DKK", "PLN", "CZK", "HUF", "ILS", "KWD", "BHD", "OMR",
    "EGP", "MAD", "XOF", "XAF", "XPF", "MUR", "LKR", "NPR", "BDT", "PKR", "KHR", "LAK", "MMK", "MNT", "RUB", "UAH", "KZT", "JOD",
    "AZN", "ARS", "CLP", "COP", "PEN", "UYU", "DOP", "CRC", "KES", "TZS", "NGN", "GHS", "MVR", "BND", "RON", "BGN", "ISK", "HRK",
}
# unambiguous symbols / prefixes (longest first matters, handled by ordering)
SYMBOLS = [
    ("US$", "USD"), ("S$", "SGD"), ("A$", "AUD"), ("NZ$", "NZD"), ("HK$", "HKD"), ("C$", "CAD"), ("R$", "BRL"), ("NT$", "TWD"),
    ("Rp", "IDR"), ("RM", "MYR"), ("€", "EUR"), ("£", "GBP"), ("฿", "THB"), ("₫", "VND"), ("₩", "KRW"), ("₹", "INR"),
    ("₺", "TRY"), ("₱", "PHP"), ("zł", "PLN"), ("Kč", "CZK"),
]


def is_iso(code: Optional[str]) -> bool:
    return isinstance(code, str) and bool(re.fullmatch(r"[A-Z]{3}", code)) and code in ISO


def currency_from_text(text: Optional[str]) -> Optional[str]:
    if not text or not isinstance(text, str):
        return None
    t = text.replace("\xa0", " ")
    found = {m for m in re.findall(r"(?<![A-Za-z])([A-Z]{3})(?![A-Za-z])", t) if m in ISO}
    if len(found) == 1:
        return next(iter(found))
    if len(found) > 1:
        return None
    for sym, code in SYMBOLS:
        if sym in t:
            return code
    return None
