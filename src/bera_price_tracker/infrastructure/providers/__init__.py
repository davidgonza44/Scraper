"""Marketplace provider adapters."""

from bera_price_tracker.infrastructure.providers.apify import (
    ApifyConfigurationError,
    ApifyFacebookMarketplaceClient,
)
from bera_price_tracker.infrastructure.providers.bright_data import (
    BrightDataConfigurationError,
    BrightDataConnectionError,
    BrightDataError,
    BrightDataFacebookMarketplaceClient,
    BrightDataHTTPError,
    BrightDataPollingTimeoutError,
    BrightDataResponseError,
    BrightDataTimeoutError,
)
from bera_price_tracker.infrastructure.providers.facebook_marketplace import (
    FacebookCandidateExplanation,
    FacebookCandidateOutcome,
    FacebookCollectionMetrics,
    FacebookMarketplaceProvider,
)
from bera_price_tracker.infrastructure.providers.mercado_libre import MercadoLibreProvider
from bera_price_tracker.infrastructure.providers.mercado_libre_errors import (
    MercadoLibreAuthenticationError,
    MercadoLibreConfigurationError,
    MercadoLibreConnectionError,
    MercadoLibreError,
    MercadoLibreHTTPError,
    MercadoLibreInvalidJSONError,
    MercadoLibreInvalidResponseError,
    MercadoLibreRateLimitError,
    MercadoLibreResponseError,
)

__all__ = [
    "ApifyConfigurationError",
    "ApifyFacebookMarketplaceClient",
    "BrightDataConfigurationError",
    "BrightDataConnectionError",
    "BrightDataError",
    "BrightDataFacebookMarketplaceClient",
    "BrightDataHTTPError",
    "BrightDataPollingTimeoutError",
    "BrightDataResponseError",
    "BrightDataTimeoutError",
    "FacebookCandidateExplanation",
    "FacebookCandidateOutcome",
    "FacebookCollectionMetrics",
    "FacebookMarketplaceProvider",
    "MercadoLibreAuthenticationError",
    "MercadoLibreConfigurationError",
    "MercadoLibreConnectionError",
    "MercadoLibreError",
    "MercadoLibreHTTPError",
    "MercadoLibreInvalidJSONError",
    "MercadoLibreInvalidResponseError",
    "MercadoLibreProvider",
    "MercadoLibreRateLimitError",
    "MercadoLibreResponseError",
]
