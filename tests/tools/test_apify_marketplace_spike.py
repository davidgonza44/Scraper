"""Offline coverage for the isolated Apify Marketplace spike."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import pytest

from tools.apify_marketplace_spike import (
    ACTOR_ID,
    PREFERRED_RUN_ID,
    RESULTS_LIMIT,
    START_URL,
    SpikeConfiguration,
    build_run_input,
    main,
    sanitize_listing,
)

TOKEN = "SPIKE_TOKEN_PREFIX-never-print-SPIKE_TOKEN_SUFFIX"
TOKEN_ENV = "BERA_TRACKER_APIFY_API_TOKEN"
SECRET_PHONE = "SECRET_PHONE_SENTINEL"
SECRET_EMAIL = "SECRET_EMAIL_SENTINEL"
SECRET_SELLER = "SECRET_SELLER_SENTINEL"


@dataclass
class FakeDatasetPage:
    items: list[object]


@dataclass
class FakeDatasetClient:
    items: list[object]
    calls: list[int] = field(default_factory=list)

    def list_items(self, *, limit: int) -> FakeDatasetPage:
        self.calls.append(limit)
        return FakeDatasetPage(items=self.items)


@dataclass
class FakeRunClient:
    run: Mapping[str, object] | None
    gets: list[str] = field(default_factory=list)

    def get(self) -> dict[str, object] | None:
        self.gets.append("get")
        if self.run is None:
            return None
        return dict(self.run)


@dataclass
class FakeActorClient:
    run: Mapping[str, object] | None
    calls: list[dict[str, object]] = field(default_factory=list)
    last_run_calls: list[str | None] = field(default_factory=list)
    error: Exception | None = None

    def call(
        self,
        *,
        run_input: dict[str, object],
        max_items: int | None = None,
    ) -> dict[str, object] | None:
        self.calls.append({"run_input": run_input, "max_items": max_items})
        if self.error is not None:
            raise self.error
        if self.run is None:
            return None
        return dict(self.run)

    def last_run(self, *, status: str | None = None) -> FakeRunClient:
        self.last_run_calls.append(status)
        return FakeRunClient(run=self.run)


@dataclass
class FakeApifyClient:
    actor_client: FakeActorClient
    dataset_client: FakeDatasetClient
    actor_ids: list[str] = field(default_factory=list)
    dataset_ids: list[str] = field(default_factory=list)
    run_ids: list[str] = field(default_factory=list)
    preferred_run: Mapping[str, object] | None = None

    def actor(self, actor_id: str) -> FakeActorClient:
        self.actor_ids.append(actor_id)
        return self.actor_client

    def dataset(self, dataset_id: str) -> FakeDatasetClient:
        self.dataset_ids.append(dataset_id)
        return self.dataset_client

    def run(self, run_id: str) -> FakeRunClient:
        self.run_ids.append(run_id)
        return FakeRunClient(run=self.preferred_run)


def _environment(*, token: str | None = TOKEN) -> dict[str, str]:
    environ: dict[str, str] = {}
    if token is not None:
        environ[TOKEN_ENV] = token
    return environ


def test_dry_run_is_default_and_does_not_create_client(
    capsys: pytest.CaptureFixture[str],
) -> None:
    factory_calls = 0

    def forbidden_factory(token: str) -> FakeApifyClient:
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError(f"dry-run created a client: {token}")

    exit_code = main([], environ=_environment(token=None), client_factory=forbidden_factory)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert factory_calls == 0
    assert "Mode: DRY RUN" in captured.out
    assert "Provider: Apify" in captured.out
    assert f"Actor: {ACTOR_ID}" in captured.out
    assert "Query: pastillas sbr" in captured.out
    assert "City: caracas" in captured.out
    assert "Results limit: 5" in captured.out
    assert "Include listing details: false" in captured.out
    assert "Token: MISSING" in captured.out
    assert "Request sent: NO" in captured.out
    assert captured.err == ""


def test_execute_without_token_does_not_create_client(
    capsys: pytest.CaptureFixture[str],
) -> None:
    factory_calls = 0

    def forbidden_factory(token: str) -> FakeApifyClient:
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("missing-token execution created a client")

    exit_code = main(
        ["--execute"],
        environ=_environment(token=None),
        client_factory=forbidden_factory,
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert factory_calls == 0
    assert "Token: MISSING" in captured.out
    assert f"{TOKEN_ENV} is required with --execute" in captured.err
    assert TOKEN not in captured.out + captured.err


def test_run_input_is_exactly_one_start_url_limit_five_no_details() -> None:
    run_input = build_run_input()

    start_urls = run_input["startUrls"]
    assert isinstance(start_urls, list)
    assert len(start_urls) == 1
    assert start_urls[0] == {"url": START_URL}
    assert run_input["resultsLimit"] == 5
    assert RESULTS_LIMIT == 5
    assert run_input["includeListingDetails"] is False
    assert set(run_input) == {"startUrls", "resultsLimit", "includeListingDetails"}


def test_execute_sends_fixed_input_and_max_items_five(
    capsys: pytest.CaptureFixture[str],
) -> None:
    actor = FakeActorClient(
        run={"status": "SUCCEEDED", "defaultDatasetId": "ds-1"},
    )
    dataset = FakeDatasetClient(
        items=[
            {
                "marketplace_listing_title": "Pastillas SBR",
                "listing_price": {"amount": "25", "formatted_amount": "$25", "currency": "USD"},
                "location": {"reverse_geocode": {"city": "Caracas"}},
                "listingUrl": "https://example.test/listing/1",
                "id": "1",
                "phone": SECRET_PHONE,
                "email": SECRET_EMAIL,
                "sellerName": SECRET_SELLER,
            }
        ]
    )
    client = FakeApifyClient(actor_client=actor, dataset_client=dataset)

    def factory(token: str) -> FakeApifyClient:
        assert token == TOKEN
        return client

    exit_code = main(["--execute"], environ=_environment(), client_factory=factory)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert len(actor.calls) == 1
    assert actor.calls[0]["run_input"] == build_run_input()
    assert actor.calls[0]["max_items"] == 5
    assert client.actor_ids == [ACTOR_ID]
    assert dataset.calls == [5]
    assert "Classification: RESULTS_FOUND" in captured.out
    assert "Number of items: 1" in captured.out
    assert "title: Pastillas SBR" in captured.out


def test_output_never_reveals_secrets_or_raw_payload(
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw_item = {
        "marketplace_listing_title": "Safe title",
        "listing_price": {"amount": "10", "formatted_amount": "$10"},
        "phone": SECRET_PHONE,
        "email": SECRET_EMAIL,
        "sellerName": SECRET_SELLER,
        "html": "<html>SECRET_HTML</html>",
        "cookies": "SECRET_COOKIE",
    }
    actor = FakeActorClient(run={"status": "SUCCEEDED", "defaultDatasetId": "ds-2"})
    dataset = FakeDatasetClient(items=[raw_item])
    client = FakeApifyClient(actor_client=actor, dataset_client=dataset)
    configuration = SpikeConfiguration.from_env(_environment())

    exit_code = main(
        ["--execute"],
        environ=_environment(),
        client_factory=lambda token: client,
    )
    captured = capsys.readouterr()
    combined = captured.out + captured.err + repr(configuration) + str(sanitize_listing(raw_item))

    assert exit_code == 0
    assert TOKEN not in combined
    assert "SPIKE_TOKEN_PREFIX" not in combined
    assert SECRET_PHONE not in captured.out
    assert SECRET_EMAIL not in captured.out
    assert SECRET_SELLER not in captured.out
    assert "SECRET_HTML" not in captured.out
    assert "SECRET_COOKIE" not in captured.out
    assert "phone" not in captured.out.lower()
    assert "email" not in captured.out.lower()


def test_request_error_is_sanitized_and_not_retried(
    capsys: pytest.CaptureFixture[str],
) -> None:
    actor = FakeActorClient(run=None, error=RuntimeError("PRIVATE_APIFY_DETAIL apify_api_fake"))
    dataset = FakeDatasetClient(items=[])
    client = FakeApifyClient(actor_client=actor, dataset_client=dataset)

    exit_code = main(
        ["--execute"],
        environ=_environment(),
        client_factory=lambda token: client,
    )

    captured = capsys.readouterr()
    assert exit_code == 3
    assert len(actor.calls) == 1
    assert "Classification: REQUEST_ERROR" in captured.out
    assert "Apify request failed" in captured.out
    assert "PRIVATE_APIFY_DETAIL" not in captured.out + captured.err
    assert "apify_api_fake" not in captured.out + captured.err
    assert TOKEN not in captured.out + captured.err
    assert RESULTS_LIMIT == 5


def test_maps_marketplace_listing_title() -> None:
    summary = sanitize_listing({"marketplace_listing_title": "Pastillas SBR Caracas"})
    assert summary.title == "Pastillas SBR Caracas"


def test_maps_listing_price_amount() -> None:
    summary = sanitize_listing({"listing_price": {"amount": 1500}})
    assert summary.price_amount == "1500"


def test_maps_listing_price_formatted_amount() -> None:
    summary = sanitize_listing({"listing_price": {"formatted_amount": "$1,500"}})
    assert summary.price_formatted == "$1,500"


def test_maps_nested_location_display_name() -> None:
    summary = sanitize_listing(
        {
            "location": {
                "reverse_geocode": {
                    "city": "Ignored City",
                    "city_page": {"display_name": "Caracas, Distrito Capital"},
                }
            }
        }
    )
    assert summary.location == "Caracas, Distrito Capital"


def test_missing_currency_is_unknown_when_formatted_amount() -> None:
    summary = sanitize_listing({"listing_price": {"formatted_amount": "$12"}})
    assert summary.currency == "UNKNOWN"
    assert summary.price_formatted == "$12"


def test_read_last_run_does_not_call_actor_and_sanitizes_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw_item = {
        "marketplace_listing_title": "Safe title",
        "listing_price": {"amount": "10", "formatted_amount": "$10"},
        "listingUrl": "https://example.test/listing/9",
        "id": "9",
        "phone": SECRET_PHONE,
        "email": SECRET_EMAIL,
        "sellerName": SECRET_SELLER,
        "description": "SECRET_DESCRIPTION",
    }
    actor = FakeActorClient(run={"status": "SUCCEEDED", "defaultDatasetId": "ds-last"})
    dataset = FakeDatasetClient(items=[raw_item])
    client = FakeApifyClient(
        actor_client=actor,
        dataset_client=dataset,
        preferred_run={
            "status": "SUCCEEDED",
            "defaultDatasetId": "ds-last",
            "id": PREFERRED_RUN_ID,
        },
    )

    exit_code = main(
        ["--read-last-run"],
        environ=_environment(),
        client_factory=lambda token: client,
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert actor.calls == []
    assert actor.last_run_calls == []
    assert client.run_ids == [PREFERRED_RUN_ID]
    assert dataset.calls == [5]
    assert "Mode: READ LAST RUN" in captured.out
    assert "New Actor runs created: 0" in captured.out
    assert "title: Safe title" in captured.out
    assert "price_amount: 10" in captured.out
    assert "price_formatted: $10" in captured.out
    assert "currency: UNKNOWN" in captured.out
    assert "listing_url: https://example.test/listing/9" in captured.out
    assert "listing_id: 9" in captured.out
    assert SECRET_PHONE not in captured.out
    assert SECRET_EMAIL not in captured.out
    assert SECRET_SELLER not in captured.out
    assert "SECRET_DESCRIPTION" not in captured.out
    assert "description" not in captured.out.lower()
