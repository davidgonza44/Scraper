"""Offline search-query quality for ConservativeProductSearchQueryGenerator.

No DeepL, Azure, Apify, Mercado Libre, MiniMax, or Facebook requests.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from bera_price_tracker.application.product_translation import (
    ConservativeProductSearchQueryGenerator,
    ProductTranslationRequest,
    ProductTranslationResult,
    TranslateProductTitle,
    extract_technical_tokens,
    validate_technical_tokens,
)
from bera_price_tracker.gui import services as gui_services
from bera_price_tracker.gui.state import AlibabaResultRow, TrackerState
from tests.unit.test_product_translation import FakeProductTranslator

MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "bera_price_tracker"
    / "application"
    / "product_translation.py"
)

MOUSE_ORIGINAL = (
    "Hot Selling 2.4G Colorful LED Dual Mode Office Laptop PC "
    "Ergonomic Silent Rechargeable Wireless Gaming Mouse"
)
MOUSE_TRANSLATED = (
    "Ratón de gran éxito de ventas de 2,4 GHz con LED de colores y modo dual, "
    "para oficina, portátil y PC; ratón inalámbrico ergonómico, silencioso, "
    "recargable y para juegos"
)
TOOLS_ORIGINAL = "Factory Direct 21V Brushless Cordless Impact Wrench 800Nm"
TOOLS_TRANSLATED = "Llave de impacto inalámbrica sin escobillas de 21 V y 800 Nm"
INDUSTRIAL_ORIGINAL = "High Quality 304 Stainless Steel Self Priming Pump 1.5kW 220V"
INDUSTRIAL_TRANSLATED = "Bomba autocebante de acero inoxidable 304 de alta calidad, 1,5 kW 220 V"
CLOTHING_ORIGINAL = "Hot Sale Women's High Waist Seamless Yoga Leggings"
CLOTHING_TRANSLATED = "Leggings de yoga para mujer de cintura alta sin costuras, superventas"
AUTO_ORIGINAL = "Wholesale Brake Pads Compatible Honda CG150"
AUTO_TRANSLATED = "Pastillas de freno compatibles con Honda CG150 al por mayor"
ELECTRONICS_ORIGINAL = "New Arrival Bluetooth 5.3 USB-C Wireless Headphones"
ELECTRONICS_TRANSLATED = "Auriculares inalámbricos Bluetooth 5.3 USB-C de nuevo lanzamiento"


def _query(original: str, translated: str) -> str:
    return ConservativeProductSearchQueryGenerator().generate(
        original_text=original,
        translated_text=translated,
    )


def _compact(text: str) -> str:
    return text.replace(" ", "").casefold()


def test_smoke_mouse_query_is_conservative_and_keeps_source_spec() -> None:
    query = _query(MOUSE_ORIGINAL, MOUSE_TRANSLATED)
    validation = validate_technical_tokens(MOUSE_ORIGINAL, MOUSE_TRANSLATED)
    assert query
    assert "gran éxito de ventas" not in query.casefold()
    assert "hot selling" not in query.casefold()
    assert "2 4" not in query
    assert "2.4" in query
    assert "2.4G" in query
    assert validation.is_reliable is False
    assert "2.4G" in validation.missing_tokens
    assert "$" not in query
    assert "USD" not in query.upper().split()
    assert "  " not in query
    assert query == query.strip()
    assert "5.3" not in query
    assert "110V" not in query
    assert query == _query(MOUSE_ORIGINAL, MOUSE_TRANSLATED)


def test_decimal_point_is_preserved() -> None:
    query = _query("Centrifugal Pump 1.5 kW", "Bomba centrífuga 1.5 kW")
    assert "1.5" in query
    assert "1 5" not in query


def test_decimal_comma_is_normalized_safely() -> None:
    query = _query("Wireless Mouse 2.4 GHz", "Ratón inalámbrico 2,4 GHz")
    assert "2.4" in query
    assert "2,4" not in query
    assert "2 4" not in query


def test_decimal_never_becomes_two_integers() -> None:
    cases = (
        ("Tool 2.4 GHz", "Herramienta 2.4 GHz"),
        ("Tool 2,4 GHz", "Herramienta 2,4 GHz"),
        ("Pump 1.5 kW", "Bomba 1,5 kW"),
        ("Hose 12.5 mm", "Manguera 12,5 mm"),
    )
    for original, translated in cases:
        query = _query(original, translated)
        assert "2 4" not in query
        assert "1 5" not in query
        assert "12 5" not in query
        assert "." in query


def test_hyphenated_technical_token_is_preserved() -> None:
    query = _query(
        "Fast Charge USB-C Wi-Fi 6 Cable X-T5 M10x1.25",
        "Cable de carga rápida USB-C Wi-Fi 6 X-T5 M10x1.25",
    )
    assert "USB-C" in query
    assert "Wi-Fi 6" in query
    assert "X-T5" in query
    assert "M10x1.25" in query


def test_trailing_plus_in_model_identifier_is_preserved() -> None:
    query = _query("Samsung Galaxy S24+", "Samsung Galaxy S24+")
    assert query == "Samsung Galaxy S24+"


def test_plus_inside_model_identifier_is_preserved() -> None:
    query = _query("Galaxy S24+ 5G", "Galaxy S24+ 5G")
    assert query == "Galaxy S24+ 5G"


def test_trailing_symbols_in_language_identifiers_are_preserved() -> None:
    for identifier in ("C#", "C++"):
        assert _query(identifier, identifier) == identifier


def test_number_unit_spacing_equivalence_is_deduplicated() -> None:
    query = _query(
        "Impact Wrench 21V 800Nm",
        "Llave de impacto 21V 21 V 800Nm 800 Nm",
    )
    compact = _compact(query)
    assert compact.count("21v") == 1
    assert compact.count("800nm") == 1
    assert "21" in query
    assert "800" in query


def test_exact_technical_duplicates_are_deduplicated() -> None:
    query = _query(
        "Bottle 500ml 1.5kW 2.4GHz",
        "Botella 500ml 500 ml 1.5kW 1.5 kW 2.4GHz 2,4 GHz",
    )
    compact = _compact(query)
    assert compact.count("500ml") == 1
    assert compact.count("1.5kw") == 1
    assert compact.count("2.4ghz") == 1


def test_uncertain_technical_equivalence_is_not_guessed() -> None:
    query = _query(
        "Device 2.4G M10 304 Bluetooth 5.3",
        "Dispositivo 2.4 GHz 10mm 304L Bluetooth 5",
    )
    assert "2.4G" in query
    assert "2.4 GHz" in query or "2.4GHz" in _compact(query)
    assert "M10" in query
    assert "10mm" in query
    assert "304" in query
    assert "304L" in query
    assert "Bluetooth 5.3" in query
    assert "Bluetooth 5" in query
    assert _compact("2.4G") != _compact("2.4GHz")


def test_original_technical_token_is_restored_when_translation_warns() -> None:
    original = "Self Priming Pump 220V 1.5kW"
    translated = "Bomba autocebante 1.5kW"
    query = _query(original, translated)
    validation = validate_technical_tokens(original, translated)
    assert validation.is_reliable is False
    assert "220V" in validation.missing_tokens
    assert translated == "Bomba autocebante 1.5kW"
    assert "220V" in query.replace(" ", "")
    assert "1.5kW" in query.replace(" ", "")


def test_english_marketplace_phrases_are_removed() -> None:
    query = _query(
        "Hot Selling Factory Direct Best Seller New Arrival Wholesale OEM",
        "Hot Selling Factory Direct Best Seller New Arrival Wholesale OEM pump housing",
    )
    folded = query.casefold()
    assert "hot selling" not in folded
    assert "factory direct" not in folded
    assert "best seller" not in folded
    assert "new arrival" not in folded
    assert "wholesale" not in folded
    assert "oem" not in folded.split()
    assert "pump" in folded
    assert "housing" in folded


def test_spanish_marketplace_phrases_are_removed() -> None:
    query = _query(
        "Promotional factory price item",
        "Artículo promocional de gran éxito de ventas, superventas, "
        "venta caliente, precio de fábrica, al por mayor y de nuevo lanzamiento",
    )
    folded = query.casefold()
    assert "gran éxito de ventas" not in folded
    assert "superventas" not in folded
    assert "venta caliente" not in folded
    assert "precio de fábrica" not in folded
    assert "al por mayor" not in folded
    assert "nuevo lanzamiento" not in folded
    assert "promocional" not in folded
    assert "artículo" in folded


def test_phrase_removal_keeps_adjacent_product_description() -> None:
    query = _query(
        "High Quality stainless steel pump housing",
        "High Quality stainless steel pump housing",
    )
    folded = query.casefold()
    assert "high quality" not in folded
    assert "stainless" in folded
    assert "steel" in folded
    assert "pump" in folded
    assert "housing" in folded


def test_unicode_letters_are_preserved_in_query() -> None:
    query = _query(
        "Bomba Café 220V 不锈钢 1.5kW",
        "Bomba Café 220V acero inoxidable 不锈钢 1.5kW",
    )
    assert "Café" in query
    assert "不锈钢" in query
    assert "220V" in query.replace(" ", "")
    assert "1.5kW" in query.replace(" ", "")


def test_quotes_are_stripped_without_losing_words() -> None:
    query = _query(
        'Ergonomic "silent" wireless device 2.4GHz',
        'Dispositivo «silencioso» "ergonómico" 2.4 GHz',
    )
    assert '"' not in query
    assert "«" not in query
    assert "»" not in query
    assert "silencioso" in query
    assert "ergonómico" in query
    assert "2.4" in query


def test_semicolons_are_stripped_without_losing_words() -> None:
    query = _query(
        "Office laptop PC device",
        "oficina; portátil; PC",
    )
    assert ";" not in query
    assert "oficina" in query
    assert "portátil" in query
    assert "PC" in query


def test_parentheses_are_stripped_without_losing_specs() -> None:
    query = _query(
        "Stainless Steel Pump (304) 220V",
        "Bomba de acero inoxidable (304) 220V",
    )
    assert "(" not in query
    assert ")" not in query
    assert "304" in query
    assert "220V" in query.replace(" ", "")
    assert "Bomba" in query


def test_repeated_whitespace_is_collapsed() -> None:
    query = _query(
        "Impact   Wrench\t21V",
        "Llave   de\nimpacto    21 V",
    )
    assert "  " not in query
    assert query == query.strip()
    assert "21 V" in query


def test_repeated_exact_phrases_are_removed() -> None:
    query = _query(
        "wireless mouse wireless mouse",
        "ratón inalámbrico ergonómico ratón inalámbrico",
    )
    folded = query.casefold()
    assert folded.count("ratón inalámbrico") == 1
    assert "ergonómico" in folded


def test_empty_translated_title_falls_back_to_original() -> None:
    query = _query("Factory Direct 21V Brushless Impact Wrench 800Nm", "   ")
    assert query
    assert "factory direct" not in query.casefold()
    assert "21V" in query.replace(" ", "")
    assert "800Nm" in query.replace(" ", "")


def test_original_only_fallback_when_translation_is_missing() -> None:
    query = _query("Hot Sale 304 Stainless Steel Pump 220V", "")
    assert query
    assert "hot sale" not in query.casefold()
    assert "304" in query
    assert "220V" in query.replace(" ", "")
    assert "Stainless" in query or "stainless" in query.casefold()


def test_blank_inputs_yield_empty_query() -> None:
    assert _query("   ", "") == ""
    assert _query("", "   ") == ""


def test_punctuation_only_translation_falls_back_to_original() -> None:
    query = _query("21V Impact Wrench 800Nm", ";;; :::")
    assert query
    assert "21V" in query.replace(" ", "")
    assert "800Nm" in query.replace(" ", "")
    assert ";" not in query


def test_connector_only_translation_falls_back_to_original() -> None:
    query = _query("304 Stainless Steel Housing", "de y para")
    assert query
    assert "304" in query
    assert "Stainless" in query or "stainless" in query.casefold()
    assert query.casefold() != "de y para"


def test_query_generator_has_no_category_dictionary() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    lowered = source.casefold()
    for hack in (
        'if "mouse"',
        "if 'mouse'",
        'if "pump"',
        'if "leggings"',
        'if "brake pads"',
        'if "ratón"',
        "mouse ->",
        "drill ->",
        "leggings ->",
        "pump ->",
    ):
        assert hack not in lowered
    query = _query(TOOLS_ORIGINAL, TOOLS_TRANSLATED)
    folded = query.casefold()
    assert "ratón" not in folded
    assert "mouse" not in folded
    assert "leggings" not in folded
    assert "mallas" not in folded


def test_query_does_not_infer_price_or_currency() -> None:
    request = ProductTranslationRequest(text="Device $4.03 USD 220V")
    result = ProductTranslationResult(
        original_text=request.text,
        translated_text="Dispositivo $4.03 USD 220V",
        target_language="es",
        provider="fake",
    )
    query = _query(request.text, result.translated_text)
    assert "$" not in query
    assert "USD" not in query.upper().split()
    assert "4.03" not in query
    assert "220V" in query.replace(" ", "")
    for value in (request, result):
        assert not hasattr(value, "price")
        assert not hasattr(value, "currency")
        for field_name in value.__dataclass_fields__:
            assert not isinstance(getattr(value, field_name), Decimal)


def test_query_generation_is_deterministic() -> None:
    first = _query(MOUSE_ORIGINAL, MOUSE_TRANSLATED)
    second = _query(MOUSE_ORIGINAL, MOUSE_TRANSLATED)
    third = ConservativeProductSearchQueryGenerator().generate(
        original_text=MOUSE_ORIGINAL,
        translated_text=MOUSE_TRANSLATED,
    )
    assert first == second == third


def test_generated_query_remains_editable_in_gui() -> None:
    state = TrackerState()
    state.alibaba_results = [AlibabaResultRow(product_id="P-1", title=TOOLS_ORIGINAL, price="$12")]
    state.prepare_ml_comparables_from_alibaba_result("P-1")
    generated = _query(TOOLS_ORIGINAL, TOOLS_TRANSLATED)
    state._finalize_product_translation(
        product_id="P-1",
        title=TOOLS_ORIGINAL,
        generation=state.ml_translation_generation,
        translated_title=TOOLS_TRANSLATED,
        search_query=generated,
    )
    assert state.ml_query == generated
    edited = generated + " extra"
    state.set_ml_query(edited)
    assert state.ml_query == edited
    assert state.ml_query_origin == gui_services.ML_QUERY_ORIGIN_USER
    assert state.ml_is_loading is False
    assert state.ml_results == []


def test_gui_does_not_auto_search_mlv_after_query_generation() -> None:
    translator = FakeProductTranslator(TOOLS_TRANSLATED)
    service = TranslateProductTitle(translator=translator)
    outcome = service.execute(ProductTranslationRequest(text=TOOLS_ORIGINAL))
    state = TrackerState()
    state.alibaba_results = [AlibabaResultRow(product_id="P-1", title=TOOLS_ORIGINAL, price="$12")]
    state.prepare_ml_comparables_from_alibaba_result("P-1")
    state._finalize_product_translation(
        product_id="P-1",
        title=TOOLS_ORIGINAL,
        generation=state.ml_translation_generation,
        translated_title=outcome.translation.translated_text,
        search_query=outcome.search_query,
    )
    assert state.ml_is_loading is False
    assert state.ml_results == []
    assert state.ml_ui_status == "INITIAL"
    assert outcome.translation.translated_text == TOOLS_TRANSLATED


def test_stale_product_a_query_cannot_overwrite_product_b() -> None:
    state = TrackerState()
    state.alibaba_results = [
        AlibabaResultRow(product_id="A", title=MOUSE_ORIGINAL, price="$4"),
        AlibabaResultRow(product_id="B", title=TOOLS_ORIGINAL, price="$5"),
    ]
    state.prepare_ml_comparables_from_alibaba_result("A")
    generation_a = state.ml_translation_generation
    title_a = state.ml_alibaba_context["title"]
    query_a = _query(MOUSE_ORIGINAL, MOUSE_TRANSLATED)
    state.prepare_ml_comparables_from_alibaba_result("B")
    state._finalize_product_translation(
        product_id="A",
        title=title_a,
        generation=generation_a,
        translated_title=MOUSE_TRANSLATED,
        search_query=query_a,
    )
    assert state.ml_alibaba_context["external_id"] == "B"
    assert state.ml_translated_title == ""
    assert state.ml_query == ""
    assert state.ml_query != query_a


def test_tools_fixture_preserves_voltage_and_torque() -> None:
    query = _query(TOOLS_ORIGINAL, TOOLS_TRANSLATED)
    folded = query.casefold()
    assert "factory direct" not in folded
    assert "21 V" in query
    assert "800 Nm" in query


def test_industrial_fixture_preserves_grade_power_and_voltage() -> None:
    query = _query(INDUSTRIAL_ORIGINAL, INDUSTRIAL_TRANSLATED)
    folded = query.casefold()
    assert "high quality" not in folded
    assert "alta calidad" not in folded
    assert "304" in query
    assert "1.5" in query
    assert "1 5" not in query
    assert "220 V" in query or "220V" in query.replace(" ", "")
    assert "kW" in query or "kw" in folded


def test_clothing_fixture_keeps_real_attributes() -> None:
    query = _query(CLOTHING_ORIGINAL, CLOTHING_TRANSLATED)
    folded = query.casefold()
    assert "hot sale" not in folded
    assert "superventas" not in folded
    assert "leggings" in folded
    assert "yoga" in folded
    assert "cintura alta" in folded
    assert "sin costuras" in folded


def test_automotive_fixture_keeps_model_and_brand() -> None:
    query = _query(AUTO_ORIGINAL, AUTO_TRANSLATED)
    folded = query.casefold()
    assert "wholesale" not in folded
    assert "al por mayor" not in folded
    assert "Honda" in query
    assert "CG150" in query
    assert "pastillas" in folded
    assert "freno" in folded


def test_electronics_fixture_keeps_bluetooth_and_usb() -> None:
    query = _query(ELECTRONICS_ORIGINAL, ELECTRONICS_TRANSLATED)
    folded = query.casefold()
    assert "new arrival" not in folded
    assert "nuevo lanzamiento" not in folded
    assert "Bluetooth 5.3" in query
    assert "USB-C" in query
    assert query.endswith("USB-C") or "USB-C" in query


def test_translation_warning_is_still_exposed_by_gui_formatter() -> None:
    validation = validate_technical_tokens(MOUSE_ORIGINAL, MOUSE_TRANSLATED)
    warning = gui_services.format_technical_token_warning(
        validation.missing_tokens,
        [f"{issue.original_token}→{issue.translated_token}" for issue in validation.changed_tokens],
    )
    assert "2.4G" in warning
    assert MOUSE_TRANSLATED == (
        "Ratón de gran éxito de ventas de 2,4 GHz con LED de colores y modo dual, "
        "para oficina, portátil y PC; ratón inalámbrico ergonómico, silencioso, "
        "recargable y para juegos"
    )


def test_technical_tokens_are_not_rewritten_to_other_values() -> None:
    original = "Tool 220V 1.5kW 800Nm M10 304 IP67"
    translated = "Herramienta 220 V 1.5 kW 800 Nm M10 304 IP67"
    query = _query(original, translated)
    compact = _compact(query)
    assert "110v" not in compact
    assert "2kw" not in compact
    assert "600nm" not in compact
    assert "m8" not in compact
    assert "220v" in compact
    assert "1.5kw" in compact
    assert "800nm" in compact
    assert "m10" in compact
    assert "304" in query
    assert "IP67" in query.replace(" ", "")


def test_extract_technical_tokens_keeps_generic_specs() -> None:
    tokens = {
        item.replace(" ", "").casefold()
        for item in extract_technical_tokens(
            "220V 1.5kW 800Nm 2.4GHz 500ml M8 M10 304 316L IP67 USB-C Bluetooth 5.3 Wi-Fi 6 CG150 G102"
        )
    }
    for expected in (
        "220v",
        "1.5kw",
        "800nm",
        "2.4ghz",
        "500ml",
        "m8",
        "m10",
        "304",
        "316l",
        "ip67",
        "usb-c",
        "bluetooth5.3",
        "wi-fi6",
        "cg150",
        "g102",
    ):
        assert expected in tokens
