"""Batch-level atomicity and empty-run tests for SQLite persistence."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from bera_price_tracker.domain import (
    CollectionBatch,
    Listing,
    ListingKey,
    MarketplaceSource,
    SearchQuery,
)
from bera_price_tracker.infrastructure.persistence import (
    PersistenceError,
    SQLiteListingRepository,
)

QUERY = SearchQuery("pastillas de freno bera")
FIRST_TIME = datetime(2026, 8, 21, 15, tzinfo=UTC)
SECOND_TIME = FIRST_TIME + timedelta(days=1)


def make_listing(
    external_id: str,
    *,
    collected_at: datetime = FIRST_TIME,
    price: str = "19.99",
    title: str | None = None,
) -> Listing:
    return Listing(
        source=MarketplaceSource.MERCADO_LIBRE,
        external_id=external_id,
        title=title or f"Producto {external_id}",
        price=Decimal(price),
        currency="VES",
        url=f"https://example.test/{external_id}",
        seller_name="Repuestos BERA",
        location="Caracas",
        product_condition="new",
        query=QUERY,
        collected_at=collected_at,
    )


def make_batch(
    collected_at: datetime,
    listings: Sequence[Listing] = (),
) -> CollectionBatch:
    return CollectionBatch.from_listings(
        source=MarketplaceSource.MERCADO_LIBRE,
        query=QUERY,
        collected_at=collected_at,
        listings=listings,
    )


@pytest.fixture
def repository(tmp_path: Path) -> Iterator[SQLiteListingRepository]:
    with SQLiteListingRepository(tmp_path / "batch.db") as sqlite_repository:
        yield sqlite_repository


def install_snapshot_failure(database_path: Path, external_id: str) -> None:
    """Install a test-only trigger that rejects one listing's snapshot."""

    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE test_rejected_listings (external_id TEXT PRIMARY KEY)")
        connection.execute(
            "INSERT INTO test_rejected_listings (external_id) VALUES (?)",
            (external_id,),
        )
        connection.execute(
            """
            CREATE TRIGGER reject_selected_snapshot
            BEFORE INSERT ON price_snapshots
            WHEN EXISTS (
                SELECT 1
                FROM listings AS l
                JOIN test_rejected_listings AS rejected
                  ON rejected.external_id = l.external_id
                WHERE l.id = NEW.listing_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'forced batch failure');
            END
            """
        )


def test_single_listing_batch_creates_one_run_and_snapshot(
    repository: SQLiteListingRepository,
) -> None:
    repository.record_collection(make_batch(FIRST_TIME, [make_listing("A")]))

    assert repository.count_listings() == 1
    assert repository.count_collection_runs() == 1
    assert repository.count_price_snapshots() == 1


def test_multiple_listing_batch_uses_one_run_and_one_snapshot_per_listing(
    repository: SQLiteListingRepository,
) -> None:
    listings = [make_listing("A"), make_listing("B"), make_listing("C")]

    repository.record_collection(make_batch(FIRST_TIME, listings))

    assert repository.count_listings() == 3
    assert repository.count_collection_runs() == 1
    assert repository.count_price_snapshots() == 3


def test_empty_batch_creates_only_one_idempotent_run(
    repository: SQLiteListingRepository,
) -> None:
    empty_batch = make_batch(FIRST_TIME)

    repository.record_collection(empty_batch)
    repository.record_collection(empty_batch)

    assert repository.count_collection_runs() == 1
    assert repository.count_listings() == 0
    assert repository.count_price_snapshots() == 0


def test_later_empty_batch_creates_another_run(repository: SQLiteListingRepository) -> None:
    repository.record_collection(make_batch(FIRST_TIME))
    repository.record_collection(make_batch(SECOND_TIME))

    assert repository.count_collection_runs() == 2
    assert repository.count_listings() == 0
    assert repository.count_price_snapshots() == 0


def test_exact_multiple_listing_batch_is_idempotent(
    repository: SQLiteListingRepository,
) -> None:
    batch = make_batch(FIRST_TIME, [make_listing("A"), make_listing("B")])

    repository.record_collection(batch)
    repository.record_collection(batch)

    assert repository.count_listings() == 2
    assert repository.count_collection_runs() == 1
    assert repository.count_price_snapshots() == 2


def test_duplicate_listing_key_uses_last_observation(
    repository: SQLiteListingRepository,
) -> None:
    first = make_listing("A", title="Pastilla vieja", price="19.99")
    last = make_listing("A", title="Pastilla nueva", price="21.99")
    batch = make_batch(FIRST_TIME, [first, last])

    repository.record_collection(batch)

    stored = repository.get_listing(first.key)
    history = repository.get_price_history(first.key)
    assert stored is not None
    assert batch.listings == (last,)
    assert stored.title == "Pastilla nueva"
    assert [entry.snapshot.price for entry in history] == [Decimal("21.99")]
    assert repository.count_price_snapshots() == 1


@pytest.mark.parametrize("rejected_external_id", ["A", "B", "C"])
def test_failure_at_any_batch_position_rolls_back_every_new_row(
    tmp_path: Path,
    rejected_external_id: str,
) -> None:
    database_path = tmp_path / f"fail-{rejected_external_id}.db"
    with SQLiteListingRepository(database_path) as repository:
        install_snapshot_failure(database_path, rejected_external_id)
        batch = make_batch(
            FIRST_TIME,
            [make_listing("A"), make_listing("B"), make_listing("C")],
        )

        with pytest.raises(PersistenceError) as captured:
            repository.record_collection(batch)

        assert isinstance(captured.value.__cause__, sqlite3.Error)
        assert repository.count_collection_runs() == 0
        assert repository.count_listings() == 0
        assert repository.count_price_snapshots() == 0


def test_failed_batch_rolls_back_existing_metadata_and_preserves_previous_snapshot(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "metadata-rollback.db"
    key_a = ListingKey(MarketplaceSource.MERCADO_LIBRE, "A")
    with SQLiteListingRepository(database_path) as repository:
        original = make_listing("A", title="Pastilla vieja", price="19.99")
        repository.record_collection(make_batch(FIRST_TIME, [original]))
        install_snapshot_failure(database_path, "B")

        updated_a = make_listing(
            "A",
            collected_at=SECOND_TIME,
            title="Pastilla nueva",
            price="21.99",
        )
        new_b = make_listing("B", collected_at=SECOND_TIME, price="25.50")

        with pytest.raises(PersistenceError):
            repository.record_collection(make_batch(SECOND_TIME, [updated_a, new_b]))

        stored_a = repository.get_listing(key_a)
        history_a = repository.get_price_history(key_a)
        assert stored_a is not None
        assert stored_a.title == "Pastilla vieja"
        assert stored_a.first_seen_at == FIRST_TIME
        assert stored_a.last_seen_at == FIRST_TIME
        assert repository.get_listing(new_b.key) is None
        assert [entry.snapshot.price for entry in history_a] == [Decimal("19.99")]
        assert repository.count_collection_runs() == 1
        assert repository.count_listings() == 1
        assert repository.count_price_snapshots() == 1
