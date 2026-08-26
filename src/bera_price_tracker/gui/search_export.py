"""Current-search CSV export. No provider I/O and no financial recomputation."""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

CSV_COLUMNS: tuple[str, ...] = (
    "search_query",
    "searched_at",
    "search_mode",
    "requested_limit",
    "marketplace",
    "product_id",
    "title",
    "price_display",
    "price_raw",
    "currency",
    "normalized_usd",
    "usd_basis",
    "usd_provenance",
    "image_url",
    "listing_url",
    "location",
    "seller",
    "condition",
    "moq",
    "relevance",
    "opportunity_score",
    "product_rating",
    "product_review_count",
    "seller_name",
    "seller_rating",
    "seller_service_score",
    "seller_reputation",
    "seller_status",
    "gold_supplier_years",
    "provider_requested",
    "provider_fetched",
    "provider_usable",
)

_TEXT_COLUMNS = frozenset(
    {
        "search_query",
        "searched_at",
        "search_mode",
        "marketplace",
        "product_id",
        "title",
        "price_display",
        "currency",
        "normalized_usd",
        "usd_basis",
        "usd_provenance",
        "image_url",
        "listing_url",
        "location",
        "seller",
        "condition",
        "moq",
        "relevance",
        "opportunity_score",
        "product_rating",
        "seller_name",
        "seller_rating",
        "seller_service_score",
        "seller_reputation",
        "seller_status",
        "gold_supplier_years",
        "provider_requested",
        "provider_fetched",
        "provider_usable",
    }
)
_FORMULA_PREFIXES = frozenset({"=", "+", "-", "@", "\t", "\r"})
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
MARKETPLACE_ALIBABA = "Alibaba"
MARKETPLACE_FACEBOOK = "Facebook Marketplace"
MARKETPLACE_ML = "Mercado Libre"


def csv_safe_text(value: object) -> str:
    """Neutralize spreadsheet formula injection for user-controlled text."""

    if value is None:
        return ""
    text = str(value)
    if not text:
        return ""
    if text[0] in _FORMULA_PREFIXES:
        return f"'{text}"
    return text


