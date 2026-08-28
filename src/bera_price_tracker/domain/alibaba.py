"""Read-only Alibaba product model. Independent from Facebook Listing."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("text fields must be strings")
    normalized = value.strip()
    return normalized or None


def _optional_decimal(value: Decimal | None, field_name: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite() or value <= Decimal("0"):
        raise ValueError(f"{field_name} must be a finite Decimal greater than zero")
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class AlibabaProduct:
    """Tolerant public Alibaba row. Prices are Decimal or absent; never invented."""

    title: str
    product_id: str | None = None
    product_url: str | None = None
    price_display: str | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    currency: str | None = None
    moq: str | None = None
    supplier_name: str | None = None
    supplier_country: str | None = None
    image_url: str | None = None
    gold_supplier_years: str | None = None
    supplier_service_score: str | None = None
    review_count: str | None = None
    review_score: str | None = None

    def __post_init__(self) -> None:
        title = _optional_text(self.title)
        if title is None:
            raise ValueError("title must not be blank")
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "product_id", _optional_text(self.product_id))
        object.__setattr__(self, "product_url", _optional_text(self.product_url))
        object.__setattr__(self, "price_display", _optional_text(self.price_display))
        min_price = _optional_decimal(self.min_price, "min_price")
        max_price = _optional_decimal(self.max_price, "max_price")
        if min_price is not None and max_price is None:
            max_price = min_price
        if min_price is not None and max_price is not None and min_price > max_price:
            min_price = None
            max_price = None
        object.__setattr__(self, "min_price", min_price)
        object.__setattr__(self, "max_price", max_price)
        object.__setattr__(self, "currency", _optional_text(self.currency))
        object.__setattr__(self, "moq", _optional_text(self.moq))
        object.__setattr__(self, "supplier_name", _optional_text(self.supplier_name))
        object.__setattr__(self, "supplier_country", _optional_text(self.supplier_country))
        object.__setattr__(self, "image_url", _optional_text(self.image_url))
        object.__setattr__(self, "gold_supplier_years", _optional_text(self.gold_supplier_years))
        object.__setattr__(
            self, "supplier_service_score", _optional_text(self.supplier_service_score)
        )
        object.__setattr__(self, "review_count", _optional_text(self.review_count))
        object.__setattr__(self, "review_score", _optional_text(self.review_score))
