"""Translation infrastructure adapters."""

from bera_price_tracker.infrastructure.translation.azure import (
    AzureProductTranslator,
    AzureTranslatorHTTPError,
    AzureTranslatorInvalidResponseError,
    AzureTranslatorNotConfiguredError,
    AzureTranslatorRateLimitError,
    AzureTranslatorTimeoutError,
    AzureTranslatorUnavailableError,
)
from bera_price_tracker.infrastructure.translation.deepl import (
    DeepLProductTranslator,
    DeepLTranslatorHTTPError,
    DeepLTranslatorInvalidResponseError,
    DeepLTranslatorNotConfiguredError,
    DeepLTranslatorQuotaError,
    DeepLTranslatorRateLimitError,
    DeepLTranslatorTimeoutError,
    DeepLTranslatorUnavailableError,
)
from bera_price_tracker.infrastructure.translation.disabled import (
    DisabledProductTranslator,
    DisabledTranslatorNotConfiguredError,
)

__all__ = [
    "AzureProductTranslator",
    "AzureTranslatorHTTPError",
    "AzureTranslatorInvalidResponseError",
    "AzureTranslatorNotConfiguredError",
    "AzureTranslatorRateLimitError",
    "AzureTranslatorTimeoutError",
    "AzureTranslatorUnavailableError",
    "DeepLProductTranslator",
    "DeepLTranslatorHTTPError",
    "DeepLTranslatorInvalidResponseError",
    "DeepLTranslatorNotConfiguredError",
    "DeepLTranslatorQuotaError",
    "DeepLTranslatorRateLimitError",
    "DeepLTranslatorTimeoutError",
    "DeepLTranslatorUnavailableError",
    "DisabledProductTranslator",
    "DisabledTranslatorNotConfiguredError",
]
