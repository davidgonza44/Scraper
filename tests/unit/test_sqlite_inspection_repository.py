"""Unit tests for the read-only SQLite collection inspection adapter."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from bera_price_tracker.application import CollectionInspectionRepository
from bera_price_tracker.domain import (
    CollectionBatch,
    Listing,
    MarketplaceSource,
    SearchQuery,
)
from bera_price_tracker.infrastructure.persistence import (
    DatabaseNotFoundError,
    PersistenceError,
    SQLiteCollectionInspectionRepository,
    SQLiteListingRepository,
    sqlite_repository,
)
from bera_price_tracker.infrastructure.persistence.migrations import MIGRATIONS, Migration

QUERY = SearchQuery("pastillas de freno bera")
OTHER_QUERY = SearchQuery("discos de freno bera")
FIRST_TIME = datetime(2026, 8, 21, 12, 0, 0, 123456, tzinfo=UTC)
SECOND_TIME = FIRST_TIME + timedelta(hours=1)
THIRD_TIME = SECOND_TIME + timedelta(hours=1)


def make_listing(
    external_id: str,
    *,
    source: MarketplaceSource = MarketplaceSource.MERCADO_LIBRE,
    query: SearchQuery = QUERY,
    collected_at: datetime = FIRST_TIME,
    title: str | None = None,
    price: str = "19.99",
    currency: str = "VES",
    seller_name: str | None = "Repuestos BERA",
    location: str | None = "Caracas",
    product_condition: str | None = "new",
) -> Listing:
    return Listing(
        source=source,
        external_id=external_id,
        title=title or f"Pastillas {external_id}",
        price=Decimal(price),
        currency=currency,
        url=f"https://example.test/{source.value}/{external_id}",
        query=query,
        collected_at=collected_at,
        seller_name=seller_name,
        location=location,
        product_condition=product_condition,
    )


def make_batch(
    *listings: Listing,
    source: MarketplaceSource = MarketplaceSource.MERCADO_LIBRE,
    query: SearchQuery = QUERY,
    collected_at: datetime = FIRST_TIME,
) -> CollectionBatch:
    return CollectionBatch(
        source=source,
        query=query,
        collected_at=collected_at,
        listings=tuple(listings),
    )


def record_batches(database_path: Path, *batches: CollectionBatch) -> None:
    with SQLiteListingRepository(database_path) as writer:
        for batch in batches:
            writer.record_collection(batch)


def test_latest_run_reconstructs_one_listing_with_exact_decimal_and_utc_timestamp(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "inspection.db"
    local_time = datetime(
        2026,
        8,
        21,
        8,
        30,
        45,
        654321,
        tzinfo=timezone(timedelta(hours=-4)),
    )
    listing = make_listing(
        "MLV-EXACT",
        collected_at=local_time,
        price="1234567890.123456789",
    )
    record_batches(
        database_path,
        make_batch(listing, collected_at=local_time),
    )

    with SQLiteCollectionInspectionRepository(database_path) as reader:
        assert isinstance(reader, CollectionInspectionRepository)
        inspection = reader.get_latest_run(
            MarketplaceSource.MERCADO_LIBRE,
            QUERY,
            20,
        )

    assert inspection is not None
    assert inspection.source is MarketplaceSource.MERCADO_LIBRE
    assert inspection.query == QUERY
    assert inspection.collected_at == local_time.astimezone(UTC)
    assert inspection.collected_at.tzinfo is UTC
    assert inspection.total_listings == 1
    assert len(inspection.observations) == 1
    observation = inspection.observations[0]
    assert not isinstance(observation, sqlite3.Row)
    assert observation.key == listing.key
    assert observation.title == listing.title
    assert observation.url == listing.url
    assert observation.price == Decimal("1234567890.123456789")
    assert str(observation.price) == "1234567890.123456789"
    assert observation.currency == "VES"
    assert observation.seller_name == "Repuestos BERA"
    assert observation.location == "Caracas"
    assert observation.product_condition == "new"


def test_chronologically_latest_run_wins_even_when_it_has_the_lower_id(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "chronological.db"
    newer = make_listing("MLV-NEW", collected_at=SECOND_TIME)
    older = make_listing("MLV-OLD", collected_at=FIRST_TIME)
    record_batches(
        database_path,
        make_batch(newer, collected_at=SECOND_TIME),
        make_batch(older, collected_at=FIRST_TIME),
    )

    with SQLiteCollectionInspectionRepository(database_path) as reader:
        inspection = reader.get_latest_run(MarketplaceSource.MERCADO_LIBRE, QUERY, 20)

    assert inspection is not None
    assert inspection.collected_at == SECOND_TIME
    assert [item.key.external_id for item in inspection.observations] == ["MLV-NEW"]


def test_equal_timestamps_are_resolved_by_highest_collection_run_id(tmp_path: Path) -> None:
    database_path = tmp_path / "timestamp-tie.db"
    timestamp = "2026-08-21T12:00:00.123456Z"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            );
            CREATE TABLE listings (
                id INTEGER PRIMARY KEY,
                source TEXT NOT NULL,
                external_id TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                seller_name TEXT,
                location TEXT,
                product_condition TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            );
            CREATE TABLE collection_runs (
                id INTEGER PRIMARY KEY,
                source TEXT NOT NULL,
                query TEXT NOT NULL,
                collected_at TEXT NOT NULL
            );
            CREATE TABLE price_snapshots (
                id INTEGER PRIMARY KEY,
                collection_run_id INTEGER NOT NULL,
                listing_id INTEGER NOT NULL,
                price TEXT NOT NULL,
                currency TEXT NOT NULL,
                usd_amount TEXT
            );
            """
        )
        connection.executemany(
            """
            INSERT INTO listings (
                id, source, external_id, title, url, first_seen_at, last_seen_at
            ) VALUES (?, 'mercado_libre', ?, ?, ?, ?, ?)
            """,
            (
                (1, "MLV-LOW-ID", "Lower run", "https://example.test/lower", timestamp, timestamp),
                (
                    2,
                    "MLV-HIGH-ID",
                    "Higher run",
                    "https://example.test/higher",
                    timestamp,
                    timestamp,
                ),
            ),
        )
        connection.executemany(
            """
            INSERT INTO collection_runs (id, source, query, collected_at)
            VALUES (?, 'mercado_libre', ?, ?)
            """,
            ((7, QUERY.text, timestamp), (9, QUERY.text, timestamp)),
        )
        connection.executemany(
            """
            INSERT INTO price_snapshots (
                id, collection_run_id, listing_id, price, currency
            ) VALUES (?, ?, ?, ?, 'VES')
            """,
            ((1, 7, 1, "10.00"), (2, 9, 2, "20.00")),
        )

    with SQLiteCollectionInspectionRepository(database_path) as reader:
        inspection = reader.get_latest_run(MarketplaceSource.MERCADO_LIBRE, QUERY, 20)

    assert inspection is not None
    assert [item.key.external_id for item in inspection.observations] == ["MLV-HIGH-ID"]


