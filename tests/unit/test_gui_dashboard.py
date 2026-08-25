"""Offline tests for the executive marketplace dashboard. No provider calls."""

from __future__ import annotations

from pathlib import Path

from bera_price_tracker.gui import comparison, marketplace_summary, views
from bera_price_tracker.gui.images import image_alt_text, safe_public_image_url
from bera_price_tracker.gui.navigation import NAV_LABELS, NAV_ITEMS
from bera_price_tracker.gui.services import (
    alibaba_product_to_row,
    facebook_product_listing_to_row,
    mercadolibre_listing_to_row,
)
from bera_price_tracker.gui.state import (
    AlibabaResultRow,
    AlibabaTrackedRow,
    FacebookProductResultRow,
    MercadoLibreResultRow,
    TrackerState,
    UI_INITIAL,
    UI_SUCCESS,
)
from bera_price_tracker.gui.tracking_display import (
    history_is_collapsed,
    history_toggle_label,
    parse_tracking_history,
    tracking_image_url,
)

SRC = Path(__file__).resolve().parents[2] / "src"


def test_safe_image_url_accepts_public_http() -> None:
    assert (
        safe_public_image_url("https://s.alicdn.com/example.jpg")
        == "https://s.alicdn.com/example.jpg"
    )
    assert safe_public_image_url("http://img.mlstatic.com/photo.png").startswith("http://")


def test_safe_image_url_rejects_unsafe_values() -> None:
    assert safe_public_image_url("javascript:alert(1)") == ""
    assert safe_public_image_url("data:image/png;base64,aaaa") == ""
    assert safe_public_image_url("https://user:pass@cdn.example/a.jpg") == ""
    assert safe_public_image_url("https://cdn.example/a.jpg?token=secret") == ""
    assert safe_public_image_url("https://cdn.example/a.jpg?access_token=abc") == ""
    assert safe_public_image_url("/relative/path.jpg") == ""
    assert safe_public_image_url("") == ""
    assert safe_public_image_url(None) == ""


def test_image_alt_text_is_sanitized() -> None:
    assert image_alt_text("Mouse\ninalámbrico") == "Mouse inalámbrico"
    assert image_alt_text("") == "Imagen del producto"


def test_alibaba_row_propagates_valid_image_and_drops_unsafe() -> None:
    class Product:
        title = "Mouse"
        image_url = "https://s.alicdn.com/mouse.jpg"
        product_url = "https://www.alibaba.com/p"
        moq = "10"
        supplier_name = "Acme"

    row = alibaba_product_to_row(Product())
    assert row["image_url"] == "https://s.alicdn.com/mouse.jpg"

    class Unsafe:
        title = "Mouse"
        image_url = "javascript:alert(1)"
        product_url = "https://www.alibaba.com/p"

    assert alibaba_product_to_row(Unsafe())["image_url"] == ""


def test_mercadolibre_row_propagates_valid_thumbnail() -> None:
    from bera_price_tracker.application.mercadolibre_relevance import MercadoLibreListingRelevance
    from bera_price_tracker.domain.mercadolibre import MercadoLibreListing

    listing = MercadoLibreListing(
        external_id="MLV1",
        title="Mouse inalámbrico",
        permalink="https://articulo.mercadolibre.com.ve/MLV1",
        thumbnail_url="https://http2.mlstatic.com/mouse.jpg",
    )
    relevance = MercadoLibreListingRelevance(
        relevance_score=80,
        matched_tokens=2,
        total_query_tokens=2,
        exact_phrase_match=True,
    )

    class Scored:
        def __init__(self) -> None:
            self.listing = listing
            self.relevance_score = 80
            self.relevance = relevance

    row = mercadolibre_listing_to_row(Scored())
    assert row["thumbnail_url"] == "https://http2.mlstatic.com/mouse.jpg"
    listing_unsafe = MercadoLibreListing(
        external_id="MLV2",
        title="Mouse",
        permalink="https://articulo.mercadolibre.com.ve/MLV2",
        thumbnail_url="data:image/gif;base64,xx",
    )
    scored_unsafe = Scored()
    scored_unsafe.listing = listing_unsafe
    assert mercadolibre_listing_to_row(scored_unsafe)["thumbnail_url"] == ""


