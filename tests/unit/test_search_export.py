"""Offline CSV export tests. No provider I/O."""

from __future__ import annotations

import csv
import io
from typing import cast

import pytest

from bera_price_tracker.gui import search_export
from bera_price_tracker.gui.state import (
    UI_ERROR,
    UI_SUCCESS,
    AlibabaResultRow,
    FacebookProductResultRow,
    MercadoLibreResultRow,
    TrackerState,
)


def _parse(payload: bytes) -> list[dict[str, str]]:
    assert payload.startswith("\ufeff".encode("utf-8"))
    text = payload.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def test_three_marketplace_listings_export_three_rows() -> None:
    rows = search_export.listing_rows_for_export(
        search_query="béisbol",
        searched_at="2026-08-25 21:00",
        search_mode="Comparar las 3 plataformas",
        requested_limit=1,
        alibaba_status=UI_SUCCESS,
        alibaba_rows=[
            AlibabaResultRow(
                title="Bate Alibaba",
                product_id="ali-1",
                price="USD 4.00",
                image_url="https://s.alicdn.com/a.jpg",
                supplier_name="Supplier A",
                review_score="4.8",
                review_count="128",
                supplier_service_score="4.9",
                gold_supplier_years="6",
                score="72",
            )
        ],
        facebook_status=UI_SUCCESS,
        facebook_rows=[
            FacebookProductResultRow(
                title="Bate de sóftball",
                external_id="fb-1",
                price="USD 150.00",
                image_url="https://scontent.xx.fbcdn.net/v/t1/b.jpg",
                permalink="https://www.facebook.com/marketplace/item/1",
                location="Caracas",
            )
        ],
        ml_status=UI_SUCCESS,
        ml_rows=[
            MercadoLibreResultRow(
                title="Bate ML",
                external_id="ml-1",
                price="USD 9.00",
                thumbnail_url="https://http2.mlstatic.com/c.jpg",
                seller_name="Shop C",
                rating_average="4.8",
                review_count="742",
                seller_reputation="MercadoLíder",
            )
        ],
    )
    assert len(rows) == 3
    by_market = {row["marketplace"]: row for row in rows}
    assert by_market["Alibaba"]["image_url"] == "https://s.alicdn.com/a.jpg"
    assert by_market["Facebook Marketplace"]["image_url"] == (
        "https://scontent.xx.fbcdn.net/v/t1/b.jpg"
    )
    assert by_market["Mercado Libre"]["image_url"] == "https://http2.mlstatic.com/c.jpg"
    assert by_market["Alibaba"]["listing_url"] == ""
    assert "facebook.com" not in by_market["Alibaba"]["listing_url"]
    assert by_market["Facebook Marketplace"]["listing_url"].startswith("https://www.facebook.com")
    assert by_market["Alibaba"]["product_rating"] == "4.8"
    assert by_market["Mercado Libre"]["product_rating"] == "4.8"
    assert by_market["Facebook Marketplace"]["product_rating"] == ""
    assert by_market["Alibaba"]["seller_rating"] == ""
    assert by_market["Alibaba"]["seller_service_score"] == "4.9"
    assert by_market["Alibaba"]["gold_supplier_years"] == "6"
    assert by_market["Alibaba"]["product_review_count"] == "128"
    assert by_market["Mercado Libre"]["seller_rating"] == ""
    assert by_market["Mercado Libre"]["seller_reputation"] == "MercadoLíder"
    payload = search_export.render_csv(rows)
    parsed = _parse(payload)
    assert parsed[0]["search_query"] == "béisbol"
    assert any("sóftball" in row["title"] for row in parsed)


def test_only_facebook_result_exports_one_row() -> None:
    rows = search_export.listing_rows_for_export(
        search_query="bate",
        searched_at="2026-08-25 21:00",
        search_mode="Una plataforma",
        requested_limit=1,
        alibaba_status="EMPTY",
        facebook_status=UI_SUCCESS,
        facebook_rows=[FacebookProductResultRow(title="Solo Facebook", external_id="fb-1")],
        ml_status="EMPTY",
    )
    assert len(rows) == 1
    assert rows[0]["marketplace"] == "Facebook Marketplace"


def test_no_results_keeps_export_disabled() -> None:
    state = TrackerState()
    assert state.export_enabled is False
    assert state.export_current_search() is None