def test_multiple_listings_are_snapshot_id_ordered_and_limit_keeps_full_total(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "limit.db"
    listings = (
        make_listing("MLV-FIRST", price="30.00"),
        make_listing("MLV-SECOND", price="10.00"),
        make_listing("MLV-THIRD", price="20.00"),
    )
    record_batches(database_path, make_batch(*listings))

    with SQLiteCollectionInspectionRepository(database_path) as reader:
        inspection = reader.get_latest_run(MarketplaceSource.MERCADO_LIBRE, QUERY, 2)

    assert inspection is not None
    assert inspection.total_listings == 3
    assert len(inspection.observations) == 2
    assert [item.key.external_id for item in inspection.observations] == [
        "MLV-FIRST",
        "MLV-SECOND",
    ]


def test_latest_empty_batch_is_found_and_does_not_fall_back_to_earlier_results(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "empty-latest.db"
    earlier = make_listing("MLV-EARLIER", collected_at=FIRST_TIME)
    record_batches(
        database_path,
        make_batch(earlier, collected_at=FIRST_TIME),
        make_batch(collected_at=SECOND_TIME),
    )

    with SQLiteCollectionInspectionRepository(database_path) as reader:
        inspection = reader.get_latest_run(MarketplaceSource.MERCADO_LIBRE, QUERY, 20)

    assert inspection is not None
    assert inspection.collected_at == SECOND_TIME
    assert inspection.total_listings == 0
    assert inspection.observations == ()


def test_unknown_query_returns_none_in_an_existing_database(tmp_path: Path) -> None:
    database_path = tmp_path / "unknown.db"
    record_batches(database_path, make_batch(make_listing("MLV-KNOWN")))

    with SQLiteCollectionInspectionRepository(database_path) as reader:
        inspection = reader.get_latest_run(
            MarketplaceSource.MERCADO_LIBRE,
            SearchQuery("nunca recolectada"),
            20,
        )

    assert inspection is None


def test_same_query_in_two_sources_is_not_mixed(tmp_path: Path) -> None:
    database_path = tmp_path / "sources.db"
    mercado_libre = make_listing("SHARED", collected_at=FIRST_TIME)
    facebook = make_listing(
        "SHARED",
        source=MarketplaceSource.FACEBOOK_MARKETPLACE,
        collected_at=SECOND_TIME,
        title="Facebook listing",
    )
    record_batches(
        database_path,
        make_batch(mercado_libre, collected_at=FIRST_TIME),
        make_batch(
            facebook,
            source=MarketplaceSource.FACEBOOK_MARKETPLACE,
            collected_at=SECOND_TIME,
        ),
    )

    with SQLiteCollectionInspectionRepository(database_path) as reader:
        inspection = reader.get_latest_run(MarketplaceSource.MERCADO_LIBRE, QUERY, 20)

    assert inspection is not None
    assert inspection.source is MarketplaceSource.MERCADO_LIBRE
    assert [item.title for item in inspection.observations] == [mercado_libre.title]


def test_other_query_runs_are_not_mixed(tmp_path: Path) -> None:
    database_path = tmp_path / "queries.db"
    requested = make_listing("MLV-REQUESTED", collected_at=FIRST_TIME)
    other = make_listing(
        "MLV-OTHER",
        query=OTHER_QUERY,
        collected_at=THIRD_TIME,
    )
    record_batches(
        database_path,
        make_batch(requested, collected_at=FIRST_TIME),
        make_batch(other, query=OTHER_QUERY, collected_at=THIRD_TIME),
    )

    with SQLiteCollectionInspectionRepository(database_path) as reader:
        inspection = reader.get_latest_run(MarketplaceSource.MERCADO_LIBRE, QUERY, 20)

    assert inspection is not None
    assert inspection.query == QUERY
    assert inspection.collected_at == FIRST_TIME
    assert [item.key.external_id for item in inspection.observations] == ["MLV-REQUESTED"]


def test_query_text_is_bound_as_an_exact_parameter(tmp_path: Path) -> None:
    database_path = tmp_path / "parameterized.db"
    unusual_query = SearchQuery("pastillas ' OR 1=1 --")
    unusual = make_listing("MLV-QUOTED", query=unusual_query)
    ordinary = make_listing("MLV-ORDINARY", collected_at=SECOND_TIME)
    record_batches(
        database_path,
        make_batch(unusual, query=unusual_query),
        make_batch(ordinary, collected_at=SECOND_TIME),
    )

    with SQLiteCollectionInspectionRepository(database_path) as reader:
        inspection = reader.get_latest_run(
            MarketplaceSource.MERCADO_LIBRE,
            unusual_query,
            20,
        )

    assert inspection is not None
    assert inspection.query == unusual_query
    assert [item.key.external_id for item in inspection.observations] == ["MLV-QUOTED"]


def test_present_and_absent_optional_metadata_are_reconstructed(tmp_path: Path) -> None:
    database_path = tmp_path / "optional.db"
    present = make_listing("MLV-PRESENT")
    absent = make_listing(
        "MLV-ABSENT",
        seller_name=None,
        location=None,
        product_condition=None,
    )
    record_batches(database_path, make_batch(present, absent))

    with SQLiteCollectionInspectionRepository(database_path) as reader:
        inspection = reader.get_latest_run(MarketplaceSource.MERCADO_LIBRE, QUERY, 20)

    assert inspection is not None
    first, second = inspection.observations
    assert (first.seller_name, first.location, first.product_condition) == (
        "Repuestos BERA",
        "Caracas",
        "new",
    )
    assert (second.seller_name, second.location, second.product_condition) == (
        None,
        None,
        None,
    )


def test_historical_price_is_joined_with_current_listing_metadata(tmp_path: Path) -> None:
    database_path = tmp_path / "current-metadata.db"
    original = make_listing("MLV-SHARED", title="Original title", price="10.00")
    updated = make_listing(
        "MLV-SHARED",
        query=OTHER_QUERY,
        collected_at=SECOND_TIME,
        title="Current title",
        price="99.00",
    )
    record_batches(
        database_path,
        make_batch(original),
        make_batch(updated, query=OTHER_QUERY, collected_at=SECOND_TIME),
    )

    with SQLiteCollectionInspectionRepository(database_path) as reader:
        inspection = reader.get_latest_run(MarketplaceSource.MERCADO_LIBRE, QUERY, 20)

    assert inspection is not None
    observation = inspection.observations[0]
    assert observation.title == "Current title"
    assert observation.price == Decimal("10.00")


def test_missing_database_and_parent_directory_are_not_created(tmp_path: Path) -> None:
    parent = tmp_path / "missing" / "nested"
    database_path = parent / "tracker.db"

    with pytest.raises(DatabaseNotFoundError, match="database not found"):
        SQLiteCollectionInspectionRepository(database_path)

    assert not database_path.exists()
    assert not parent.exists()


def test_connection_is_query_only_and_rejects_writes(tmp_path: Path) -> None:
    database_path = tmp_path / "read-only.db"
    record_batches(database_path, make_batch(make_listing("MLV-READ-ONLY")))
    before = database_path.read_bytes()

    reader = SQLiteCollectionInspectionRepository(database_path)
    connection = reader._connection
    assert connection is not None
    query_only = connection.execute("PRAGMA query_only").fetchone()
    assert query_only is not None
    assert int(query_only[0]) == 1
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        connection.execute("UPDATE listings SET title = 'forbidden'")
    reader.close()
    reader.close()

    assert database_path.read_bytes() == before
    with pytest.raises(PersistenceError, match="closed"):
        reader.get_latest_run(MarketplaceSource.MERCADO_LIBRE, QUERY, 20)


def test_inspection_open_never_applies_pending_writer_migrations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "no-migration.db"
    record_batches(database_path, make_batch(make_listing("MLV-NO-MIGRATION")))
    marker = Migration(
        version=3,
        name="003_must_not_run_from_inspection",
        statements=("CREATE TABLE forbidden_inspection_migration (id INTEGER)",),
    )
    monkeypatch.setattr(sqlite_repository, "MIGRATIONS", (*MIGRATIONS, marker))

    with SQLiteCollectionInspectionRepository(database_path) as reader:
        assert reader.get_latest_run(MarketplaceSource.MERCADO_LIBRE, QUERY, 20) is not None

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone() == (2,)
        marker_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'forbidden_inspection_migration'"
        ).fetchone()
    assert marker_table is None
