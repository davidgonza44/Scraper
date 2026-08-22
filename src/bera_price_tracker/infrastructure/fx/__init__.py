"""Exchange-rate adapters. No live FX client is wired."""

from bera_price_tracker.infrastructure.fx.stub import StubExchangeRateProvider

__all__ = ["StubExchangeRateProvider"]
