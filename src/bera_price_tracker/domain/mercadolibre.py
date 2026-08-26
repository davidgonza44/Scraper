"""Read-only Mercado Libre Venezuela listing. Independent from Facebook and Alibaba."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from bera_price_tracker.domain.models import ListingKey, MarketplaceSource


def _optional_text(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    return normalized or None


def _required_text(value: str, field_name: str) -> str:
    normalized = _optional_text(value, field_name)
    if normalized is None:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def _optional_decimal(value: Decimal | None, field_name: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite() or value <= Decimal("0"):
        raise ValueError(f"{field_name} must be a finite Decimal greater than zero")
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class MercadoLibreListing:
    """Public MLV row. Prices are Decimal or absent; currency is never inferred."""

    external_id: str
    title: str
    permalink: str | None = None
    price: Decimal | None = None
    original_price: Decimal | None = None
    currency: str | None = None
    condition: str | None = None
    thumbnail_url: str | None = None
    seller_name: str | None = None
    seller_reputation: str | None = None
    seller_status: str | None = None
    official_store: bool | None = None
    rating_average: str | None = None
    review_count: str | None = None
    free_shipping: bool | None = None
    country: str | None = None
    site_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "external_id", _required_text(self.external_id, "external_id"))
        object.__setattr__(self, "title", _required_text(self.title, "title"))
        object.__setattr__(self, "permalink", _optional_text(self.permalink, "permalink"))
        object.__setattr__(self, "price", _optional_decimal(self.price, "price"))
        object.__setattr__(
            self, "original_price", _optional_decimal(self.original_price, "original_price")
        )
        currency = _optional_text(self.currency, "currency")
        object.__setattr__(self, "currency", None if currency is None else currency.upper())
        object.__setattr__(self, "condition", _optional_text(self.condition, "condition"))
        object.__setattr__(
            self, "thumbnail_url", _optional_text(self.thumbnail_url, "thumbnail_url")
        )
        object.__setattr__(self, "seller_name", _optional_text(self.seller_name, "seller_name"))
        object.__setattr__(
            self, "seller_reputation", _optional_text(self.seller_reputation, "seller_reputation")
        )
        object.__setattr__(
            self, "seller_status", _optional_text(self.seller_status, "seller_status")
        )
        if self.official_store is not None and not isinstance(self.official_store, bool):
            raise TypeError("official_store must be a bool")
        object.__setattr__(
            self, "rating_average", _optional_text(self.rating_average, "rating_average")
        )
        object.__setattr__(self, "review_count", _optional_text(self.review_count, "review_count"))
        if self.free_shipping is not None and not isinstance(self.free_shipping, bool):
            raise TypeError("free_shipping must be a bool")
        object.__setattr__(self, "country", _optional_text(self.country, "country"))
        site_id = _optional_text(self.site_id, "site_id")
        object.__setattr__(self, "site_id", None if site_id is None else site_id.upper())

    @property
    def source(self) -> MarketplaceSource:
        return MarketplaceSource.MERCADO_LIBRE

    @property
    def key(self) -> ListingKey:
        return ListingKey(source=MarketplaceSource.MERCADO_LIBRE, external_id=self.external_id)
