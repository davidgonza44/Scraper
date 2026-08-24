"""Explicitly disabled product translator. Never performs HTTP."""

from __future__ import annotations

from bera_price_tracker.application.ports import ProductTranslatorNotConfiguredError
from bera_price_tracker.application.product_translation import (
    DISABLED_TRANSLATOR_PROVIDER,
    ProductTranslationRequest,
    ProductTranslationResult,
    require_non_empty_product_text,
)

_DISABLED_MESSAGE = (
    "Product translation is disabled. Set BERA_TRACKER_TRANSLATOR_PROVIDER to deepl or azure."
)


class DisabledTranslatorNotConfiguredError(ProductTranslatorNotConfiguredError):
    """Raised when translation is explicitly or implicitly disabled."""


class DisabledProductTranslator:
    """Fail closed without calling DeepL or Azure."""

    provider = DISABLED_TRANSLATOR_PROVIDER

    def __repr__(self) -> str:
        return "DisabledProductTranslator(configured=False)"

    @property
    def is_configured(self) -> bool:
        return False

    def translate(self, request: ProductTranslationRequest) -> ProductTranslationResult:
        if not isinstance(request, ProductTranslationRequest):
            raise TypeError("request must be a ProductTranslationRequest")
        require_non_empty_product_text(request.text)
        raise DisabledTranslatorNotConfiguredError(_DISABLED_MESSAGE)
