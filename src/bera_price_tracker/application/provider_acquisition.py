"""Ephemeral acquisition counts. Never stores raw provider payloads."""

from __future__ import annotations

from dataclasses import dataclass

UNAVAILABLE = "No disponible"


@dataclass(frozen=True, slots=True)
class ProviderAcquisitionMetrics:
    """Requested vs received vs mapped counts for one provider call."""

    requested: int
    fetched: int
    usable: int

    @property
    def rejected(self) -> int:
        return max(0, self.fetched - self.usable)


def format_count(value: int | None, *, available: bool = True) -> str:
    """Return a display count, or ``No disponible`` when the metric is unknown."""

    if not available or value is None:
        return UNAVAILABLE
    if isinstance(value, bool) or not isinstance(value, int):
        return UNAVAILABLE
    if value < 0:
        return UNAVAILABLE
    return str(value)
