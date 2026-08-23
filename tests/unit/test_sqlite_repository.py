"""Unit tests for the SQLite persistence adapter."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from bera_price_tracker.domain import (
    CollectionBatch,
    Listing,
    MarketplaceSource,
    SearchQuery,
)
from bera_price_tracker.infrastructure.persistence import (
    PersistenceError,
    SQLiteListingRepository,
    sqlite_repository,
)
from bera_price_tracker.infrastructure.persistence.migrations import MIGRATIONS, Migration

BASE_TIME = datetime(2026, 8, 21, 12, 30, 45, 123456, tzinfo=UTC)


def make_listing(
    *,
    external_id: str = "MLV-123",
    source: MarketplaceSource = MarketplaceSource.MERCADO_LIBRE,
    title: str = "Pastillas BERA",
    price: Decimal = Decimal("19.99"),
    currency: str = "USD",
    query: str = "pastillas bera",
    collected_at: datetime = BASE_TIME,
    seller_name: str | None = "Repuestos BERA",
    location: str | None = "Caracas, Distrito Capital",
    product_condition: str | None = "new",
) -> Listing:
    return Listing(
        source=source,
        external_id=external_id,
        title=title,
        price=price,
        currency=currency,
        url=f"https://example.test/{source.value}/{external_id}",
        query=SearchQuery(query),
        collected_at=collected_at,
        seller_name=seller_name,
        location=location,
        product_condition=product_condition,
    )


def record(repository: SQLiteListingRepository, listing: Listing) -> None:
    repository.record_collection(
        CollectionBatch(
            source=listing.source,
            query=listing.query,
            collected_at=listing.collected_at,
            listings=(listing,),
        )
    )


@pytest.fixture
def repository(tmp_path: Path) -> Iterator[SQLiteListingRepository]:
    with SQLiteListingRepository(tmp_path / "tracker.db") as sqlite_repository:
        yield sqlite_repository


def test_creates_parent_database_and_initial_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "nested" / "data" / "tracker.db"

    with SQLiteListingRepository(database_path) as repository:
        assert database_path.is_file()
        assert repository.database_path == str(database_path)
        assert repository.schema_version() == 3

    with sqlite3.connect(database_path) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert {
            "schema_migrations",
            "listings",
            "collection_runs",
            "price_snapshots",
        } <= tables
        price_column = next(
            row
            for row in connection.execute("PRAGMA table_info(price_snapshots)")
            if row[1] == "price"
        )
        assert price_column[2] == "TEXT"


def test_running_migrations_twice_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "tracker.db"

    SQLiteListingRepository(database_path).close()
    with SQLiteListingRepository(database_path) as repository:
        assert repository.schema_version() == 3

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone() == (3,)


def test_migration_error_rolls_back_the_whole_pending_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "migration-rollback.db"
    SQLiteListingRepository(database_path).close()
    broken_migration = Migration(
        version=4,
        name="004_broken_for_test",
        statements=("CREATE TABLE must_be_rolled_back (id INTEGER)", "NOT VALID SQL"),
    )
    monkeypatch.setattr(sqlite_repository, "MIGRATIONS", (*MIGRATIONS, broken_migration))

    with pytest.raises(PersistenceError, match="migrations"):
        SQLiteListingRepository(database_path)

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone() == (3,)
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = 'must_be_rolled_back'"
        ).fetchone() == (0,)


def test_foreign_keys_are_enabled(repository: SQLiteListingRepository) -> None:
    assert repository.foreign_keys_enabled()


def test_insert_listing_run_and_snapshot(repository: SQLiteListingRepository) -> None:
    listing = make_listing()

    record(repository, listing)

    stored = repository.get_listing(listing.key)
    assert stored is not None
    assert stored.key == listing.key
    assert stored.title == listing.title
    assert stored.url == listing.url
    assert stored.seller_name == listing.seller_name
    assert stored.location == listing.location
    assert stored.product_condition == listing.product_condition
    assert stored.first_seen_at == listing.collected_at
    assert stored.last_seen_at == listing.collected_at
    assert repository.count_listings() == 1
    assert repository.count_collection_runs() == 1
    assert repository.count_price_snapshots() == 1


def test_exact_observation_is_idempotent(repository: SQLiteListingRepository) -> None:
    listing = make_listing()

    record(repository, listing)
    record(repository, listing)

    assert repository.count_listings() == 1
    assert repository.count_collection_runs() == 1
    assert repository.count_price_snapshots() == 1


def test_later_observation_updates_current_metadata_and_seen_times(
    repository: SQLiteListingRepository,
) -> None:
    first = make_listing(title="Título original")
    later_time = BASE_TIME + timedelta(hours=1)
    later = make_listing(title="Título actualizado", collected_at=later_time)

    record(repository, first)
    record(repository, later)

    stored = repository.get_listing(first.key)
    assert stored is not None
    assert stored.id > 0
    assert stored.title == "Título actualizado"
    assert stored.first_seen_at == BASE_TIME
    assert stored.last_seen_at == later_time
    assert repository.count_listings() == 1
    assert repository.count_collection_runs() == 2
    assert repository.count_price_snapshots() == 2


def test_optional_metadata_is_preserved_on_none_and_updated_on_new_text(
    repository: SQLiteListingRepository,
) -> None:
    initial = make_listing()
    absent = make_listing(
        collected_at=BASE_TIME + timedelta(minutes=1),
        seller_name=None,
        location=None,
        product_condition=None,
    )
    changed = make_listing(
        collected_at=BASE_TIME + timedelta(minutes=2),
        seller_name="Nuevo vendedor",
        location="Valencia, Carabobo",
        product_condition="used",
    )

    record(repository, initial)
    record(repository, absent)
    preserved = repository.get_listing(initial.key)
    assert preserved is not None
    assert preserved.seller_name == "Repuestos BERA"
    assert preserved.location == "Caracas, Distrito Capital"
    assert preserved.product_condition == "new"

    record(repository, changed)
    updated = repository.get_listing(initial.key)
    assert updated is not None
    assert updated.seller_name == "Nuevo vendedor"
    assert updated.location == "Valencia, Carabobo"
    assert updated.product_condition == "used"


def test_later_run_keeps_same_price_as_a_new_observation(
    repository: SQLiteListingRepository,
) -> None:
    first = make_listing(price=Decimal("19.99"))
    later = make_listing(price=Decimal("19.99"), collected_at=BASE_TIME + timedelta(days=1))

    record(repository, first)
    record(repository, later)

    history = repository.get_price_history(first.key)
    assert [entry.snapshot.price for entry in history] == [Decimal("19.99"), Decimal("19.99")]
    assert repository.count_collection_runs() == 2
    assert repository.count_price_snapshots() == 2


def test_later_run_keeps_a_changed_price(repository: SQLiteListingRepository) -> None:
    first = make_listing(price=Decimal("19.99"))
    later = make_listing(price=Decimal("20.50"), collected_at=BASE_TIME + timedelta(days=1))

    record(repository, first)
    record(repository, later)

    history = repository.get_price_history(first.key)
    assert [entry.snapshot.price for entry in history] == [Decimal("19.99"), Decimal("20.50")]


@pytest.mark.parametrize("price_text", ["19.99", "0.1", "1250.50", "999999999.99"])
def test_decimal_round_trip_is_exact(
    repository: SQLiteListingRepository,
    price_text: str,
) -> None:
    listing = make_listing(external_id=f"MLV-{price_text}", price=Decimal(price_text))

    record(repository, listing)

    restored = repository.get_price_history(listing.key)[0].snapshot.price
    assert restored == Decimal(price_text)
    assert str(restored) == price_text


def test_utc_timestamp_round_trip_is_aware(repository: SQLiteListingRepository) -> None:
    local_offset = timezone(timedelta(hours=-4))
    source_time = datetime(2026, 8, 21, 8, 30, 45, 654321, tzinfo=local_offset)
    listing = make_listing(collected_at=source_time)

    record(repository, listing)

    stored = repository.get_listing(listing.key)
    history_time = repository.get_price_history(listing.key)[0].snapshot.collected_at
    assert stored is not None
    assert stored.first_seen_at == source_time.astimezone(UTC)
    assert stored.first_seen_at.tzinfo is UTC
    assert stored.last_seen_at.tzinfo is UTC
    assert history_time == source_time.astimezone(UTC)
    assert history_time.tzinfo is UTC


def test_history_is_ordered_chronologically(repository: SQLiteListingRepository) -> None:
    later = make_listing(price=Decimal("30"), collected_at=BASE_TIME + timedelta(days=2))
    earlier = make_listing(price=Decimal("10"), collected_at=BASE_TIME)
    middle = make_listing(price=Decimal("20"), collected_at=BASE_TIME + timedelta(days=1))

    record(repository, later)
    record(repository, earlier)
    record(repository, middle)

    history = repository.get_price_history(later.key)
    assert [entry.snapshot.price for entry in history] == [
        Decimal("10"),
        Decimal("20"),
        Decimal("30"),
    ]
    assert [entry.snapshot.collected_at for entry in history] == sorted(
        entry.snapshot.collected_at for entry in history
    )


def test_same_external_id_from_two_marketplaces_remains_separate(
    repository: SQLiteListingRepository,
) -> None:
    mercado_libre = make_listing(external_id="shared-id")
    facebook = make_listing(
        external_id="shared-id",
        source=MarketplaceSource.FACEBOOK_MARKETPLACE,
    )

    record(repository, mercado_libre)
    record(repository, facebook)

    assert repository.count_listings() == 2
    assert repository.get_listing(mercado_libre.key) is not None
    assert repository.get_listing(facebook.key) is not None


def test_two_queries_can_observe_the_same_listing(repository: SQLiteListingRepository) -> None:
    broad_query = make_listing(query="pastillas bera")
    model_query = make_listing(query="pastillas bera sbr")

    record(repository, broad_query)
    record(repository, model_query)

    history = repository.get_price_history(broad_query.key)
    assert repository.count_listings() == 1
    assert repository.count_collection_runs() == 2
    assert repository.count_price_snapshots() == 2
    assert [entry.query.text for entry in history] == ["pastillas bera", "pastillas bera sbr"]


def test_transaction_rolls_back_when_snapshot_insert_fails(tmp_path: Path) -> None:
    database_path = tmp_path / "rollback.db"
    with SQLiteListingRepository(database_path) as repository:
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                """
                CREATE TRIGGER reject_snapshot
                BEFORE INSERT ON price_snapshots
                BEGIN
                    SELECT RAISE(ABORT, 'forced test failure');
                END
                """
            )

        with pytest.raises(PersistenceError) as captured:
            record(repository, make_listing())

        assert isinstance(captured.value.__cause__, sqlite3.Error)
        assert repository.count_listings() == 0
        assert repository.count_collection_runs() == 0
        assert repository.count_price_snapshots() == 0


def test_conflicting_snapshot_for_same_run_is_rejected_and_rolled_back(
    repository: SQLiteListingRepository,
) -> None:
    initial = make_listing(price=Decimal("19.99"), title="Original")
    conflicting = make_listing(price=Decimal("20.00"), title="No debe persistir")
    record(repository, initial)

    with pytest.raises(PersistenceError, match="conflicting observation"):
        record(repository, conflicting)

    stored = repository.get_listing(initial.key)
    assert stored is not None
    assert stored.title == "Original"
    assert repository.count_price_snapshots() == 1


def test_memory_database_does_not_create_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    with SQLiteListingRepository(":memory:") as repository:
        record(repository, make_listing())
        assert repository.count_listings() == 1

    assert list(tmp_path.iterdir()) == []


def test_connection_closes_cleanly(tmp_path: Path) -> None:
    repository = SQLiteListingRepository(tmp_path / "closed.db")
    repository.close()
    repository.close()

    with pytest.raises(PersistenceError, match="closed"):
        repository.count_listings()