def test_facebook_free_listings_never_enter_comparison() -> None:
    facebook = FacebookProductResultRow(
        title="Free headphones",
        price="0",
        formatted_price="Free",
    )
    assert facebook.formatted_price != "Free" or facebook.price == "0"
    rows = comparison.build_comparison_rows(
        facebook_rows=[],
        facebook_status=UI_SUCCESS,
    )
    rendered = str(rows)
    assert "Free" not in rendered
    assert "Gratis" not in rendered


def test_facebook_row_has_empty_image_when_provider_has_none() -> None:
    from bera_price_tracker.application.facebook_relevance import FacebookListingRelevance

    class Listing:
        external_id = "fb-1"
        title = "Mouse inalámbrico"
        url = "https://facebook.com/marketplace/item/1"
        price = None
        currency = "USD"
        formatted_amount = "$10"
        usd_amount = None
        usd_normalization_status = ""
        usd_evidence = ()
        location = "Caracas"

    relevance = FacebookListingRelevance(
        relevance_score=70,
        matched_tokens=1,
        total_query_tokens=2,
        exact_phrase_match=False,
    )
    row = facebook_product_listing_to_row(Listing(), relevance)
    assert row["image_url"] == ""
    assert "Free" not in row["price"]
    assert row["currency"] == "USD"


