"""Offline image provenance tests for completed-search comparison cells."""

from __future__ import annotations

from bera_price_tracker.gui import comparison
from bera_price_tracker.gui.images import safe_public_image_url
from bera_price_tracker.gui.services import facebook_product_listing_to_row
from bera_price_tracker.gui.state import (
    UI_SUCCESS,
    AlibabaResultRow,
    FacebookProductResultRow,
    MercadoLibreResultRow,
)

ALIBABA_IMAGE = "https://s.alicdn.com/kf/alibaba-a.jpg"
FACEBOOK_IMAGE = "https://scontent.xx.fbcdn.net/v/t1/facebook-b.jpg"
ML_IMAGE = "https://http2.mlstatic.com/ml-c.jpg"


def test_cross_market_images_stay_on_their_cells() -> None:
    rows = comparison.build_comparison_rows(
        alibaba_rows=[
            AlibabaResultRow(
                title="Alibaba A",
                product_id="ali-a",
                image_url=ALIBABA_IMAGE,
                price="USD 4.00",
            )
        ],
        facebook_rows=[
            FacebookProductResultRow(
                title="Facebook B",
                image_url=FACEBOOK_IMAGE,
                price="USD 150.00",
                location="Caracas",
            )
        ],
        ml_rows=[
            MercadoLibreResultRow(
                title="Mercado C",
                thumbnail_url=ML_IMAGE,
                price="USD 9.00",
            )
        ],
        alibaba_status=UI_SUCCESS,
        facebook_status=UI_SUCCESS,
        ml_status=UI_SUCCESS,
    )
    alibaba_row = next(row for row in rows if row["alibaba_has_listing"])
    facebook_row = next(row for row in rows if row["facebook_has_listing"])
    ml_row = next(row for row in rows if row["ml_has_listing"])
    assert alibaba_row["alibaba_image_url"] == ALIBABA_IMAGE
    assert alibaba_row["facebook_image_url"] != FACEBOOK_IMAGE
    assert alibaba_row["ml_image_url"] != ML_IMAGE
    assert facebook_row["facebook_image_url"] == FACEBOOK_IMAGE
    assert facebook_row["alibaba_image_url"] != ALIBABA_IMAGE
    assert facebook_row["ml_image_url"] != ML_IMAGE
    assert ml_row["ml_image_url"] == ML_IMAGE
    assert ml_row["alibaba_image_url"] != ALIBABA_IMAGE
    assert ml_row["facebook_image_url"] != FACEBOOK_IMAGE
    assert alibaba_row["product_image_url"] == ALIBABA_IMAGE
    assert facebook_row["product_image_url"] == FACEBOOK_IMAGE
    assert ml_row["product_image_url"] == ML_IMAGE


def test_missing_image_falls_back_independently() -> None:
    rows = comparison.build_comparison_rows(
        alibaba_rows=[AlibabaResultRow(title="No photo", product_id="ali-empty", image_url="")],
        facebook_rows=[FacebookProductResultRow(title="FB photo", image_url=FACEBOOK_IMAGE)],
        ml_rows=[MercadoLibreResultRow(title="ML empty", thumbnail_url="")],
        alibaba_status=UI_SUCCESS,
        facebook_status=UI_SUCCESS,
        ml_status=UI_SUCCESS,
    )
    alibaba_row = next(row for row in rows if row["alibaba_has_listing"])
    ml_row = next(row for row in rows if row["ml_has_listing"])
    assert alibaba_row["alibaba_image_url"] == ""
    assert alibaba_row["facebook_image_url"] == ""
    assert ml_row["ml_image_url"] == ""
    assert ml_row["alibaba_image_url"] == ""


def test_unsafe_facebook_image_rejected_at_ui_boundary() -> None:
    class Listing:
        external_id = "1"
        title = "Bate"
        url = "https://www.facebook.com/marketplace/item/1"
        price = None
        currency = "USD"
        formatted_amount = "$10"
        usd_amount = None
        usd_normalization_status = None
        usd_evidence = ()
        location = "Caracas"
        image_url = "https://cdn.example/a.jpg?token=secret"

    class Relevance:
        relevance_score = 50
        matched_tokens = 1
        total_query_tokens = 1

    row = facebook_product_listing_to_row(Listing(), Relevance())
    assert row["image_url"] == ""
    assert row["title"] == "Bate"
    assert safe_public_image_url("https://cdn.example/a.jpg?token=secret") == ""
