"""The one registry for hotel-chain eligibility rules.

This module deliberately contains policy, not scraping code.  Each booking engine still has its
own crawler; its crawler reports observed facts and the location writer applies this registry.
Changing a chain's treatment is therefore a reviewed code/configuration change, not an ad-hoc
decision inside a scraper.
"""
from dataclasses import dataclass
from enum import StrEnum
from typing import Dict


class LocationScope(StrEnum):
    """What makes a hotel part of the product's usable location universe."""

    REDEMPTION_REQUIRED = "REDEMPTION_REQUIRED"
    BOOKABLE_ONLY = "BOOKABLE_ONLY"


@dataclass(frozen=True)
class ChainPolicy:
    chain: str
    location_scope: LocationScope
    rationale: str


# This is the canonical registry.  `engine.schema.ensure_location_schema` mirrors these rows into
# SQLite only so database triggers can reject direct-SQL bypasses too.
CHAIN_POLICIES: Dict[str, ChainPolicy] = {
    "ACCOR": ChainPolicy("ACCOR", LocationScope.BOOKABLE_ONLY,
                         "No observed full-points award-room product; include cash-bookable hotels."),
    "GHA": ChainPolicy("GHA", LocationScope.BOOKABLE_ONLY,
                       "Treat as cash-bookable until an official full award-room product is observed."),
    "HILTON": ChainPolicy("HILTON", LocationScope.REDEMPTION_REQUIRED,
                          "Include only hotels with an observed full-points award room."),
    "HYATT": ChainPolicy("HYATT", LocationScope.REDEMPTION_REQUIRED,
                         "Include only hotels with an observed full-points award room."),
    "IHG": ChainPolicy("IHG", LocationScope.REDEMPTION_REQUIRED,
                       "Include only hotels with an observed full-points award room."),
    "JEN": ChainPolicy("JEN", LocationScope.BOOKABLE_ONLY,
                        "Shangri-La family cash-bookable policy."),
    "LANGHAM": ChainPolicy("LANGHAM", LocationScope.REDEMPTION_REQUIRED,
                           "Full Award Point Reward Stays qualify; Points + Cash never qualifies."),
    "MARRIOTT": ChainPolicy("MARRIOTT", LocationScope.REDEMPTION_REQUIRED,
                            "Include only hotels with an observed full-points award room."),
    "SHANGRI-LA": ChainPolicy("SHANGRI-LA", LocationScope.BOOKABLE_ONLY,
                               "Cash-bookable policy unless an official full award-room product is observed."),
    "TRADERS": ChainPolicy("TRADERS", LocationScope.BOOKABLE_ONLY,
                            "Shangri-La family cash-bookable policy."),
    "WYNDHAM": ChainPolicy("WYNDHAM", LocationScope.REDEMPTION_REQUIRED,
                           "Include only hotels with an observed full-points award room."),
}


def policy_for(chain: str) -> ChainPolicy:
    """Return a policy or fail closed: an unregistered chain cannot be ingested."""
    try:
        return CHAIN_POLICIES[chain.strip().upper()]
    except (AttributeError, KeyError) as exc:
        raise ValueError(f"No chain policy registered for {chain!r}; location ingestion is refused.") from exc


def is_cash_plus_points(offer_kind: str | None) -> bool:
    """Recognize hybrid offers so chain parsers can discard them before rate ingestion."""
    return (offer_kind or "").strip().upper().replace(" ", "_") in {
        "CASH_PLUS_POINTS", "POINTS_PLUS_CASH", "CASH_AND_POINTS", "HYBRID"
    }
