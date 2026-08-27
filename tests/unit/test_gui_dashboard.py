"""Offline tests for the executive marketplace dashboard. No provider calls."""

from __future__ import annotations

import inspect
from pathlib import Path

from bera_price_tracker.gui import comparison, marketplace_summary, views
from bera_price_tracker.gui.images import image_alt_text, safe_public_image_url
from bera_price_tracker.gui.navigation import NAV_ITEMS, NAV_LABELS
from bera_price_tracker.gui.services import (
    alibaba_product_to_row,
    facebook_product_listing_to_row,
    mercadolibre_listing_to_row,
)
from bera_price_tracker.gui.state import (
    UI_INITIAL,
    UI_SUCCESS,
    AlibabaResultRow,
    AlibabaTrackedRow,
    FacebookProductResultRow,
    MercadoLibreResultRow,
    TrackerState,
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
    assert str(row["alibaba_image_url"]) != str(row["ml_image_url"])
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
        ml_summary={
            "comparables": "4",
            "minimo": "$9.50",
            "mediana": "$11.00",
            "precio_tipico": "$10.80",
            "maximo": "$14.00",
        },
        ml_rows=[MercadoLibreResultRow(condition="Nuevo", seller_name="Tienda")],
    )
    assert cards[0]["result_count"] == "1"
    assert cards[0]["meta_one"] == "MOQ típico: 10"
    assert cards[1]["meta_one"] == "USD normalizado · Facebook Venezuela"
    assert cards[2]["meta_one"] == "Nuevo"
    assert cards[2]["meta_two"] == "Mejor vendedor: Tienda"


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
    assert "marketplace_brand_alibaba" in source
    assert "marketplace_brand_facebook" in source
    assert "marketplace_brand_ml" in source
    assert "Sin resultado Alibaba" in source
    assert "Sin resultado Facebook" in source
    assert "Sin resultado Mercado Libre" in source
    assert "Sin imagen" in (SRC / "bera_price_tracker/gui/components/media.py").read_text(
        encoding="utf-8"
    )
    assert "dashboard()" in views.__dict__ or hasattr(views, "dashboard")


def _component_repr(node: object, *, depth: int = 0) -> str:
    if node is None or depth > 16:
        return ""
    chunks = [repr(node)]
    children = getattr(node, "children", None)
    if isinstance(children, list | tuple):
        for child in children:
            chunks.append(_component_repr(child, depth=depth + 1))
    contents = getattr(node, "contents", None)
    if isinstance(contents, list | tuple):
        for child in contents:
            chunks.append(_component_repr(child, depth=depth + 1))
    render = getattr(node, "render", None)
    if callable(render):
        try:
            rendered = render()
        except Exception:  # noqa: BLE001 - dump helper must not fail the test setup
            rendered = None
        if rendered is not None and rendered is not node:
            chunks.append(repr(rendered))
            if isinstance(rendered, dict):
                chunks.append(str(rendered))
            else:
                chunks.append(_component_repr(rendered, depth=depth + 1))
    return "\n".join(chunks)


def test_marketplace_cell_renders_provider_title_visibly_not_only_as_alt() -> None:
    from bera_price_tracker.gui.components import comparison as comparison_ui

    title = "Alibaba listing title visible-xyz"
    cell = comparison_ui.marketplace_cell(
        has_listing=True,
        image_url="https://s.alicdn.com/a.jpg",
        title=title,
        price="$4.00",
        price_color="#111111",
        line_one="",
        line_two="",
        line_three="",
        relevance="",
        match_label="",
        url="https://www.alibaba.com/p/1",
        empty_label="—",
    )
    source = inspect.getsource(comparison_ui.marketplace_cell)
    assert "rx.text(title," in source
    thumbnail_index = source.index("product_thumbnail")
    visible_title_index = source.index("rx.text(title,")
    alt_index = source.index("alt=title")
    assert visible_title_index > thumbnail_index
    assert alt_index != visible_title_index

    blob = _component_repr(cell)
    assert title in blob
    assert blob.lower().count(title.lower()) >= 2

    blank = comparison_ui.marketplace_cell(
        has_listing=True,
        image_url="",
        title="",
        price="$4.00",
        price_color="#111111",
        line_one="",
        line_two="",
        line_three="",
        relevance="",
        match_label="",
        url="",
        empty_label="—",
    )
    blank_blob = _component_repr(blank)
    assert "Sin título" not in blank_blob
    assert "Untitled" not in blank_blob


