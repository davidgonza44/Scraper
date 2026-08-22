"""Cost-bounded Bright Data client for Facebook Marketplace discovery."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import cast
from urllib.parse import quote, urlsplit

import httpx

_SCRAPE_PATH = "/datasets/v3/scrape"
_PROGRESS_PATH = "/datasets/v3/progress"
_SNAPSHOT_PATH = "/datasets/v3/snapshot"
_MAX_RECORDS_PER_INPUT = 5
_PENDING_STATUSES = frozenset({"pending", "starting", "running", "collecting", "digesting"})
_TERMINAL_FAILURE_STATUSES = frozenset({"failed", "canceled"})
_CANDIDATE_FIELDS = frozenset(
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
        "description",
    }
)

type Sleeper = Callable[[float], None]
type MonotonicClock = Callable[[], float]


class BrightDataError(RuntimeError):
    """Base error for sanitized Bright Data failures."""


class BrightDataConfigurationError(BrightDataError):
    """Raised when local Bright Data configuration is unusable."""


class BrightDataConnectionError(BrightDataError):
    """Raised when Bright Data cannot be reached."""


class BrightDataTimeoutError(BrightDataError):
    """Raised when one Bright Data HTTP operation times out."""


class BrightDataHTTPError(BrightDataError):
    """Raised for an unexpected Bright Data HTTP status."""

    def __init__(self, status_code: int, sanitized_body: str | None = None) -> None:
        self.status_code = status_code
        self.sanitized_body = sanitized_body
        super().__init__(f"Bright Data returned HTTP {status_code}")


class BrightDataResponseError(BrightDataError):
    """Raised when the response envelope cannot be interpreted safely."""


class BrightDataPollingTimeoutError(BrightDataError):
    """Raised when an existing snapshot does not finish within the configured bound."""


@dataclass(frozen=True, slots=True)
class BrightDataFacebookCandidate:
    """Allowlisted source fields; description is transient classification input."""

    product_id: str | None
    title: str | None
    final_price: object
    currency: str | None
    condition: str | None
    location: str | None
    country_code: str | None
    url: str | None
    listing_date: str | None
    description: str | None


@dataclass(frozen=True, slots=True)
class BrightDataFacebookResult:
    """Sanitized records and source-boundary counts from one discovery request."""

    records: tuple[BrightDataFacebookCandidate, ...]
    fetched: int
    source_errors: int


class BrightDataFacebookMarketplaceClient:
    """Fetch at most five records for one keyword/city input with no POST retry."""

    def __init__(
        self,
        *,
        api_token: str | None,
        base_url: str,
        dataset_id: str,
        request_timeout_seconds: float,
        poll_interval_seconds: float,
        poll_timeout_seconds: float,
        client: httpx.Client | None = None,
        sleeper: Sleeper = time.sleep,
        monotonic: MonotonicClock = time.monotonic,
    ) -> None:
        self._api_token = _required_text(api_token, "Bright Data API token")
        self._base_url = _normalized_base_url(base_url)
        self._dataset_id = _required_text(dataset_id, "Bright Data dataset ID")
        self._request_timeout = httpx.Timeout(
            _positive_finite(request_timeout_seconds, "Bright Data request timeout")
        )
        self._poll_interval_seconds = _positive_finite(
            poll_interval_seconds, "Bright Data poll interval"
        )
        self._poll_timeout_seconds = _positive_finite(
            poll_timeout_seconds, "Bright Data poll timeout"
        )
        self._client = client
        self._sleeper = sleeper
        self._monotonic = monotonic
        self._headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_token}",
        }

    def fetch(self, keyword: str, city: str, limit: int) -> BrightDataFacebookResult:
        """Run one scrape POST, following only a snapshot returned by that POST."""

        normalized_keyword = _required_text(keyword, "keyword")
        normalized_city = _required_text(city, "city")
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise BrightDataConfigurationError("Bright Data record limit must be an integer")
        if not 1 <= limit <= _MAX_RECORDS_PER_INPUT:
            raise BrightDataConfigurationError(
                f"Bright Data record limit must be between 1 and {_MAX_RECORDS_PER_INPUT}"
            )

        if self._client is not None:
            return self._fetch_with_client(
                self._client,
                keyword=normalized_keyword,
                city=normalized_city,
                limit=limit,
            )

        transport = httpx.HTTPTransport(retries=0)
        with httpx.Client(transport=transport, timeout=self._request_timeout) as owned_client:
            return self._fetch_with_client(
                owned_client,
                keyword=normalized_keyword,
                city=normalized_city,
                limit=limit,
            )

    def _fetch_with_client(
        self,
        client: httpx.Client,
        *,
        keyword: str,
        city: str,
        limit: int,
    ) -> BrightDataFacebookResult:
        response = self._request(
            client,
            "POST",
            _SCRAPE_PATH,
            params={
                "dataset_id": self._dataset_id,
                "notify": "false",
                "include_errors": "true",
                "type": "discover_new",
                "discover_by": "keyword",
                "limit_per_input": str(limit),
            },
            json_body={
                "input": [{"keyword": keyword, "city": city, "date_listed": ""}],
                "limit_per_input": limit,
            },
        )
        if response.status_code == 200:
            return _parse_records(response.content, max_items=limit)
        if response.status_code != 202:
            raise self._http_error(response)

        snapshot_id = _parse_snapshot_id(response.content)
        self._wait_until_ready(client, snapshot_id)
        snapshot_response = self._request(
            client,
            "GET",
            f"{_SNAPSHOT_PATH}/{quote(snapshot_id, safe='')}",
            params={"format": "json"},
        )
        if snapshot_response.status_code != 200:
            raise self._http_error(snapshot_response)
        return _parse_records(snapshot_response.content, max_items=limit)

    def _wait_until_ready(self, client: httpx.Client, snapshot_id: str) -> None:
        deadline = self._monotonic() + self._poll_timeout_seconds
        progress_path = f"{_PROGRESS_PATH}/{quote(snapshot_id, safe='')}"

        while True:
            if self._monotonic() >= deadline:
                raise BrightDataPollingTimeoutError(
                    "Bright Data snapshot polling exceeded its configured timeout"
                )

            response = self._request(client, "GET", progress_path)
            if response.status_code != 200:
                raise self._http_error(response)
            status = _parse_progress_status(response.content)
            if status == "ready":
                return
            if status in _TERMINAL_FAILURE_STATUSES:
                raise BrightDataResponseError(
                    f"Bright Data snapshot finished with status {status!r}"
                )
            if status not in _PENDING_STATUSES:
                raise BrightDataResponseError("Bright Data returned an unknown snapshot status")

            remaining = deadline - self._monotonic()
            if remaining <= 0:
                raise BrightDataPollingTimeoutError(
                    "Bright Data snapshot polling exceeded its configured timeout"
                )
            self._sleeper(min(self._poll_interval_seconds, remaining))

    def _http_error(self, response: httpx.Response) -> BrightDataHTTPError:
        return BrightDataHTTPError(
            response.status_code,
            _sanitized_error_body(response.content, self._api_token),
        )

    def _request(
        self,
        client: httpx.Client,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json_body: Mapping[str, object] | None = None,
    ) -> httpx.Response:
        headers = self._headers
        if json_body is not None:
            headers = {**headers, "Content-Type": "application/json"}
        try:
            return client.request(
                method,
                f"{self._base_url}{path}",
                params=params,
                headers=headers,
                json=json_body,
                timeout=self._request_timeout,
            )
        except httpx.TimeoutException:
            raise BrightDataTimeoutError("Bright Data request timed out") from None
        except httpx.TransportError:
            raise BrightDataConnectionError("Bright Data connection failed") from None


def _required_text(value: str | None, field_name: str) -> str:
    if value is None:
        raise BrightDataConfigurationError(f"{field_name} is required")
    if not isinstance(value, str):
        raise BrightDataConfigurationError(f"{field_name} must be text")
    normalized = value.strip()
    if not normalized:
        raise BrightDataConfigurationError(f"{field_name} must not be blank")
    return normalized


def _positive_finite(value: float, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BrightDataConfigurationError(f"{field_name} must be a number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0:
        raise BrightDataConfigurationError(f"{field_name} must be finite and greater than zero")
    return normalized


def _normalized_base_url(value: str) -> str:
    normalized = _required_text(value, "Bright Data base URL")
    parsed = urlsplit(normalized)
    if parsed.scheme.lower() not in {"http", "https"} or parsed.hostname is None:
        raise BrightDataConfigurationError("Bright Data base URL must be absolute HTTP(S)")
    if parsed.username is not None or parsed.password is not None:
        raise BrightDataConfigurationError("Bright Data base URL must not contain credentials")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise BrightDataConfigurationError(
            "Bright Data base URL must not contain a path, query, or fragment"
        )
    try:
        _ = parsed.port
    except ValueError:
        raise BrightDataConfigurationError(
            "Bright Data base URL contains an invalid port"
        ) from None
    return f"{parsed.scheme.lower()}://{parsed.netloc}".rstrip("/")


def _json_value(content: bytes) -> object:
    try:
        return json.loads(content, parse_float=Decimal)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise BrightDataResponseError("Bright Data returned invalid JSON") from None


def _sanitized_error_body(content: bytes, api_token: str) -> str | None:
    text = content.decode("utf-8", errors="replace").replace(api_token, "[REDACTED]")
    normalized = " ".join(text.split())
    return normalized[:2_000] or None


def _parse_snapshot_id(content: bytes) -> str:
    payload = _json_value(content)
    if not isinstance(payload, dict):
        raise BrightDataResponseError("Bright Data HTTP 202 response must be an object")
    response = cast(dict[str, object], payload)
    snapshot_id = response.get("snapshot_id")
    if not isinstance(snapshot_id, str) or not snapshot_id.strip():
        raise BrightDataResponseError("Bright Data HTTP 202 response lacks a snapshot ID")
    return snapshot_id.strip()


def _parse_progress_status(content: bytes) -> str:
    payload = _json_value(content)
    if not isinstance(payload, dict):
        raise BrightDataResponseError("Bright Data progress response must be an object")
    response = cast(dict[str, object], payload)
    status = response.get("status")
    if not isinstance(status, str) or not status.strip():
        raise BrightDataResponseError("Bright Data progress response lacks a status")
    return status.strip().casefold()


def _parse_records(content: bytes, *, max_items: int) -> BrightDataFacebookResult:
    payload = _json_value(content)
    if not isinstance(payload, list):
        raise BrightDataResponseError("Bright Data results must be a JSON list")

    bounded_payload = payload[:max_items]
    records: list[BrightDataFacebookCandidate] = []
    source_errors = 0
    for raw_item in bounded_payload:
        if not isinstance(raw_item, dict):
            source_errors += 1
            continue
        item = cast(dict[str, object], raw_item)
        if "error" in item or "error_code" in item or not _CANDIDATE_FIELDS.intersection(item):
            source_errors += 1
            continue
        try:
            records.append(_parse_candidate(item))
        except (TypeError, ValueError):
            source_errors += 1

    return BrightDataFacebookResult(
        records=tuple(records),
        fetched=len(bounded_payload),
        source_errors=source_errors,
    )


def _parse_candidate(item: Mapping[str, object]) -> BrightDataFacebookCandidate:
    return BrightDataFacebookCandidate(
        product_id=_optional_product_id(item.get("product_id")),
        title=_optional_text(item.get("title"), "title"),
        final_price=item.get("final_price"),
        currency=_optional_text(item.get("currency"), "currency"),
        condition=_optional_text(item.get("condition"), "condition"),
        location=_optional_text(item.get("location"), "location"),
        country_code=_optional_text(item.get("country_code"), "country_code"),
        url=_optional_text(item.get("url"), "url"),
        listing_date=_optional_text(item.get("listing_date"), "listing_date"),
        description=_optional_text(item.get("description"), "description"),
    )


def _optional_product_id(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise TypeError("product_id must be text, an integer, or null")
    normalized = str(value).strip()
    return normalized or None


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be text or null")
    normalized = value.strip()
    return normalized or None
