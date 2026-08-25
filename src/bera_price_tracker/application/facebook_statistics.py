"""Provenance-aware statistics for generic Facebook Marketplace comparables."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from bera_price_tracker.application.mercadolibre_statistics import (
    MercadoLibrePriceStatistics,
    available_currencies,
    calculate_mercadolibre_price_statistics,
    explicit_currency,
)
from bera_price_tracker.domain.money import (
    FACEBOOK_VENEZUELA_EVIDENCE,
    NormalizationStatus,
    quantize_money,
)


class FacebookStatisticsBasis(StrEnum):
    """Auditable monetary basis for one Facebook benchmark row."""

    SOURCE_CURRENCY = "source_currency"
    FACEBOOK_VENEZUELA_NORMALIZED_USD = "facebook_venezuela_normalized_usd"


@dataclass(frozen=True, slots=True)
class FacebookPriceStatistics(MercadoLibrePriceStatistics):
    """Comparable aggregates plus their source/normalization provenance."""

    basis: FacebookStatisticsBasis
    source_currencies: tuple[str, ...]
    normalization_statuses: tuple[str, ...]
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _UsdComparable:
    price: Decimal
    currency: str = "USD"


def _ordered_unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _usd_evidence(listing: object) -> tuple[str, ...]:
    raw = getattr(listing, "usd_evidence", ())
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(value.strip() for value in raw if isinstance(value, str) and value.strip())


def _normalization_status(listing: object) -> str | None:
    raw = getattr(listing, "usd_normalization_status", None)
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip()


def _positive_usd_amount(listing: object) -> Decimal | None:
    value = getattr(listing, "usd_amount", None)
    if isinstance(value, bool) or not isinstance(value, Decimal):
        return None
    if not value.is_finite() or value <= Decimal("0"):
        return None
    return value


def _with_provenance(
    statistics: MercadoLibrePriceStatistics,
    *,
    basis: FacebookStatisticsBasis,
    source_currencies: tuple[str, ...],
    normalization_statuses: tuple[str, ...],
    evidence: tuple[str, ...],
) -> FacebookPriceStatistics:
    return FacebookPriceStatistics(
        total_listings=statistics.total_listings,
        priced_listings=statistics.priced_listings,
        currency=statistics.currency,
        minimum=statistics.minimum,
        maximum=statistics.maximum,
        average=statistics.average,
        median=statistics.median,
        p25=statistics.p25,
        p75=statistics.p75,
        iqr=statistics.iqr,
        trimmed_mean=statistics.trimmed_mean,
        lower_fence=statistics.lower_fence,
        upper_fence=statistics.upper_fence,
        outlier_count=statistics.outlier_count,
        basis=basis,
        source_currencies=source_currencies,
        normalization_statuses=normalization_statuses,
        evidence=evidence,
    )


def calculate_facebook_statistics_by_currency(
    listings: Sequence[object],
) -> tuple[FacebookPriceStatistics, ...]:
    """Aggregate only unambiguous source currencies; UNKNOWN and Facebook VEF stay out."""

    eligible = tuple(
        listing
        for listing in listings
        if explicit_currency(listing) not in {None, "VEF"}
        and FACEBOOK_VENEZUELA_EVIDENCE not in _usd_evidence(listing)
    )
    rows: list[FacebookPriceStatistics] = []
    for currency in available_currencies(eligible):
        matching = tuple(listing for listing in eligible if explicit_currency(listing) == currency)
        statuses = _ordered_unique(
            tuple(
                status
                for listing in matching
                if (status := _normalization_status(listing)) is not None
            )
        )
        evidence = _ordered_unique(
            tuple(item for listing in matching for item in _usd_evidence(listing))
        )
        rows.append(
            _with_provenance(
                calculate_mercadolibre_price_statistics(eligible, currency=currency),
                basis=FacebookStatisticsBasis.SOURCE_CURRENCY,
                source_currencies=(currency,),
                normalization_statuses=statuses,
                evidence=evidence,
            )
        )
    return tuple(rows)


def calculate_facebook_venezuela_usd_statistics(
    listings: Sequence[object],
) -> FacebookPriceStatistics | None:
    """Aggregate policy-normalized VEF amounts without FX or source-currency mutation."""

    comparables: list[_UsdComparable] = []
    for listing in listings:
        source_amount = getattr(listing, "price", None)
        usd_amount = _positive_usd_amount(listing)
        if (
            explicit_currency(listing) != "VEF"
            or _normalization_status(listing) != NormalizationStatus.NORMALIZED.value
            or FACEBOOK_VENEZUELA_EVIDENCE not in _usd_evidence(listing)
            or getattr(listing, "usd_exchange_rate", None) is not None
            or getattr(listing, "usd_exchange_rate_source", None) is not None
            or getattr(listing, "usd_exchange_rate_at", None) is not None
            or isinstance(source_amount, bool)
            or not isinstance(source_amount, Decimal)
            or not source_amount.is_finite()
            or source_amount <= Decimal("0")
            or usd_amount is None
            or usd_amount != quantize_money(source_amount)
        ):
            continue
        comparables.append(_UsdComparable(price=usd_amount))
    if not comparables:
        return None
    return _with_provenance(
        calculate_mercadolibre_price_statistics(comparables, currency="USD"),
        basis=FacebookStatisticsBasis.FACEBOOK_VENEZUELA_NORMALIZED_USD,
        source_currencies=("VEF",),
        normalization_statuses=(NormalizationStatus.NORMALIZED.value,),
        evidence=(FACEBOOK_VENEZUELA_EVIDENCE,),
    )


def calculate_facebook_statistics(
    listings: Sequence[object],
) -> tuple[FacebookPriceStatistics, ...]:
    """Return contextual Facebook-VE USD first, then separate source-currency rows."""

    normalized = calculate_facebook_venezuela_usd_statistics(listings)
    source = calculate_facebook_statistics_by_currency(listings)
    return source if normalized is None else (normalized, *source)


__all__ = [
    "FacebookPriceStatistics",
    "FacebookStatisticsBasis",
    "calculate_facebook_statistics",
    "calculate_facebook_statistics_by_currency",
    "calculate_facebook_venezuela_usd_statistics",
]
