"""Cost-conscious Bright Data Facebook Marketplace acquisition spike.

This tool is deliberately isolated from the production providers, application services,
and persistence adapters. Its default mode is a dry run; only ``--execute`` can issue the
single HTTP request represented here.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import IntEnum
from typing import cast

import httpx

BRIGHT_DATA_ENDPOINT = "https://api.brightdata.com/datasets/v3/scrape"
DEFAULT_DATASET_ID = "gd_lvt9iwuh6fbcwmx1a"
DEFAULT_TIMEOUT_SECONDS = 70.0
DEFAULT_DISPLAY_LIMIT = 5
MIN_DISPLAY_LIMIT = 1
MAX_DISPLAY_LIMIT = 20

_TOKEN_ENV = "BERA_TRACKER_BRIGHTDATA_API_TOKEN"
_DATASET_ENV = "BERA_TRACKER_BRIGHTDATA_DATASET_ID"
_TIMEOUT_ENV = "BERA_TRACKER_BRIGHTDATA_TIMEOUT_SECONDS"
_DISPLAY_FIELDS = frozenset(
    {
        "product_id",
        "title",
        "final_price",
        "currency",
        "condition",
        "location",
        "country_code",
        "url",
        "listing_date",
    }
)
_DOCUMENTED_MARKETPLACE_FIELDS = _DISPLAY_FIELDS | {
    "initial_price",
    "description",
    "images",
    "seller_description",
    "color",
    "brand",
    "videos",
    "profile_id",
}


class SpikeExitCode(IntEnum):
    """Stable exit codes for this experimental command."""

    SUCCESS = 0
    CONFIGURATION_ERROR = 2
    REQUEST_ERROR = 3
    RESPONSE_ERROR = 4


class SpikeConfigurationError(ValueError):
    """The local spike configuration is invalid or incomplete."""


class BrightDataRequestError(RuntimeError):
    """The one permitted Bright Data request did not complete successfully."""


class BrightDataResponseError(RuntimeError):
    """Bright Data returned invalid or unexpected response data."""


@dataclass(frozen=True, slots=True)
class SpikeConfiguration:
    """Validated spike configuration with a redacted credential representation."""

    dataset_id: str
    timeout_seconds: float
    _api_token: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> SpikeConfiguration:
        """Load configuration directly from the environment without reading ``.env``."""

        values = os.environ if environ is None else environ
        dataset_id = values.get(_DATASET_ENV, DEFAULT_DATASET_ID).strip()
        if not dataset_id:
            raise SpikeConfigurationError(f"{_DATASET_ENV} must not be blank")

        raw_timeout = values.get(_TIMEOUT_ENV, str(DEFAULT_TIMEOUT_SECONDS))
        try:
            timeout_seconds = float(raw_timeout)
        except ValueError:
            raise SpikeConfigurationError(f"{_TIMEOUT_ENV} must be a number") from None
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise SpikeConfigurationError(f"{_TIMEOUT_ENV} must be finite and greater than zero")

        raw_token = values.get(_TOKEN_ENV)
        api_token = None if raw_token is None else raw_token.strip() or None
        return cls(
            dataset_id=dataset_id,
            timeout_seconds=timeout_seconds,
            _api_token=api_token,
        )

    @property
    def api_token_configured(self) -> bool:
        """Return token presence without revealing any credential material."""

        return self._api_token is not None

    def require_api_token(self) -> str:
        """Return the credential only to the HTTP boundary, or fail safely."""

        if self._api_token is None:
            raise SpikeConfigurationError(f"{_TOKEN_ENV} is required with --execute")
        return self._api_token


@dataclass(frozen=True, slots=True)
class MarketplaceRecord:
    """Allowlisted subset of one experimental Bright Data result."""

    product_id: str | None
    title: str | None
    final_price: Decimal | None
    currency: str | None
    condition: str | None
    location: str | None
    country_code: str | None
    url: str | None
    listing_date: str | None


@dataclass(frozen=True, slots=True)
class SpikeResponse:
    """Sanitized successful response from the single request."""

    http_status: int
    records: tuple[MarketplaceRecord, ...]


def _display_limit(raw_value: str) -> int:
    try:
        value = int(raw_value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("display limit must be an integer") from error
    if not MIN_DISPLAY_LIMIT <= value <= MAX_DISPLAY_LIMIT:
        raise argparse.ArgumentTypeError(
            f"display limit must be between {MIN_DISPLAY_LIMIT} and {MAX_DISPLAY_LIMIT}"
        )
    return value


def build_parser() -> argparse.ArgumentParser:
    """Build the isolated spike argument parser."""

    parser = argparse.ArgumentParser(
        prog="brightdata_marketplace_spike.py",
        description="Experimentally inspect Bright Data Facebook Marketplace results.",
    )
    parser.add_argument("keyword", help="One Facebook Marketplace discovery keyword.")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Send one real request, which may consume Bright Data credits/records.",
    )
    parser.add_argument(
        "--display-limit",
        type=_display_limit,
        default=DEFAULT_DISPLAY_LIMIT,
        metavar="N",
        help=(
            f"Maximum records shown locally (default: {DEFAULT_DISPLAY_LIMIT}; "
            f"range: {MIN_DISPLAY_LIMIT}..{MAX_DISPLAY_LIMIT}). "
            "Display limit does not limit Bright Data records processed or billed."
        ),
    )
    return parser


def _validated_keyword(raw_keyword: str) -> str:
    keyword = raw_keyword.strip()
    if not keyword:
        raise SpikeConfigurationError("keyword must not be blank")
    return keyword


def _request_body(keyword: str) -> dict[str, list[dict[str, str]]]:
    return {"input": [{"keyword": keyword}]}


def _post_once(
    client: httpx.Client,
    configuration: SpikeConfiguration,
    keyword: str,
) -> httpx.Response:
    token = configuration.require_api_token()
    try:
        return client.post(
            BRIGHT_DATA_ENDPOINT,
            params={"dataset_id": configuration.dataset_id},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=_request_body(keyword),
            timeout=configuration.timeout_seconds,
        )
    except httpx.TimeoutException:
        raise BrightDataRequestError("Timeout while waiting for Bright Data") from None
    except httpx.TransportError:
        raise BrightDataRequestError("Connection failure while contacting Bright Data") from None


def _validate_http_status(response: httpx.Response) -> None:
    status = response.status_code
    if status == 200:
        return
    if status == 202:
        raise BrightDataRequestError(
            "Bright Data is still processing the request (HTTP 202); no follow-up request was sent"
        )
    if status == 400:
        raise BrightDataRequestError("Invalid Bright Data request (HTTP 400)")
    if status in {401, 403}:
        raise BrightDataRequestError("Bright Data authentication/authorization error")
    if status == 402:
        raise BrightDataRequestError("Bright Data billing/credits problem (HTTP 402)")
    if status == 429:
        raise BrightDataRequestError("Bright Data rate limit (HTTP 429)")
    if status >= 500:
        raise BrightDataRequestError("Bright Data/server failure")
    raise BrightDataRequestError(f"Unexpected Bright Data HTTP status: {status}")


def _optional_text(record: Mapping[str, object], field_name: str) -> str | None:
    value = record.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise BrightDataResponseError(f"Bright Data field {field_name!r} must be text or null")
    normalized = value.strip()
    return normalized or None


def _optional_product_id(record: Mapping[str, object]) -> str | None:
    value = record.get("product_id")
    if value is None:
        return None
    if isinstance(value, bool):
        raise BrightDataResponseError(
            "Bright Data field 'product_id' must be text, an integer, or null"
        )
    if isinstance(value, (str, int)):
        normalized = str(value).strip()
        return normalized or None
    raise BrightDataResponseError(
        "Bright Data field 'product_id' must be text, an integer, or null"
    )


def _optional_decimal(record: Mapping[str, object], field_name: str) -> Decimal | None:
    value = record.get(field_name)
    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, float):
        raise BrightDataResponseError(
            f"Bright Data field {field_name!r} must be an exact decimal value or null"
        )
    try:
        if isinstance(value, Decimal):
            decimal_value = value
        elif isinstance(value, int):
            decimal_value = Decimal(value)
        elif isinstance(value, str) and value.strip():
            decimal_value = Decimal(value.strip())
        else:
            raise BrightDataResponseError(
                f"Bright Data field {field_name!r} must be an exact decimal value or null"
            )
    except InvalidOperation:
        raise BrightDataResponseError(
            f"Bright Data field {field_name!r} must be an exact decimal value or null"
        ) from None
    if not decimal_value.is_finite():
        raise BrightDataResponseError(f"Bright Data field {field_name!r} must be finite")
    return decimal_value


def parse_marketplace_response(content: bytes) -> tuple[MarketplaceRecord, ...]:
    """Parse a Bright Data JSON list without ever creating binary floats."""

    try:
        payload: object = json.loads(content, parse_float=Decimal)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise BrightDataResponseError("Bright Data returned invalid JSON") from None
    if not isinstance(payload, list):
        raise BrightDataResponseError("Bright Data response must be a JSON list")

    records: list[MarketplaceRecord] = []
    for index, raw_record in enumerate(payload, start=1):
        if not isinstance(raw_record, dict):
            raise BrightDataResponseError(f"Bright Data record {index} must be a JSON object")
        record = cast(dict[str, object], raw_record)
        if not _DOCUMENTED_MARKETPLACE_FIELDS.intersection(record):
            raise BrightDataResponseError(f"Bright Data record {index} has an unexpected structure")
        records.append(
            MarketplaceRecord(
                product_id=_optional_product_id(record),
                title=_optional_text(record, "title"),
                final_price=_optional_decimal(record, "final_price"),
                currency=_optional_text(record, "currency"),
                condition=_optional_text(record, "condition"),
                location=_optional_text(record, "location"),
                country_code=_optional_text(record, "country_code"),
                url=_optional_text(record, "url"),
                listing_date=_optional_text(record, "listing_date"),
            )
        )
    return tuple(records)


def execute_spike(
    configuration: SpikeConfiguration,
    keyword: str,
    *,
    client: httpx.Client | None = None,
) -> SpikeResponse:
    """Make exactly one request and return only the allowlisted response data."""

    if client is None:
        transport = httpx.HTTPTransport(retries=0)
        with httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(configuration.timeout_seconds),
        ) as owned_client:
            response = _post_once(owned_client, configuration, keyword)
    else:
        response = _post_once(client, configuration, keyword)

    _validate_http_status(response)
    records = parse_marketplace_response(response.content)
    return SpikeResponse(http_status=response.status_code, records=records)


def _print_request_plan(
    configuration: SpikeConfiguration,
    keyword: str,
    *,
    execute: bool,
    display_limit: int,
) -> None:
    print("Bright Data Facebook Marketplace spike")
    print()
    print(f"Mode: {'EXECUTE' if execute else 'DRY RUN'}")
    print("Method: POST")
    print(f"Endpoint: {BRIGHT_DATA_ENDPOINT}")
    print(f"Keyword: {keyword}")
    print(f"Dataset ID: {configuration.dataset_id}")
    token_status = "CONFIGURED" if configuration.api_token_configured else "NOT CONFIGURED"
    print(f"API token: {token_status}")
    print(f"Timeout: {configuration.timeout_seconds:g}s")
    print(f"Input items: {len(_request_body(keyword)['input'])}")
    print(f"Display limit: {display_limit} (local output only)")
    print("Cost notice: display limit does not limit Bright Data records processed or billed.")


def _print_optional(label: str, value: object | None) -> None:
    if value is not None:
        print(f"{label}: {value}")


def _print_response(response: SpikeResponse, *, display_limit: int) -> None:
    records = response.records
    displayed_records = records[:display_limit]
    countries = Counter(
        record.country_code for record in records if record.country_code is not None
    )

    print()
    print(f"HTTP status: {response.http_status}")
    print(f"Records returned: {len(records)}")
    print(f"Records displayed: {len(displayed_records)}")
    print()
    if countries:
        print("Countries:")
        for country_code in sorted(countries):
            print(f"{country_code}: {countries[country_code]}")
        print(f"Venezuela records found: {'YES' if countries['VE'] > 0 else 'NO'}")
    else:
        print("Country information unavailable")
        print("Venezuela records found: UNKNOWN")

    for index, record in enumerate(displayed_records, start=1):
        print()
        print(f"[{index}]")
        _print_optional("Product ID", record.product_id)
        _print_optional("Title", record.title)
        _print_optional("Final price", record.final_price)
        _print_optional("Currency", record.currency)
        _print_optional("Condition", record.condition)
        _print_optional("Location", record.location)
        _print_optional("Country code", record.country_code)
        _print_optional("URL", record.url)
        _print_optional("Listing date", record.listing_date)


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    client: httpx.Client | None = None,
) -> int:
    """Run a dry-run plan or one explicitly authorized Bright Data request."""

    namespace = build_parser().parse_args(argv)
    try:
        keyword = _validated_keyword(cast(str, namespace.keyword))
        configuration = SpikeConfiguration.from_env(environ)
    except SpikeConfigurationError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return SpikeExitCode.CONFIGURATION_ERROR

    execute = cast(bool, namespace.execute)
    display_limit = cast(int, namespace.display_limit)
    _print_request_plan(
        configuration,
        keyword,
        execute=execute,
        display_limit=display_limit,
    )
    if not execute:
        print()
        print("DRY RUN — no request sent")
        return SpikeExitCode.SUCCESS

    try:
        response = execute_spike(configuration, keyword, client=client)
    except SpikeConfigurationError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return SpikeExitCode.CONFIGURATION_ERROR
    except BrightDataRequestError as error:
        print(f"Request error: {error}", file=sys.stderr)
        return SpikeExitCode.REQUEST_ERROR
    except BrightDataResponseError as error:
        print(f"Response error: {error}", file=sys.stderr)
        return SpikeExitCode.RESPONSE_ERROR

    _print_response(response, display_limit=display_limit)
    return SpikeExitCode.SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
