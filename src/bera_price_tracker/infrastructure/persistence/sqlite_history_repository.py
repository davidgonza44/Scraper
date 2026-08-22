"""Read-only SQLite adapter for one listing's persisted history."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import TracebackType

from bera_price_tracker.application import ListingHistoryRepository
from bera_price_tracker.domain import (
    ListingHistory,
    ListingKey,
    PriceObservation,
    SearchQuery,
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


class DatabaseNotFoundError(PersistenceError):
    """Raised when a read-only database target does not exist."""


class SQLiteListingHistoryRepository(ListingHistoryRepository):
    """Read listing history through a SQLite connection opened with ``mode=ro``."""

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
            raise PersistenceError("could not open SQLite history in read-only mode") from exc

    @property
    def database_path(self) -> str:
        return self._database_path

    def __enter__(self) -> SQLiteListingHistoryRepository:
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
            raise PersistenceError("could not close SQLite history") from exc

    def get_history(self, key: ListingKey) -> ListingHistory | None:
        """Return current metadata and chronological observations for ``key``."""

        connection = self._connection_or_raise()
        try:
            rows = connection.execute(
                """
                SELECT
                    l.title,
                    l.url,
                    l.seller_name,
                    l.location,
                    l.product_condition,
                    l.first_seen_at,
                    l.last_seen_at,
                    ps.id AS snapshot_id,
                    ps.price,
                    ps.currency,
                    ps.usd_amount,
                    cr.query,
                    cr.collected_at
                FROM listings AS l
                LEFT JOIN price_snapshots AS ps ON ps.listing_id = l.id
                LEFT JOIN collection_runs AS cr ON cr.id = ps.collection_run_id
                WHERE l.source = ? AND l.external_id = ?
                ORDER BY cr.collected_at ASC, cr.id ASC, ps.id ASC
                """,
                (key.source.value, key.external_id),
            ).fetchall()
        except sqlite3.Error as exc:
            raise PersistenceError("could not read listing history") from exc

        if not rows:
            return None
        try:
            return self._history_from_rows(key, rows)
        except PersistenceError:
            raise
        except (TypeError, ValueError) as exc:
            raise PersistenceError("stored listing history is invalid") from exc

    @staticmethod
    def _history_from_rows(key: ListingKey, rows: list[sqlite3.Row]) -> ListingHistory:
        metadata = rows[0]
        observations: list[PriceObservation] = []
        for row in rows:
            if row["snapshot_id"] is None:
                continue
            observations.append(
                PriceObservation(
                    price=_decimal_from_text(row["price"]),
                    currency=SQLiteListingHistoryRepository._stored_text(
                        row["currency"], "currency"
                    ),
                    collected_at=_datetime_from_text(row["collected_at"]),
                    query=SearchQuery(
                        SQLiteListingHistoryRepository._stored_text(row["query"], "query")
                    ),
                    usd_amount=_optional_decimal_from_text(row["usd_amount"]),
                )
            )

        return ListingHistory(
            key=key,
            title=SQLiteListingHistoryRepository._stored_text(metadata["title"], "title"),
            url=SQLiteListingHistoryRepository._stored_text(metadata["url"], "url"),
            seller_name=SQLiteListingHistoryRepository._optional_stored_text(
                metadata["seller_name"], "seller_name"
            ),
            location=SQLiteListingHistoryRepository._optional_stored_text(
                metadata["location"], "location"
            ),
            product_condition=SQLiteListingHistoryRepository._optional_stored_text(
                metadata["product_condition"], "product_condition"
            ),
            first_seen_at=_datetime_from_text(metadata["first_seen_at"]),
            last_seen_at=_datetime_from_text(metadata["last_seen_at"]),
            observations=tuple(observations),
        )

    @staticmethod
    def _stored_text(value: object, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise PersistenceError(f"stored {field_name} is invalid")
        return value

    @staticmethod
    def _optional_stored_text(value: object, field_name: str) -> str | None:
        if value is None:
            return None
        return SQLiteListingHistoryRepository._stored_text(value, field_name)

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
            raise PersistenceError("SQLite history is closed")
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
