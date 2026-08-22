"""Synchronous adapter for Mercado Libre's official search API."""

from __future__ import annotations

import json
import logging
import math
import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from email.utils import parsedate_to_datetime
from typing import cast
from urllib.parse import quote

import httpx

from bera_price_tracker import __version__
from bera_price_tracker.config import is_valid_mercadolibre_site_id
from bera_price_tracker.domain import Listing, MarketplaceSource, SearchQuery
from bera_price_tracker.infrastructure.providers.mercado_libre_errors import (
    MercadoLibreAuthenticationError,
    MercadoLibreConfigurationError,
    MercadoLibreConnectionError,
    MercadoLibreHTTPError,
    MercadoLibreInvalidJSONError,
    MercadoLibreInvalidResponseError,
    MercadoLibreRateLimitError,
)

_API_BASE_URL = "https://api.mercadolibre.com"
_MAX_PAGE_SIZE = 100
_MAX_RESULTS = 1_000
_MAX_RETRIES = 5
_MAX_RETRY_DELAY_SECONDS = 30.0
_TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_logger = logging.getLogger(__name__)

type Sleeper = Callable[[float], None]
type Jitter = Callable[[], float]
type Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class _SearchPage:
    items: list[object]
    total: int


class MercadoLibreProvider:
    """Search Mercado Libre listings through the official REST API."""

    def __init__(
        self,
        *,
        site_id: str | None,
        access_token: str | None,
        page_size: int = 50,
        max_pages: int = 3,
        timeout_seconds: float = 10.0,
        max_retries: int = 2,
        client: httpx.Client | None = None,
        sleeper: Sleeper = time.sleep,
        jitter: Jitter = random.random,
        clock: Clock = _utc_now,
    ) -> None:
        self._site_id = self._validate_site_id(site_id)
        self._access_token = self._validate_access_token(access_token)
        self._validate_limits(page_size, max_pages, timeout_seconds, max_retries)

        self._page_size = page_size
        self._max_pages = max_pages
        self._timeout = httpx.Timeout(timeout_seconds)
        self._max_retries = max_retries
        self._client = client
        self._sleeper = sleeper
        self._jitter = jitter
        self._clock = clock
        self._url = f"{_API_BASE_URL}/sites/{quote(self._site_id, safe='')}/search"
        self._headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._access_token}",
            "User-Agent": f"bera-price-tracker/{__version__}",
        }

    @property
    def source(self) -> MarketplaceSource:
        return MarketplaceSource.MERCADO_LIBRE

    def search(self, query: SearchQuery) -> list[Listing]:
        """Return normalized listings for ``query`` using bounded pagination."""

        _logger.info(
            "provider=mercado_libre site_id=%s query=%r page_size=%d max_pages=%d",
            self._site_id,
            query.text,
            self._page_size,
            self._max_pages,
        )
        collected_at = self._collected_at()
        if self._client is not None:
            return self._search_with_client(self._client, query, collected_at)

        with httpx.Client(headers=self._headers, timeout=self._timeout) as client:
            return self._search_with_client(client, query, collected_at)

    def _search_with_client(
        self,
        client: httpx.Client,
        query: SearchQuery,
        collected_at: datetime,
    ) -> list[Listing]:
        listings: list[Listing] = []
        offset = 0

        for page_number in range(1, self._max_pages + 1):
            params = self._build_params(query, offset)
            response = self._request(client, params, page_number)
            page = self._parse_page(response)
            received_count = len(page.items)

            if received_count == 0:
                _logger.info(
                    "provider=mercado_libre site_id=%s page=%d offset=%d results=0",
                    self._site_id,
                    page_number,
                    offset,
                )
                break

            remaining_capacity = _MAX_RESULTS - len(listings)
            items = page.items[: min(self._page_size, remaining_capacity)]
            accepted_count = 0
            for raw_item in items:
                try:
                    listing = self._normalize_item(raw_item, query, collected_at)
                except (TypeError, ValueError):
                    _logger.warning(
                        "provider=mercado_libre site_id=%s item_id=%s discarded_invalid_item",
                        self._site_id,
                        self._safe_item_id(raw_item),
                    )
                    continue
                listings.append(listing)
                accepted_count += 1

            _logger.info(
                "provider=mercado_libre site_id=%s page=%d offset=%d received=%d accepted=%d",
                self._site_id,
                page_number,
                offset,
                received_count,
                accepted_count,
            )

            next_offset = offset + self._page_size
            if (
                received_count < self._page_size
                or next_offset >= page.total
                or len(listings) >= _MAX_RESULTS
            ):
                break
            offset = next_offset

        return listings

    def _build_params(self, query: SearchQuery, offset: int) -> dict[str, str | int]:
        return {"q": query.text, "limit": self._page_size, "offset": offset}

    def _request(
        self,
        client: httpx.Client,
        params: Mapping[str, str | int],
        page_number: int,
    ) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            try:
                response = client.get(
                    self._url,
                    params=params,
                    headers=self._headers,
                    timeout=self._timeout,
                )
            except httpx.TimeoutException:
                if attempt >= self._max_retries:
                    raise MercadoLibreConnectionError(
                        "Mercado Libre request timed out after retry exhaustion"
                    ) from None
                self._wait_before_retry(attempt, page_number, reason="timeout")
                continue
            except httpx.TransportError:
                if attempt >= self._max_retries:
                    raise MercadoLibreConnectionError(
                        "Mercado Libre connection failed after retry exhaustion"
                    ) from None
                self._wait_before_retry(attempt, page_number, reason="connection")
                continue

            if response.status_code in _TRANSIENT_STATUS_CODES:
                if attempt >= self._max_retries:
                    if response.status_code == 429:
                        raise MercadoLibreRateLimitError
                    raise MercadoLibreHTTPError(
                        response.status_code,
                        f"Mercado Libre HTTP {response.status_code} retries were exhausted",
                    )
                delay = self._retry_delay(attempt, response)
                self._log_retry(attempt, page_number, str(response.status_code), delay)
                self._sleeper(delay)
                continue

            self._validate_http(response)
            return response

        raise AssertionError("bounded retry loop exited unexpectedly")

    def _wait_before_retry(self, attempt: int, page_number: int, *, reason: str) -> None:
        delay = self._exponential_delay(attempt)
        self._log_retry(attempt, page_number, reason, delay)
        self._sleeper(delay)

    def _log_retry(self, attempt: int, page_number: int, reason: str, delay: float) -> None:
        _logger.warning(
            "provider=mercado_libre site_id=%s page=%d retry=%d/%d reason=%s delay_seconds=%.3f",
            self._site_id,
            page_number,
            attempt + 1,
            self._max_retries,
            reason,
            delay,
        )

    def _retry_delay(self, attempt: int, response: httpx.Response) -> float:
        if response.status_code == 429:
            retry_after = self._parse_retry_after(response.headers.get("Retry-After"))
            if retry_after is not None:
                return retry_after
        return self._exponential_delay(attempt)

    def _exponential_delay(self, attempt: int) -> float:
        jitter = self._jitter()
        if not math.isfinite(jitter):
            jitter = 0.0
        bounded_jitter = min(max(jitter, 0.0), 1.0) * 0.25
        return float(min(0.5 * (2**attempt) + bounded_jitter, _MAX_RETRY_DELAY_SECONDS))

    def _parse_retry_after(self, raw_value: str | None) -> float | None:
        if raw_value is None:
            return None
        value = raw_value.strip()
        try:
            seconds = float(value)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
            except (TypeError, ValueError, OverflowError):
                return None
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            seconds = (retry_at.astimezone(UTC) - self._clock().astimezone(UTC)).total_seconds()
        if not math.isfinite(seconds) or seconds < 0:
            return None
        return min(seconds, _MAX_RETRY_DELAY_SECONDS)

    @staticmethod
    def _validate_http(response: httpx.Response) -> None:
        if response.status_code in {401, 403}:
            raise MercadoLibreAuthenticationError(response.status_code)
        if response.status_code == 429:
            raise MercadoLibreRateLimitError
        if response.status_code >= 400:
            raise MercadoLibreHTTPError(response.status_code)

    @staticmethod
    def _parse_page(response: httpx.Response) -> _SearchPage:
        try:
            payload: object = response.json(parse_float=Decimal)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise MercadoLibreInvalidJSONError("Mercado Libre returned invalid JSON") from None

        if not isinstance(payload, dict):
            raise MercadoLibreInvalidResponseError("Mercado Libre response must be an object")
        body = cast(dict[str, object], payload)
        results = body.get("results")
        paging = body.get("paging")
        if not isinstance(results, list):
            raise MercadoLibreInvalidResponseError(
                "Mercado Libre response field 'results' must be a list"
            )
        if not isinstance(paging, dict):
            raise MercadoLibreInvalidResponseError(
                "Mercado Libre response field 'paging' must be an object"
            )
        paging_body = cast(dict[str, object], paging)
        total = paging_body.get("total")
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise MercadoLibreInvalidResponseError(
                "Mercado Libre response field 'paging.total' must be a non-negative integer"
            )
        return _SearchPage(items=cast(list[object], results), total=total)

    @staticmethod
    def _normalize_item(
        raw_item: object,
        query: SearchQuery,
        collected_at: datetime,
    ) -> Listing:
        if not isinstance(raw_item, dict):
            raise TypeError("item must be an object")
        item = cast(dict[str, object], raw_item)
        return Listing(
            source=MarketplaceSource.MERCADO_LIBRE,
            external_id=MercadoLibreProvider._required_item_text(item, "id"),
            title=MercadoLibreProvider._required_item_text(item, "title"),
            price=MercadoLibreProvider._item_price(item.get("price")),
            currency=MercadoLibreProvider._required_item_text(item, "currency_id"),
            url=MercadoLibreProvider._required_item_text(item, "permalink"),
            seller_name=MercadoLibreProvider._seller_name(item),
            location=MercadoLibreProvider._location(item),
            product_condition=MercadoLibreProvider._optional_item_text(item, "condition"),
            query=query,
            collected_at=collected_at,
        )

    @staticmethod
    def _required_item_text(item: Mapping[str, object], field_name: str) -> str:
        value = item.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"item field {field_name!r} must be a non-blank string")
        return value

    @staticmethod
    def _optional_item_text(item: Mapping[str, object], field_name: str) -> str | None:
        value = item.get(field_name)
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"item field {field_name!r} must be a non-blank string or null")
        return value

    @staticmethod
    def _item_price(value: object) -> Decimal:
        if isinstance(value, bool):
            raise TypeError("item price must be numeric")
        if isinstance(value, Decimal):
            return value
        if isinstance(value, int):
            return Decimal(value)
        raise TypeError("item price must be an integer or decimal JSON number")

    @staticmethod
    def _seller_name(item: Mapping[str, object]) -> str | None:
        seller = item.get("seller")
        if not isinstance(seller, dict):
            return None
        seller_body = cast(dict[str, object], seller)
        for field_name in ("nickname", "name"):
            value = seller_body.get(field_name)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _location(item: Mapping[str, object]) -> str | None:
        direct_location = item.get("location")
        if isinstance(direct_location, str) and direct_location.strip():
            return direct_location.strip()

        for field_name in ("address", "seller_address", "location"):
            address = item.get(field_name)
            if not isinstance(address, dict):
                continue
            address_body = cast(dict[str, object], address)
            city = MercadoLibreProvider._location_part(address_body, "city_name", "city")
            state = MercadoLibreProvider._location_part(address_body, "state_name", "state")
            parts = [part for part in (city, state) if part is not None]
            if len(parts) == 2 and parts[0] == parts[1]:
                parts.pop()
            if parts:
                return ", ".join(parts)
        return None

    @staticmethod
    def _location_part(
        address: Mapping[str, object],
        flat_field: str,
        nested_field: str,
    ) -> str | None:
        flat_value = address.get(flat_field)
        if isinstance(flat_value, str) and flat_value.strip():
            return flat_value.strip()

        nested_value = address.get(nested_field)
        if not isinstance(nested_value, dict):
            return None
        name = cast(dict[str, object], nested_value).get("name")
        return name.strip() if isinstance(name, str) and name.strip() else None

    @staticmethod
    def _safe_item_id(raw_item: object) -> str:
        if isinstance(raw_item, dict):
            value = cast(dict[str, object], raw_item).get("id")
            if isinstance(value, str) and value.strip():
                return value.strip()
        return "unknown"

    def _collected_at(self) -> datetime:
        timestamp = self._clock()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise MercadoLibreConfigurationError("provider clock must be timezone-aware")
        return timestamp.astimezone(UTC)

    @staticmethod
    def _validate_site_id(site_id: str | None) -> str:
        if site_id is None or not site_id.strip():
            raise MercadoLibreConfigurationError("BERA_TRACKER_MERCADOLIBRE_SITE_ID is required")
        normalized = site_id.strip().upper()
        if not is_valid_mercadolibre_site_id(normalized):
            raise MercadoLibreConfigurationError(
                "Mercado Libre site ID contains invalid characters"
            )
        return normalized

    @staticmethod
    def _validate_access_token(access_token: str | None) -> str:
        if access_token is None or not access_token.strip():
            raise MercadoLibreConfigurationError(
                "BERA_TRACKER_MERCADOLIBRE_ACCESS_TOKEN is required"
            )
        return access_token.strip()

    @staticmethod
    def _validate_limits(
        page_size: int,
        max_pages: int,
        timeout_seconds: float,
        max_retries: int,
    ) -> None:
        if page_size <= 0 or page_size > _MAX_PAGE_SIZE:
            raise MercadoLibreConfigurationError(
                f"page_size must be between 1 and {_MAX_PAGE_SIZE}"
            )
        if max_pages <= 0:
            raise MercadoLibreConfigurationError("max_pages must be greater than zero")
        if page_size * max_pages > _MAX_RESULTS:
            raise MercadoLibreConfigurationError(
                f"page_size * max_pages must not exceed {_MAX_RESULTS}"
            )
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise MercadoLibreConfigurationError(
                "timeout_seconds must be finite and greater than zero"
            )
        if max_retries < 0 or max_retries > _MAX_RETRIES:
            raise MercadoLibreConfigurationError(
                f"max_retries must be between 0 and {_MAX_RETRIES}"
            )
