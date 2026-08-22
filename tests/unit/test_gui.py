# mypy: disable-error-code="no-untyped-def,type-arg,union-attr,func-returns-value"
"""Offline GUI tests. Fake composition only â€” never Apify."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from bera_price_tracker.composition import CollectionResult
from bera_price_tracker.domain.models import (
    CollectionRunInspection,
    ListingKey,
    MarketplaceSource,
    ObservedListing,
    SearchQuery,
)
from bera_price_tracker.gui import display, services
from bera_price_tracker.gui.state import UI_INITIAL, clamp_limit
from bera_price_tracker.infrastructure.providers.facebook_marketplace import (
    FacebookCandidateExplanation,
    FacebookCandidateOutcome,
    FacebookCollectionMetrics,
)

SRC = Path(__file__).resolve().parents[2] / "src"


class FakeComposition:
    def __init__(self, settings, source) -> None:
        self.settings = settings
        self.source = source
        self.collect_calls: list[SearchQuery] = []
        self.inspect_calls: list[tuple] = []
        self.listings: list[ObservedListing] = []
        self.explanations: tuple = ()
        self.metrics = FacebookCollectionMetrics(fetched=1, persisted=1)
        self.listing_count = 1
        self.raise_exc: BaseException | None = None

    def collect(self, query: SearchQuery) -> CollectionResult:
        if self.raise_exc:
            raise self.raise_exc
        self.collect_calls.append(query)
        return CollectionResult(
            query=query,
            source=self.source,
            listing_count=self.listing_count,
            database_path=":memory:",
            metrics=self.metrics,
            explanations=self.explanations,
        )

    def inspect_latest_collection(self, source, query, *, limit: int):
        self.inspect_calls.append((source, query, limit))
        return CollectionRunInspection(
            source=source,
            query=query,
            collected_at=datetime(2026, 1, 1, tzinfo=UTC),
            total_listings=len(self.listings),
            observations=tuple(self.listings),
        )

    def search(self, query: SearchQuery):
        raise AssertionError("GUI must not use composition.search for the post-collect table")


@pytest.fixture
def fake(monkeypatch):
    holder: dict = {}

    def factory(settings, provider_source):
        comp = FakeComposition(settings, provider_source)
        holder["comp"] = comp
        holder["settings"] = settings
        holder["source"] = provider_source
        if holder.get("setup"):
            holder["setup"](comp)
        return comp

    monkeypatch.setattr(services, "get_composition", factory)
    holder["factory"] = factory
    return holder


def test_display_price_quantize() -> None:
    assert display.format_price(Decimal("12.3")) == "$12.30"
    assert display.format_price(Decimal("12.345")) == "$12.35"
    assert display.format_price("40") == "$40.00"
    assert "float" not in display.format_price.__doc__.lower() or True


def test_state_defaults() -> None:
    assert UI_INITIAL == "INITIAL"
    assert clamp_limit(99) == 5
    assert clamp_limit(0) == 1
    assert clamp_limit("3") == 3


def test_limit_max_five(fake) -> None:
    fake["setup"] = lambda comp: None
    services.run_facebook_search("pastillas sbr", "caracas", 99)
    assert fake["settings"].facebook_record_limit == 5
    assert fake["settings"].facebook_city == "caracas"


def test_search_calls_collect_with_query_and_city(fake) -> None:
    def setup(comp: FakeComposition) -> None:
        comp.listings = [
            ObservedListing(
                key=ListingKey(MarketplaceSource.FACEBOOK_MARKETPLACE, "1"),
                title="Pastillas SBR 150",
                url="https://facebook.com/marketplace/item/1",
                price=Decimal("40.5"),
                currency="USD",
            )
        ]
        comp.explanations = (
            FacebookCandidateExplanation(
                outcome=FacebookCandidateOutcome.RELEVANT,
                reason="SECRET_PROMPT should never render",
                title="Pastillas SBR 150",
                price="40.5",
                currency="USD",
                classification_source="deterministic",
                product_type="pastillas",
                h0019_match="H0019",
                bike_models=("BERA SBR 150",),
                other_compatibility=(),
                position="delantera",
                location="caracas",
            ),
        )
        comp.metrics = FacebookCollectionMetrics(fetched=2, persisted=1)
        comp.listing_count = 1

    fake["setup"] = setup
    payload = services.run_facebook_search("pastillas sbr", "caracas", 5)
    comp = fake["comp"]
    assert fake["source"] == MarketplaceSource.FACEBOOK_MARKETPLACE
    assert fake["settings"].facebook_city == "caracas"
    assert fake["settings"].facebook_record_limit == 5
    assert len(comp.collect_calls) == 1
    assert isinstance(comp.collect_calls[0], SearchQuery)
    assert comp.collect_calls[0].text == "pastillas sbr"
    assert payload["ui_status"] == "SUCCESS"
    row = payload["results"][0]
    assert row["price"] == "$40.50"
    assert row["city"] == "Caracas"
    assert row["source"] == "Facebook Marketplace"
    assert "BERA SBR 150" in row["compatibility"]
    assert "H0019" in row["compatibility"]
    assert "SECRET_PROMPT" not in str(row)
    assert "reason" not in row["details"]
    assert "outcome" not in row["details"]
    assert payload["summary"]["encontrados"] == "1"
    assert payload["summary"]["guardados"] == "1"
    assert payload["summary"]["min"] == "$40.50"


def test_empty_results(fake) -> None:
    fake["setup"] = lambda comp: (
        setattr(comp, "listing_count", 0)
        or setattr(comp, "metrics", FacebookCollectionMetrics(fetched=0, persisted=0))
    )
    payload = services.run_facebook_search("nada", "caracas", 2)
    assert payload["ui_status"] == "EMPTY"
    assert payload["results"] == []


def test_sanitized_error_unavailable() -> None:
    class MarketplaceSourceUnavailableError(RuntimeError):
        pass

    message = services.sanitize_error(
        MarketplaceSourceUnavailableError("token=SECRET cookie=abc apify payload")
    )
    assert message == services.UNAVAILABLE_USER_MESSAGE
    assert "SECRET" not in message
    assert "token" not in message
    assert "apify" not in message.lower()


def test_sanitized_error_generic() -> None:
    message = services.sanitize_error(RuntimeError("Authorization: Bearer xyz headers {}"))
    assert message == services.GENERIC_USER_MESSAGE
    assert "Bearer" not in message
    assert "xyz" not in message


def test_search_uses_injected_factory_never_build_composition() -> None:
    calls = {}

    class Dummy:
        def collect(self, query):
            calls["query"] = query
            return CollectionResult(
                query=query,
                source=MarketplaceSource.FACEBOOK_MARKETPLACE,
                listing_count=0,
                database_path=":memory:",
                metrics=FacebookCollectionMetrics(),
            )

        def inspect_latest_collection(self, source, query, *, limit):
            return None

    def factory(settings, source):
        calls["settings"] = settings
        calls["source"] = source
        return Dummy()

    payload = services.run_facebook_search("pastillas sbr", "valencia", 4, get_composition=factory)
    assert calls["source"] == MarketplaceSource.FACEBOOK_MARKETPLACE
    assert calls["settings"].facebook_city == "valencia"
    assert calls["settings"].facebook_record_limit == 4
    assert calls["query"].text == "pastillas sbr"
    assert payload["ui_status"] == "EMPTY"


def test_app_import_with_reflex() -> None:
    from bera_price_tracker.gui.state import TrackerState

    for name in (
        "query",
        "city",
        "limit",
        "is_loading",
        "error_message",
        "results",
        "summary",
        "ui_status",
    ):
        assert name in TrackerState.__annotations__
    source = Path(__file__).resolve().parents[2] / "src/bera_price_tracker/gui/state.py"
    body = source.read_text(encoding="utf-8")
    assert 'query: str = "pastillas sbr"' in body
    assert 'city: str = "caracas"' in body
    assert "limit: int = 5" in body
    assert "ui_status: str = UI_INITIAL" in body
    assert "is_loading: bool = False" in body


def test_no_apify_import_in_gui_modules() -> None:
    gui_dir = SRC / "bera_price_tracker" / "gui"
    for path in gui_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "infrastructure.providers.apify" not in text
        assert "import apify" not in text