def _cell(column: str, value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    if column == "price_raw" and _NUMBER.fullmatch(text):
        return text
    if column == "product_review_count" and _NUMBER.fullmatch(text):
        return text
    if column == "requested_limit" and _NUMBER.fullmatch(text):
        return text
    if column in _TEXT_COLUMNS:
        return csv_safe_text(text)
    return csv_safe_text(text)


def _attr(row: object, *names: str) -> str:
    for name in names:
        if isinstance(row, Mapping) and name in row:
            value = row.get(name)
        else:
            value = getattr(row, name, None)
        if value is None:
            continue
        text = str(value).strip()
        if text and text != "—":
            return text
    return ""


def _blank_unavailable(value: str) -> str:
    if value in {"No disponible", "—"}:
        return ""
    return value


def export_filename(*, searched_at: str = "", query: str = "", now: datetime | None = None) -> str:
    stamp = ""
    digits = re.sub(r"\D", "", searched_at)
    if len(digits) >= 12:
        stamp = digits[:12]
    elif now is not None:
        stamp = now.strftime("%Y%m%d%H%M%S")
    else:
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    slug_source = _UNSAFE_FILENAME.sub("-", query.strip().casefold()).strip("-")
    slug_source = slug_source.replace("..", "-")
    slug = re.sub(r"-{2,}", "-", slug_source).strip("-.")[:24].strip("-.")
    if slug:
        return f"bera-search-{stamp}-{slug}.csv"
    return f"bera-search-{stamp}.csv"


def _row(
    *,
    context: Mapping[str, str],
    marketplace: str,
    product_id: str,
    title: str,
    price_display: str,
    price_raw: str,
    currency: str,
    normalized_usd: str = "",
    usd_basis: str = "",
    usd_provenance: str = "",
    image_url: str = "",
    listing_url: str = "",
    location: str = "",
    seller: str = "",
    condition: str = "",
    moq: str = "",
    relevance: str = "",
    opportunity_score: str = "",
    product_rating: str = "",
    product_review_count: str = "",
    seller_name: str = "",
    seller_rating: str = "",
    seller_service_score: str = "",
    seller_reputation: str = "",
    seller_status: str = "",
    gold_supplier_years: str = "",
    provider_requested: str = "",
    provider_fetched: str = "",
    provider_usable: str = "",
) -> dict[str, str]:
    values = {
        **context,
        "marketplace": marketplace,
        "product_id": product_id,
        "title": title,
        "price_display": price_display,
        "price_raw": price_raw,
        "currency": currency,
        "normalized_usd": normalized_usd,
        "usd_basis": usd_basis,
        "usd_provenance": usd_provenance,
        "image_url": image_url,
        "listing_url": listing_url,
        "location": location,
        "seller": seller,
        "condition": condition,
        "moq": moq,
        "relevance": relevance,
        "opportunity_score": opportunity_score,
        "product_rating": product_rating,
        "product_review_count": product_review_count,
        "seller_name": seller_name,
        "seller_rating": seller_rating,
        "seller_service_score": seller_service_score,
        "seller_reputation": seller_reputation,
        "seller_status": seller_status,
        "gold_supplier_years": gold_supplier_years,
        "provider_requested": _blank_unavailable(provider_requested),
        "provider_fetched": _blank_unavailable(provider_fetched),
        "provider_usable": _blank_unavailable(provider_usable),
    }
    return {column: _cell(column, values.get(column, "")) for column in CSV_COLUMNS}


def listing_rows_for_export(
    *,
    search_query: str,
    searched_at: str,
    search_mode: str,
    requested_limit: int,
    alibaba_status: str,
    alibaba_rows: Sequence[Any] = (),
    alibaba_diagnostic: Mapping[str, str] | None = None,
    facebook_status: str,
    facebook_rows: Sequence[Any] = (),
    facebook_diagnostic: Mapping[str, str] | None = None,
    ml_status: str,
    ml_rows: Sequence[Any] = (),
    ml_diagnostic: Mapping[str, str] | None = None,
) -> list[dict[str, str]]:
    """One CSV row per current-session listing of successful providers."""

    context = {
        "search_query": search_query,
        "searched_at": searched_at,
        "search_mode": search_mode,
        "requested_limit": str(requested_limit),
    }
    rows: list[dict[str, str]] = []
    if alibaba_status == "SUCCESS":
        diag = dict(alibaba_diagnostic or {})
        for item in alibaba_rows:
            seller = _attr(item, "supplier_name")
            rows.append(
                _row(
                    context=context,
                    marketplace=MARKETPLACE_ALIBABA,
                    product_id=_attr(item, "product_id"),
                    title=_attr(item, "title"),
                    price_display=_attr(item, "price"),
                    price_raw=_attr(item, "representative", "price_min"),
                    currency=_attr(item, "currency"),
                    image_url=_attr(item, "image_url"),
                    listing_url=_attr(item, "url"),
                    seller=seller,
                    moq=_attr(item, "moq"),
                    relevance=_attr(item, "relevance"),
                    opportunity_score=_attr(item, "score"),
                    product_rating=_attr(item, "review_score"),
                    product_review_count=_attr(item, "review_count"),
                    seller_name=seller,
                    seller_rating="",
                    seller_service_score=_attr(item, "supplier_service_score"),
                    seller_reputation="",
                    seller_status="",
                    gold_supplier_years=_attr(item, "gold_supplier_years"),
                    provider_requested=_attr(diag, "requested"),
                    provider_fetched=_attr(diag, "fetched"),
                    provider_usable=_attr(diag, "usable"),
                )
            )
    if facebook_status == "SUCCESS":
        diag = dict(facebook_diagnostic or {})
        for item in facebook_rows:
            rows.append(
                _row(
                    context=context,
                    marketplace=MARKETPLACE_FACEBOOK,
                    product_id=_attr(item, "external_id"),
                    title=_attr(item, "title"),
                    price_display=_attr(item, "price"),
                    price_raw=_attr(item, "price_raw"),
                    currency=_attr(item, "currency"),
                    normalized_usd=_attr(item, "usd_price", "usd_amount"),
                    usd_basis=_attr(item, "usd_basis"),
                    usd_provenance=_attr(item, "usd_provenance"),
                    image_url=_attr(item, "image_url"),
                    listing_url=_attr(item, "permalink"),
                    location=_attr(item, "location"),
                    relevance=_attr(item, "relevance"),
                    provider_requested=_attr(diag, "requested"),
                    provider_fetched=_attr(diag, "fetched"),
                    provider_usable=_attr(diag, "usable"),
                )
            )
    if ml_status == "SUCCESS":
        diag = dict(ml_diagnostic or {})
        for item in ml_rows:
            seller = _attr(item, "seller_name")
            rows.append(
                _row(
                    context=context,
                    marketplace=MARKETPLACE_ML,
                    product_id=_attr(item, "external_id"),
                    title=_attr(item, "title"),
                    price_display=_attr(item, "price"),
                    price_raw=_attr(item, "price_raw"),
                    currency=_attr(item, "currency"),
                    image_url=_attr(item, "thumbnail_url"),
                    listing_url=_attr(item, "permalink"),
                    seller=seller,
                    condition=_attr(item, "condition"),
                    relevance=_attr(item, "relevance"),
                    product_rating=_attr(item, "rating_average"),
                    product_review_count=_attr(item, "review_count"),
                    seller_name=seller,
                    seller_rating="",
                    seller_reputation=_attr(item, "seller_reputation"),
                    seller_status=_attr(item, "seller_status"),
                    provider_requested=_attr(diag, "requested"),
                    provider_fetched=_attr(diag, "fetched"),
                    provider_usable=_attr(diag, "usable"),
                )
            )
    return rows


def render_csv(rows: Sequence[Mapping[str, str]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(CSV_COLUMNS), extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in CSV_COLUMNS})
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")