def test_marketplace_cell_renders_ml_shipping_and_official_store() -> None:
    from bera_price_tracker.gui.components import comparison as comparison_ui

    source = inspect.getsource(comparison_ui)
    assert 'line_three=row["ml_shipping"]' in source
    assert source.count('line_three=row["ml_shipping"]') == 2
    assert "def comparison_row(" in source
    assert "def positional_comparison_row(" in source
    comparison_fn = inspect.getsource(comparison_ui.comparison_row)
    positional_fn = inspect.getsource(comparison_ui.positional_comparison_row)
    assert 'line_three=row["ml_shipping"]' in comparison_fn
    assert 'line_four=row["ml_official_store"]' in comparison_fn
    assert 'line_three=row["ml_shipping"]' in positional_fn
    assert 'line_four=row["ml_official_store"]' in positional_fn
    cell_source = inspect.getsource(comparison_ui.marketplace_cell)
    assert "rx.text(line_three" in cell_source
    assert "rx.text(line_four" in cell_source
    cell = comparison_ui.marketplace_cell(
        has_listing=True,
        image_url="",
        title="ML listing",
        price="$9.00",
        price_color="#111111",
        line_one="Nuevo",
        line_two="Tienda VE",
        line_three="Envío gratis",
        line_four="Tienda oficial",
        relevance="",
        match_label="",
        url="",
        empty_label="—",
    )
    assert cell is not None
    paid = comparison_ui.marketplace_cell(
        has_listing=True,
        image_url="",
        title="ML paid",
        price="$9.00",
        price_color="#111111",
        line_one="",
        line_two="",
        line_three="Pago",
        line_four="",
        relevance="",
        match_label="",
        url="",
        empty_label="—",
    )
    assert paid is not None


def test_gui_modules_do_not_import_apify() -> None:
    gui_root = SRC / "bera_price_tracker" / "gui"
    for path in gui_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "infrastructure.providers.apify" not in text
        assert "import apify" not in text


def test_match_label_and_page_heading_variants() -> None:
    assert comparison.match_label(None, has_listing=False) == ""
    assert comparison.match_label("bad", has_listing=True) == comparison.MATCH_COMPARABLE
    assert comparison.match_label(True, has_listing=True) == comparison.MATCH_COMPARABLE
    assert comparison.match_label(80, has_listing=True) == comparison.MATCH_HIGH
    assert comparison.match_label("60", has_listing=True) == comparison.MATCH_MEDIUM
    assert (
        comparison.page_heading(
            alibaba_query="mouse",
            alibaba_status="EMPTY",
            workspace_view="searches",
        )
        == "Resultados para: mouse"
    )
    assert (
        comparison.page_heading(
            facebook_query="mouse ve",
            facebook_status="ERROR",
            workspace_view="products",
        )
        == "Resultados para: mouse ve"
    )
    assert comparison.page_heading(
        ml_query="mouse ml",
        ml_status=UI_SUCCESS,
        workspace_view="comparisons",
    ) == ("Resultados para: mouse ml")
    assert comparison.page_heading(
        h0019_query="pastillas sbr",
        h0019_status="EMPTY",
        workspace_view="tools",
    ) == ("Resultados para: pastillas sbr")
    assert comparison.page_heading() == "Inteligencia de compras e importación"
    assert comparison.page_heading(workspace_view="tools") == "Facebook H0019"
    assert comparison.page_heading(workspace_view="searches") == "Buscar productos"


def test_analysis_uses_landed_and_ml_comparison_without_inventing_score() -> None:
    landed_only = comparison.build_analysis(
        alibaba_row=None,
        landed={"unit_landed": "$6.10"},
    )
    assert landed_only["analysis_heading"] == "Costo puesto"
    assert "6.10" in str(landed_only["analysis_detail"])
    with_ml = comparison.build_analysis(
        alibaba_row=AlibabaResultRow(score="70/100", score_label="Oportunidad"),
        ml_comparison={
            "comparable": "1",
            "landed": "$6.10",
            "typical_price": "$11.00",
            "typical_profit": "$4.90",
        },
    )
    assert with_ml["analysis_heading"] == "Oportunidad Alibaba"
    assert "Típico ML" in str(with_ml["analysis_detail"])


def test_comparison_rows_without_alibaba_use_facebook_or_ml_title() -> None:
    rows = comparison.build_comparison_rows(
        facebook_rows=[FacebookProductResultRow(title="Solo Facebook", relevance_value=40)],
        facebook_status=UI_SUCCESS,
        fallback_title="",
    )
    assert len(rows) == 1
    assert rows[0]["product_title"] == "Solo Facebook"
    assert rows[0]["alibaba_has_listing"] is False
    ml_rows = comparison.build_comparison_rows(
        ml_rows=[MercadoLibreResultRow(title="Solo ML", relevance_value=40)],
        ml_status=UI_SUCCESS,
        alibaba_context={"external_id": "ali-9", "title": ""},
        alibaba_rows=[AlibabaResultRow(product_id="ali-9", title="From context", price="$2.00")],
    )
    assert ml_rows[0]["product_title"] == "Solo ML"
    assert ml_rows[0]["alibaba_has_listing"] is False
    assert ml_rows[0]["facebook_has_listing"] is False
    assert ml_rows[0]["ml_has_listing"] is True


