"""Explicit composition root for command-line use cases."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bera_price_tracker.application import (
    AlibabaFollowObservation,
    AlibabaNegotiationDrafter,
    AlibabaProductRefreshProvider,
    AlibabaRefreshSummary,
    AlibabaTrackedProduct,
    CollectionClock,
    CollectListings,
    DatabaseDiagnosticsRepository,
    DiagnoseEnvironment,
    DiagnosticReport,
    FollowAlibabaPrice,
    GetListingHistory,
    GetListingStatistics,
    HybridProductClassifier,
    InspectLatestCollection,
    ListAlibabaTracked,
    MarketplaceProvider,
    RecordAlibabaPriceSnapshot,
    RefreshTrackedAlibabaProducts,
    SearchAlibabaProducts,
    SearchMercadoLibreProducts,
    TranslateProductTitle,
    UnfollowAlibabaPrice,
)
from bera_price_tracker.application.ports import ProductTranslator
from bera_price_tracker.config import (
    TRANSLATOR_PROVIDER_AZURE,
    TRANSLATOR_PROVIDER_DEEPL,
    Settings,
    resolve_process_settings,
)
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
from bera_price_tracker.infrastructure.providers.alibaba_refresh import (
    ApifyAlibabaProductRefreshClient,
)
from bera_price_tracker.infrastructure.providers.mercadolibre_apify import ApifyMercadoLibreClient
from bera_price_tracker.infrastructure.translation import (
    AzureProductTranslator,
    DeepLProductTranslator,
    DisabledProductTranslator,
)

if TYPE_CHECKING:
    import httpx

    from bera_price_tracker.application.product_translation import InMemoryProductTranslationCache

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


def _alibaba_refresh_provider(settings: Settings) -> AlibabaProductRefreshProvider:
    return ApifyAlibabaProductRefreshClient(
        _api_token=settings.apify_api_token,
        actor_id=settings.apify_alibaba_refresh_actor,
        max_request_retries=settings.apify_alibaba_refresh_retries,
        max_concurrency=settings.apify_alibaba_refresh_concurrency,
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

    def follow_alibaba_price(
        self,
        observation: AlibabaFollowObservation,
        *,
        clock: CollectionClock | None = None,
    ) -> AlibabaTrackedProduct:
        """Persist one already-loaded Alibaba product. No marketplace HTTP."""

        _logger.info(
            "command=follow_alibaba product_id=%s database=%s started",
            observation.product_id,
            self.settings.database_path,
        )
        with self.repository_factory(self.settings) as repository:
            service = FollowAlibabaPrice(
                repository=repository,
                clock=clock or self.collection_clock or (lambda: datetime.now(UTC)),
            )
            tracked = service.execute(observation)
        _logger.info(
            "command=follow_alibaba product_id=%s snapshots=%d completed",
            tracked.product_id,
            tracked.variation.snapshot_count,
        )
        return tracked

    def record_alibaba_price_snapshot(
        self,
        observation: AlibabaFollowObservation,
        *,
        clock: CollectionClock | None = None,
    ) -> AlibabaTrackedProduct:
        """Append a later Alibaba snapshot from already-loaded data."""

        with self.repository_factory(self.settings) as repository:
            service = RecordAlibabaPriceSnapshot(
                repository=repository,
                clock=clock or self.collection_clock or (lambda: datetime.now(UTC)),
            )
            return service.execute(observation)

    def unfollow_alibaba_price(self, product_id: str) -> AlibabaTrackedProduct:
        """Deactivate Alibaba tracking without deleting history."""

        _logger.info(
            "command=unfollow_alibaba product_id=%s database=%s started",
            product_id,
            self.settings.database_path,
        )
        with self.repository_factory(self.settings) as repository:
            tracked = UnfollowAlibabaPrice(repository=repository).execute(product_id)
        _logger.info(
            "command=unfollow_alibaba product_id=%s active=%s completed",
            tracked.product_id,
            tracked.is_active,
        )
        return tracked

    def list_alibaba_tracked(self, *, active_only: bool = True) -> list[AlibabaTrackedProduct]:
        """Read followed Alibaba products from local SQLite."""

        with self.repository_factory(self.settings) as repository:
            return ListAlibabaTracked(repository=repository).execute(active_only=active_only)

    def refresh_alibaba_products(
        self,
        product_ids: Sequence[str],
        *,
        operation_id: str,
        clock: CollectionClock | None = None,
        refresh_provider: AlibabaProductRefreshProvider | None = None,
    ) -> AlibabaRefreshSummary:
        """Refresh selected followed products in one product-detail batch."""

        provider = refresh_provider or _alibaba_refresh_provider(self.settings)
        _logger.info(
            "command=refresh_alibaba count=%d database=%s started",
            len(product_ids),
            self.settings.database_path,
        )
        with self.repository_factory(self.settings) as repository:
            summary = RefreshTrackedAlibabaProducts(
                repository=repository,
                provider=provider,
                clock=clock or self.collection_clock or (lambda: datetime.now(UTC)),
            ).execute(product_ids, operation_id=operation_id)
        _logger.info(
            "command=refresh_alibaba requested=%d updated=%d unchanged=%d completed",
            summary.requested,
            summary.updated,
            summary.unchanged,
        )
        return summary

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

    resolved = resolve_process_settings(settings)
    client = ApifyAlibabaClient(
        _api_token=resolved.apify_api_token,
        actor_id=resolved.apify_alibaba_actor,
    )
    return SearchAlibabaProducts(provider=client)


def build_mercadolibre_search(settings: Settings | None = None) -> SearchMercadoLibreProducts:
    """Wire SearchMercadoLibreProducts to Apify without opening a run."""

    resolved = resolve_process_settings(settings)
    client = ApifyMercadoLibreClient(
        _api_token=resolved.apify_api_token,
        actor_id=resolved.apify_mercadolibre_actor,
    )
    return SearchMercadoLibreProducts(provider=client)


def build_product_translator(
    settings: Settings | None = None,
    *,
    client: httpx.Client | None = None,
) -> ProductTranslator:
    """Wire the configured translator. Never falls back to another provider."""

    resolved = resolve_process_settings(settings)
    provider = resolved.resolved_translator_provider()
    if provider == TRANSLATOR_PROVIDER_DEEPL:
        return DeepLProductTranslator(
            api_key=resolved.deepl_api_key,
            endpoint=resolved.deepl_api_endpoint,
            timeout_seconds=resolved.deepl_timeout_seconds,
            client=client,
        )
    if provider == TRANSLATOR_PROVIDER_AZURE:
        return AzureProductTranslator(
            api_key=resolved.azure_translator_key,
            endpoint=resolved.azure_translator_endpoint,
            region=resolved.azure_translator_region,
            timeout_seconds=resolved.azure_translator_timeout_seconds,
            client=client,
        )
    return DisabledProductTranslator()


def build_product_title_translator(
    settings: Settings | None = None,
    *,
    client: httpx.Client | None = None,
    cache: InMemoryProductTranslationCache | None = None,
) -> TranslateProductTitle:
    """Wire translation + conservative query generation. No marketplace HTTP."""

    from bera_price_tracker.application.product_translation import (
        ConservativeProductSearchQueryGenerator,
    )
    from bera_price_tracker.application.product_translation import (
        InMemoryProductTranslationCache as Cache,
    )

    translator = build_product_translator(settings, client=client)
    resolved_cache = Cache() if cache is None else cache
    return TranslateProductTitle(
        translator=translator,
        query_generator=ConservativeProductSearchQueryGenerator(),
        cache=resolved_cache,
    )


def build_alibaba_negotiation_drafter(
    settings: Settings | None = None,
) -> AlibabaNegotiationDrafter:
    """Wire MiniMax/Ollama for Alibaba negotiation drafts. No marketplace HTTP."""

    from bera_price_tracker.infrastructure.ai import OllamaAlibabaNegotiationDrafter

    resolved = resolve_process_settings(settings)
    drafter: AlibabaNegotiationDrafter = OllamaAlibabaNegotiationDrafter(
        base_url=resolved.ollama_base_url,
        model=resolved.ollama_model,
        timeout_seconds=resolved.ollama_timeout_seconds,
    )
    return drafter