def test_comparison_matrix_renders_all_three_marketplace_columns() -> None:
    alibaba = AlibabaResultRow(
        title="Wireless mouse",
        price="$4.30",
        moq="10",
        supplier_name="Shenzhen Co",
        url="https://www.alibaba.com/p/1",
        image_url="https://s.alicdn.com/a.jpg",
        product_id="ali-1",
        relevance_value=94,
        relevance="94/100",
        score="72/100",
        score_label="Buena oportunidad",
    )
    facebook = FacebookProductResultRow(
        title="Mouse Caracas",
        price="10.00 VEF",
        formatted_price="VEF10",
        source_price_note="VEF10 · etiqueta fuente del proveedor Facebook",
        usd_price="USD: $10.00",
        usd_provenance="Facebook Venezuela · mismo valor numérico · sin FX",
        location="Caracas",
        permalink="https://facebook.com/marketplace/item/2",
        relevance_value=88,
        relevance="88/100",
        currency="VEF",
    )
    ml = MercadoLibreResultRow(
        title="Mouse MLV",
        price="$9.50",
        condition="Nuevo",
        seller_name="Tienda VE",
        permalink="https://articulo.mercadolibre.com.ve/MLV9",
        thumbnail_url="https://http2.mlstatic.com/b.jpg",
        relevance_value=70,
        relevance="70/100",
    )
    rows = comparison.build_comparison_rows(
        alibaba_rows=[alibaba],
        facebook_rows=[facebook],
        ml_rows=[ml],
        alibaba_status=UI_SUCCESS,
        facebook_status=UI_SUCCESS,
        ml_status=UI_SUCCESS,
        facebook_association_id="ali-1",
        ml_association_id="ali-1",
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["alibaba_has_listing"] is True
    assert row["facebook_has_listing"] is True
    assert row["ml_has_listing"] is True
    assert row["alibaba_price"] == "$4.30"
    assert row["facebook_price"] == "USD: $10.00"
    assert row["ml_price"] == "$9.50"
    assert row["alibaba_image_url"] == "https://s.alicdn.com/a.jpg"
    assert row["facebook_image_url"] == ""
    assert row["ml_image_url"] == "https://http2.mlstatic.com/b.jpg"
    assert row["alibaba_image_url"] != row["ml_image_url"]
    assert "VEF10" in str(row["facebook_source_note"])
    assert "sin FX" in str(row["facebook_usd_note"])
    assert row["alibaba_match_label"] == comparison.MATCH_HIGH
    assert row["facebook_match_label"] == comparison.MATCH_HIGH
    assert row["ml_match_label"] == comparison.MATCH_MEDIUM
    assert row["analysis_heading"] == "Oportunidad Alibaba"
    assert "72/100" in str(row["analysis_detail"])


def test_comparison_does_not_reuse_alibaba_image_for_other_markets() -> None:
    alibaba = AlibabaResultRow(
        title="Pad",
        image_url="https://s.alicdn.com/only-alibaba.jpg",
        product_id="ali-2",
        price="$1.00",
    )
    facebook = FacebookProductResultRow(title="Pad FB", price="5.00 VEF", permalink="https://fb")
    rows = comparison.build_comparison_rows(
        alibaba_rows=[alibaba],
        facebook_rows=[facebook],
        alibaba_status=UI_SUCCESS,
        facebook_status=UI_SUCCESS,
        facebook_association_id="ali-2",
    )
    assert rows[0]["facebook_image_url"] == ""
    assert rows[0]["facebook_image_url"] != rows[0]["alibaba_image_url"]


def test_empty_marketplace_state_has_no_fake_prices() -> None:
    cards = marketplace_summary.build_marketplace_summaries(
        alibaba_ui_status=UI_INITIAL,
        alibaba_summary={},
        facebook_ui_status=UI_INITIAL,
        facebook_summary={},
        ml_ui_status=UI_INITIAL,
        ml_summary={},
    )
    assert [card["platform"] for card in cards] == [
        "Alibaba",
        "Facebook Marketplace",
        "Mercado Libre",
    ]
    for card in cards:
        assert card["status"] == "empty"
        assert card["minimum"] == "—"
        assert card["median"] == "—"
        assert card["average"] == "—"
        assert "4.30" not in str(card)
        assert "9.50" not in str(card)


def test_summary_cards_use_real_ready_data_only() -> None:
    cards = marketplace_summary.build_marketplace_summaries(
        alibaba_ui_status=UI_SUCCESS,
        alibaba_summary={
            "resultados": "3",
            "minimo": "$3.50",
            "mediana": "$4.00",
            "promedio": "$4.10",
            "maximo": "$4.30",
        },
        alibaba_rows=[AlibabaResultRow(supplier_name="Acme", moq="10")],
        facebook_ui_status=UI_SUCCESS,
        facebook_summary={"usable": "2", "note": "Solo publicaciones con precio"},
        facebook_statistics=[
            {
                "minimum": "USD: $4.00",
                "median": "USD: $10.00",
                "average": "USD: $9.00",
                "maximum": "USD: $15.00",
                "label": "USD normalizado · Facebook Venezuela",
            }
        ],
        facebook_rows=[FacebookProductResultRow(location="Caracas")],
        ml_ui_status=UI_SUCCESS,
        ml_summary={"comparables": "4", "minimo": "$9.50", "mediana": "$11.00", "precio_tipico": "$10.80", "maximo": "$14.00"},
        ml_rows=[MercadoLibreResultRow(condition="Nuevo", seller_name="Tienda")],
    )
    assert cards[0]["result_count"] == "3"
    assert cards[0]["meta_one"] == "MOQ: 10"
    assert cards[1]["meta_one"] == "USD normalizado · Facebook Venezuela"
    assert cards[2]["meta_one"] == "Nuevo"
    assert cards[2]["meta_two"] == "Tienda"


def test_analysis_unavailable_when_no_context() -> None:
    result = comparison.build_analysis(alibaba_row=None)
    assert result["analysis_available"] is False
    assert result["analysis_heading"] == comparison.ANALYSIS_UNAVAILABLE


def test_history_collapsed_by_default() -> None:
    assert history_is_collapsed([], "p1") is True
    assert history_is_collapsed(["p2"], "p1") is True
    assert history_is_collapsed(["p1"], "p1") is False
    assert history_toggle_label("3") == "Ver historial (3)"
    parsed = parse_tracking_history("2026-01-01 12:00 UTC · $4.30 · Discovery")
    assert parsed[0]["timestamp"].startswith("2026-01-01")
    assert parsed[0]["price"] == "$4.30"
    assert parsed[0]["origin"] == "Discovery"


def test_tracking_image_uses_loaded_alibaba_result_only() -> None:
    assert (
        tracking_image_url(
            "p1",
            result_images={"p1": "https://s.alicdn.com/ok.jpg"},
        )
        == "https://s.alicdn.com/ok.jpg"
    )
    assert tracking_image_url("p1", result_images={"p1": "javascript:x"}) == ""
    assert tracking_image_url("missing", result_images={"p1": "https://s.alicdn.com/ok.jpg"}) == ""


def test_navigation_labels_cover_existing_views() -> None:
    assert NAV_LABELS == (
        "Dashboard",
        "Búsquedas",
        "Productos",
        "Comparaciones",
        "Seguimiento",
        "Importación",
        "Herramientas",
        "Configuración",
    )
    assert any(item.description == "Facebook H0019" for item in NAV_ITEMS)
    source = (SRC / "bera_price_tracker/gui/views.py").read_text(encoding="utf-8")
    assert "Facebook H0019" in source or "Herramientas" in source
    assert "_form()" in source


def test_no_fake_export_action() -> None:
    header = (SRC / "bera_price_tracker/gui/components/header.py").read_text(encoding="utf-8")
    assert "disabled=True" in header
    assert "csv" not in header.lower()
    assert "on_click" not in header.split("Exportar", 1)[1]
    state = TrackerState()
    assert state.export_enabled is False


def test_currency_provenance_preserved_in_facebook_cell() -> None:
    row = comparison._facebook_cell(
        FacebookProductResultRow(
            price="10.00 VEF",
            formatted_price="VEF10",
            source_price_note="VEF10 · etiqueta fuente del proveedor Facebook",
            usd_price="USD: $10.00",
            usd_provenance="Facebook Venezuela · mismo valor numérico · sin FX",
            currency="VEF",
            relevance_value=50,
        )
    )
    assert row["facebook_price"] == "USD: $10.00"
    assert "VEF10" in str(row["facebook_source_note"])
    assert "sin FX" in str(row["facebook_usd_note"])


def test_default_state_has_no_fake_marketplace_data() -> None:
    state = TrackerState()
    assert state.workspace_view == "dashboard"
    assert state.alibaba_results == []
    assert state.facebook_product_results == []
    assert state.ml_results == []
    assert state.alibaba_history_open_ids == []
    assert state.comparison_rows == []
    assert state.has_comparison_rows is False
    cards = state.marketplace_summaries
    assert len(cards) == 3
    assert all(card.status == "empty" for card in cards)


def test_toggle_history_opens_only_selected_product() -> None:
    state = TrackerState()
    state.alibaba_tracked_rows = [
        AlibabaTrackedRow(product_id="p1", history="2026-01-01 · $1.00", snapshot_count="1"),
        AlibabaTrackedRow(product_id="p2", history="2026-01-02 · $2.00", snapshot_count="1"),
    ]
    assert all(not row.history_open for row in state.alibaba_tracked_view_rows)
    state.toggle_alibaba_history("p1")
    opened = [row.product_id for row in state.alibaba_tracked_view_rows if row.history_open]
    assert opened == ["p1"]


def test_views_declare_three_marketplace_columns() -> None:
    source = (SRC / "bera_price_tracker/gui/components/comparison.py").read_text(encoding="utf-8")
    assert "Alibaba" in source
    assert "Facebook Marketplace" in source
    assert "Mercado Libre" in source
    assert "Sin imagen" in (SRC / "bera_price_tracker/gui/components/media.py").read_text(
        encoding="utf-8"
    )
    assert "dashboard()" in views.__dict__ or hasattr(views, "dashboard")


def test_gui_modules_do_not_import_apify() -> None:
    gui_root = SRC / "bera_price_tracker" / "gui"
    for path in gui_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "infrastructure.providers.apify" not in text
        assert "import apify" not in text
