"""Isolated Apify Facebook Marketplace acquisition spike.

This tool is deliberately isolated from production providers. Default mode is a dry run;
only ``--execute`` can start one Actor run. ``--read-last-run`` only reads an existing
SUCCEEDED dataset and never calls ``actor.call``.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, cast

_TOKEN_ENV = "BERA_TRACKER_APIFY_API_TOKEN"
ACTOR_ID = "apify/facebook-marketplace-scraper"
PROVIDER_NAME = "Apify"
DEFAULT_QUERY = "pastillas sbr"
DEFAULT_CITY = "caracas"
RESULTS_LIMIT = 5
INCLUDE_LISTING_DETAILS = False
START_URL = "https://www.facebook.com/marketplace/caracas/search/?query=pastillas%20sbr"
PREFERRED_RUN_ID = "bdmqOKRl57f0aTRRx"


class SpikeOutcome(StrEnum):
    """Sanitized classification of the spike result."""

    RESULTS_FOUND = "RESULTS_FOUND"
    EMPTY = "EMPTY"
    ACTOR_FAILED = "ACTOR_FAILED"
    REQUEST_ERROR = "REQUEST_ERROR"


class SpikeConfigurationError(ValueError):
    """The local spike configuration is invalid or incomplete."""


class ApifyRequestError(RuntimeError):
    """The one permitted Apify run did not complete successfully."""


class _RunClient(Protocol):
    def get(self) -> dict[str, object] | None: ...


class _ActorClient(Protocol):
    def call(
        self, *, run_input: dict[str, object], max_items: int | None = None
    ) -> dict[str, object] | None: ...

    def last_run(self, *, status: str | None = None) -> _RunClient: ...


class _DatasetPage(Protocol):
    items: list[object]


class _DatasetClient(Protocol):
    def list_items(self, *, limit: int) -> _DatasetPage: ...


class _ApifyClientLike(Protocol):
    def actor(self, actor_id: str) -> _ActorClient: ...

    def dataset(self, dataset_id: str) -> _DatasetClient: ...

    def run(self, run_id: str) -> _RunClient: ...


ClientFactory = Callable[[str], _ApifyClientLike]


@dataclass(frozen=True, slots=True)
class SpikeConfiguration:
    """Validated spike configuration with a redacted credential representation."""

    _api_token: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> SpikeConfiguration:
        values = os.environ if environ is None else environ
        raw_token = values.get(_TOKEN_ENV)
        api_token = None if raw_token is None else raw_token.strip() or None
        return cls(_api_token=api_token)

    @property
    def api_token_configured(self) -> bool:
        return self._api_token is not None

    def require_api_token(self) -> str:
        if self._api_token is None:
            raise SpikeConfigurationError(f"{_TOKEN_ENV} is required with --execute")
        return self._api_token


@dataclass(frozen=True, slots=True)
class ListingSummary:
    title: str | None
    price_amount: str | None
    price_formatted: str | None
    currency: str | None
    location: str | None
    listing_url: str | None
    listing_id: str | None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apify_marketplace_spike.py",
        description="Experimentally inspect Apify Facebook Marketplace results.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--execute",
        action="store_true",
        help="Start one real Apify Actor run. Default is dry run with no request.",
    )
    mode.add_argument(
        "--read-last-run",
        action="store_true",
        help="Read the latest SUCCEEDED Actor dataset. Never starts a new run.",
    )
    return parser


def build_run_input() -> dict[str, object]:
    """Return the single fixed Actor input. Always resultsLimit=5 and one start URL."""

    return {
        "startUrls": [{"url": START_URL}],
        "resultsLimit": RESULTS_LIMIT,
        "includeListingDetails": INCLUDE_LISTING_DETAILS,
    }


def _as_mapping(value: object) -> Mapping[str, object] | None:
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)
    return None


def _scalar_text(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (str, int)):
        normalized = str(value).strip()
        if normalized:
            return normalized
    return None


def _nested_get(record: Mapping[str, object], *keys: str) -> object:
    current: object = record
    for key in keys:
        mapping = _as_mapping(current)
        if mapping is None:
            return None
        current = mapping.get(key)
    return current


def _price_object(record: Mapping[str, object]) -> Mapping[str, object] | None:
    listing_price = _as_mapping(record.get("listing_price"))
    if listing_price is not None:
        return listing_price
    return _as_mapping(record.get("listingPrice"))


def _price_amount(record: Mapping[str, object]) -> str | None:
    listing_price = _as_mapping(record.get("listing_price"))
    if listing_price is not None:
        amount = _scalar_text(listing_price.get("amount"))
        if amount is not None:
            return amount
    listing_price_legacy = _as_mapping(record.get("listingPrice"))
    if listing_price_legacy is not None:
        return _scalar_text(listing_price_legacy.get("amount"))
    return None


def _price_formatted(record: Mapping[str, object]) -> str | None:
    listing_price = _as_mapping(record.get("listing_price"))
    if listing_price is not None:
        formatted = _scalar_text(listing_price.get("formatted_amount"))
        if formatted is not None:
            return formatted
    listing_price_legacy = _as_mapping(record.get("listingPrice"))
    if listing_price_legacy is not None:
        formatted = _scalar_text(listing_price_legacy.get("formatted_amount"))
        if formatted is not None:
            return formatted
        return _scalar_text(listing_price_legacy.get("formatted_amount_zeros_stripped"))
    return None


def _price_currency(price: Mapping[str, object] | None, price_formatted: str | None) -> str | None:
    if price is None:
        return None
    explicit = _scalar_text(price.get("currency"))
    if explicit is not None:
        return explicit
    if price_formatted is not None:
        return "UNKNOWN"
    return None


def _location_text(record: Mapping[str, object]) -> str | None:
    display_name = _scalar_text(
        _nested_get(record, "location", "reverse_geocode", "city_page", "display_name")
    )
    if display_name is not None:
        return display_name
    city = _scalar_text(_nested_get(record, "location", "reverse_geocode", "city"))
    if city is not None:
        return city
    location_text = record.get("locationText")
    mapped = _as_mapping(location_text)
    if mapped is not None:
        return _scalar_text(mapped.get("text"))
    return _scalar_text(location_text)


def sanitize_listing(raw: object) -> ListingSummary:
    if not isinstance(raw, Mapping):
        return ListingSummary(None, None, None, None, None, None, None)
    record = cast(Mapping[str, object], raw)
    price = _price_object(record)
    price_formatted = _price_formatted(record)
    return ListingSummary(
        title=_scalar_text(record.get("marketplace_listing_title"))
        or _scalar_text(record.get("listingTitle")),
        price_amount=_price_amount(record),
        price_formatted=price_formatted,
        currency=_price_currency(price, price_formatted),
        location=_location_text(record),
        listing_url=_scalar_text(record.get("listingUrl")) or _scalar_text(record.get("itemUrl")),
        listing_id=_scalar_text(record.get("id")),
    )


def _mode_label(*, execute: bool, read_last_run: bool) -> str:
    if execute:
        return "EXECUTE"
    if read_last_run:
        return "READ LAST RUN"
    return "DRY RUN"


def _print_plan(configuration: SpikeConfiguration, *, execute: bool, read_last_run: bool) -> None:
    token_status = "CONFIGURED" if configuration.api_token_configured else "MISSING"
    print(f"Mode: {_mode_label(execute=execute, read_last_run=read_last_run)}")
    print(f"Provider: {PROVIDER_NAME}")
    print(f"Actor: {ACTOR_ID}")
    print(f"Query: {DEFAULT_QUERY}")
    print(f"City: {DEFAULT_CITY}")
    print(f"Results limit: {RESULTS_LIMIT}")
    print("Include listing details: false")
    print(f"Token: {token_status}")
    if not execute:
        print("Request sent: NO")
        print("New Actor runs created: 0")


def _print_optional(label: str, value: str | None) -> None:
    if value is not None:
        print(f"{label}: {value}")


def _print_summaries(summaries: Sequence[ListingSummary]) -> None:
    for index, summary in enumerate(summaries[:RESULTS_LIMIT], start=1):
        print()
        print(f"[{index}]")
        _print_optional("title", summary.title)
        _print_optional("price_amount", summary.price_amount)
        _print_optional("price_formatted", summary.price_formatted)
        _print_optional("currency", summary.currency)
        _print_optional("location", summary.location)
        _print_optional("listing_url", summary.listing_url)
        _print_optional("listing_id", summary.listing_id)


def _default_client_factory(token: str) -> _ApifyClientLike:
    from apify_client import ApifyClient

    return cast(_ApifyClientLike, ApifyClient(token))


def _run_status(run: Mapping[str, object]) -> str:
    status = run.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip()
    return "UNKNOWN"


def _dataset_id(run: Mapping[str, object]) -> str | None:
    value = run.get("defaultDatasetId")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _preferred_succeeded_run(client: _ApifyClientLike) -> Mapping[str, object] | None:
    try:
        preferred = client.run(PREFERRED_RUN_ID).get()
    except Exception:
        preferred = None
    if isinstance(preferred, Mapping) and _run_status(preferred) == "SUCCEEDED":
        return preferred
    return None


def _load_dataset_summaries(
    client: _ApifyClientLike, dataset_id: str
) -> tuple[ListingSummary, ...]:
    page = client.dataset(dataset_id).list_items(limit=RESULTS_LIMIT)
    raw_items = list(page.items)
    return tuple(sanitize_listing(item) for item in raw_items[:RESULTS_LIMIT])


def _summaries_outcome(
    status: str, summaries: tuple[ListingSummary, ...]
) -> tuple[SpikeOutcome, str, tuple[ListingSummary, ...]]:
    if not summaries:
        return SpikeOutcome.EMPTY, status, ()
    return SpikeOutcome.RESULTS_FOUND, status, summaries


def execute_spike(
    configuration: SpikeConfiguration,
    *,
    client_factory: ClientFactory | None = None,
) -> tuple[SpikeOutcome, str, tuple[ListingSummary, ...]]:
    token = configuration.require_api_token()
    factory = client_factory or _default_client_factory
    run_input = build_run_input()
    try:
        client = factory(token)
        actor_client = client.actor(ACTOR_ID)
        run = actor_client.call(run_input=run_input, max_items=RESULTS_LIMIT)
    except SpikeConfigurationError:
        raise
    except Exception as error:
        raise ApifyRequestError("Apify request failed") from error

    if not isinstance(run, Mapping):
        raise ApifyRequestError("Apify returned no run object")

    status = _run_status(run)
    if status != "SUCCEEDED":
        return SpikeOutcome.ACTOR_FAILED, status, ()

    dataset_id = _dataset_id(run)
    if dataset_id is None:
        raise ApifyRequestError("Apify run is missing a dataset id")

    try:
        summaries = _load_dataset_summaries(client, dataset_id)
    except Exception as error:
        raise ApifyRequestError("Apify dataset download failed") from error
    return _summaries_outcome(status, summaries)


def read_last_succeeded_spike(
    configuration: SpikeConfiguration,
    *,
    client_factory: ClientFactory | None = None,
) -> tuple[SpikeOutcome, str, tuple[ListingSummary, ...]]:
    token = configuration.require_api_token()
    factory = client_factory or _default_client_factory
    try:
        client = factory(token)
        run = _preferred_succeeded_run(client)
        if run is None:
            last_run = client.actor(ACTOR_ID).last_run(status="SUCCEEDED").get()
            if not isinstance(last_run, Mapping):
                raise ApifyRequestError("Apify returned no run object")
            run = last_run
    except SpikeConfigurationError:
        raise
    except ApifyRequestError:
        raise
    except Exception as error:
        raise ApifyRequestError("Apify request failed") from error

    status = _run_status(run)
    if status != "SUCCEEDED":
        return SpikeOutcome.ACTOR_FAILED, status, ()

    dataset_id = _dataset_id(run)
    if dataset_id is None:
        raise ApifyRequestError("Apify run is missing a dataset id")

    try:
        summaries = _load_dataset_summaries(client, dataset_id)
    except Exception as error:
        raise ApifyRequestError("Apify dataset download failed") from error
    return _summaries_outcome(status, summaries)


def _print_result(outcome: SpikeOutcome, status: str, summaries: tuple[ListingSummary, ...]) -> int:
    print(f"Classification: {outcome}")
    print(f"Run status: {status}")
    print(f"Number of items: {len(summaries)}")
    _print_summaries(summaries)
    return 0 if outcome is not SpikeOutcome.ACTOR_FAILED else 4


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    client_factory: ClientFactory | None = None,
) -> int:
    namespace = build_parser().parse_args(argv)
    configuration = SpikeConfiguration.from_env(environ)
    execute = cast(bool, namespace.execute)
    read_last_run = cast(bool, namespace.read_last_run)
    _print_plan(configuration, execute=execute, read_last_run=read_last_run)
    if not execute and not read_last_run:
        return 0

    action = execute_spike if execute else read_last_succeeded_spike
    try:
        outcome, status, summaries = action(
            configuration,
            client_factory=client_factory,
        )
    except SpikeConfigurationError as error:
        print(f"Classification: {SpikeOutcome.REQUEST_ERROR}")
        print(f"Request error: {error}", file=sys.stderr)
        return 2
    except ApifyRequestError as error:
        print(f"Classification: {SpikeOutcome.REQUEST_ERROR}")
        print("Run status: UNKNOWN")
        print("Number of items: 0")
        print(f"Request error: {error}")
        return 3
    return _print_result(outcome, status, summaries)


if __name__ == "__main__":
    raise SystemExit(main())
