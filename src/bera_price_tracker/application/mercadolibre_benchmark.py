"""Local published-price benchmark and landed-cost comparison. No FX. No negotiation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

from bera_price_tracker.application.mercadolibre_relevance import (
    MercadoLibreListingRelevance,
    relevance_label,
    score_mercadolibre_relevance,
)
from bera_price_tracker.application.mercadolibre_statistics import (
    MercadoLibrePriceStatistics,
    calculate_mercadolibre_price_statistics,
    dominant_currency,
    explicit_currency,
    is_price_outlier,
    listing_price,
)
from bera_price_tracker.domain.mercadolibre import MercadoLibreListing
from bera_price_tracker.domain.money import quantize_money

DEFAULT_BENCHMARK_RELEVANCE = 60
SORT_ORIGINAL = "original"
SORT_PRICE_ASC = "price_asc"
SORT_PRICE_DESC = "price_desc"
SORT_RELEVANCE_DESC = "relevance_desc"
PERCENT_QUANTUM = Decimal("0.01")
CURRENCY_MISMATCH_MESSAGE = "Las monedas no son comparables sin una fuente de conversión."
PUBLISHED_PRICES_NOTE = "Precios publicados observados en Mercado Libre Venezuela"


@dataclass(frozen=True, slots=True)
class MercadoLibreScoredListing:
    """Listing plus deterministic relevance. Original listing is never mutated."""

    listing: MercadoLibreListing
    relevance: MercadoLibreListingRelevance

    @property
    def relevance_score(self) -> int:
        return self.relevance.relevance_score

    @property
    def relevance_label(self) -> str:
        return relevance_label(self.relevance.relevance_score)


@dataclass(frozen=True, slots=True)
class MercadoLibreMarketBenchmark:
    """Published-price market snapshot for one currency. Not completed sales."""

    comparable_count: int
    currency: str | None
    p25: Decimal | None
    median: Decimal | None
    p75: Decimal | None
    typical_price: Decimal | None
    minimum: Decimal | None
    maximum: Decimal | None
    average: Decimal | None
    iqr: Decimal | None
    trimmed_mean: Decimal | None
    outlier_count: int
    total_results: int
    note: str = PUBLISHED_PRICES_NOTE


@dataclass(frozen=True, slots=True)
class LocalProfitScenario:
    """One published local-price scenario versus a landed unit cost."""

    name: str
    local_price: Decimal
    profit_per_unit: Decimal
    margin_percent: Decimal | None


@dataclass(frozen=True, slots=True)
class MercadoLibreLandedComparison:
    """Visual comparison only. Never writes negotiation opening/target/ceiling."""

    comparable: bool
    currency: str | None
    landed_cost_per_unit: Decimal | None
    conservative: LocalProfitScenario | None
    typical: LocalProfitScenario | None
    high: LocalProfitScenario | None
    message: str


def score_listings(
    query: object, listings: Sequence[MercadoLibreListing]
) -> list[MercadoLibreScoredListing]:
    relevances = score_mercadolibre_relevance(query, listings)
    return [
        MercadoLibreScoredListing(listing=listing, relevance=relevance)
        for listing, relevance in zip(listings, relevances, strict=True)
    ]


def apply_mercadolibre_table_view(
    rows: Sequence[MercadoLibreScoredListing],
    *,
    sort: str = SORT_ORIGINAL,
    minimum: Decimal | None = None,
    maximum: Decimal | None = None,
    hide_outliers: bool = False,
    min_relevance: int = 0,
    stats: MercadoLibrePriceStatistics | None = None,
) -> list[MercadoLibreScoredListing]:
    """Derive visible rows. The original sequence is never mutated."""

    visible = list(rows)
    if min_relevance > 0:
        visible = [row for row in visible if row.relevance_score >= min_relevance]
    if minimum is not None or maximum is not None:
        bounded: list[MercadoLibreScoredListing] = []
        for row in visible:
            price = listing_price(row.listing)
            if price is None:
                continue
            if minimum is not None and price < minimum:
                continue
            if maximum is not None and price > maximum:
                continue
            bounded.append(row)
        visible = bounded
    if hide_outliers and stats is not None:
        kept: list[MercadoLibreScoredListing] = []
        for row in visible:
            price = listing_price(row.listing)
            if price is None:
                kept.append(row)
                continue
            if is_price_outlier(price, stats.lower_fence, stats.upper_fence):
                continue
            kept.append(row)
        visible = kept
    if sort in (SORT_PRICE_ASC, SORT_PRICE_DESC):
        priced = [row for row in visible if listing_price(row.listing) is not None]
        unpriced = [row for row in visible if listing_price(row.listing) is None]
        priced.sort(
            key=lambda row: listing_price(row.listing) or Decimal("0"),
            reverse=sort == SORT_PRICE_DESC,
        )
        visible = priced + unpriced
    elif sort == SORT_RELEVANCE_DESC:
        visible = sorted(visible, key=lambda row: row.relevance_score, reverse=True)
    return visible


def comparable_listings(
    rows: Sequence[MercadoLibreScoredListing],
    *,
    min_relevance: int = DEFAULT_BENCHMARK_RELEVANCE,
    currency: str | None = None,
) -> list[MercadoLibreScoredListing]:
    selected: list[MercadoLibreScoredListing] = []
    for row in rows:
        if row.relevance_score < min_relevance:
            continue
        price = listing_price(row.listing)
        code = explicit_currency(row.listing)
        if price is None or code is None:
            continue
        if currency is not None and code != currency.strip().upper():
            continue
        selected.append(row)
    return selected


def build_market_benchmark(
    rows: Sequence[MercadoLibreScoredListing],
    *,
    min_relevance: int = DEFAULT_BENCHMARK_RELEVANCE,
    currency: str | None = None,
    total_results: int | None = None,
) -> MercadoLibreMarketBenchmark:
    comparables = comparable_listings(rows, min_relevance=min_relevance, currency=currency)
    listings = [row.listing for row in comparables]
    resolved = currency.strip().upper() if isinstance(currency, str) and currency.strip() else None
    if resolved is None:
        resolved = dominant_currency(listings)
    if resolved is None:
        return MercadoLibreMarketBenchmark(
            comparable_count=0,
            currency=None,
            p25=None,
            median=None,
            p75=None,
            typical_price=None,
            minimum=None,
            maximum=None,
            average=None,
            iqr=None,
            trimmed_mean=None,
            outlier_count=0,
            total_results=len(rows) if total_results is None else total_results,
        )
    stats = calculate_mercadolibre_price_statistics(listings, currency=resolved)
    return MercadoLibreMarketBenchmark(
        comparable_count=stats.priced_listings,
        currency=stats.currency,
        p25=stats.p25,
        median=stats.median,
        p75=stats.p75,
        typical_price=stats.trimmed_mean,
        minimum=stats.minimum,
        maximum=stats.maximum,
        average=stats.average,
        iqr=stats.iqr,
        trimmed_mean=stats.trimmed_mean,
        outlier_count=stats.outlier_count,
        total_results=len(rows) if total_results is None else total_results,
    )


def _scenario(name: str, local_price: Decimal, landed: Decimal) -> LocalProfitScenario:
    profit = quantize_money(local_price - landed)
    margin: Decimal | None = None
    if local_price > Decimal("0"):
        margin = (profit / local_price * Decimal("100")).quantize(
            PERCENT_QUANTUM, rounding=ROUND_HALF_EVEN
        )
    return LocalProfitScenario(
        name=name,
        local_price=local_price,
        profit_per_unit=profit,
        margin_percent=margin,
    )


def compare_landed_to_local_market(
    *,
    landed_cost_per_unit: Decimal,
    landed_currency: str,
    benchmark: MercadoLibreMarketBenchmark,
) -> MercadoLibreLandedComparison:
    """Compare a valid landed unit cost to published P25/median/P75. No FX."""

    if isinstance(landed_cost_per_unit, bool) or not isinstance(landed_cost_per_unit, Decimal):
        raise TypeError("landed_cost_per_unit must be a Decimal")
    if not landed_cost_per_unit.is_finite():
        raise ValueError("landed_cost_per_unit must be finite")
    if not isinstance(landed_currency, str) or not landed_currency.strip():
        raise ValueError("landed_currency must not be blank")
    landed_code = landed_currency.strip().upper()
    market_code = benchmark.currency
    if market_code is None or market_code != landed_code:
        return MercadoLibreLandedComparison(
            comparable=False,
            currency=None,
            landed_cost_per_unit=landed_cost_per_unit,
            conservative=None,
            typical=None,
            high=None,
            message=CURRENCY_MISMATCH_MESSAGE,
        )
    if benchmark.p25 is None or benchmark.median is None or benchmark.p75 is None:
        return MercadoLibreLandedComparison(
            comparable=False,
            currency=market_code,
            landed_cost_per_unit=landed_cost_per_unit,
            conservative=None,
            typical=None,
            high=None,
            message="No hay suficientes precios publicados comparables.",
        )
    return MercadoLibreLandedComparison(
        comparable=True,
        currency=market_code,
        landed_cost_per_unit=landed_cost_per_unit,
        conservative=_scenario("Conservador", benchmark.p25, landed_cost_per_unit),
        typical=_scenario("Típico", benchmark.median, landed_cost_per_unit),
        high=_scenario("Alto", benchmark.p75, landed_cost_per_unit),
        message="",
    )


__all__ = [
    "CURRENCY_MISMATCH_MESSAGE",
    "DEFAULT_BENCHMARK_RELEVANCE",
    "PUBLISHED_PRICES_NOTE",
    "SORT_ORIGINAL",
    "SORT_PRICE_ASC",
    "SORT_PRICE_DESC",
    "SORT_RELEVANCE_DESC",
    "LocalProfitScenario",
    "MercadoLibreLandedComparison",
    "MercadoLibreMarketBenchmark",
    "MercadoLibreScoredListing",
    "apply_mercadolibre_table_view",
    "build_market_benchmark",
    "comparable_listings",
    "compare_landed_to_local_market",
    "score_listings",
]
