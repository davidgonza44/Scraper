"""In-memory exchange-rate stub for tests. No HTTP."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from bera_price_tracker.domain import ExchangeRate


class StubExchangeRateProvider:
    """Return a caller-supplied rate. Never contacts a network."""

    def __init__(
        self,
        rate: Decimal,
        *,
        source: str = "stub",
        observed_at: datetime | None = None,
    ) -> None:
        if not isinstance(rate, Decimal):
            raise TypeError("rate must be a Decimal")
        self._rate = rate
        self._source = source
        self._observed_at = observed_at or datetime(2026, 8, 22, 12, 0, tzinfo=UTC)

    def get_rate(self, base: str = "USD", quote: str = "VES") -> ExchangeRate:
        if base != "USD" or quote != "VES":
            raise ValueError("stub only supports USD/VES")
        return ExchangeRate(rate=self._rate, source=self._source, observed_at=self._observed_at)
