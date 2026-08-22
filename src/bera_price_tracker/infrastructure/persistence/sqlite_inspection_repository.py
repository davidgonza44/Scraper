"""Read-only SQLite adapter for inspecting one persisted collection run."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import TracebackType

from bera_price_tracker.application import CollectionInspectionRepository
from bera_price_tracker.domain import (
    CollectionRunInspection,
    ListingKey,
    MarketplaceSource,
    ObservedListing,
    SearchQuery,
)
from bera_price_tracker.infrastructure.persistence.sqlite_history_repository import (
    DatabaseNotFoundError,
)
from bera_price_tracker.infrastructure.persistence.sqlite_repository import (
    PersistenceError,
    _datetime_from_text,
    _decimal_from_text,
    _optional_decimal_from_text,
)

_DEFAULT_BUSY_TIMEOUT_MS = 5_000
_REQUIRED_TABLES = frozenset(
    {"schema_migrations", "listings", "collection_runs", "price_snapshots"}
)


class SQLiteCollectionInspectionRepository(CollectionInspectionRepository):
    """Inspect the latest matching run through a ``mode=ro`` SQLite connection.

    Observations are ordered by their persisted price-snapshot identity. Listing
    metadata is the current value from ``listings``; price and currency come from
    the selected historical collection run.
    """

    def __init__(
        self,
        database_path: str | Path,
        *,
        busy_timeout_ms: int = _DEFAULT_BUSY_TIMEOUT_MS,
    ) -> None:
        if busy_timeout_ms <= 0:
            raise ValueError("busy_timeout_ms must be greater than zero")

        target = str(database_path)
        if not target.strip():
            raise ValueError("database_path must not be blank")

        path = Path(target).expanduser()
        if not path.is_file():
            raise DatabaseNotFoundError(f"database not found: {target}")

        self._database_path = target
        self._connection: sqlite3.Connection | None = None
        try:
            database_uri = f"{path.resolve().as_uri()}?mode=ro"
            connection = sqlite3.connect(database_uri, uri=True, isolation_level=None)
            connection.row_factory = sqlite3.Row
            self._connection = connection
            connection.execute(f"PRAGMA busy_timeout = {busy_timeout_ms:d}")
            connection.execute("PRAGMA query_only = ON")
            self._validate_schema(connection)
        except PersistenceError:
            self._discard_connection_after_initialization_failure()
            raise
        except (OSError, sqlite3.Error) as exc:
            self._discard_connection_after_initialization_failure()
            raise PersistenceError("could not open SQLite inspection in read-only mode") from exc

    @property
    def database_path(self) -> str:
        """Return the configured database target."""

        return self._database_path

    def __enter__(self) -> SQLiteCollectionInspectionRepository:
        self._connection_or_raise()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the read-only connection; repeated calls are safe."""

        connection = self._connection
        if connection is None:
            return
        self._connection = None
        try:
            connection.close()
        except sqlite3.Error as exc:
            raise PersistenceError("could not close SQLite inspection") from exc

    def get_latest_run(
        self,
        source: MarketplaceSource,
        query: SearchQuery,
        limit: int,
    ) -> CollectionRunInspection | None:
        """Return a limited view of the latest run for exactly ``source`` and ``query``."""

        if not isinstance(source, MarketplaceSource):
            raise TypeError("source must be a MarketplaceSource")
        if not isinstance(query, SearchQuery):
            raise TypeError("query must be a SearchQuery")
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise TypeError("limit must be an integer")
        if limit <= 0:
            raise ValueError("limit must be greater than zero")

        connection = self._connection_or_raise()
        try:
            rows = connection.execute(
                """
                WITH latest_run AS (
                    SELECT id, source, query, collected_at
                    FROM collection_runs
                    WHERE source = ? AND query = ?
                    ORDER BY collected_at DESC, id DESC
                    LIMIT 1
                )
                SELECT
                    lr.id AS run_id,
                    lr.source AS run_source,
                    lr.query AS run_query,
                    lr.collected_at,
                    (
                        SELECT COUNT(*)
                        FROM price_snapshots AS counted
                        WHERE counted.collection_run_id = lr.id
                    ) AS total_listings,
                    ps.id AS snapshot_id,
                    l.source AS listing_source,
                    l.external_id,
                    l.title,
                    l.url,
                    l.seller_name,
                    l.location,
                    l.product_condition,
                    ps.price,
                    ps.currency,
                    ps.usd_amount
                FROM latest_run AS lr
                LEFT JOIN price_snapshots AS ps ON ps.collection_run_id = lr.id
                LEFT JOIN listings AS l ON l.id = ps.listing_id
                ORDER BY ps.id ASC
                LIMIT ?
                """,
                (source.value, query.text, limit),
            ).fetchall()
        except sqlite3.Error as exc:
            raise PersistenceError("could not inspect latest collection run") from exc

        if not rows:
            return None
        try:
            return self._inspection_from_rows(rows)
        except PersistenceError:
            raise
        except (TypeError, ValueError) as exc:
            raise PersistenceError("stored collection inspection is invalid") from exc

    @classmethod
    def _inspection_from_rows(cls, rows: list[sqlite3.Row]) -> CollectionRunInspection:
        run = rows[0]
        try:
            source = MarketplaceSource(cls._stored_text(run["run_source"], "source"))
        except ValueError as exc:
            raise PersistenceError("stored collection source is invalid") from exc

        observations: list[ObservedListing] = []
        for row in rows:
            if row["snapshot_id"] is None:
                continue
            try:
                listing_source = MarketplaceSource(
                    cls._stored_text(row["listing_source"], "listing source")
                )
            except ValueError as exc:
                raise PersistenceError("stored listing source is invalid") from exc
            observations.append(
                ObservedListing(
                    key=ListingKey(
                        source=listing_source,
                        external_id=cls._stored_text(row["external_id"], "external_id"),
                    ),
                    title=cls._stored_text(row["title"], "title"),
                    url=cls._stored_text(row["url"], "url"),
                    price=_decimal_from_text(row["price"]),
                    currency=cls._stored_text(row["currency"], "currency"),
                    usd_amount=_optional_decimal_from_text(row["usd_amount"]),
                    seller_name=cls._optional_stored_text(row["seller_name"], "seller_name"),
                    location=cls._optional_stored_text(row["location"], "location"),
                    product_condition=cls._optional_stored_text(
                        row["product_condition"], "product_condition"
                    ),
                )
            )

        total_listings = run["total_listings"]
        if not isinstance(total_listings, int) or isinstance(total_listings, bool):
            raise PersistenceError("stored collection listing count is invalid")
        return CollectionRunInspection(
            source=source,
            query=SearchQuery(cls._stored_text(run["run_query"], "query")),
            collected_at=_datetime_from_text(run["collected_at"]),
            total_listings=total_listings,
            observations=tuple(observations),
        )

    @staticmethod
    def _stored_text(value: object, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise PersistenceError(f"stored {field_name} is invalid")
        return value

    @classmethod
    def _optional_stored_text(cls, value: object, field_name: str) -> str | None:
        if value is None:
            return None
        return cls._stored_text(value, field_name)

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name IN (
                  'schema_migrations', 'listings', 'collection_runs', 'price_snapshots'
              )
            """
        ).fetchall()
        available = {str(row[0]) for row in rows}
        if available != _REQUIRED_TABLES:
            raise PersistenceError("database schema is not initialized")

    def _connection_or_raise(self) -> sqlite3.Connection:
        if self._connection is None:
            raise PersistenceError("SQLite inspection is closed")
        return self._connection

    def _discard_connection_after_initialization_failure(self) -> None:
        connection = self._connection
        self._connection = None
        if connection is None:
            return
        try:
            connection.close()
        except sqlite3.Error:
            pass
