"""SQLite adapter for listing metadata and price observations."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import TracebackType

from bera_price_tracker.application.ports import ListingRepository
from bera_price_tracker.domain import (
    CollectionBatch,
    Listing,
    ListingKey,
    MarketplaceSource,
    PriceSnapshot,
    SearchQuery,
)
from bera_price_tracker.infrastructure.persistence.migrations import MIGRATIONS

_DEFAULT_BUSY_TIMEOUT_MS = 5_000
_MEMORY_DATABASE = ":memory:"


class PersistenceError(RuntimeError):
    """Raised when a persistence operation cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class StoredListing:
    """Current listing metadata reconstructed without database-specific types."""

    id: int
    key: ListingKey
    title: str
    url: str
    seller_name: str | None
    location: str | None
    product_condition: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    is_active: bool = True
    price_min: Decimal | None = None
    price_max: Decimal | None = None
    price_display: str | None = None


@dataclass(frozen=True, slots=True)
class StoredPriceObservation:
    """One price snapshot together with the collection run that produced it."""

    collection_run_id: int
    query: SearchQuery
    snapshot: PriceSnapshot


def _datetime_to_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PersistenceError("timestamps must be timezone-aware")
    utc_value = value.astimezone(UTC)
    return utc_value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _datetime_from_text(value: object) -> datetime:
    if not isinstance(value, str):
        raise PersistenceError("stored timestamp is not text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PersistenceError("stored timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PersistenceError("stored timestamp is not timezone-aware")
    return parsed.astimezone(UTC)


def _decimal_to_text(value: Decimal) -> str:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= Decimal("0"):
        raise PersistenceError("price must be a finite positive Decimal")
    return str(value)


def _decimal_from_text(value: object) -> Decimal:
    if not isinstance(value, str):
        raise PersistenceError("stored price is not text")
    try:
        price = Decimal(value)
    except InvalidOperation as exc:
        raise PersistenceError("stored price is invalid") from exc
    if not price.is_finite() or price <= Decimal("0"):
        raise PersistenceError("stored price is invalid")
    return price


def _optional_decimal_from_text(value: object) -> Decimal | None:
    if value is None:
        return None
    return _decimal_from_text(value)


def _optional_decimal_to_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, Decimal) or not value.is_finite() or value <= Decimal("0"):
        raise PersistenceError("optional amount must be a finite positive Decimal")
    return str(value)


