"""Offline tests for Mercado Libre search mapping and pagination."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import httpx
import pytest

from bera_price_tracker.application import MarketplaceProvider
from bera_price_tracker.domain import MarketplaceSource, SearchQuery
from bera_price_tracker.infrastructure.providers import (
    MercadoLibreInvalidJSONError,
    MercadoLibreInvalidResponseError,
    MercadoLibreProvider,
)

type Handler = Callable[[httpx.Request], httpx.Response]

_FIXED_TIME = datetime(2026, 8, 21, 15, 0, tzinfo=UTC)
_TOKEN = "offline-test-token"


def _item(
    external_id: str = "MLV-123",
    *,
    title: str = "Pastillas de freno BERA",
    price: object = 19.99,
    include_optional: bool = True,
) -> dict[str, object]:
    item: dict[str, object] = {
        "id": external_id,
        "title": title,
        "price": price,
        "currency_id": "USD",
        "permalink": f"https://articulo.example/{external_id}",
    }
    if include_optional:
        item.update(
            {
                "condition": "new",
                "seller": {"id": 123, "nickname": "REPUESTOS_BERA"},
                "address": {"city_name": "Caracas", "state_name": "Distrito Capital"},
            }
        )
    return item


def _response(
    request: httpx.Request,
    *,
    items: list[object] | None = None,
    total: int | None = None,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    results = [] if items is None else items
    body = {"paging": {"total": len(results) if total is None else total}, "results": results}
    return httpx.Response(status_code, json=body, headers=headers, request=request)


def _no_sleep(_: float) -> None:
    return None


def _fixed_clock() -> datetime:
    return _FIXED_TIME


def _provider(
    handler: Handler,
    *,
    site_id: str = "MLV",
    page_size: int = 50,
    max_pages: int = 3,
    max_retries: int = 2,
    timeout_seconds: float = 10.0,
    clock: Callable[[], datetime] = _fixed_clock,
) -> MercadoLibreProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return MercadoLibreProvider(
        site_id=site_id,
        access_token=_TOKEN,
        page_size=page_size,
        max_pages=max_pages,
        max_retries=max_retries,
        timeout_seconds=timeout_seconds,
        client=client,
        sleeper=_no_sleep,
        jitter=lambda: 0.0,
        clock=clock,
    )


def test_request_and_full_listing_mapping() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(request, items=[_item()], total=1)

    provider = _provider(handler, timeout_seconds=7.5)
    query = SearchQuery("pastillas de freno bera")

    listings = provider.search(query)

    assert isinstance(provider, MarketplaceProvider)
    assert provider.source is MarketplaceSource.MERCADO_LIBRE
    assert len(requests) == 1
    request = requests[0]
    assert request.url.path == "/sites/MLV/search"
    assert request.url.params["q"] == query.text
    assert request.url.params["limit"] == "50"
    assert request.url.params["offset"] == "0"
    assert request.headers["Authorization"] == f"Bearer {_TOKEN}"
    assert request.headers["User-Agent"] == "bera-price-tracker/0.1.0"
    assert _TOKEN not in str(request.url)
    timeout = cast(dict[str, float], request.extensions["timeout"])
    assert timeout["connect"] == 7.5

    listing = listings[0]
    assert listing.external_id == "MLV-123"
    assert listing.title == "Pastillas de freno BERA"
    assert listing.price == Decimal("19.99")
    assert listing.currency == "USD"
    assert listing.url == "https://articulo.example/MLV-123"
    assert listing.product_condition == "new"
    assert listing.seller_name == "REPUESTOS_BERA"
    assert listing.location == "Caracas, Distrito Capital"
    assert listing.query == query
    assert listing.collected_at == _FIXED_TIME


def test_configured_site_id_is_used_without_a_hardcoded_country() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return _response(request)

    _provider(handler, site_id="MLA").search(SearchQuery("pastillas bera"))

    assert paths == ["/sites/MLA/search"]


def test_optional_fields_are_none_when_absent() -> None:
    provider = _provider(
        lambda request: _response(request, items=[_item(include_optional=False)], total=1)
    )

    listing = provider.search(SearchQuery("pastillas bera"))[0]

    assert listing.seller_name is None
    assert listing.location is None
    assert listing.product_condition is None


def test_optional_null_and_invalid_infrastructure_values_become_none() -> None:
    item = _item(include_optional=False)
    item.update(
        {
            "seller": ["not", "a", "seller"],
            "address": None,
            "seller_address": ["not", "an", "address"],
            "location": {"city": {"name": ["not", "text"]}},
            "condition": None,
        }
    )
    provider = _provider(lambda request: _response(request, items=[item], total=1))

    listing = provider.search(SearchQuery("pastillas bera"))[0]

    assert listing.seller_name is None
    assert listing.location is None
    assert listing.product_condition is None


@pytest.mark.parametrize(
    ("field_name", "raw_location", "expected"),
    [
        (
            "address",
            {"city": {"name": "Caracas"}, "state": {"name": "Distrito Capital"}},
            "Caracas, Distrito Capital",
        ),
        ("seller_address", {"city": {"name": "Maracay"}, "state": None}, "Maracay"),
        (
            "location",
            {"city_name": "Valencia", "state": {"name": "Carabobo"}},
            "Valencia, Carabobo",
        ),
        ("address", {"city": {"name": None}, "state": {"name": []}}, None),
    ],
)
def test_location_is_normalized_only_from_usable_text(
    field_name: str,
    raw_location: object,
    expected: str | None,
) -> None:
    item = _item(include_optional=False)
    item[field_name] = raw_location
    provider = _provider(lambda request: _response(request, items=[item], total=1))

    listing = provider.search(SearchQuery("pastillas bera"))[0]

    assert listing.location == expected
    assert listing.location is None or isinstance(listing.location, str)


@pytest.mark.parametrize(
    ("seller", "expected"),
    [
        (None, None),
        ([], None),
        ({}, None),
        ({"nickname": None}, None),
        ({"nickname": {"value": "not text"}}, None),
        ({"nickname": "  ", "name": " Repuestos Centro "}, "Repuestos Centro"),
        ({"nickname": " TIENDA_BERA ", "name": "Ignored fallback"}, "TIENDA_BERA"),
    ],
)
def test_seller_name_is_only_a_usable_string(seller: object, expected: str | None) -> None:
    item = _item(include_optional=False)
    item["seller"] = seller
    provider = _provider(lambda request: _response(request, items=[item], total=1))

    listing = provider.search(SearchQuery("pastillas bera"))[0]

    assert listing.seller_name == expected
    assert listing.seller_name is None or isinstance(listing.seller_name, str)


@pytest.mark.parametrize("literal", ["19.99", "0.1", "1250.50"])
def test_decimal_json_numbers_preserve_their_exact_representation(literal: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        content = (
            '{"paging":{"total":1},"results":[{'
            '"id":"MLV-DECIMAL","title":"Pastillas BERA",'
            f'"price":{literal},"currency_id":"USD",'
            '"permalink":"https://articulo.example/MLV-DECIMAL"}]}'
        ).encode()
        return httpx.Response(
            200,
            content=content,
            headers={"Content-Type": "application/json"},
            request=request,
        )

    listing = _provider(handler).search(SearchQuery("pastillas bera"))[0]

    assert listing.price == Decimal(literal)
    assert str(listing.price) == literal


def test_invalid_item_is_discarded_without_losing_valid_items(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    provider = _provider(
        lambda request: _response(
            request,
            items=[_item("MLV-BAD", title=""), _item("MLV-GOOD")],
            total=2,
        )
    )

    listings = provider.search(SearchQuery("pastillas bera"))

    assert [listing.external_id for listing in listings] == ["MLV-GOOD"]
    assert "MLV-BAD" in caplog.text
    assert "discarded_invalid_item" in caplog.text
    assert "Pastillas de freno BERA" not in caplog.text


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"paging": {"total": 0}},
        {"paging": [], "results": []},
        {"paging": {"total": "one"}, "results": []},
    ],
)
def test_structurally_invalid_payload_fails(payload: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    with pytest.raises(MercadoLibreInvalidResponseError):
        _provider(handler).search(SearchQuery("pastillas bera"))


def test_invalid_json_fails_explicitly() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json", request=request)

    with pytest.raises(MercadoLibreInvalidJSONError):
        _provider(handler).search(SearchQuery("pastillas bera"))


def test_empty_page_stops_without_results() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return _response(request, items=[], total=20)

    assert _provider(handler, page_size=2).search(SearchQuery("pastillas bera")) == []
    assert request_count == 1


def test_two_pages_use_limit_and_offset() -> None:
    offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["offset"])
        offsets.append(offset)
        if offset == 0:
            return _response(
                request,
                items=[_item("MLV-1"), _item("MLV-2")],
                total=3,
            )
        return _response(request, items=[_item("MLV-3")], total=3)

    listings = _provider(handler, page_size=2).search(SearchQuery("pastillas bera"))

    assert offsets == [0, 2]
    assert [listing.external_id for listing in listings] == ["MLV-1", "MLV-2", "MLV-3"]


def test_all_pages_in_one_search_share_a_single_collected_at() -> None:
    clock_calls = 0

    def clock() -> datetime:
        nonlocal clock_calls
        timestamp = _FIXED_TIME + timedelta(seconds=clock_calls)
        clock_calls += 1
        return timestamp

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["offset"])
        if offset == 0:
            return _response(request, items=[_item("MLV-1")], total=2)
        return _response(request, items=[_item("MLV-2")], total=2)

    listings = _provider(handler, page_size=1, clock=clock).search(SearchQuery("pastillas bera"))

    assert clock_calls == 1
    assert [listing.collected_at for listing in listings] == [_FIXED_TIME, _FIXED_TIME]


def test_max_pages_is_a_hard_stop() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return _response(request, items=[_item(f"MLV-{request_count}")], total=10)

    listings = _provider(handler, page_size=1, max_pages=2).search(SearchQuery("pastillas bera"))

    assert request_count == 2
    assert len(listings) == 2


def test_paging_total_stops_a_full_page() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return _response(request, items=[_item("MLV-1"), _item("MLV-2")], total=2)

    listings = _provider(handler, page_size=2).search(SearchQuery("pastillas bera"))

    assert request_count == 1
    assert len(listings) == 2
