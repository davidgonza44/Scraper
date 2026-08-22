"""Explicit composition root for command-line use cases."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from bera_price_tracker.application import (
    CollectionClock,
    CollectListings,
    DatabaseDiagnosticsRepository,
    DiagnoseEnvironment,
    DiagnosticReport,
    GetListingHistory,
    GetListingStatistics,
    HybridProductClassifier,
    InspectLatestCollection,
    MarketplaceProvider,
    SearchAlibabaProducts,
)
from bera_price_tracker.config import Settings
from bera_price_tracker.domain import (
    CollectionRunInspection,
    Listing,
    ListingHistory,
    ListingKey,
    ListingStatistics,
    MarketplaceSource,
    SearchQuery,
)
from bera_price_tracker.infrastructure.ai import OllamaAIProductClassifier
from bera_price_tracker.infrastructure.persistence import (
    SQLiteCollectionInspectionRepository,
    SQLiteDatabaseDiagnostics,
    SQLiteListingHistoryRepository,
    SQLiteListingRepository,
)
from bera_price_tracker.infrastructure.providers import (
    ApifyFacebookMarketplaceClient,
    BrightDataFacebookMarketplaceClient,
    FacebookCandidateExplanation,
    FacebookCollectionMetrics,
    FacebookMarketplaceProvider,
    MercadoLibreProvider,
)
from bera_price_tracker.infrastructure.providers.alibaba import ApifyAlibabaClient

_logger = logging.getLogger(__name__)

type ProviderFactory = Callable[[Settings], MarketplaceProvider]
type RepositoryFactory = Callable[[Settings], SQLiteListingRepository]
type HistoryRepositoryFactory = Callable[[Settings], SQLiteListingHistoryRepository]
type InspectionRepositoryFactory = Callable[[Settings], SQLiteCollectionInspectionRepository]
type DiagnosticsRepositoryFactory = Callable[[Settings], DatabaseDiagnosticsRepository]


def _mercado_libre_provider(settings: Settings) -> MarketplaceProvider:
    """Build the production provider without creating an HTTP client eagerly.

    Without an injected client, ``MercadoLibreProvider.search`` owns and closes its
    short-lived ``httpx.Client``. A custom factory that injects a client retains ownership
    of that client.
    """

    return MercadoLibreProvider(
        site_id=settings.mercadolibre_site_id,
        access_token=settings.mercadolibre_access_token,
        page_size=settings.mercadolibre_page_size,
        max_pages=settings.mercadolibre_max_pages,
        timeout_seconds=settings.mercadolibre_timeout_seconds,
        max_retries=settings.mercadolibre_max_retries,
    )


def _facebook_brightdata_provider(settings: Settings) -> MarketplaceProvider:
    """Build the legacy Bright Data Facebook provider without issuing requests."""

    client = BrightDataFacebookMarketplaceClient(
        api_token=settings.brightdata_api_token,
        base_url=settings.brightdata_base_url,
        dataset_id=settings.brightdata_dataset_id,
        request_timeout_seconds=settings.brightdata_timeout_seconds,
        poll_interval_seconds=settings.brightdata_poll_interval_seconds,
        poll_timeout_seconds=settings.brightdata_poll_timeout_seconds,
    )
    classifier = HybridProductClassifier(
        ai_classifier=OllamaAIProductClassifier(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout_seconds=settings.ollama_timeout_seconds,
        )
    )
    return FacebookMarketplaceProvider(
        client=client,
        classifier=classifier,
        city=settings.facebook_city,
        record_limit=settings.facebook_record_limit,
    )


def _facebook_marketplace_provider(settings: Settings) -> MarketplaceProvider:
    """Build the default Apify Facebook provider without issuing requests."""

    client = ApifyFacebookMarketplaceClient(api_token=settings.apify_api_token)
    classifier = HybridProductClassifier(
        ai_classifier=OllamaAIProductClassifier(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout_seconds=settings.ollama_timeout_seconds,
        )
    )
    return FacebookMarketplaceProvider(
        client=client,
        classifier=classifier,
        city=settings.facebook_city,
        record_limit=settings.facebook_record_limit,
    )


def _sqlite_repository(settings: Settings) -> SQLiteListingRepository:
    return SQLiteListingRepository(settings.database_path)


def _sqlite_history_repository(settings: Settings) -> SQLiteListingHistoryRepository:
    return SQLiteListingHistoryRepository(settings.database_path)


def _sqlite_inspection_repository(settings: Settings) -> SQLiteCollectionInspectionRepository:
    return SQLiteCollectionInspectionRepository(settings.database_path)


def _sqlite_diagnostics_repository(settings: Settings) -> DatabaseDiagnosticsRepository:
    return SQLiteDatabaseDiagnostics(settings.database_path)


@dataclass(frozen=True, slots=True)
class CollectionResult:
    """Human-facing summary data returned by the collection composition."""

    query: SearchQuery
    source: MarketplaceSource
    listing_count: int
    database_path: str
    metrics: FacebookCollectionMetrics | None = None
    explanations: tuple[FacebookCandidateExplanation, ...] = ()


@dataclass(slots=True)
class ApplicationComposition:
    """Construct and connect application services to concrete infrastructure."""

    settings: Settings
    provider_factory: ProviderFactory = _mercado_libre_provider
    repository_factory: RepositoryFactory = _sqlite_repository
    history_repository_factory: HistoryRepositoryFactory = _sqlite_history_repository
    inspection_repository_factory: InspectionRepositoryFactory = _sqlite_inspection_repository
    diagnostics_repository_factory: DiagnosticsRepositoryFactory = _sqlite_diagnostics_repository
    collection_clock: CollectionClock | None = None

    def search(self, query: SearchQuery) -> list[Listing]:
        """Execute the read-only search path without constructing persistence."""

        provider = self.provider_factory(self.settings)
        _logger.info(
            "command=search source=%s query=%r started",
            provider.source.value,
            query.text,
        )
        listings = provider.search(query)
        _logger.info(
            "command=search source=%s query=%r received=%d completed",
            provider.source.value,
            query.text,
            len(listings),
        )
        return listings

    def collect(self, query: SearchQuery) -> CollectionResult:
        """Collect and persist listings as one atomic batch.

        Constructing the provider first validates required marketplace configuration
        before SQLite can create a database.
        """

        provider = self.provider_factory(self.settings)
        _logger.info(
            "command=collect source=%s query=%r database=%s started",
            provider.source.value,
            query.text,
            self.settings.database_path,
        )
        with self.repository_factory(self.settings) as repository:
            if self.collection_clock is None:
                service = CollectListings(provider=provider, repository=repository)
            else:
                service = CollectListings(
                    provider=provider,
                    repository=repository,
                    clock=self.collection_clock,
                )
            listings = service.execute(query)

        _logger.info(
            "command=collect source=%s query=%r received=%d persisted=%d completed",
            provider.source.value,
            query.text,
            len(listings),
            len(listings),
        )
        return CollectionResult(
            query=query,
            source=provider.source,
            listing_count=len(listings),
            database_path=self.settings.database_path,
            metrics=(
                provider.last_metrics if isinstance(provider, FacebookMarketplaceProvider) else None
            ),
            explanations=(
                provider.last_explanations
                if isinstance(provider, FacebookMarketplaceProvider)
                else ()
            ),
        )

    def history(self, key: ListingKey) -> ListingHistory | None:
        """Read local SQLite history without constructing a marketplace provider."""

        _logger.info(
            "command=history source=%s external_id=%s database=%s started",
            key.source.value,
            key.external_id,
            self.settings.database_path,
        )
        with self.history_repository_factory(self.settings) as repository:
            history = GetListingHistory(repository=repository).execute(key)
        _logger.info(
            "command=history source=%s external_id=%s found=%s completed",
            key.source.value,
            key.external_id,
            history is not None,
        )
        return history

    def statistics(self, key: ListingKey) -> ListingStatistics | None:
        """Derive local statistics without constructing HTTP or write adapters."""

        _logger.info(
            "command=stats source=%s external_id=%s database=%s started",
            key.source.value,
            key.external_id,
            self.settings.database_path,
        )
        with self.history_repository_factory(self.settings) as repository:
            statistics = GetListingStatistics(repository=repository).execute(key)
        _logger.info(
            "command=stats source=%s external_id=%s found=%s completed",
            key.source.value,
            key.external_id,
            statistics is not None,
        )
        return statistics

    def inspect_latest_collection(
        self,
        source: MarketplaceSource,
        query: SearchQuery,
        *,
        limit: int,
    ) -> CollectionRunInspection | None:
        """Read the latest persisted batch without constructing HTTP or write adapters."""

        _logger.info(
            "command=inspect source=%s query=%r limit=%d database=%s started",
            source.value,
            query.text,
            limit,
            self.settings.database_path,
        )
        with self.inspection_repository_factory(self.settings) as repository:
            inspection = InspectLatestCollection(repository=repository).execute(
                source,
                query,
                limit=limit,
            )
        _logger.info(
            "command=inspect source=%s query=%r found=%s shown=%d completed",
            source.value,
            query.text,
            inspection is not None,
            0 if inspection is None else len(inspection.observations),
        )
        return inspection

    def doctor(self) -> DiagnosticReport:
        """Diagnose local readiness without constructing HTTP or write adapters."""

        _logger.info("command=doctor database=%s started", self.settings.database_path)
        repository = self.diagnostics_repository_factory(self.settings)
        report = DiagnoseEnvironment(repository=repository).execute(self.settings)
        _logger.info(
            "command=doctor python_compatible=%s marketplace_status=%s "
            "database_state=%s overall=%s completed",
            report.python_compatible,
            report.mercado_libre_status.value,
            report.database.state.value,
            report.overall.value,
        )
        return report


def build_composition(
    settings: Settings,
    *,
    provider_source: MarketplaceSource = MarketplaceSource.MERCADO_LIBRE,
    provider_factory: ProviderFactory | None = None,
    repository_factory: RepositoryFactory | None = None,
    history_repository_factory: HistoryRepositoryFactory | None = None,
    inspection_repository_factory: InspectionRepositoryFactory | None = None,
    diagnostics_repository_factory: DiagnosticsRepositoryFactory | None = None,
    collection_clock: CollectionClock | None = None,
) -> ApplicationComposition:
    """Build the dependency graph without opening HTTP or SQLite resources."""

    if not isinstance(provider_source, MarketplaceSource):
        raise TypeError("provider_source must be a MarketplaceSource")
    if provider_source is MarketplaceSource.FACEBOOK_MARKETPLACE:
        default_provider_factory = (
            _facebook_brightdata_provider
            if settings.facebook_backend == "brightdata"
            else _facebook_marketplace_provider
        )
    else:
        default_provider_factory = _mercado_libre_provider

    return ApplicationComposition(
        settings=settings,
        provider_factory=provider_factory or default_provider_factory,
        repository_factory=repository_factory or _sqlite_repository,
        history_repository_factory=(history_repository_factory or _sqlite_history_repository),
        inspection_repository_factory=(
            inspection_repository_factory or _sqlite_inspection_repository
        ),
        diagnostics_repository_factory=(
            diagnostics_repository_factory or _sqlite_diagnostics_repository
        ),
        collection_clock=collection_clock,
    )


def build_alibaba_search(settings: Settings | None = None) -> SearchAlibabaProducts:
    """Wire SearchAlibabaProducts to Apify without opening a run."""

    resolved = Settings.from_env() if settings is None else settings
    client = ApifyAlibabaClient(
        _api_token=resolved.apify_api_token,
        actor_id=resolved.apify_alibaba_actor,
    )
    return SearchAlibabaProducts(provider=client)
