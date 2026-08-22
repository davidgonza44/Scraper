"""Offline tests for Mercado Libre HTTP failures and retry policy."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest

from bera_price_tracker.domain import SearchQuery
from bera_price_tracker.infrastructure.providers import (
    MercadoLibreAuthenticationError,
    MercadoLibreConfigurationError,
    MercadoLibreConnectionError,
    MercadoLibreHTTPError,
    MercadoLibreProvider,
    MercadoLibreRateLimitError,
)

type Handler = Callable[[httpx.Request], httpx.Response]

_FIXED_TIME = datetime(2026, 8, 21, 15, 0, tzinfo=UTC)
_TOKEN = "offline-secret-token"


def _empty_response(
    request: httpx.Request,
    status_code: int = 200,
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        json={"paging": {"total": 0}, "results": []},
        headers=headers,
        request=request,
    )


def _provider(
    handler: Handler,
    *,
    max_retries: int = 2,
    sleeps: list[float] | None = None,
    access_token: str = _TOKEN,
) -> MercadoLibreProvider:
    delays = [] if sleeps is None else sleeps
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return MercadoLibreProvider(
        site_id="MLV",
        access_token=access_token,
        max_retries=max_retries,
        client=client,
        sleeper=delays.append,
        jitter=lambda: 0.0,
        clock=lambda: _FIXED_TIME,
    )


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (400, MercadoLibreHTTPError),
        (401, MercadoLibreAuthenticationError),
        (403, MercadoLibreAuthenticationError),
        (404, MercadoLibreHTTPError),
    ],
)
def test_non_transient_http_errors_are_not_retried(
    status_code: int,
    error_type: type[Exception],
) -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return _empty_response(request, status_code)

    with pytest.raises(error_type):
        _provider(handler).search(SearchQuery("pastillas bera"))

    assert request_count == 1


def test_429_is_retried_then_succeeds() -> None:
    request_count = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            return _empty_response(request, 429)
        return _empty_response(request)

    result = _provider(handler, max_retries=1, sleeps=sleeps).search(SearchQuery("pastillas bera"))

    assert result == []
    assert request_count == 2
    assert sleeps == [0.5]


def test_retry_after_is_respected_without_real_sleep() -> None:
    request_count = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            return _empty_response(request, 429, headers={"Retry-After": "7"})
        return _empty_response(request)

    _provider(handler, max_retries=1, sleeps=sleeps).search(SearchQuery("pastillas bera"))

    assert sleeps == [7.0]


def test_500_is_retried_then_succeeds() -> None:
    request_count = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return _empty_response(request, 500 if request_count == 1 else 200)

    result = _provider(handler, max_retries=1, sleeps=sleeps).search(SearchQuery("pastillas bera"))

    assert result == []
    assert request_count == 2
    assert sleeps == [0.5]


def test_timeout_is_retried_then_succeeds() -> None:
    request_count = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            raise httpx.ReadTimeout("offline timeout", request=request)
        return _empty_response(request)

    result = _provider(handler, max_retries=1, sleeps=sleeps).search(SearchQuery("pastillas bera"))

    assert result == []
    assert request_count == 2
    assert sleeps == [0.5]


def test_connection_error_is_retried_then_succeeds() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            raise httpx.ConnectError("offline connection error", request=request)
        return _empty_response(request)

    result = _provider(handler, max_retries=1).search(SearchQuery("pastillas bera"))

    assert result == []
    assert request_count == 2


def test_transient_http_retry_exhaustion_is_explicit() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return _empty_response(request, 503)

    with pytest.raises(MercadoLibreHTTPError, match="retries were exhausted") as captured:
        _provider(handler, max_retries=2).search(SearchQuery("pastillas bera"))

    assert captured.value.status_code == 503
    assert request_count == 3


def test_rate_limit_retry_exhaustion_is_distinct() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return _empty_response(request, 429)

    with pytest.raises(MercadoLibreRateLimitError):
        _provider(handler, max_retries=1).search(SearchQuery("pastillas bera"))

    assert request_count == 2


def test_timeout_retry_exhaustion_is_distinct() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        raise httpx.ReadTimeout("offline timeout", request=request)

    with pytest.raises(MercadoLibreConnectionError, match="timed out"):
        _provider(handler, max_retries=1).search(SearchQuery("pastillas bera"))

    assert request_count == 2


def test_token_is_absent_from_logs_and_exceptions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)

    def handler(request: httpx.Request) -> httpx.Response:
        return _empty_response(request, 401)

    with pytest.raises(MercadoLibreAuthenticationError) as captured:
        _provider(handler, max_retries=0, access_token=_TOKEN).search(SearchQuery("pastillas bera"))

    assert _TOKEN not in str(captured.value)
    assert _TOKEN not in caplog.text


def test_missing_required_configuration_is_rejected_before_http() -> None:
    with pytest.raises(MercadoLibreConfigurationError, match="SITE_ID"):
        MercadoLibreProvider(site_id=None, access_token=_TOKEN)
    with pytest.raises(MercadoLibreConfigurationError, match="ACCESS_TOKEN"):
        MercadoLibreProvider(site_id="MLV", access_token=None)


def test_unsafe_limits_are_rejected_before_http() -> None:
    with pytest.raises(MercadoLibreConfigurationError, match="page_size"):
        MercadoLibreProvider(site_id="MLV", access_token=_TOKEN, page_size=101)
    with pytest.raises(MercadoLibreConfigurationError, match="1000"):
        MercadoLibreProvider(
            site_id="MLV",
            access_token=_TOKEN,
            page_size=100,
            max_pages=11,
        )
    with pytest.raises(MercadoLibreConfigurationError, match="timeout"):
        MercadoLibreProvider(site_id="MLV", access_token=_TOKEN, timeout_seconds=0)
    with pytest.raises(MercadoLibreConfigurationError, match="max_retries"):
        MercadoLibreProvider(site_id="MLV", access_token=_TOKEN, max_retries=-1)
