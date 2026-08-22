"""Monetary helpers and USD normalization results.

Domain code never fetches exchange rates. A rate, if present, is injected.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum

MONEY_QUANTUM = Decimal("0.01")
FACEBOOK_VENEZUELA_EVIDENCE = "facebook_venezuela_price_semantics"
UNSUPPORTED_CURRENCY_EVIDENCE = "unsupported_currency_semantics"
DOLLAR_SYMBOL_EVIDENCE = "dollar_symbol"


class NormalizationStatus(StrEnum):
    """Outcome of attempting to present a price in USD."""

    NORMALIZED = "normalized"
    ALREADY_USD = "already_usd"
    DOLLAR_SYMBOL = "dollar_symbol"
    UNSUPPORTED_CURRENCY = "unsupported_currency"
    MISSING_RATE = "missing_rate"
    INVALID = "invalid"


def quantize_money(value: Decimal) -> Decimal:
    """Round a finite Decimal to two monetary places (banker's rounding)."""

    if not isinstance(value, Decimal):
        raise TypeError("amount must be a Decimal")
    if not value.is_finite():
        raise ValueError("amount must be finite")
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)


def format_usd_display(amount: Decimal) -> str:
    """Return a display string ``$X.XX`` for a USD amount."""

    quantized = quantize_money(amount)
    return f"${quantized:.2f}"


def format_usd_line(amount: Decimal | None) -> str:
    """Preferred CLI/GUI USD line."""

    if amount is None:
        return "USD: unavailable"
    return f"USD: {format_usd_display(amount)}"


@dataclass(frozen=True, slots=True, kw_only=True)
class ExchangeRate:
    """Quote units per one unit of base. Never hard-coded by domain logic."""

    rate: Decimal
    source: str
    observed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.rate, Decimal):
            raise TypeError("rate must be a Decimal")
        if not self.rate.is_finite() or self.rate <= Decimal("0"):
            raise ValueError("rate must be a finite positive Decimal")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source must not be blank")
        if not isinstance(self.observed_at, datetime):
            raise TypeError("observed_at must be a datetime")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        object.__setattr__(self, "source", self.source.strip())
        object.__setattr__(self, "observed_at", self.observed_at.astimezone(UTC))
        object.__setattr__(self, "rate", self.rate)


@dataclass(frozen=True, slots=True, kw_only=True)
class NormalizedPrice:
    """Source money plus optional USD presentation. Originals are never rewritten."""

    original_amount: Decimal
    original_currency: str
    original_formatted: str | None
    usd_amount: Decimal | None
    normalization_status: NormalizationStatus
    evidence: tuple[str, ...]
    usd_exchange_rate: Decimal | None = None
    usd_exchange_rate_source: str | None = None
    usd_exchange_rate_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.original_amount, Decimal):
            raise TypeError("original_amount must be a Decimal")
        if not isinstance(self.normalization_status, NormalizationStatus):
            raise TypeError("normalization_status must be a NormalizationStatus")
        object.__setattr__(self, "evidence", tuple(self.evidence))
        if self.usd_amount is not None:
            object.__setattr__(self, "usd_amount", quantize_money(self.usd_amount))