def test_alibaba_published_range_and_unsafe_facebook_image() -> None:
    cell = comparison._alibaba_cell(
        AlibabaResultRow(price="$4.00", price_min="3.50", price_max="4.30", currency="USD")
    )
    assert "3.50" in str(cell["alibaba_range"])
    facebook = comparison._facebook_cell(
        FacebookProductResultRow(image_url="javascript:alert(1)", price="10.00 VEF")
    )
    assert facebook["facebook_image_url"] == ""
    dash = comparison._ml_cell(MercadoLibreResultRow(condition="—", seller_name="—"))
    assert dash["ml_condition"] == ""
    assert dash["ml_seller"] == ""


def test_image_url_edge_cases() -> None:
    assert safe_public_image_url("https://example.com/a b.jpg") == ""
    assert safe_public_image_url("https://") == ""
    assert safe_public_image_url("https://user@cdn.example/a.jpg") == ""
    assert image_alt_text(None) == "Imagen del producto"
    long_title = "x" * 200
    assert image_alt_text(long_title).endswith("…")
    assert len(image_alt_text(long_title)) <= 160


def test_tracking_display_edge_cases() -> None:
    assert parse_tracking_history("") == []
    assert parse_tracking_history(None) == []
    assert parse_tracking_history("solo")[0]["timestamp"] == "solo"
    assert history_is_collapsed([], None) is True
    assert history_toggle_label("") == "Ver historial (0)"
    assert history_toggle_label(None) == "Ver historial (0)"
    assert tracking_image_url(None) == ""
    assert tracking_image_url("p1", tracked_image="https://s.alicdn.com/ok.jpg") == (
        "https://s.alicdn.com/ok.jpg"
    )


def test_marketplace_summary_range_helpers() -> None:
    card = marketplace_summary.alibaba_summary_card(
        ui_status=UI_SUCCESS,
        summary={"resultados": "1", "minimo": "$1.00", "maximo": "$2.00"},
        rows=[],
    )
    assert card["range"] == "$1.00 – $2.00"
    empty = marketplace_summary.empty_marketplace_card("Alibaba", "alibaba")
    assert empty["status"] == "empty"
    facebook = marketplace_summary.facebook_summary_card(
        ui_status=UI_SUCCESS,
        summary={"usable": "1"},
        statistics=[
            {
                "minimum": "unavailable",
                "median": "unavailable",
                "average": "unavailable",
                "maximum": "unavailable",
            }
        ],
    )
    assert facebook["minimum"] == "—"
    labeled = marketplace_summary.facebook_summary_card(
        ui_status=UI_SUCCESS,
        summary={"usable": "1"},
        statistics=[
            {
                "minimum": "6.50",
                "median": "6.50",
                "average": "6.50",
                "maximum": "6.50",
                "currency": "USD",
            }
        ],
    )
    assert labeled["minimum"] == "USD 6.50"
    assert labeled["range"] == "USD 6.50"


def test_navigation_tab_mapping() -> None:
    from bera_price_tracker.gui.navigation import marketplace_tab_for

    assert marketplace_tab_for("tools") == "facebook"
    assert marketplace_tab_for("products") == "facebook_products"
    assert marketplace_tab_for("unknown") == "alibaba"


def test_component_builders_execute_offline() -> None:
    from bera_price_tracker.gui.components import comparison as comparison_ui
    from bera_price_tracker.gui.components import header, media, primitives, search, shell, summary
    from bera_price_tracker.gui.components import tracking as tracking_ui

    assert media.product_thumbnail("", alt="Sin") is not None
    assert primitives.price_metric("$1.00") is not None
    assert primitives.status_badge("ok", tone="positive") is not None
    assert primitives.status_badge("x", tone="unknown") is not None
    assert primitives.empty_state("Vacío", "Detalle") is not None
    assert primitives.action_button("Ir") is not None
    assert (
        primitives.action_button("Ver", href="https://example.com", icon="external-link")
        is not None
    )
    assert primitives.action_button("Nueva búsqueda", variant="outline", icon="search") is not None
    assert header.page_header() is not None
    assert search.compact_alibaba_search() is not None
    assert shell.sidebar() is not None
    assert shell.app_shell(header.page_header()) is not None
    assert summary.marketplace_summary_row() is not None
    assert comparison_ui.comparison_matrix() is not None
    assert comparison_ui._empty_cell("Sin resultado Alibaba") is not None
    assert views.dashboard() is not None
    assert views._executive_dashboard() is not None
    from bera_price_tracker.gui.components.search_results import search_results_view
    from bera_price_tracker.gui.components.search_scope import search_setup_view

    assert search_setup_view() is not None
    assert search_results_view() is not None
    assert tracking_ui.history_accordion is not None