class SQLiteListingRepository(ListingRepository):
    """Store observations in one SQLite database connection.

    A repository instance owns its connection and must be closed explicitly or used as
    a context manager. File databases use WAL for light concurrency; this adapter is not
    intended as a high-concurrency replacement for a client/server database.
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

        self._database_path = target
        self._connection: sqlite3.Connection | None = None
        try:
            if target != _MEMORY_DATABASE:
                parent = Path(target).expanduser().parent
                parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(target, isolation_level=None)
            connection.row_factory = sqlite3.Row
            self._connection = connection
            self._configure_connection(connection, busy_timeout_ms, target == _MEMORY_DATABASE)
            self._apply_migrations(connection)
        except PersistenceError:
            self._discard_connection_after_initialization_failure()
            raise
        except (OSError, sqlite3.Error) as exc:
            self._discard_connection_after_initialization_failure()
            raise PersistenceError("could not initialize SQLite persistence") from exc

    @property
    def database_path(self) -> str:
        """Return the configured database target without opening another connection."""

        return self._database_path

    def __enter__(self) -> SQLiteListingRepository:
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
        """Close the owned connection; repeated calls are safe."""

        connection = self._connection
        if connection is None:
            return
        self._connection = None
        try:
            connection.close()
        except sqlite3.Error as exc:
            raise PersistenceError("could not close SQLite persistence") from exc

    def record_collection(self, batch: CollectionBatch) -> None:
        """Persist one run and all its listing observations in one transaction."""

        if not isinstance(batch, CollectionBatch):
            raise TypeError("batch must be a CollectionBatch")
        connection = self._connection_or_raise()
        try:
            connection.execute("BEGIN IMMEDIATE")
            run_id = self._get_or_create_collection_run(connection, batch)
            for listing in batch.listings:
                listing_id = self._upsert_listing(connection, listing)
                self._insert_snapshot(connection, run_id, listing_id, listing)
            connection.commit()
        except PersistenceError as exc:
            connection.rollback()
            raise PersistenceError(f"could not record collection batch: {exc}") from exc
        except sqlite3.Error as exc:
            connection.rollback()
            raise PersistenceError("could not record collection batch") from exc
        except Exception as exc:
            connection.rollback()
            raise PersistenceError("could not record collection batch") from exc

    def get_listing(self, key: ListingKey) -> StoredListing | None:
        """Return current metadata for a natural listing identity."""

        connection = self._connection_or_raise()
        try:
            row = connection.execute(
                """
                SELECT id, source, external_id, title, url, seller_name, location,
                       product_condition, first_seen_at, last_seen_at, is_active,
                       price_min, price_max, price_display
                FROM listings
                WHERE source = ? AND external_id = ?
                """,
                (key.source.value, key.external_id),
            ).fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError("could not read listing metadata") from exc
        if row is None:
            return None
        return self._stored_listing(row)

    def get_price_history(self, key: ListingKey) -> list[StoredPriceObservation]:
        """Return price observations in ascending collection time order."""

        connection = self._connection_or_raise()
        try:
            rows = connection.execute(
                """
                SELECT cr.id AS run_id, cr.query, cr.collected_at, ps.price, ps.currency,
                       ps.usd_amount, ps.price_min, ps.price_max
                FROM price_snapshots AS ps
                JOIN collection_runs AS cr ON cr.id = ps.collection_run_id
                JOIN listings AS l ON l.id = ps.listing_id
                WHERE l.source = ? AND l.external_id = ?
                ORDER BY cr.collected_at ASC, ps.id ASC
                """,
                (key.source.value, key.external_id),
            ).fetchall()
        except sqlite3.Error as exc:
            raise PersistenceError("could not read price history") from exc

        return [
            StoredPriceObservation(
                collection_run_id=int(row["run_id"]),
                query=SearchQuery(str(row["query"])),
                snapshot=PriceSnapshot(
                    listing_key=key,
                    price=_decimal_from_text(row["price"]),
                    currency=str(row["currency"]),
                    collected_at=_datetime_from_text(row["collected_at"]),
                    usd_amount=_optional_decimal_from_text(row["usd_amount"]),
                    price_min=_optional_decimal_from_text(row["price_min"]),
                    price_max=_optional_decimal_from_text(row["price_max"]),
                ),
            )
            for row in rows
        ]

    def set_listing_active(self, key: ListingKey, active: bool) -> bool:
        """Mark a listing active or inactive without deleting snapshots."""

        if not isinstance(key, ListingKey):
            raise TypeError("key must be a ListingKey")
        connection = self._connection_or_raise()
        try:
            cursor = connection.execute(
                """
                UPDATE listings
                SET is_active = ?
                WHERE source = ? AND external_id = ?
                """,
                (1 if active else 0, key.source.value, key.external_id),
            )
        except sqlite3.Error as exc:
            raise PersistenceError("could not update listing tracking state") from exc
        return cursor.rowcount > 0

    def list_listing_keys(
        self,
        source: MarketplaceSource,
        *,
        active_only: bool = False,
    ) -> list[ListingKey]:
        """Return listing identities for one marketplace source."""

        if not isinstance(source, MarketplaceSource):
            raise TypeError("source must be a MarketplaceSource")
        connection = self._connection_or_raise()
        try:
            if active_only:
                rows = connection.execute(
                    """
                    SELECT external_id
                    FROM listings
                    WHERE source = ? AND is_active = 1
                    ORDER BY last_seen_at DESC, title ASC
                    """,
                    (source.value,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT external_id
                    FROM listings
                    WHERE source = ?
                    ORDER BY last_seen_at DESC, title ASC
                    """,
                    (source.value,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise PersistenceError("could not list listings") from exc
        return [ListingKey(source=source, external_id=str(row["external_id"])) for row in rows]

    def count_listings(self) -> int:
        """Return the number of unique marketplace listings."""

        return self._count("SELECT COUNT(*) FROM listings", "listings")

    def count_collection_runs(self) -> int:
        """Return the number of distinct collection runs."""

        return self._count("SELECT COUNT(*) FROM collection_runs", "collection runs")

    def count_price_snapshots(self) -> int:
        """Return the number of persisted listing observations."""

        return self._count("SELECT COUNT(*) FROM price_snapshots", "price snapshots")

    def schema_version(self) -> int:
        """Return the greatest applied migration version."""

        connection = self._connection_or_raise()
        try:
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError("could not read schema version") from exc
        if row is None:
            raise PersistenceError("schema version query returned no result")
        return int(row[0])

    def foreign_keys_enabled(self) -> bool:
        """Report whether this connection enforces foreign keys."""

        connection = self._connection_or_raise()
        try:
            row = connection.execute("PRAGMA foreign_keys").fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError("could not read foreign key configuration") from exc
        return row is not None and int(row[0]) == 1

    @staticmethod
    def _configure_connection(
        connection: sqlite3.Connection,
        busy_timeout_ms: int,
        is_memory: bool,
    ) -> None:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {busy_timeout_ms:d}")
        if not is_memory:
            connection.execute("PRAGMA journal_mode = WAL")
        row = connection.execute("PRAGMA foreign_keys").fetchone()
        if row is None or int(row[0]) != 1:
            raise sqlite3.OperationalError("SQLite foreign key enforcement is unavailable")

    @staticmethod
    def _apply_migrations(connection: sqlite3.Connection) -> None:
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    applied_at TEXT NOT NULL
                )
                """
            )
            applied_rows = connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
            applied = {int(row[0]) for row in applied_rows}
            known = {migration.version for migration in MIGRATIONS}
            unknown = applied - known
            if unknown:
                versions = ", ".join(str(version) for version in sorted(unknown))
                raise PersistenceError(f"database has unknown schema version(s): {versions}")

            applied_at = _datetime_to_text(datetime.now(UTC))
            for migration in MIGRATIONS:
                if migration.version in applied:
                    continue
                for statement in migration.statements:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (migration.version, migration.name, applied_at),
                )
            connection.commit()
        except PersistenceError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise PersistenceError("could not apply SQLite schema migrations") from exc

    @staticmethod
    def _upsert_listing(connection: sqlite3.Connection, listing: Listing) -> int:
        seen_at = _datetime_to_text(listing.collected_at)
        connection.execute(
            """
            INSERT INTO listings (
                source, external_id, title, url, seller_name, location,
                product_condition, first_seen_at, last_seen_at, is_active,
                price_min, price_max, price_display
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            ON CONFLICT (source, external_id) DO UPDATE SET
                title = excluded.title,
                url = excluded.url,
                seller_name = COALESCE(excluded.seller_name, listings.seller_name),
                location = COALESCE(excluded.location, listings.location),
                product_condition = COALESCE(
                    excluded.product_condition, listings.product_condition
                ),
                last_seen_at = CASE
                    WHEN excluded.last_seen_at > listings.last_seen_at
                    THEN excluded.last_seen_at
                    ELSE listings.last_seen_at
                END,
                price_min = COALESCE(excluded.price_min, listings.price_min),
                price_max = COALESCE(excluded.price_max, listings.price_max),
                price_display = COALESCE(excluded.price_display, listings.price_display)
            """,
            (
                listing.source.value,
                listing.external_id,
                listing.title,
                listing.url,
                listing.seller_name,
                listing.location,
                listing.product_condition,
                seen_at,
                seen_at,
                _optional_decimal_to_text(listing.price_min),
                _optional_decimal_to_text(listing.price_max),
                listing.formatted_amount,
            ),
        )
        row = connection.execute(
            "SELECT id FROM listings WHERE source = ? AND external_id = ?",
            (listing.source.value, listing.external_id),
        ).fetchone()
        if row is None:
            raise sqlite3.IntegrityError("listing upsert returned no identity")
        return int(row[0])

    @staticmethod
    def _get_or_create_collection_run(
        connection: sqlite3.Connection,
        batch: CollectionBatch,
    ) -> int:
        collected_at = _datetime_to_text(batch.collected_at)
        identity = (batch.source.value, batch.query.text, collected_at)
        connection.execute(
            """
            INSERT INTO collection_runs (source, query, collected_at)
            VALUES (?, ?, ?)
            ON CONFLICT (source, query, collected_at) DO NOTHING
            """,
            identity,
        )
        row = connection.execute(
            """
            SELECT id FROM collection_runs
            WHERE source = ? AND query = ? AND collected_at = ?
            """,
            identity,
        ).fetchone()
        if row is None:
            raise sqlite3.IntegrityError("collection run upsert returned no identity")
        return int(row[0])

    @staticmethod
    def _insert_snapshot(
        connection: sqlite3.Connection,
        run_id: int,
        listing_id: int,
        listing: Listing,
    ) -> None:
        price = _decimal_to_text(listing.price)
        usd_amount = _optional_decimal_to_text(listing.usd_amount)
        usd_rate = _optional_decimal_to_text(listing.usd_exchange_rate)
        rate_at = (
            None
            if listing.usd_exchange_rate_at is None
            else _datetime_to_text(listing.usd_exchange_rate_at)
        )
        evidence = ",".join(listing.usd_evidence) if listing.usd_evidence else None
        connection.execute(
            """
            INSERT INTO price_snapshots (
                collection_run_id, listing_id, price, currency,
                usd_amount, usd_exchange_rate, usd_exchange_rate_source,
                usd_exchange_rate_at, usd_normalization_status, usd_evidence,
                original_formatted, price_min, price_max
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (collection_run_id, listing_id) DO NOTHING
            """,
            (
                run_id,
                listing_id,
                price,
                listing.currency,
                usd_amount,
                usd_rate,
                listing.usd_exchange_rate_source,
                rate_at,
                listing.usd_normalization_status,
                evidence,
                listing.formatted_amount,
                _optional_decimal_to_text(listing.price_min),
                _optional_decimal_to_text(listing.price_max),
            ),
        )
        row = connection.execute(
            """
            SELECT price, currency FROM price_snapshots
            WHERE collection_run_id = ? AND listing_id = ?
            """,
            (run_id, listing_id),
        ).fetchone()
        if row is None:
            raise sqlite3.IntegrityError("snapshot insert returned no observation")
        if row["price"] != price or row["currency"] != listing.currency:
            raise PersistenceError("collection run already contains a conflicting observation")

    def _stored_listing(self, row: sqlite3.Row) -> StoredListing:
        try:
            source = MarketplaceSource(str(row["source"]))
        except ValueError as exc:
            raise PersistenceError("stored listing source is invalid") from exc
        is_active_raw = row["is_active"]
        is_active = True if is_active_raw is None else bool(int(is_active_raw))
        return StoredListing(
            id=int(row["id"]),
            key=ListingKey(source=source, external_id=str(row["external_id"])),
            title=str(row["title"]),
            url=str(row["url"]),
            seller_name=self._optional_stored_text(row["seller_name"]),
            location=self._optional_stored_text(row["location"]),
            product_condition=self._optional_stored_text(row["product_condition"]),
            first_seen_at=_datetime_from_text(row["first_seen_at"]),
            last_seen_at=_datetime_from_text(row["last_seen_at"]),
            is_active=is_active,
            price_min=_optional_decimal_from_text(row["price_min"]),
            price_max=_optional_decimal_from_text(row["price_max"]),
            price_display=self._optional_stored_text(row["price_display"]),
        )

    @staticmethod
    def _optional_stored_text(value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise PersistenceError("stored optional metadata is not text")
        return value

    def _count(self, statement: str, resource: str) -> int:
        connection = self._connection_or_raise()
        try:
            row = connection.execute(statement).fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not count {resource}") from exc
        if row is None:
            raise PersistenceError(f"count query for {resource} returned no result")
        return int(row[0])

    def _connection_or_raise(self) -> sqlite3.Connection:
        if self._connection is None:
            raise PersistenceError("SQLite persistence is closed")
        return self._connection

    def _discard_connection_after_initialization_failure(self) -> None:
        connection = self._connection
        self._connection = None
        if connection is None:
            return
        try:
            connection.close()
        except sqlite3.Error:
            # Preserve the initialization error that explains why this cleanup ran.
            pass
