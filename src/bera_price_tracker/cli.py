"""Command-line adapter for BERA Price Tracker."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from enum import IntEnum
from typing import cast

from bera_price_tracker.application import (
    DEFAULT_INSPECTION_LIMIT,
    MAX_INSPECTION_LIMIT,
    MIN_INSPECTION_LIMIT,
    CollectionClock,
    DatabaseState,
    DiagnosticReport,
    DiagnosticStatus,
    MarketplaceSourceUnavailable,
    StatisticsUnavailableError,
)
from bera_price_tracker.composition import (
    DiagnosticsRepositoryFactory,
    HistoryRepositoryFactory,
    InspectionRepositoryFactory,
    ProviderFactory,
    RepositoryFactory,
    build_composition,
)
from bera_price_tracker.config import (
    DEFAULT_FACEBOOK_CITY,
    DEFAULT_FACEBOOK_RECORD_LIMIT,
    MAX_FACEBOOK_RECORD_LIMIT,
    Settings,
)
from bera_price_tracker.domain import (
    CollectionRunInspection,
    Listing,
    ListingHistory,
    ListingKey,
    ListingStatistics,
    MarketplaceSource,
    SearchQuery,
    format_usd_line,
)
from bera_price_tracker.infrastructure.persistence import (
    DatabaseNotFoundError,
    PersistenceError,
)
from bera_price_tracker.infrastructure.providers import (
    ApifyConfigurationError,
    BrightDataConfigurationError,
    BrightDataConnectionError,
    BrightDataError,
    BrightDataHTTPError,
    BrightDataPollingTimeoutError,
    BrightDataResponseError,
    BrightDataTimeoutError,
    FacebookCandidateExplanation,
    FacebookCollectionMetrics,
    MercadoLibreAuthenticationError,
    MercadoLibreConfigurationError,
    MercadoLibreConnectionError,
    MercadoLibreError,
    MercadoLibreHTTPError,
    MercadoLibreRateLimitError,
    MercadoLibreResponseError,
)
from bera_price_tracker.logging_config import configure_logging

_logger = logging.getLogger(__name__)


class ExitCode(IntEnum):
    """Stable process exit codes for CLI callers."""

    SUCCESS = 0
    UNEXPECTED_ERROR = 1
    USAGE_OR_CONFIGURATION = 2
    PROVIDER_ERROR = 3
    PERSISTENCE_ERROR = 4
    NOT_FOUND = 5
    STATISTICS_UNAVAILABLE = 6


def _add_listing_identity_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("external_id", help="Marketplace listing identifier.")
    _add_source_argument(parser)


def _add_source_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--source",
        choices=tuple(source.value for source in MarketplaceSource),
        default=MarketplaceSource.MERCADO_LIBRE.value,
        help="Marketplace source (default: mercado_libre).",
    )


def _inspection_limit(value: str) -> int:
    try:
        limit = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("limit must be an integer") from error
    if not MIN_INSPECTION_LIMIT <= limit <= MAX_INSPECTION_LIMIT:
        raise argparse.ArgumentTypeError(
            f"limit must be between {MIN_INSPECTION_LIMIT} and {MAX_INSPECTION_LIMIT}"
        )
    return limit


def _facebook_record_limit(value: str) -> int:
    try:
        limit = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("limit must be an integer") from error
    if not 1 <= limit <= MAX_FACEBOOK_RECORD_LIMIT:
        raise argparse.ArgumentTypeError(
            f"Facebook limit must be between 1 and {MAX_FACEBOOK_RECORD_LIMIT}"
        )
    return limit


def _add_marketplace_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--provider",
        choices=("mercado_libre", "facebook"),
        default="mercado_libre",
        help="Marketplace provider (default: mercado_libre).",
    )
    parser.add_argument(
        "--city",
        default=None,
        metavar="CITY",
        help=f"Facebook city (default: {DEFAULT_FACEBOOK_CITY}).",
    )
    parser.add_argument(
        "--limit",
        type=_facebook_record_limit,
        default=None,
        metavar="N",
        help=(
            "Maximum Facebook records for one input "
            f"(default: {DEFAULT_FACEBOOK_RECORD_LIMIT}; max: {MAX_FACEBOOK_RECORD_LIMIT})."
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bera-price-tracker",
        description="Track brake pad listing prices for BERA motorcycles.",
    )
    subparsers = parser.add_subparsers(dest="command")
    search_parser = subparsers.add_parser(
        "search",
        help="Search one configured marketplace provider.",
    )
    search_parser.add_argument("query", help="Marketplace search query.")
    _add_marketplace_arguments(search_parser)
    collect_parser = subparsers.add_parser(
        "collect",
        help="Search one marketplace and persist the relevant observed listings.",
    )
    collect_parser.add_argument("query", help="Marketplace search query to collect.")
    _add_marketplace_arguments(collect_parser)
    collect_parser.add_argument(
        "--explain",
        action="store_true",
        help="Print one sanitized decision summary per Facebook candidate.",
    )
    subparsers.add_parser(
        "doctor",
        help="Diagnose local configuration and SQLite readiness without using HTTP.",
    )
    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect the latest persisted collection batch in local SQLite.",
    )
    inspect_parser.add_argument("query", help="Previously collected marketplace query.")
    _add_source_argument(inspect_parser)
    inspect_parser.add_argument(
        "--limit",
        type=_inspection_limit,
        default=DEFAULT_INSPECTION_LIMIT,
        metavar="N",
        help=(
            f"Maximum listings to show (default: {DEFAULT_INSPECTION_LIMIT}; "
            f"range: {MIN_INSPECTION_LIMIT}..{MAX_INSPECTION_LIMIT})."
        ),
    )
    history_parser = subparsers.add_parser(
        "history",
        help="Read one listing's price history from local SQLite.",
    )
    _add_listing_identity_arguments(history_parser)
    stats_parser = subparsers.add_parser(
        "stats",
        help="Calculate one listing's statistics from local SQLite history.",
    )
    _add_listing_identity_arguments(stats_parser)
    return parser


def _source_name(source: MarketplaceSource) -> str:
    if source is MarketplaceSource.MERCADO_LIBRE:
        return "Mercado Libre"
    if source is MarketplaceSource.ALIBABA:
        return "Alibaba"
    return source.value


def _original_price_label(amount: object, currency: str, formatted: str | None = None) -> str:
    if formatted:
        return formatted
    return f"{amount} {currency}"


def _print_usd_block(
    usd_amount: object,
    original_amount: object,
    original_currency: str,
    formatted: str | None = None,
) -> None:
    usd = usd_amount if isinstance(usd_amount, Decimal) else None
    print(format_usd_line(usd))
    if usd is None or formatted is not None or original_currency != "USD":
        print(f"Original: {_original_price_label(original_amount, original_currency, formatted)}")


def _print_facebook_metrics(metrics: FacebookCollectionMetrics) -> None:
    print("Facebook collection summary:")
    print(f"  fetched: {metrics.fetched}")
    print(f"  source_errors: {metrics.source_errors}")
    print(f"  non_ve: {metrics.non_ve}")
    print(f"  invalid_price: {metrics.invalid_price}")
    print(f"  out_of_scope_location: {metrics.out_of_scope_location}")
    print(f"  deterministic_relevant: {metrics.deterministic_relevant}")
    print(f"  deterministic_irrelevant: {metrics.deterministic_irrelevant}")
    print(f"  ai_requested: {metrics.ai_requested}")
    print(f"  ai_relevant: {metrics.ai_relevant}")
    print(f"  ai_irrelevant: {metrics.ai_irrelevant}")
    print(f"  review: {metrics.review}")
    print(f"  duplicates: {metrics.duplicates}")
    print(f"  persisted: {metrics.persisted}")


def _print_facebook_explanations(
    explanations: tuple[FacebookCandidateExplanation, ...],
) -> None:
    print("Facebook candidate explanations:")
    for index, explanation in enumerate(explanations, start=1):
        print()
        print(f"[{index}]")
        if explanation.title is not None:
            print(f"title: {explanation.title}")
        if explanation.usd_amount is not None:
            print(format_usd_line(explanation.usd_amount))
        if explanation.price is not None and explanation.currency is not None:
            print(f"price: {explanation.price} {explanation.currency}")
        print(f"decision: {explanation.outcome.value}")
        if explanation.classification_source is not None:
            print(f"source: {explanation.classification_source}")
            print(f"product_type: {explanation.product_type}")
            print(f"h0019_match: {explanation.h0019_match or 'none'}")
        if explanation.bike_models:
            print(f"bike_models: {', '.join(explanation.bike_models)}")
        if explanation.other_compatibility:
            print(f"other_compatibility: {', '.join(explanation.other_compatibility)}")
        if explanation.position is not None:
            print(f"position: {explanation.position}")
        if explanation.location is not None:
            print(f"location: {explanation.location}")
        print(f"reason: {explanation.reason}")


def _print_search_results(listings: list[Listing]) -> None:
    for listing in listings:
        print(f"ID: {listing.external_id}")
        print(listing.title)
        _print_usd_block(
            listing.usd_amount,
            listing.price,
            listing.currency,
            listing.formatted_amount,
        )
        print(listing.url)
        print()


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _print_listing_history(history: ListingHistory) -> None:
    print(f"ID: {history.key.external_id}")
    print(f"Source: {_source_name(history.key.source)}")
    print(f"Title: {history.title}")
    print(f"URL: {history.url}")
    if history.seller_name is not None:
        print(f"Seller: {history.seller_name}")
    if history.location is not None:
        print(f"Location: {history.location}")
    if history.product_condition is not None:
        print(f"Condition: {history.product_condition}")
    print(f"First seen: {_format_timestamp(history.first_seen_at)}")
    print(f"Last seen: {_format_timestamp(history.last_seen_at)}")
    print()
    print("Price history:")
    for observation in history.observations:
        print(
            f"{_format_timestamp(observation.collected_at)} | "
            f"{format_usd_line(observation.usd_amount)} | "
            f"{observation.price} {observation.currency} | {observation.query.text}"
        )


def _print_collection_inspection(inspection: CollectionRunInspection) -> None:
    print(f"Query: {inspection.query.text}")
    print(f"Source: {_source_name(inspection.source)}")
    print(f"Collected at: {_format_timestamp(inspection.collected_at)}")
    print(f"Listings: {inspection.total_listings}")
    print(f"Showing: {len(inspection.observations)}")
    for index, observation in enumerate(inspection.observations, start=1):
        print()
        print(f"[{index}]")
        print(f"ID: {observation.key.external_id}")
        print(f"Title: {observation.title}")
        _print_usd_block(observation.usd_amount, observation.price, observation.currency)
        print(f"Price: {observation.price} {observation.currency}")
        if observation.product_condition is not None:
            print(f"Condition: {observation.product_condition}")
        if observation.seller_name is not None:
            print(f"Seller: {observation.seller_name}")
        if observation.location is not None:
            print(f"Location: {observation.location}")
        print(f"URL: {observation.url}")


def _section_status(status: DiagnosticStatus) -> str:
    return "OK" if status is DiagnosticStatus.READY else status.value


def _database_schema_description(report: DiagnosticReport) -> str:
    database = report.database
    if database.state is DatabaseState.OK:
        assert database.schema_version is not None
        return f"OK (version {database.schema_version})"
    if database.state is DatabaseState.NOT_INITIALIZED:
        return "NOT INITIALIZED"
    if database.state is DatabaseState.INCOMPATIBLE:
        found = "unknown" if database.schema_version is None else str(database.schema_version)
        return f"INCOMPATIBLE (expected {database.expected_schema_version}, found {found})"
    return "ERROR"


def _print_diagnostic_report(report: DiagnosticReport) -> None:
    python_version = ".".join(str(part) for part in report.python_version)
    python_status = "OK" if report.python_compatible else "INCOMPLETE"
    site_id = report.mercadolibre_site_id or "NOT CONFIGURED"
    if report.mercadolibre_site_id is not None and not report.mercadolibre_site_id_valid:
        site_id = f"{site_id} (INVALID)"

    print("BERA Price Tracker diagnostics")
    print()
    print("Python:")
    print(f"  Version: {python_version}")
    print(f"  Status: {python_status}")
    print()
    print("Mercado Libre:")
    print(f"  Site ID: {site_id}")
    token_status = "CONFIGURED" if report.access_token_configured else "NOT CONFIGURED"
    print(f"  Access token: {token_status}")
    print(f"  Page size: {report.page_size}")
    print(f"  Max pages: {report.max_pages}")
    print(f"  Timeout: {report.timeout_seconds:g}s")
    print(f"  Retries: {report.max_retries}")
    print(f"  Status: {_section_status(report.mercado_libre_status)}")
    print()
    print("Database:")
    print(f"  Path: {report.database.path}")
    print(f"  Exists: {'yes' if report.database.exists else 'no'}")
    print(f"  Schema: {_database_schema_description(report)}")
    if report.database.detail is not None:
        print(f"  Detail: {report.database.detail}")
    if report.database.state is DatabaseState.OK:
        database_status = "OK"
    elif report.database.state is DatabaseState.NOT_INITIALIZED:
        database_status = "INCOMPLETE"
    else:
        database_status = "ERROR"
    print(f"  Status: {database_status}")
    print()
    print("Facebook Marketplace:")
    print("  Status: NOT CONFIGURED")
    print()
    azure_status = "CONFIGURED" if report.azure_translator_configured else "NOT CONFIGURED"
    print("Azure Translator:")
    print(f"  Status: {azure_status}")
    print()
    print(f"Overall: {report.overall.value}")


def _format_signed_decimal(value: Decimal) -> str:
    return f"+{value}" if value > Decimal("0") else str(value)


def _format_percentage(value: Decimal) -> str:
    with localcontext() as context:
        context.rounding = ROUND_HALF_EVEN
        magnitude = format(value.copy_abs(), ".2f")
    if value > Decimal("0"):
        sign = "+"
    elif value < Decimal("0"):
        sign = "-"
    else:
        sign = ""
    return f"{sign}{magnitude}%"


def _print_listing_statistics(statistics: ListingStatistics) -> None:
    print(f"ID: {statistics.key.external_id}")
    print(f"Source: {_source_name(statistics.key.source)}")
    print(f"Title: {statistics.title}")
    print(f"Currency: {statistics.currency}")
    print()
    print(f"Current price: {statistics.current_price}")
    if statistics.previous_price is None:
        print("Previous price: unavailable")
        print("Change: unavailable")
    else:
        print(f"Previous price: {statistics.previous_price}")
        assert statistics.absolute_change is not None
        change = _format_signed_decimal(statistics.absolute_change)
        if statistics.percentage_change is None:
            print(f"Change: {change} (percentage unavailable)")
        else:
            percentage = _format_percentage(statistics.percentage_change)
            print(f"Change: {change} ({percentage})")
    print()
    print(f"Minimum: {statistics.minimum_price}")
    print(f"Maximum: {statistics.maximum_price}")
    print(f"Average: {statistics.average_price}")
    print(f"Median: {statistics.median_price}")
    print()
    print(f"Observations: {statistics.observation_count}")
    print(f"First observation: {_format_timestamp(statistics.first_observed_at)}")
    print(f"Last observation: {_format_timestamp(statistics.last_observed_at)}")


def _report_error(
    command: str,
    *,
    category: str,
    message: str,
    exit_code: ExitCode,
) -> ExitCode:
    _logger.error("command=%s failure=%s", command, category)
    print(message, file=sys.stderr)
    return exit_code


def main(
    argv: Sequence[str] | None = None,
    *,
    provider_factory: ProviderFactory | None = None,
    repository_factory: RepositoryFactory | None = None,
    history_repository_factory: HistoryRepositoryFactory | None = None,
    inspection_repository_factory: InspectionRepositoryFactory | None = None,
    diagnostics_repository_factory: DiagnosticsRepositoryFactory | None = None,
    collection_clock: CollectionClock | None = None,
) -> int:
    parser = build_parser()
    namespace = parser.parse_args(argv)
    command = cast(str | None, getattr(namespace, "command", None))

    if command is None:
        parser.print_help()
        return ExitCode.SUCCESS

    query: SearchQuery | None = None
    listing_key: ListingKey | None = None
    inspection_source: MarketplaceSource | None = None
    inspection_limit: int | None = None
    provider_source = MarketplaceSource.MERCADO_LIBRE
    requested_city: str | None = None
    requested_record_limit: int | None = None
    if command in {"search", "collect", "inspect"}:
        raw_query = cast(str, namespace.query)
        try:
            query = SearchQuery(raw_query)
        except (TypeError, ValueError) as error:
            return _report_error(
                command,
                category="invalid_query",
                message=f"Invalid query: {error}",
                exit_code=ExitCode.USAGE_OR_CONFIGURATION,
            )
        if command == "inspect":
            inspection_source = MarketplaceSource(cast(str, namespace.source))
            inspection_limit = cast(int, namespace.limit)
        else:
            provider_name = cast(str, namespace.provider)
            if provider_name == "facebook":
                provider_source = MarketplaceSource.FACEBOOK_MARKETPLACE
                requested_city = cast(str | None, namespace.city)
                requested_record_limit = cast(int | None, namespace.limit)
    elif command in {"history", "stats"}:
        try:
            listing_key = ListingKey(
                source=MarketplaceSource(cast(str, namespace.source)),
                external_id=cast(str, namespace.external_id),
            )
        except (TypeError, ValueError) as error:
            return _report_error(
                command,
                category="invalid_listing_key",
                message=f"Invalid listing identity: {error}",
                exit_code=ExitCode.USAGE_OR_CONFIGURATION,
            )

    try:
        settings = Settings.from_env()
        if provider_source is MarketplaceSource.FACEBOOK_MARKETPLACE:
            settings = replace(
                settings,
                facebook_city=requested_city or settings.facebook_city,
                facebook_record_limit=(
                    requested_record_limit
                    if requested_record_limit is not None
                    else settings.facebook_record_limit
                ),
            )
        configure_logging(settings.log_level)
    except (TypeError, ValueError) as error:
        return _report_error(
            command,
            category="invalid_configuration",
            message=f"Configuration error: {error}",
            exit_code=ExitCode.USAGE_OR_CONFIGURATION,
        )

    try:
        composition = build_composition(
            settings,
            provider_source=provider_source,
            provider_factory=provider_factory,
            repository_factory=repository_factory,
            history_repository_factory=history_repository_factory,
            inspection_repository_factory=inspection_repository_factory,
            diagnostics_repository_factory=diagnostics_repository_factory,
            collection_clock=collection_clock,
        )
        if command == "search":
            assert query is not None
            listings = composition.search(query)
            if not listings:
                print("No listings found.")
            else:
                _print_search_results(listings)
            return ExitCode.SUCCESS

        if command == "collect":
            assert query is not None
            result = composition.collect(query)
            print(f"Query: {result.query.text}")
            source_name = (
                "Facebook Marketplace"
                if result.source is MarketplaceSource.FACEBOOK_MARKETPLACE
                else _source_name(result.source)
            )
            print(f"Source: {source_name}")
            print(f"Collected: {result.listing_count} listings")
            print(f"Database: {result.database_path}")
            if result.metrics is not None:
                _print_facebook_metrics(result.metrics)
            if cast(bool, namespace.explain) and result.explanations:
                _print_facebook_explanations(result.explanations)
            return ExitCode.SUCCESS

        if command == "doctor":
            report = composition.doctor()
            _print_diagnostic_report(report)
            if report.overall is DiagnosticStatus.READY:
                return ExitCode.SUCCESS
            if report.overall is DiagnosticStatus.ERROR:
                return ExitCode.PERSISTENCE_ERROR
            return ExitCode.USAGE_OR_CONFIGURATION

        if command == "inspect":
            assert query is not None
            assert inspection_source is not None
            assert inspection_limit is not None
            inspection = composition.inspect_latest_collection(
                inspection_source,
                query,
                limit=inspection_limit,
            )
            if inspection is None:
                return _report_error(
                    command,
                    category="collection_not_found",
                    message=f"No collection found for query: {query.text}",
                    exit_code=ExitCode.NOT_FOUND,
                )
            _print_collection_inspection(inspection)
            return ExitCode.SUCCESS

        if command == "history":
            assert listing_key is not None
            history = composition.history(listing_key)
            if history is None:
                return _report_error(
                    command,
                    category="listing_not_found",
                    message=(
                        f"Listing not found: {listing_key.source.value}/{listing_key.external_id}"
                    ),
                    exit_code=ExitCode.NOT_FOUND,
                )
            _print_listing_history(history)
            return ExitCode.SUCCESS

        if command == "stats":
            assert listing_key is not None
            statistics = composition.statistics(listing_key)
            if statistics is None:
                return _report_error(
                    command,
                    category="listing_not_found",
                    message=(
                        f"Listing not found: {listing_key.source.value}/{listing_key.external_id}"
                    ),
                    exit_code=ExitCode.NOT_FOUND,
                )
            _print_listing_statistics(statistics)
            return ExitCode.SUCCESS
    except StatisticsUnavailableError as error:
        return _report_error(
            command,
            category="statistics_unavailable",
            message=f"Statistics error: {error}",
            exit_code=ExitCode.STATISTICS_UNAVAILABLE,
        )
    except ApifyConfigurationError as error:
        return _report_error(
            command,
            category="provider_configuration",
            message=f"Configuration error: {error}",
            exit_code=ExitCode.USAGE_OR_CONFIGURATION,
        )
    except MarketplaceSourceUnavailable as error:
        return _report_error(
            command,
            category="marketplace_source_unavailable",
            message=f"Marketplace source unavailable: {error}",
            exit_code=ExitCode.PROVIDER_ERROR,
        )
    except BrightDataConfigurationError as error:
        return _report_error(
            command,
            category="provider_configuration",
            message=f"Configuration error: {error}",
            exit_code=ExitCode.USAGE_OR_CONFIGURATION,
        )
    except BrightDataHTTPError as error:
        detail = "" if error.sanitized_body is None else f" Server detail: {error.sanitized_body}"
        return _report_error(
            command,
            category=f"provider_http_{error.status_code}",
            message=f"Bright Data request failed with HTTP {error.status_code}.{detail}",
            exit_code=ExitCode.PROVIDER_ERROR,
        )
    except BrightDataPollingTimeoutError:
        return _report_error(
            command,
            category="provider_polling_timeout",
            message="Bright Data snapshot did not become ready before the polling timeout.",
            exit_code=ExitCode.PROVIDER_ERROR,
        )
    except (BrightDataConnectionError, BrightDataTimeoutError):
        return _report_error(
            command,
            category="provider_connectivity",
            message="Could not connect to Bright Data or the request timed out.",
            exit_code=ExitCode.PROVIDER_ERROR,
        )
    except BrightDataResponseError:
        return _report_error(
            command,
            category="provider_response",
            message="Bright Data returned an invalid response.",
            exit_code=ExitCode.PROVIDER_ERROR,
        )
    except BrightDataError:
        return _report_error(
            command,
            category="provider",
            message="Bright Data could not complete the request.",
            exit_code=ExitCode.PROVIDER_ERROR,
        )
    except MercadoLibreConfigurationError as error:
        return _report_error(
            command,
            category="provider_configuration",
            message=f"Configuration error: {error}",
            exit_code=ExitCode.USAGE_OR_CONFIGURATION,
        )
    except MercadoLibreAuthenticationError:
        return _report_error(
            command,
            category="provider_authentication",
            message="Mercado Libre authentication or authorization failed.",
            exit_code=ExitCode.PROVIDER_ERROR,
        )
    except MercadoLibreRateLimitError:
        return _report_error(
            command,
            category="provider_rate_limit",
            message="Mercado Libre rate limit was exhausted.",
            exit_code=ExitCode.PROVIDER_ERROR,
        )
    except MercadoLibreConnectionError:
        return _report_error(
            command,
            category="provider_connectivity",
            message="Could not connect to Mercado Libre or the request timed out.",
            exit_code=ExitCode.PROVIDER_ERROR,
        )
    except MercadoLibreResponseError:
        return _report_error(
            command,
            category="provider_response",
            message="Mercado Libre returned an invalid response.",
            exit_code=ExitCode.PROVIDER_ERROR,
        )
    except MercadoLibreHTTPError as error:
        return _report_error(
            command,
            category=f"provider_http_{error.status_code}",
            message=f"Mercado Libre request failed with HTTP {error.status_code}.",
            exit_code=ExitCode.PROVIDER_ERROR,
        )
    except MercadoLibreError:
        return _report_error(
            command,
            category="provider",
            message="Mercado Libre could not complete the request.",
            exit_code=ExitCode.PROVIDER_ERROR,
        )
    except DatabaseNotFoundError as error:
        return _report_error(
            command,
            category="database_not_found",
            message=f"Persistence error: {error}",
            exit_code=ExitCode.PERSISTENCE_ERROR,
        )
    except PersistenceError as error:
        return _report_error(
            command,
            category="persistence",
            message=f"Persistence error: {error}",
            exit_code=ExitCode.PERSISTENCE_ERROR,
        )
    except Exception as error:
        _logger.error(
            "command=%s unexpected_failure error_type=%s",
            command,
            type(error).__name__,
        )
        print("Unexpected error while executing the command.", file=sys.stderr)
        return ExitCode.UNEXPECTED_ERROR

    parser.error(f"unknown command: {command}")
    return ExitCode.USAGE_OR_CONFIGURATION
