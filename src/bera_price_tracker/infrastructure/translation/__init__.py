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

__all__ = [
    "AzureProductTranslator",
    "AzureTranslatorHTTPError",
    "AzureTranslatorInvalidResponseError",
    "AzureTranslatorNotConfiguredError",
    "AzureTranslatorRateLimitError",
    "AzureTranslatorTimeoutError",
    "AzureTranslatorUnavailableError",
]
