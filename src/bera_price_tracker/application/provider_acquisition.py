"""Ephemeral acquisition counts. Never stores raw provider payloads."""

from __future__ import annotations

from dataclasses import dataclass

UNAVAILABLE = "No disponible"


@dataclass(frozen=True, slots=True)
class ProviderAcquisitionMetrics:
    """Counts observed by one existing low-level provider acquisition.

    This compatibility contract remains the input boundary for current adapters.
    Generic logical searches consolidate one or more such acquisitions into the
    provider-neutral :class:`ProviderRunMetrics` below.
    """

    requested: int
    fetched: int
    usable: int

    @property
    def rejected(self) -> int:
        return max(0, self.fetched - self.usable)


@dataclass(frozen=True, slots=True)
class ProviderRunMetrics:
    """Truthful aggregate metrics for one logical generic-provider search.

    ``acquisition_budget`` is the finite ceiling available to the strategy.
    ``acquisition_requested`` counts only candidate limits from internal
    acquisitions that actually ran. Optional stages remain ``None`` when the
    strategy cannot observe them truthfully. No arithmetic identity between
    fetched, mapped, rejected, and usable is implied.
    """

    display_requested: int
    acquisition_budget: int
    acquisition_requested: int
    fetched: int | None
    mapped: int | None
    rejected: int | None
    usable: int
    displayed: int

    def __post_init__(self) -> None:
        for name, value in (
            ("display_requested", self.display_requested),
            ("acquisition_budget", self.acquisition_budget),
            ("acquisition_requested", self.acquisition_requested),
            ("usable", self.usable),
            ("displayed", self.displayed),
        ):
            _require_count(name, value)
        for optional_name, optional_value in (
            ("fetched", self.fetched),
            ("mapped", self.mapped),
            ("rejected", self.rejected),
        ):
            if optional_value is not None:
                _require_count(optional_name, optional_value)
        if self.display_requested < 1:
            raise ValueError("display_requested must be positive")
        if self.acquisition_requested > self.acquisition_budget:
            raise ValueError("acquisition_requested cannot exceed acquisition_budget")
        if self.displayed > self.display_requested or self.displayed > self.usable:
            raise ValueError("displayed cannot exceed display_requested or usable")


def _require_count(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must not be negative")


def format_count(value: int | None, *, available: bool = True) -> str:
    """Return a display count, or ``No disponible`` when the metric is unknown."""

    if not available or value is None:
        return UNAVAILABLE
    if isinstance(value, bool) or not isinstance(value, int):
        return UNAVAILABLE
    if value < 0:
        return UNAVAILABLE
    return str(value)
