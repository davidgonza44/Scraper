"""Offline Apify Facebook Marketplace client and provider mapping tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from bera_price_tracker.application import (
    HybridProductClassifier,
    MarketplaceSourceUnavailable,
)
from bera_price_tracker.domain import MarketplaceSource, SearchQuery
from bera_price_tracker.infrastructure.providers.apify import (
    ACTOR_ID,
    ApifyConfigurationError,
    ApifyFacebookMarketplaceClient,
    build_run_input,
    map_apify_item,
)
from bera_price_tracker.infrastructure.providers.facebook_marketplace import (
    FacebookMarketplaceProvider,
)

COLLECTED_AT = datetime(2026, 8, 22, 6, 0, tzinfo=UTC)
TOKEN = "apify_api_test_token_value"


@dataclass
class FakeDataset:
    items: list[object]

    def list_items(self, *, limit: int) -> SimpleNamespace:
        return SimpleNamespace(items=list(self.items)[:limit])


@dataclass
class FakeActor:
    run: dict[str, object] | None
    calls: list[dict[str, object]] = field(default_factory=list)

    def call(
        self, *, run_input: dict[str, object], max_items: int | None = None
    ) -> dict[str, object] | None:
        self.calls.append({"run_input": run_input, "max_items": max_items})
        return self.run


@dataclass
class FakeClient:
    actor_client: FakeActor
    dataset_items: list[object]
    actor_ids: list[str] = field(default_factory=list)
    dataset_ids: list[str] = field(default_factory=list)

    def actor(self, actor_id: str) -> FakeActor:
        self.actor_ids.append(actor_id)
        return self.actor_client

    def dataset(self, dataset_id: str) -> FakeDataset:
        self.dataset_ids.append(dataset_id)
        return FakeDataset(self.dataset_items)


class ScriptedAI:
    calls: list[object] = []

    def classify(self, candidate: object) -> Any:
        raise AssertionError("AI must not be called")


def _factory_for(client: FakeClient) -> Any:
    def factory(token: str) -> FakeClient:
        assert token == TOKEN
        return client

    return factory


def _client(
    *,
    status: str = "SUCCEEDED",
    items: list[object] | None = None,
    run: dict[str, object] | None | str = "ok",
) -> tuple[ApifyFacebookMarketplaceClient, FakeActor, FakeClient]:
    actor = FakeActor(None if run is None else {"status": status, "defaultDatasetId": "dataset-1"})
    fake = FakeClient(actor, items or [])
    return (
        ApifyFacebookMarketplaceClient(api_token=TOKEN, client_factory=_factory_for(fake)),
        actor,
        fake,
    )


def _raw_item(**changes: object) -> dict[str, object]:
    item: dict[str, object] = {
        "id": "123",
        "listingUrl": "https://www.facebook.com/marketplace/item/123",
        "marketplace_listing_title": "Pastillas Bera SBR 150",
        "listing_price": {
            "amount": "12.50",
            "formatted_amount": "VEF 12.50",
        },
        "location": {
            "reverse_geocode": {
                "city": "Caracas",
                "city_page": {"display_name": "Caracas"},
            }
        },
    }
    item.update(changes)
    return item


def test_actor_input_uses_one_encoded_start_url_and_no_listing_details() -> None:
    client, actor, fake = _client(items=[])
    client.fetch("pastillas sbr", "caracas", 5)
    assert fake.actor_ids == [ACTOR_ID]
    assert actor.calls == [
        {
            "run_input": {
                "startUrls": [
                    {
                        "url": (
                            "https://www.facebook.com/marketplace/caracas/search/"
                            "?query=pastillas%20sbr"
                        )
                    }
                ],
                "resultsLimit": 5,
                "includeListingDetails": False,
            },
            "max_items": 5,
        }
    ]
    assert (
        build_run_input(query="pastillas sbr", city="caracas", limit=5)["includeListingDetails"]
        is False
    )


def test_limit_rejects_values_above_five() -> None:
    client, _, _ = _client(items=[])
    with pytest.raises(ApifyConfigurationError, match="limit"):
        client.fetch("pastillas sbr", "caracas", 6)


def test_mapping_uses_marketplace_listing_title() -> None:
    mapped = map_apify_item(_raw_item())
    assert mapped is not None
    assert mapped.title == "Pastillas Bera SBR 150"
    fallback = map_apify_item(
        {
            "id": "9",
            "listingTitle": "Pastillas Honda CG125 ES4",
            "listing_price": {"amount": "1", "formatted_amount": "VEF1"},
        }
    )
    assert fallback is not None
    assert fallback.title == "Pastillas Honda CG125 ES4"


def test_price_is_mapped_as_decimal_not_float() -> None:
    mapped = map_apify_item(
        _raw_item(listing_price={"amount": "12.50", "formatted_amount": "VEF12.50"})
    )
    assert mapped is not None
    assert mapped.price == Decimal("12.50")
    assert type(mapped.price) is Decimal


def test_formatted_amount_vef5_becomes_vef() -> None:
    mapped = map_apify_item(_raw_item(listing_price={"amount": "5", "formatted_amount": "VEF5"}))
    assert mapped is not None
    assert mapped.currency == "VEF"


def test_dollar_prefix_without_iso_code_is_unknown() -> None:
    mapped = map_apify_item(_raw_item(listing_price={"amount": "4", "formatted_amount": "$4"}))
    assert mapped is not None
    assert mapped.currency == "UNKNOWN"


def test_caracas_location_is_accepted_for_city_slug() -> None:
    client, _, _ = _client(items=[_raw_item()])
    provider = FacebookMarketplaceProvider(
        client=client,
        classifier=HybridProductClassifier(ScriptedAI()),
        city="caracas",
        record_limit=5,
        clock=lambda: COLLECTED_AT,
    )
    listings = provider.search(SearchQuery("pastillas sbr"))
    assert len(listings) == 1
    assert listings[0].location == "Caracas"
    assert listings[0].source is MarketplaceSource.FACEBOOK_MARKETPLACE
    assert provider.last_metrics.out_of_scope_location == 0


def test_different_normalizable_location_is_out_of_scope() -> None:
    item = _raw_item(
        location={
            "reverse_geocode": {
                "city": "Valencia",
                "city_page": {"display_name": "Valencia"},
            }
        }
    )
    client, _, _ = _client(items=[item])
    provider = FacebookMarketplaceProvider(
        client=client,
        classifier=HybridProductClassifier(ScriptedAI()),
        city="caracas",
        record_limit=5,
        clock=lambda: COLLECTED_AT,
    )
    assert provider.search(SearchQuery("pastillas sbr")) == []
    assert provider.last_metrics.out_of_scope_location == 1
    assert provider.last_metrics.source_errors == 0
    assert provider.last_explanations[0].reason == "out_of_scope_location"


def test_failed_actor_raises_source_unavailable() -> None:
    client, _, _ = _client(status="FAILED", items=[])
    with pytest.raises(MarketplaceSourceUnavailable):
        client.fetch("pastillas sbr", "caracas", 5)


def test_succeeded_empty_dataset_is_a_valid_empty_batch() -> None:
    client, _, _ = _client(items=[])
    provider = FacebookMarketplaceProvider(
        client=client,
        classifier=HybridProductClassifier(ScriptedAI()),
        city="caracas",
        record_limit=5,
        clock=lambda: COLLECTED_AT,
    )
    assert provider.search(SearchQuery("pastillas sbr")) == []
    assert provider.last_metrics.fetched == 0
    assert provider.last_metrics.persisted == 0


def test_relevant_title_becomes_a_listing() -> None:
    client, _, _ = _client(items=[_raw_item()])
    provider = FacebookMarketplaceProvider(
        client=client,
        classifier=HybridProductClassifier(ScriptedAI()),
        city="caracas",
        record_limit=5,
        clock=lambda: COLLECTED_AT,
    )
    listings = provider.search(SearchQuery("pastillas sbr"))
    assert len(listings) == 1
    listing = listings[0]
    assert listing.external_id == "123"
    assert listing.title == "Pastillas Bera SBR 150"
    assert listing.price == Decimal("12.50")
    assert listing.currency == "VEF"
    assert listing.url == "https://www.facebook.com/marketplace/item/123"
    assert provider.last_metrics.deterministic_relevant == 1
    assert provider.last_metrics.persisted == 1


def test_token_never_appears_in_errors_or_repr() -> None:
    client = ApifyFacebookMarketplaceClient(
        api_token=TOKEN, client_factory=lambda token: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    with pytest.raises(MarketplaceSourceUnavailable) as error:
        client.fetch("pastillas sbr", "caracas", 1)
    rendered = f"{error.value!s}{error.value!r}{client!r}"
    assert TOKEN not in rendered
    assert "apify_api_" not in rendered


def test_dollar_four_unknown_currency_becomes_a_listing() -> None:
    item = _raw_item(
        marketplace_listing_title="Pastillas de Bera sbr 150",
        listing_price={"amount": "4", "formatted_amount": "$4"},
    )
    client, _, _ = _client(items=[item])
    provider = FacebookMarketplaceProvider(
        client=client,
        classifier=HybridProductClassifier(ScriptedAI()),
        city="caracas",
        record_limit=5,
        clock=lambda: COLLECTED_AT,
    )
    listings = provider.search(SearchQuery("pastillas sbr"))
    assert len(listings) == 1
    listing = listings[0]
    assert listing.price == Decimal("4")
    assert listing.currency == "UNKNOWN"
    assert listing.formatted_amount == "$4"
    assert listing.usd_amount == Decimal("4.00")
    assert listing.usd_normalization_status == "dollar_symbol"


def test_vef5_listing_displays_usd_without_changing_original() -> None:
    item = _raw_item(listing_price={"amount": "5", "formatted_amount": "VEF5"})
    client, _, _ = _client(items=[item])
    provider = FacebookMarketplaceProvider(
        client=client,
        classifier=HybridProductClassifier(ScriptedAI()),
        city="caracas",
        record_limit=5,
        clock=lambda: COLLECTED_AT,
    )
    listing = provider.search(SearchQuery("pastillas sbr"))[0]
    assert listing.price == Decimal("5")
    assert listing.currency == "VEF"
    assert listing.formatted_amount == "VEF5"
    assert listing.usd_amount == Decimal("5.00")
    assert listing.usd_evidence == ("facebook_venezuela_price_semantics",)
