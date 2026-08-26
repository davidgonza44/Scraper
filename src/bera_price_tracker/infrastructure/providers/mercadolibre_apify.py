"""Apify Mercado Libre Venezuela client. Isolated from Facebook and Alibaba."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Protocol, cast
from urllib.parse import urlsplit

from bera_price_tracker.application import MarketplaceSourceUnavailable
from bera_price_tracker.application.alibaba_reputation import parse_rating_0_5, parse_review_count
from bera_price_tracker.application.provider_acquisition import ProviderAcquisitionMetrics
from bera_price_tracker.application.services import validate_mercadolibre_search
from bera_price_tracker.domain.mercadolibre import MercadoLibreListing
from bera_price_tracker.infrastructure.providers.apify import (
    ApifyClientConfiguration,
    ApifyConfigurationError,
)

DEFAULT_MERCADOLIBRE_ACTOR = "piotrv1001/mercado-libre-listings-scraper"
MLV_SITE_ID = "MLV"
VE_COUNTRY = "venezuela"
VE_HOST_SUFFIX = "mercadolibre.com.ve"
_FOREIGN_SITES = frozenset(
    {
        "MLA",
        "MLB",
        "MLM",
        "MCO",
        "MLC",
        "MPE",
        "MLU",
        "MEC",
        "MBO",
        "MPA",
        "MPY",
        "MRD",
        "MCR",
        "MNI",
        "MGT",
        "MHN",
        "MSV",
    }
)
_FOREIGN_HOST_MARKERS = (
    "mercadolibre.com.ar",
    "mercadolibre.com.mx",
    "mercadolivre.com.br",
    "mercadolibre.cl",
    "mercadolibre.com.co",
    "mercadolibre.com.pe",
    "mercadolibre.com.uy",
    "mercadolibre.com.ec",
    "mercadolibre.com.bo",
    "mercadolibre.com.pa",
    "mercadolibre.com.py",
    "mercadolibre.com.do",
    "mercadolibre.co.cr",
    "mercadolibre.com.ni",
    "mercadolibre.com.gt",
    "mercadolibre.com.hn",
    "mercadolibre.com.sv",
)


class _ActorClient(Protocol):
    def call(self, *, run_input: dict[str, object]) -> dict[str, object] | None: ...


class _DatasetPage(Protocol):
    items: list[object]


class _DatasetClient(Protocol):
    def list_items(self, *, limit: int) -> _DatasetPage: ...


class _ApifyClientLike(Protocol):
    def actor(self, actor_id: str) -> _ActorClient: ...

    def dataset(self, dataset_id: str) -> _DatasetClient: ...


ClientFactory = Callable[[str], _ApifyClientLike]


def build_mercadolibre_run_input(*, query: str, limit: int) -> dict[str, object]:
    """Actor input using only documented fields for MLV search."""

    return {
        "siteId": MLV_SITE_ID,
        "searchQueries": [query],
        "maxItems": limit,
    }


def _as_mapping(value: object) -> Mapping[str, object] | None:
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)
    return None


def _scalar_text(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (str, int)):
        normalized = str(value).strip()
        if normalized:
            return normalized
    return None


def parse_mercadolibre_price(raw: object) -> Decimal | None:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, Decimal):
        price = raw
    elif isinstance(raw, int):
        price = Decimal(raw)
    elif isinstance(raw, str):
        try:
            price = Decimal(raw.strip())
        except (InvalidOperation, ValueError):
            return None
    elif isinstance(raw, float):
        try:
            price = Decimal(str(raw))
        except (InvalidOperation, ValueError):
            return None
    else:
        return None
    if not price.is_finite() or price <= Decimal("0"):
        return None
    return price


def _hostname(url: str | None) -> str | None:
    if url is None:
        return None
    host = urlsplit(url).hostname
    if host is None:
        return None
    return host.casefold()


def permalink_is_venezuela(url: str | None) -> bool:
    host = _hostname(url)
    return host is not None and host.endswith(VE_HOST_SUFFIX)


def permalink_is_foreign(url: str | None) -> bool:
    host = _hostname(url)
    if host is None:
        return False
    return any(marker in host for marker in _FOREIGN_HOST_MARKERS)


def _nested_text(record: Mapping[str, object], parent: str, child: str) -> str | None:
    nested = record.get(parent)
    mapping = _as_mapping(nested)
    if mapping is not None:
        return _scalar_text(mapping.get(child))
    return _scalar_text(record.get(f"{parent}.{child}"))


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def _rating_text(value: object) -> str | None:
    """Return only a finite, genuine product rating on the 0–5 scale."""

    return _decimal_text(parse_rating_0_5(value))


def _review_count_text(value: object) -> str | None:
    """Return only a finite, non-negative numeric review count."""

    return _decimal_text(parse_review_count(value))


def _seller_mapping(record: Mapping[str, object]) -> Mapping[str, object] | None:
    return _as_mapping(record.get("seller"))


def _seller_reputation_text(seller: Mapping[str, object]) -> str | None:
    """Categorical Mercado Libre reputation. Never converted into 0–5 stars."""

    reputation = seller.get("reputation")
    if isinstance(reputation, str):
        return _scalar_text(reputation)
    mapped = _as_mapping(reputation)
    if mapped is None:
        return None
    for key in ("level_id", "levelId", "power_seller_status", "powerSellerStatus"):
        text = _scalar_text(mapped.get(key))
        if text is not None:
            return text
    return None


def _seller_status_text(seller: Mapping[str, object]) -> str | None:
    parts: list[str] = []
    power = _scalar_text(seller.get("powerSellerStatus") or seller.get("power_seller_status"))
    if power is not None:
        parts.append(power)
    store = _scalar_text(seller.get("storeName") or seller.get("store_name"))
    if store is not None:
        parts.append(store)
    official = seller.get("isOfficialStore")
    if official is None:
        official = seller.get("is_official_store")
    if official is True:
        parts.append("Tienda oficial")
    return " · ".join(parts) or None


def is_venezuela_listing(
    *,
    external_id: str | None,
    site_id: str | None,
    permalink: str | None,
    country: str | None,
) -> bool:
    """Accept only listings with Venezuela evidence and no foreign-site evidence."""

    normalized_site = (
        site_id.strip().upper() if isinstance(site_id, str) and site_id.strip() else None
    )
    normalized_country = (
        country.casefold() if isinstance(country, str) and country.strip() else None
    )
    foreign = False
    if normalized_site is not None and normalized_site in _FOREIGN_SITES:
        foreign = True
    if permalink_is_foreign(permalink):
        foreign = True
    if normalized_country is not None and normalized_country != VE_COUNTRY:
        foreign = True
    if foreign:
        return False

    if normalized_site == MLV_SITE_ID:
        return True
    if permalink_is_venezuela(permalink):
        return True
    if normalized_country == VE_COUNTRY:
        return True
    if isinstance(external_id, str) and external_id.upper().startswith(MLV_SITE_ID):
        return True
    return False


def map_mercadolibre_item(raw: object) -> MercadoLibreListing | None:
    """Map one Actor dataset item. Malformed or non-MLV rows are skipped."""

    record = _as_mapping(raw)
    if record is None:
        return None
    external_id = _scalar_text(record.get("id") or record.get("item_id"))
    title = _scalar_text(record.get("title"))
    if external_id is None or title is None:
        return None
    permalink = _scalar_text(record.get("permalink") or record.get("url"))
    site_id = _scalar_text(record.get("siteId") or record.get("site_id") or record.get("site"))
    country = _nested_text(record, "location", "country")
    if not is_venezuela_listing(
        external_id=external_id,
        site_id=site_id,
        permalink=permalink,
        country=country,
    ):
        return None
    currency = _scalar_text(record.get("currency") or record.get("currency_id"))
    free_shipping_raw = record.get("freeShipping")
    if free_shipping_raw is None:
        free_shipping_raw = record.get("free_shipping")
    free_shipping = free_shipping_raw if isinstance(free_shipping_raw, bool) else None
    seller = _seller_mapping(record)
    official_raw = None if seller is None else seller.get("isOfficialStore")
    if official_raw is None and seller is not None:
        official_raw = seller.get("is_official_store")
    official_store = official_raw if isinstance(official_raw, bool) else None
    return MercadoLibreListing(
        external_id=external_id,
        title=title,
        permalink=permalink,
        price=parse_mercadolibre_price(record.get("price")),
        original_price=parse_mercadolibre_price(
            record.get("originalPrice", record.get("original_price"))
        ),
        currency=currency,
        condition=_scalar_text(record.get("condition")),
        thumbnail_url=_scalar_text(record.get("thumbnailUrl") or record.get("thumbnail")),
        seller_name=None if seller is None else _scalar_text(seller.get("nickname")),
        seller_reputation=None if seller is None else _seller_reputation_text(seller),
        seller_status=None if seller is None else _seller_status_text(seller),
        official_store=official_store,
        rating_average=_rating_text(record.get("ratingAverage", record.get("rating_average"))),
        review_count=_review_count_text(record.get("reviewCount", record.get("review_count"))),
        free_shipping=free_shipping,
        country=country,
        site_id=site_id,
    )


def _run_status(run: Mapping[str, object]) -> str:
    status = run.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip()
    return "UNKNOWN"


def _dataset_id(run: Mapping[str, object]) -> str | None:
    value = run.get("defaultDatasetId")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _default_client_factory(token: str) -> _ApifyClientLike:
    from apify_client import ApifyClient

    return cast(_ApifyClientLike, ApifyClient(token))


@dataclass(frozen=True, slots=True)
class ApifyMercadoLibreClient:
    """Run piotrv1001/mercado-libre-listings-scraper once and map public fields."""

    _api_token: str | None = field(default=None, repr=False)
    actor_id: str = DEFAULT_MERCADOLIBRE_ACTOR
    client_factory: ClientFactory | None = field(default=None, repr=False)
    last_metrics: ProviderAcquisitionMetrics | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        actor = self.actor_id.strip() if isinstance(self.actor_id, str) else ""
        if not actor:
            raise ApifyConfigurationError("mercadolibre actor id must not be blank")
        object.__setattr__(self, "actor_id", actor)
        object.__setattr__(
            self, "_api_token", None if self._api_token is None else self._api_token.strip() or None
        )

    def search(self, query: str, limit: int) -> list[MercadoLibreListing]:
        normalized_query, normalized_limit = validate_mercadolibre_search(query, limit)
        configuration = ApifyClientConfiguration.from_value(self._api_token)
        token = configuration.require_api_token()
        run_input = build_mercadolibre_run_input(query=normalized_query, limit=normalized_limit)
        factory = self.client_factory or _default_client_factory
        try:
            client = factory(token)
            run = client.actor(self.actor_id).call(run_input=run_input)
        except ApifyConfigurationError:
            raise
        except MarketplaceSourceUnavailable:
            raise
        except Exception as error:
            raise MarketplaceSourceUnavailable("Mercado Libre source is unavailable") from error

        if not isinstance(run, Mapping):
            raise MarketplaceSourceUnavailable("Mercado Libre source is unavailable")
        if _run_status(run) != "SUCCEEDED":
            raise MarketplaceSourceUnavailable("Mercado Libre source is unavailable")
        dataset_id = _dataset_id(run)
        if dataset_id is None:
            raise MarketplaceSourceUnavailable("Mercado Libre source is unavailable")

        try:
            page = client.dataset(dataset_id).list_items(limit=normalized_limit)
            raw_items = list(page.items)[:normalized_limit]
        except Exception as error:
            raise MarketplaceSourceUnavailable("Mercado Libre source is unavailable") from error

        listings: list[MercadoLibreListing] = []
        for raw_item in raw_items:
            mapped = map_mercadolibre_item(raw_item)
            if mapped is not None:
                listings.append(mapped)
        object.__setattr__(
            self,
            "last_metrics",
            ProviderAcquisitionMetrics(
                requested=normalized_limit,
                fetched=len(raw_items),
                usable=len(listings),
            ),
        )
        return listings


__all__ = [
    "DEFAULT_MERCADOLIBRE_ACTOR",
    "MLV_SITE_ID",
    "ApifyMercadoLibreClient",
    "build_mercadolibre_run_input",
    "is_venezuela_listing",
    "map_mercadolibre_item",
    "parse_mercadolibre_price",
    "permalink_is_venezuela",
]
