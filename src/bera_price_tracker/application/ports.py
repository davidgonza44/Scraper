"""Application ports implemented by infrastructure adapters."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from bera_price_tracker.domain import (
    CollectionBatch,
    CollectionRunInspection,
    ExchangeRate,
    Listing,
    ListingHistory,
    ListingKey,
    MarketplaceSource,
    SearchQuery,
)

if TYPE_CHECKING:
    from bera_price_tracker.application.classification import (
        AIClassification,
        SanitizedProductCandidate,
    )
    from bera_price_tracker.application.product_translation import (
        ProductTranslationRequest,
        ProductTranslationResult,
    )
    from bera_price_tracker.domain.alibaba import AlibabaProduct
    from bera_price_tracker.domain.mercadolibre import MercadoLibreListing


class ProviderNotConfiguredError(RuntimeError):
    """Raised when a provider adapter has not been configured yet."""


class MarketplaceSourceUnavailable(RuntimeError):
    """Raised when a marketplace source cannot produce a collection batch."""


class AIClassifierUnavailableError(RuntimeError):
    """Raised by an AI adapter when it cannot produce a classification."""


class AIClassifierInvalidResponseError(RuntimeError):
    """Raised by an AI adapter when provider output cannot satisfy the contract."""


class AlibabaNegotiationDraftUnavailableError(RuntimeError):
    """Raised when MiniMax/Ollama cannot produce a negotiation draft."""


class AlibabaNegotiationDraftInvalidError(RuntimeError):
    """Raised when MiniMax/Ollama output cannot satisfy the negotiation contract."""


class ProductTranslatorNotConfiguredError(ProviderNotConfiguredError):
    """Raised when the product translator adapter has no local configuration."""


class ProductTranslatorUnavailableError(RuntimeError):
    """Raised when a translator adapter cannot complete a request."""


class ProductTranslatorTimeoutError(ProductTranslatorUnavailableError):
    """Raised when a translator request exceeds its configured timeout."""


class ProductTranslatorHTTPError(ProductTranslatorUnavailableError):
    """Raised for a non-success translator HTTP status."""

    def __init__(self, status_code: int, message: str | None = None) -> None:
        self.status_code = status_code
        super().__init__(message or f"Product translator request failed with HTTP {status_code}")


class ProductTranslatorRateLimitError(ProductTranslatorHTTPError):
    """Raised when the translator rejects the request as rate-limited."""

    def __init__(self, status_code: int = 429) -> None:
        super().__init__(status_code, "Product translator rate limit was reached")


class ProductTranslatorQuotaError(ProductTranslatorHTTPError):
    """Raised when the translator rejects the request as over quota."""

    def __init__(self, status_code: int = 456) -> None:
        super().__init__(status_code, "Product translator quota was exceeded")


class ProductTranslatorInvalidResponseError(RuntimeError):
    """Raised when translator output cannot satisfy the translation contract."""


class ProductTranslationEmptyTextError(ValueError):
    """Raised when the source product text is empty and must not be translated."""


@runtime_checkable
class AIProductClassifier(Protocol):
    """Provider-neutral boundary for structured AI product classification."""

    def classify(self, candidate: SanitizedProductCandidate) -> AIClassification:
        """Classify sanitized, explicitly untrusted marketplace data."""

        ...


@runtime_checkable
class AlibabaSearchProvider(Protocol):
    """Read-only Alibaba search. Implementations must not persist."""

    def search(self, query: str, limit: int) -> list[AlibabaProduct]:
        """Return mapped Alibaba products for one query."""

        ...


@runtime_checkable
class MercadoLibreSearchProvider(Protocol):
    """Read-only Mercado Libre Venezuela search. Implementations must not persist."""

    def search(self, query: str, limit: int) -> list[MercadoLibreListing]:
        """Return mapped Mercado Libre listings for one query."""

        ...


@runtime_checkable
class AlibabaProductRefreshProvider(Protocol):
    """Product-detail refresh. Must not reuse keyword search."""

    def refresh_products(self, products: Sequence[Any]) -> Any:
        """Refresh the given tracked products in one batch."""

        ...


@runtime_checkable
class ProductTranslator(Protocol):
    """Provider-neutral product-text translation. Must not touch money fields."""

    def translate(self, request: ProductTranslationRequest) -> ProductTranslationResult:
        """Translate one product text. Implementations must not infer currency."""

        ...


@runtime_checkable
class ProductSearchQueryGenerator(Protocol):
    """Derive an editable commercial search query from a translation."""

    def generate(self, *, original_text: str, translated_text: str) -> str:
        """Return a conservative query. Must not invent attributes or prices."""

        ...


@runtime_checkable
class AlibabaNegotiationDrafter(Protocol):
    """MiniMax drafts and summaries. Must not invent or change prices."""

    def draft_opening(self, context: Any) -> str:
        """Draft the first supplier-facing message."""

        ...

    def analyze_reply(self, context: Any, supplier_text: str) -> Any:
        """Summarize a pasted supplier reply without inventing numbers."""

        ...

    def draft_counter(self, context: Any) -> str:
        """Draft the next message using the authorized counter price."""

        ...


@runtime_checkable
class MarketplaceProvider(Protocol):
    """Search contract for any marketplace source."""

    @property
    def source(self) -> MarketplaceSource:
        """Return the marketplace represented by the adapter."""

        ...

    def search(self, query: SearchQuery) -> list[Listing]:
        """Return normalized listings matching ``query``."""

        ...


@runtime_checkable
class ListingRepository(Protocol):
    """Persistence boundary for complete marketplace collection batches."""

    def record_collection(self, batch: CollectionBatch) -> None:
        """Persist one collection run and all its observations atomically."""

        ...


@runtime_checkable
class ListingHistoryRepository(Protocol):
    """Read-only boundary for one listing's current metadata and price history."""

    def get_history(self, key: ListingKey) -> ListingHistory | None:
        """Return history for ``key`` or ``None`` when the listing is unknown."""

        ...


@runtime_checkable
class CollectionInspectionRepository(Protocol):
    """Read-only boundary for inspecting the latest persisted collection run."""

    def get_latest_run(
        self,
        source: MarketplaceSource,
        query: SearchQuery,
        limit: int,
    ) -> CollectionRunInspection | None:
        """Return the latest run for ``source`` and ``query``, if one exists."""

        ...


@runtime_checkable
class ExchangeRateProvider(Protocol):
    """Infrastructure boundary for a quote-per-base exchange rate.

    Implementations must not be called from domain code. A missing or fake
    adapter is valid; this protocol never implies a live FX HTTP client.
    """

    def get_rate(self, base: str = "USD", quote: str = "VES") -> ExchangeRate:
        """Return ``quote`` units per one unit of ``base``."""

        ...
