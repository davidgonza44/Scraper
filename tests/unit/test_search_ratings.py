"""Offline product-rating vs seller-reputation tests. No invented stars."""

from __future__ import annotations

from types import SimpleNamespace

from bera_price_tracker.domain.mercadolibre import MercadoLibreListing
from bera_price_tracker.gui import comparison, search_session
from bera_price_tracker.gui.services import alibaba_product_to_row, mercadolibre_listing_to_row
from bera_price_tracker.gui.state import (
    UI_SUCCESS,
    AlibabaResultRow,
    MercadoLibreResultRow,
)
from bera_price_tracker.infrastructure.providers.mercadolibre_apify import map_mercadolibre_item


def test_alibaba_review_score_becomes_product_stars() -> None:
    rating = search_session.product_rating_display("4.8", review_count="128")
    assert rating["available"] is True
    assert rating["value"] == "4.8"
    assert rating["caption"] == "Calificación del producto"
    assert "128 reseñas" in str(rating["label"])
    row = comparison._alibaba_cell(
        AlibabaResultRow(title="bate", review_score="4.8", review_count="128")
    )
    assert row["alibaba_rating_available"] is True
    assert row["alibaba_rating_caption"] == "Calificación del producto"
    assert "128 reseñas" in str(row["alibaba_rating_label"])


def test_supplier_service_score_does_not_become_product_stars() -> None:
    row = comparison._alibaba_cell(
        AlibabaResultRow(
            title="bate",
            review_score="",
            supplier_service_score="4.9",
            gold_supplier_years="6",
            supplier_name="Acme",
        )
    )
    assert row["alibaba_rating_available"] is False
    assert row["alibaba_rating_label"] == "Sin calificación"
    assert "Servicio: 4.9" in str(row["alibaba_trust_line"])
    assert "Gold Supplier: 6 años" in str(row["alibaba_trust_line"])


def test_bera_reputation_score_does_not_become_stars() -> None:
    row = comparison._alibaba_cell(
        AlibabaResultRow(title="bate", reputation="82", reputation_value=82, review_score="")
    )
    assert row["alibaba_rating_available"] is False


def test_missing_alibaba_review_score_is_unrated() -> None:
    row = comparison._alibaba_cell(AlibabaResultRow(title="bate"))
    assert row["alibaba_rating_available"] is False
    assert row["alibaba_rating_label"] == "Sin calificación"


def test_alibaba_product_to_row_keeps_review_count() -> None:
    product = SimpleNamespace(
        title="bate",
        min_price=None,
        max_price=None,
        currency="USD",
        moq="10",
        supplier_name="Acme",
        supplier_country="CN",
        product_url="https://www.alibaba.com/p/1",
        image_url="https://s.alicdn.com/a.jpg",
        product_id="1",
        review_score="4.8",
        review_count="128",
        supplier_service_score="4.9",
        gold_supplier_years="6",
    )
    row = alibaba_product_to_row(product)
    assert row["review_score"] == "4.8"
    assert row["review_count"] == "128"
    assert row["supplier_service_score"] == "4.9"


def test_mercadolibre_rating_average_becomes_product_stars() -> None:
    mapped = map_mercadolibre_item(
        {
            "id": "MLV123",
            "title": "Bate ML",
            "price": 12.5,
            "currency": "USD",
            "permalink": "https://articulo.mercadolibre.com.ve/MLV-123",
            "siteId": "MLV",
            "ratingAverage": 4.8,
            "reviewCount": "742",
            "seller": {
                "nickname": "TIENDA_VE",
                "reputation": {"level_id": "green_power"},
                "powerSellerStatus": "platinum",
                "isOfficialStore": True,
                "storeName": "Tienda VE",
            },
        }
    )
    assert mapped is not None
    assert mapped.rating_average == "4.8"
    assert mapped.review_count == "742"
    assert mapped.seller_name == "TIENDA_VE"
    assert mapped.seller_reputation == "green_power"
    assert mapped.official_store is True
    row = mercadolibre_listing_to_row(
        SimpleNamespace(
            listing=mapped,
            relevance_score=80,
            relevance=SimpleNamespace(matched_tokens=1, total_query_tokens=1),
        )
    )
    assert row["rating_average"] == "4.8"
    assert row["review_count"] == "742"
    assert row["seller_reputation"] == "green_power"
    cell = comparison._ml_cell(
        MercadoLibreResultRow(
            title="Bate ML",
            rating_average="4.8",
            review_count="742",
            seller_name="TIENDA_VE",
            seller_reputation="green_power",
            seller_status="platinum · Tienda oficial",
        )
    )
    assert cell["ml_rating_available"] is True
    assert "742 reseñas" in str(cell["ml_rating_label"])
    assert cell["ml_rating_caption"] == "Calificación del producto"
    assert "Reputación: green_power" in str(cell["ml_trust_line"])
    assert "★" not in str(cell["ml_trust_line"])


def test_categorical_seller_reputation_does_not_become_stars() -> None:
    rating = search_session.product_rating_display("green_power")
    assert rating["available"] is False
    cell = comparison._ml_cell(
        MercadoLibreResultRow(title="Bate", seller_reputation="MercadoLíder", rating_average="")
    )
    assert cell["ml_rating_available"] is False
    assert cell["ml_rating_label"] == "Sin calificación"
    assert "MercadoLíder" in str(cell["ml_trust_line"])


def test_missing_ml_rating_is_unrated() -> None:
    listing = MercadoLibreListing(
        external_id="MLV1",
        title="Sin rating",
        permalink="https://articulo.mercadolibre.com.ve/MLV-1",
        currency="USD",
    )
    assert listing.rating_average is None
    cell = comparison._ml_cell(MercadoLibreResultRow(title="Sin rating"))
    assert cell["ml_rating_available"] is False


def test_alibaba_rating_never_appears_on_ml_listing() -> None:
    rows = comparison.build_comparison_rows(
        alibaba_rows=[AlibabaResultRow(title="A", product_id="a", review_score="4.8")],
        ml_rows=[MercadoLibreResultRow(title="M", rating_average="3.1")],
        alibaba_status=UI_SUCCESS,
        ml_status=UI_SUCCESS,
    )
    alibaba = next(row for row in rows if row["alibaba_has_listing"])
    ml = next(row for row in rows if row["ml_has_listing"])
    assert alibaba["alibaba_rating_label"] != ml["ml_rating_label"]
    assert alibaba["ml_rating_available"] is False
    assert ml["alibaba_rating_available"] is False


def test_relevance_and_opportunity_never_become_rating() -> None:
    assert search_session.product_rating_display("90")["available"] is False
    assert search_session.product_rating_display("72")["available"] is False
    cell = comparison._alibaba_cell(
        AlibabaResultRow(title="bate", relevance="90/100", score="88", review_score="")
    )
    assert cell["alibaba_rating_available"] is False
    assert cell["opportunity_available"] is True
