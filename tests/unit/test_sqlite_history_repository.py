"""Tests for the dedicated read-only SQLite history adapter."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from bera_price_tracker.application import ListingHistoryRepository
from bera_price_tracker.domain import (
    CollectionBatch,
    Listing,
    ListingKey,
    MarketplaceSource,
    SearchQuery,
)
from bera_price_tracker.infrastructure.persistence import (
    DatabaseNotFoundError,
    PersistenceError,
    SQLiteListingHistoryRepository,
    SQLiteListingRepository,
    sqlite_repository,
)
from bera_price_tracker.infrastructure.persistence.migrations import MIGRATIONS, Migration

FIRST_TIME = datetime(2026, 8, 1, 14, tzinfo=UTC)
SECOND_TIME = FIRST_TIME + timedelta(days=9)
THIRD_TIME = FIRST_TIME + timedelta(days=19)
QUERY_ONE = SearchQuery("pastillas de freno bera")
QUERY_TWO = SearchQuery("pastillas bera")


def make_listing(
    *,
    source: MarketplaceSource = MarketplaceSource.MERCADO_LIBRE,
    external_id: str = "MLV123",
    title: str = "Pastillas de freno BERA SBR",
    price: str = "19.99",
    currency: str = "VES",
    query: SearchQuery = QUERY_ONE,
    collected_at: datetime = FIRST_TIME,
    seller_name: str | None = "Repuestos BERA",
    location: str | None = "Caracas",
    product_condition: str | None = "new",
) -> Listing:
    return Listing(
        source=source,
        external_id=external_id,
        title=title,
        price=Decimal(price),
        currency=currency,
        url=f"https://example.test/{source.value}/{external_id}",
        query=query,
        collected_at=collected_at,
        seller_name=seller_name,
        location=location,
        product_condition=product_condition,
    )


def persist(repository: SQLiteListingRepository, listing: Listing) -> None:
    repository.record_collection(
        CollectionBatch(
            source=listing.source,
            query=listing.query,
            collected_at=listing.collected_at,
            listings=(listing,),
        )
    )


def test_missing_database_is_not_created(tmp_path: Path) -> None:
    database_path = tmp_path / "missing" / "history.db"

    with pytest.raises(DatabaseNotFoundError, match="database not found"):
        SQLiteListingHistoryRepository(database_path)

    assert not database_path.exists()
    assert not database_path.parent.exists()


def test_existing_uninitialized_database_is_not_migrated(tmp_path: Path) -> None:
    database_path = tmp_path / "uninitialized.db"
    sqlite3.connect(database_path).close()

    with pytest.raises(PersistenceError, match="schema is not initialized"):
        SQLiteListingHistoryRepository(database_path)

    with sqlite3.connect(database_path) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    assert tables == []


def test_one_observation_returns_current_metadata_decimal_and_utc(tmp_path: Path) -> None:
    database_path = tmp_path / "one.db"
    listing = make_listing(price="25.50")
    with SQLiteListingRepository(database_path) as writer:
        persist(writer, listing)

    with SQLiteListingHistoryRepository(database_path) as reader:
        assert isinstance(reader, ListingHistoryRepository)
        history = reader.get_history(listing.key)

    assert history is not None
    assert history.key == listing.key
    assert history.title == listing.title
    assert history.url == listing.url
    assert history.seller_name == "Repuestos BERA"
    assert history.location == "Caracas"
    assert history.product_condition == "new"
    assert history.first_seen_at == FIRST_TIME
    assert history.first_seen_at.tzinfo is UTC
    assert history.last_seen_at == FIRST_TIME
    assert len(history.observations) == 1
    observation = history.observations[0]
    assert observation.price == Decimal("25.50")
    assert str(observation.price) == "25.50"
    assert observation.currency == "VES"
    assert observation.collected_at == FIRST_TIME
    assert observation.collected_at.tzinfo is UTC
    assert observation.query == QUERY_ONE


def test_multiple_observations_are_chronological_and_keep_repeated_prices_and_queries(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "multiple.db"
    first = make_listing(price="19.99", query=QUERY_ONE, collected_at=FIRST_TIME)
    third = make_listing(price="21.99", query=QUERY_ONE, collected_at=THIRD_TIME)
    second = make_listing(
        price="19.99",
        currency="USD",
        query=QUERY_TWO,
        collected_at=SECOND_TIME,
    )
    with SQLiteListingRepository(database_path) as writer:
        persist(writer, first)
        persist(writer, third)
        persist(writer, second)

    with SQLiteListingHistoryRepository(database_path) as reader:
        history = reader.get_history(first.key)

    assert history is not None
    assert [observation.collected_at for observation in history.observations] == [
        FIRST_TIME,
        SECOND_TIME,
        THIRD_TIME,
    ]
    assert [observation.price for observation in history.observations] == [
        Decimal("19.99"),
        Decimal("19.99"),
        Decimal("21.99"),
    ]
    assert [str(observation.price) for observation in history.observations] == [
        "19.99",
        "19.99",
        "21.99",
    ]
    assert [observation.currency for observation in history.observations] == [
        "VES",
        "USD",
        "VES",
    ]
    assert [observation.query for observation in history.observations] == [
        QUERY_ONE,
        QUERY_TWO,
        QUERY_ONE,
    ]


def test_absent_optional_metadata_remains_none(tmp_path: Path) -> None:
    database_path = tmp_path / "optional.db"
    listing = make_listing(
        seller_name=None,
        location=None,
        product_condition=None,
    )
    with SQLiteListingRepository(database_path) as writer:
        persist(writer, listing)

    with SQLiteListingHistoryRepository(database_path) as reader:
        history = reader.get_history(listing.key)

    assert history is not None
    assert history.seller_name is None
    assert history.location is None
    assert history.product_condition is None


def test_lookup_uses_source_and_external_id_without_mixing_histories(tmp_path: Path) -> None:
    database_path = tmp_path / "sources.db"
    mercado_libre = make_listing(title="Mercado Libre", price="19.99")
    facebook = make_listing(
        source=MarketplaceSource.FACEBOOK_MARKETPLACE,
        title="Facebook",
        price="21.99",
    )
    with SQLiteListingRepository(database_path) as writer:
        persist(writer, mercado_libre)
        persist(writer, facebook)

    with SQLiteListingHistoryRepository(database_path) as reader:
        ml_history = reader.get_history(mercado_libre.key)
        fb_history = reader.get_history(facebook.key)

    assert ml_history is not None
    assert fb_history is not None
    assert ml_history.title == "Mercado Libre"
    assert fb_history.title == "Facebook"
    assert [item.price for item in ml_history.observations] == [Decimal("19.99")]
    assert [item.price for item in fb_history.observations] == [Decimal("21.99")]


def test_unknown_listing_returns_none(tmp_path: Path) -> None:
    database_path = tmp_path / "not-found.db"
    with SQLiteListingRepository(database_path):
        pass

    with SQLiteListingHistoryRepository(database_path) as reader:
        history = reader.get_history(ListingKey(MarketplaceSource.MERCADO_LIBRE, "MLV-MISSING"))

    assert history is None


def test_connection_rejects_writes_and_closes_cleanly(tmp_path: Path) -> None:
    database_path = tmp_path / "read-only.db"
    listing = make_listing()
    with SQLiteListingRepository(database_path) as writer:
        persist(writer, listing)

    reader = SQLiteListingHistoryRepository(database_path)
    connection = reader._connection
    assert connection is not None
    query_only = connection.execute("PRAGMA query_only").fetchone()
    assert query_only is not None
    assert int(query_only[0]) == 1
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        connection.execute("UPDATE listings SET title = 'forbidden'")
    reader.close()
    reader.close()
    with pytest.raises(PersistenceError, match="closed"):
        reader.get_history(listing.key)


def test_history_open_never_applies_pending_writer_migrations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "no-migration.db"
    listing = make_listing()
    with SQLiteListingRepository(database_path) as writer:
        persist(writer, listing)

    marker = Migration(
        version=3,
        name="003_must_not_run_from_history",
        statements=("CREATE TABLE forbidden_history_migration (id INTEGER)",),
    )
    monkeypatch.setattr(sqlite_repository, "MIGRATIONS", (*MIGRATIONS, marker))

    with SQLiteListingHistoryRepository(database_path) as reader:
        assert reader.get_history(listing.key) is not None

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone() == (2,)
        marker_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'forbidden_history_migration'"
        ).fetchone()
    assert marker_table is None
