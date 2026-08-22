"""Offline contract coverage for the production Bright Data client."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from bera_price_tracker.infrastructure.providers import (
    BrightDataConfigurationError,
    BrightDataFacebookMarketplaceClient,
    BrightDataHTTPError,
    BrightDataPollingTimeoutError,
)


def _client(
    handler: httpx.MockTransport,
    *,
    sleeper: Callable[[float], None] | None = None,
    monotonic: Callable[[], float] | None = None,
    poll_timeout: float = 60.0,
) -> tuple[BrightDataFacebookMarketplaceClient, httpx.Client]:
    http_client = httpx.Client(transport=handler)
    return (
        BrightDataFacebookMarketplaceClient(
            api_token="test-token",
            base_url="https://api.brightdata.test",
            dataset_id="dataset-1",
            request_timeout_seconds=10.0,
            poll_interval_seconds=5.0,
            poll_timeout_seconds=poll_timeout,
            client=http_client,
            sleeper=sleeper or (lambda _seconds: None),
            monotonic=monotonic or (lambda: 0.0),
        ),
        http_client,
    )


def test_http_200_sends_one_bounded_input_and_keeps_only_allowlisted_fields() -> None:
    requests: list[httpx.Request] = []
    items: list[dict[str, object]] = [
        {
            "product_id": "FB-1",
            "title": "Pastillas Honda CG125 ES4",
            "final_price": 12.75,
            "currency": "USD",
            "condition": "new",
            "location": "Caracas",
            "country_code": "VE",
            "url": "https://facebook.example/FB-1",
            "listing_date": "2026-08-21",
            "description": "Pastillas de freno",
            "cookies": "private-cookie",
            "profile_id": "private-profile",
            "seller_description": "private-seller",
            "phone": "+58 000 0000000",
            "images": ["private-image"],
        },
        {"error": "Redirect to login page.", "error_code": "bad_input"},
        {"product_id": "FB-2", "title": "two"},
        {"product_id": "FB-3", "title": "three"},
        {"product_id": "FB-4", "title": "four"},
        {"product_id": "FB-5", "title": "must be locally bounded"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=items, request=request)

    client, http_client = _client(httpx.MockTransport(handler))
    try:
        result = client.fetch(keyword="pastilla bera sbr", city="caracas", limit=5)
    finally:
        http_client.close()

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/datasets/v3/scrape"
    assert request.url.params["dataset_id"] == "dataset-1"
    assert request.url.params["notify"] == "false"
    assert request.url.params["include_errors"] == "true"
    assert request.url.params["type"] == "discover_new"
    assert request.url.params["discover_by"] == "keyword"
    assert request.url.params["limit_per_input"] == "5"
    assert "format" not in request.url.params
    assert json.loads(request.content) == {
        "input": [
            {
                "keyword": "pastilla bera sbr",
                "city": "caracas",
                "date_listed": "",
            }
        ],
        "limit_per_input": 5,
    }
    assert result.fetched == 5
    assert result.source_errors == 1
    assert [record.product_id for record in result.records] == ["FB-1", "FB-2", "FB-3", "FB-4"]
    first = result.records[0]
    assert str(first.final_price) == "12.75"
    assert first.description == "Pastillas de freno"
    assert not hasattr(first, "cookies")
    assert not hasattr(first, "profile_id")
    assert "private" not in repr(first)


def test_http_202_polls_and_downloads_only_the_returned_snapshot() -> None:
    requests: list[httpx.Request] = []
    progress_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal progress_calls
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(202, json={"snapshot_id": "snap-1"}, request=request)
        if request.url.path == "/datasets/v3/progress/snap-1":
            progress_calls += 1
            status = "running" if progress_calls == 1 else "ready"
            return httpx.Response(200, json={"status": status}, request=request)
        assert request.url.path == "/datasets/v3/snapshot/snap-1"
        return httpx.Response(
            200,
            json=[{"product_id": "FB-1", "title": "Pastillas H0019"}],
            request=request,
        )

    client, http_client = _client(
        httpx.MockTransport(handler),
        sleeper=lambda _seconds: None,
        monotonic=lambda: 0.0,
    )
    try:
        result = client.fetch(keyword="pastillas", city="caracas", limit=5)
    finally:
        http_client.close()

    assert result.records[0].product_id == "FB-1"
    assert sum(request.method == "POST" for request in requests) == 1
    assert [request.url.path for request in requests] == [
        "/datasets/v3/scrape",
        "/datasets/v3/progress/snap-1",
        "/datasets/v3/progress/snap-1",
        "/datasets/v3/snapshot/snap-1",
    ]


def test_snapshot_polling_timeout_never_repeats_the_scrape_post() -> None:
    requests: list[httpx.Request] = []
    now = [0.0]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(202, json={"snapshot_id": "snap-timeout"}, request=request)
        return httpx.Response(200, json={"status": "running"}, request=request)

    def sleep(seconds: float) -> None:
        now[0] += seconds

    client, http_client = _client(
        httpx.MockTransport(handler),
        sleeper=sleep,
        monotonic=lambda: now[0],
        poll_timeout=5.0,
    )
    try:
        with pytest.raises(BrightDataPollingTimeoutError, match="polling"):
            client.fetch(keyword="pastillas", city="caracas", limit=5)
    finally:
        http_client.close()

    assert sum(request.method == "POST" for request in requests) == 1
    assert all(request.url.path != "/datasets/v3/snapshot/snap-timeout" for request in requests)


def test_invalid_limit_is_rejected_before_any_http_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[], request=request)

    client, http_client = _client(httpx.MockTransport(handler))
    try:
        with pytest.raises(BrightDataConfigurationError, match="between 1 and 5"):
            client.fetch(keyword="pastillas", city="caracas", limit=6)
    finally:
        http_client.close()

    assert requests == []


def test_http_failure_captures_diagnostic_body_without_exposing_the_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            text="invalid token test-token\nprovider diagnostic",
            request=request,
        )

    client, http_client = _client(httpx.MockTransport(handler))
    try:
        with pytest.raises(BrightDataHTTPError) as raised:
            client.fetch(keyword="pastillas", city="caracas", limit=5)
    finally:
        http_client.close()

    assert raised.value.status_code == 401
    assert raised.value.sanitized_body == "invalid token [REDACTED] provider diagnostic"
    assert "test-token" not in str(raised.value)
    assert "test-token" not in (raised.value.sanitized_body or "")
