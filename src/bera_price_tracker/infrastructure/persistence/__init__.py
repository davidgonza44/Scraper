"""Persistence adapters exposed by the infrastructure layer."""

from bera_price_tracker.infrastructure.persistence.sqlite_diagnostics import (
    SQLiteDatabaseDiagnostics,
)
from bera_price_tracker.infrastructure.persistence.sqlite_history_repository import (
    DatabaseNotFoundError,
    SQLiteListingHistoryRepository,
)
from bera_price_tracker.infrastructure.persistence.sqlite_inspection_repository import (
    SQLiteCollectionInspectionRepository,
)
from bera_price_tracker.infrastructure.persistence.sqlite_repository import (
    PersistenceError,
    SQLiteListingRepository,
    StoredListing,
    StoredPriceObservation,
)

__all__ = [
    "DatabaseNotFoundError",
    "PersistenceError",
    "SQLiteCollectionInspectionRepository",
    "SQLiteDatabaseDiagnostics",
    "SQLiteListingRepository",
    "SQLiteListingHistoryRepository",
    "StoredListing",
    "StoredPriceObservation",
]