def test_partial_exports_successful_listings_only() -> None:
    state = TrackerState()
    state.apply_partial_search_fixture()
    assert state.search_session_phase == "PARTIAL"
    assert state.export_enabled is True
    rows = search_export.listing_rows_for_export(
        search_query=state.search_session_query,
        searched_at=state.search_completed_at,
        search_mode=state.search_mode_label,
        requested_limit=state.search_limit,
        alibaba_status=state.alibaba_ui_status,
        alibaba_rows=state.alibaba_results,
        facebook_status=state.facebook_product_ui_status,
        facebook_rows=state.facebook_product_results,
        ml_status=state.ml_ui_status,
        ml_rows=state.ml_results,
    )
    markets = [row["marketplace"] for row in rows]
    assert markets == ["Alibaba", "Mercado Libre"]
    assert "Facebook Marketplace" not in markets


def test_formula_injection_is_neutralized() -> None:
    rows = search_export.listing_rows_for_export(
        search_query="=HYPERLINK()",
        searched_at="2026-08-25 21:00",
        search_mode="Comparar",
        requested_limit=1,
        alibaba_status=UI_SUCCESS,
        alibaba_rows=[
            AlibabaResultRow(title='=HYPERLINK("http://evil")', product_id="1"),
            AlibabaResultRow(title="+SUM(1,2)", product_id="2"),
            AlibabaResultRow(title="-1+1", product_id="3"),
            AlibabaResultRow(title="@evil", product_id="4"),
        ],
        facebook_status=UI_ERROR,
        ml_status="EMPTY",
    )
    titles = [row["title"] for row in rows]
    assert titles == [
        '\'=HYPERLINK("http://evil")',
        "'+SUM(1,2)",
        "'-1+1",
        "'@evil",
    ]
    assert rows[0]["search_query"].startswith("'=")
    parsed = _parse(search_export.render_csv(rows))
    assert parsed[0]["title"].startswith("'=")


def test_csv_quotes_commas_quotes_and_newlines() -> None:
    rows = search_export.listing_rows_for_export(
        search_query="búsqueda",
        searched_at="2026-08-25 21:00",
        search_mode="Comparar",
        requested_limit=1,
        alibaba_status=UI_SUCCESS,
        alibaba_rows=[
            AlibabaResultRow(title="Bate de béisbol, aluminio", product_id="1"),
            AlibabaResultRow(title='Bate "pro"', product_id="2"),
            AlibabaResultRow(title="linea1\nlinea2", product_id="3"),
        ],
        facebook_status="EMPTY",
        ml_status="EMPTY",
    )
    parsed = _parse(search_export.render_csv(rows))
    assert parsed[0]["title"] == "Bate de béisbol, aluminio"
    assert parsed[1]["title"] == 'Bate "pro"'
    assert "linea1" in parsed[2]["title"] and "linea2" in parsed[2]["title"]
    assert parsed[0]["search_query"] == "búsqueda"


def test_numeric_price_raw_is_not_formula_escaped() -> None:
    rows = search_export.listing_rows_for_export(
        search_query="bate",
        searched_at="2026-08-25 21:00",
        search_mode="Comparar",
        requested_limit=1,
        alibaba_status="EMPTY",
        facebook_status=UI_SUCCESS,
        facebook_rows=[
            FacebookProductResultRow(title="Bate", price_raw="150.00", price="USD 150.00")
        ],
        ml_status="EMPTY",
    )
    assert rows[0]["price_raw"] == "150.00"


def test_export_filename_is_safe() -> None:
    name = search_export.export_filename(searched_at="2026-08-25 21:15", query="bate/../x")
    assert name.startswith("bera-search-202608252115-")
    assert "/" not in name
    assert ".." not in name
    assert name.endswith(".csv")


def test_complete_fixture_enables_export_and_nueva_busqueda_disables() -> None:
    state = TrackerState()
    state.apply_complete_search_fixture()
    assert state.export_enabled is True
    state.start_new_search()
    assert state.export_enabled is False
    assert state.current_export_listing_count() == 0


def test_view_filters_do_not_remove_current_session_export_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = TrackerState()
    state.apply_complete_search_fixture()
    state.alibaba_results = [
        AlibabaResultRow(title="A", price_raw="1", representative="1"),
        AlibabaResultRow(title="B", price_raw="2", representative="2"),
        AlibabaResultRow(title="C", price_raw="3", representative="3"),
    ]
    state.alibaba_price_min = "2"
    state.alibaba_price_max = "2"
    assert [row.title for row in state.alibaba_visible_rows] == ["B"]
    assert state.current_export_listing_count() == 5

    captured: dict[str, object] = {}

    def capture(**kwargs: object) -> list[dict[str, str]]:
        captured.update(kwargs)
        return [{column: "" for column in search_export.CSV_COLUMNS}]

    monkeypatch.setattr(search_export, "listing_rows_for_export", capture)
    assert state.export_current_search() is not None
    exported = cast(list[AlibabaResultRow], captured["alibaba_rows"])
    assert [row.title for row in exported] == ["A", "B", "C"]
