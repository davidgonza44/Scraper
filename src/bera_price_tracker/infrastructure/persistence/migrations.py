"""Versioned SQLite schema migrations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Migration:
    """One append-only schema change."""

    version: int
    name: str
    statements: tuple[str, ...]


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        name="001_initial",
        statements=(
            """
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
                last_seen_at TEXT NOT NULL,
                UNIQUE (source, external_id)
            )
            """,
            """
            CREATE TABLE collection_runs (
                id INTEGER PRIMARY KEY,
                source TEXT NOT NULL,
                query TEXT NOT NULL,
                collected_at TEXT NOT NULL,
                UNIQUE (source, query, collected_at)
            )
            """,
            """
            CREATE TABLE price_snapshots (
                id INTEGER PRIMARY KEY,
                collection_run_id INTEGER NOT NULL,
                listing_id INTEGER NOT NULL,
                price TEXT NOT NULL,
                currency TEXT NOT NULL,
                FOREIGN KEY (collection_run_id)
                    REFERENCES collection_runs (id) ON DELETE RESTRICT,
                FOREIGN KEY (listing_id)
                    REFERENCES listings (id) ON DELETE RESTRICT,
                UNIQUE (collection_run_id, listing_id)
            )
            """,
            """
            CREATE INDEX idx_price_snapshots_listing_id
            ON price_snapshots (listing_id)
            """,
            """
            CREATE INDEX idx_collection_runs_collected_at
            ON collection_runs (collected_at)
            """,
        ),
    ),
    Migration(
        version=2,
        name="002_price_snapshot_usd_columns",
        statements=(
            "ALTER TABLE price_snapshots ADD COLUMN usd_amount TEXT",
            "ALTER TABLE price_snapshots ADD COLUMN usd_exchange_rate TEXT",
            "ALTER TABLE price_snapshots ADD COLUMN usd_exchange_rate_source TEXT",
            "ALTER TABLE price_snapshots ADD COLUMN usd_exchange_rate_at TEXT",
            "ALTER TABLE price_snapshots ADD COLUMN usd_normalization_status TEXT",
            "ALTER TABLE price_snapshots ADD COLUMN usd_evidence TEXT",
            "ALTER TABLE price_snapshots ADD COLUMN original_formatted TEXT",
        ),
    ),
)
