"""Offline product translation, token preservation, and search-query tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from bera_price_tracker.application import (
    ConservativeProductSearchQueryGenerator,
    InMemoryProductTranslationCache,
    ProductSearchQueryGenerator,
    ProductSearchTranslation,
    ProductTranslationEmptyTextError,
    ProductTranslationRequest,
    ProductTranslationResult,
    ProductTranslator,
    TechnicalTokenMismatchError,
    TranslateProductTitle,
    extract_technical_tokens,
    require_non_empty_product_text,
    validate_technical_tokens,
)
from bera_price_tracker.gui import services as gui_services


class FakeProductTranslator:
    def __init__(
        self,
        translated: str,
        *,
        source_language: str | None = "en",
        provider: str = "fake",
    ) -> None:
        self.translated = translated
        self.source_language = source_language
        self.provider = provider
        self.calls: list[ProductTranslationRequest] = []
        self.error: BaseException | None = None

    def translate(self, request: ProductTranslationRequest) -> ProductTranslationResult:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return ProductTranslationResult(
            original_text=request.text,
            translated_text=self.translated,
            source_language=self.source_language,
            target_language=request.target_language,
            provider=self.provider,
        )


def _translate(
    original: str,
    translated: str,
    *,
    cache: InMemoryProductTranslationCache | None = None,
    source_language: str | None = None,
) -> tuple[FakeProductTranslator, ProductSearchTranslation]:
    translator = FakeProductTranslator(translated, source_language="en")
    service = TranslateProductTitle(translator=translator, cache=cache)
    outcome = service.execute(
        ProductTranslationRequest(text=original, source_language=source_language)
    )
    return translator, outcome


def test_translation_success_returns_spanish_text() -> None:
    _translator, outcome = _translate(
        "Factory Direct 21V Brushless Cordless Impact Wrench 800Nm",
        "Llave de impacto inalámbrica sin escobillas 21V 800Nm",
    )
    assert outcome.translation.translated_text == (
        "Llave de impacto inalámbrica sin escobillas 21V 800Nm"
    )
    assert outcome.translation.target_language == "es"
    assert outcome.translation.provider == "fake"
    assert "Factory Direct" not in outcome.search_query


def test_automatic_source_language_is_omitted_on_the_request() -> None:
    translator, outcome = _translate(
        "Women's High Waist Seamless Yoga Leggings",
        "Leggings de yoga para mujer de cintura alta sin costuras",
    )
    assert translator.calls[0].source_language is None
    assert outcome.translation.source_language == "en"


def test_unicode_titles_are_translated_without_change_to_specs() -> None:
    original = "Bomba Café 220V 不锈钢 1.5kW"
    translated = "Bomba Café 220V acero inoxidable 1.5kW"
    _translator, outcome = _translate(original, translated)
    assert "Café" in outcome.translation.translated_text
    assert "220V" in outcome.translation.translated_text
    assert "1.5kW" in outcome.translation.translated_text
    assert outcome.is_technically_reliable is True


def test_empty_title_fails_before_translator() -> None:
    translator = FakeProductTranslator("no")
    with pytest.raises(ProductTranslationEmptyTextError, match="empty"):
        TranslateProductTitle(translator=translator).execute(ProductTranslationRequest(text="   "))
    assert translator.calls == []
    with pytest.raises(ProductTranslationEmptyTextError):
        require_non_empty_product_text("")


@pytest.mark.parametrize(
    ("original", "token"),
    [
        ("Impact Wrench 220V brushless", "220V"),
        ("Centrifugal Pump 1.5kW 220V", "1.5kW"),
        ("Cordless Impact Wrench 800Nm", "800Nm"),
        ("Hex Bolt M10 stainless", "M10"),
        ("Stainless Steel 316L pump", "316L"),
        ("Outdoor Light IP67 housing", "IP67"),
        ("Fast Charge USB-C cable", "USB-C"),
        ("Mouse Bluetooth 5.3 receiver", "Bluetooth 5.3"),
        ("Replacement carburetor CG150", "CG150"),
        ("Gaming mouse G102 12000 DPI", "G102"),
    ],
)
def test_technical_token_is_preserved(original: str, token: str) -> None:
    translated = f"Producto traducido {original}"
    _translator, outcome = _translate(original, translated)
    normalized_tokens = {
        item.casefold().replace(" ", "")
        for item in extract_technical_tokens(outcome.translation.translated_text)
    }
    assert token.casefold().replace(" ", "") in normalized_tokens
    assert outcome.is_technically_reliable is True
    assert token.replace(" ", "").casefold() in outcome.search_query.replace(" ", "").casefold()


def test_lost_technical_token_is_deterministic_warning() -> None:
    original = "Self Priming Pump 220V 1.5kW"
    translated = "Bomba autocebante 1.5kW"
    _translator, outcome = _translate(original, translated)
    assert outcome.is_technically_reliable is False
    assert "220V" in outcome.technical_tokens.missing_tokens
    with pytest.raises(TechnicalTokenMismatchError, match="220V"):
        from bera_price_tracker.application.product_translation import (
            require_reliable_technical_tokens,
        )

        require_reliable_technical_tokens(
            outcome.technical_tokens, outcome.translation.translated_text
        )
    warning = gui_services.format_technical_token_warning(
        outcome.technical_tokens.missing_tokens,
        [
            f"{issue.original_token}→{issue.translated_token}"
            for issue in outcome.technical_tokens.changed_tokens
        ],
    )
    assert "220V" in warning
    assert outcome.translation.translated_text == translated


def test_changed_technical_token_is_deterministic_warning() -> None:
    validation = validate_technical_tokens(
        "Centrifugal Pump 220V 1.5kW",
        "Bomba centrífuga 110V 1.5kW",
    )
    assert validation.is_reliable is False
    assert validation.changed_tokens
    assert validation.changed_tokens[0].original_token == "220V"
    assert validation.changed_tokens[0].translated_token == "110V"


@pytest.mark.parametrize(
    ("original", "translated"),
    [
        ("Impact Wrench 21V", "Llave de impacto 21 V"),
        ("Impact Wrench 800Nm", "Llave de impacto 800 Nm"),
        ("Centrifugal Pump 1.5kW", "Bomba centrífuga 1.5 kW"),
        ("Bottle 500ml", "Botella 500 ml"),
        ("Wireless Mouse 2.4GHz", "Ratón inalámbrico 2.4 GHz"),
        (
            "21V Brushless Cordless Impact Wrench 800Nm",
            "Llave de impacto inalámbrica sin escobillas de 21 V, 800 Nm",
        ),
    ],
)
def test_number_unit_spacing_is_technically_equivalent(original: str, translated: str) -> None:
    validation = validate_technical_tokens(original, translated)
    assert validation.is_reliable is True
    assert validation.missing_tokens == ()
    assert validation.changed_tokens == ()
    _translator, outcome = _translate(original, translated)
    assert outcome.translation.translated_text == translated
    assert outcome.is_technically_reliable is True


@pytest.mark.parametrize(
    ("original", "translated", "original_token"),
    [
        ("Tool 21V", "Herramienta 18 V", "21V"),
        ("Tool 800Nm", "Herramienta 600 Nm", "800Nm"),
        ("Pump 1.5kW", "Bomba 2 kW", "1.5kW"),
        ("Bottle 500ml", "Botella 750 ml", "500ml"),
        ("Mouse 2.4GHz", "Ratón 5 GHz", "2.4GHz"),
    ],
)
def test_number_unit_value_change_is_not_equivalent(
    original: str, translated: str, original_token: str
) -> None:
    validation = validate_technical_tokens(original, translated)
    assert validation.is_reliable is False
    assert original_token in (
        validation.missing_tokens
        + tuple(issue.original_token for issue in validation.changed_tokens)
    )
    _translator, outcome = _translate(original, translated)
    assert outcome.translation.translated_text == translated
    assert outcome.is_technically_reliable is False


def test_deepl_spaced_units_keep_translation_and_query_intact() -> None:
    original = "21V Brushless Cordless Impact Wrench 800Nm"
    translated = "Llave de impacto inalámbrica sin escobillas de 21 V, 800 Nm"
    _translator, outcome = _translate(original, translated)
    assert outcome.translation.translated_text == translated
    assert outcome.is_technically_reliable is True
    assert "21 V" in outcome.search_query
    assert "800 Nm" in outcome.search_query


def test_translation_models_have_no_currency_or_price_authority() -> None:
    request = ProductTranslationRequest(text="Mouse $4.03 USD 220V")
    result = ProductTranslationResult(
        original_text=request.text,
        translated_text="Ratón $4.03 USD 220V",
        target_language="es",
        provider="fake",
    )
    for value in (request, result):
        assert not hasattr(value, "price")
        assert not hasattr(value, "currency")
        assert not hasattr(value, "moq")
        for field_name in value.__dataclass_fields__:
            assert not isinstance(getattr(value, field_name), Decimal)
    query = ConservativeProductSearchQueryGenerator().generate(
        original_text=request.text,
        translated_text=result.translated_text,
    )
    assert "USD" not in query.upper().split()
    assert "$" not in query
    assert "4.03" not in query
    assert "220V" in query.replace(" ", "")


def test_generated_search_query_is_conservative_and_editable() -> None:
    generator: ProductSearchQueryGenerator = ConservativeProductSearchQueryGenerator()
    query = generator.generate(
        original_text="Factory Direct 21V Brushless Cordless Impact Wrench 800Nm OEM",
        translated_text="Factory Direct llave de impacto inalámbrica sin escobillas 21V 800Nm OEM",
    )
    assert "factory direct" not in query.casefold()
    assert "oem" not in query.casefold()
    assert "21V" in query.replace(" ", "")
    assert "800Nm" in query.replace(" ", "")
    edited = query + " gamer"
    assert edited != query
    assert edited.endswith("gamer")


def test_search_query_does_not_invent_product_attributes() -> None:
    query = ConservativeProductSearchQueryGenerator().generate(
        original_text="304 Stainless Steel Self Priming Centrifugal Pump 1.5kW 220V",
        translated_text="Bomba centrífuga autocebante de acero inoxidable 304 1.5kW 220V",
    )
    assert "ratón" not in query.casefold()
    assert "taladro" not in query.casefold()
    assert "304" in query
    assert "1.5kW" in query.replace(" ", "")
    assert "220V" in query.replace(" ", "")


def test_cache_avoids_duplicate_translation_within_session() -> None:
    cache = InMemoryProductTranslationCache()
    translator, first = _translate(
        "Wireless mouse G102",
        "Ratón inalámbrico G102",
        cache=cache,
    )
    second_translator = FakeProductTranslator("IGNORED")
    second = TranslateProductTitle(translator=second_translator, cache=cache).execute(
        ProductTranslationRequest(text="Wireless mouse G102")
    )
    assert len(translator.calls) == 1
    assert second_translator.calls == []
    assert second.translation.translated_text == first.translation.translated_text
    assert len(cache) == 1


def test_cache_does_not_reuse_results_across_providers() -> None:
    cache = InMemoryProductTranslationCache()
    azure = FakeProductTranslator("Traducción Azure", provider="azure")
    TranslateProductTitle(translator=azure, cache=cache).execute(
        ProductTranslationRequest(text="Wireless mouse G102")
    )
    deepl = FakeProductTranslator("Traducción DeepL", provider="deepl")
    second = TranslateProductTitle(translator=deepl, cache=cache).execute(
        ProductTranslationRequest(text="Wireless mouse G102")
    )
    assert len(azure.calls) == 1
    assert len(deepl.calls) == 1
    assert second.translation.translated_text == "Traducción DeepL"
    assert second.translation.provider == "deepl"
    assert len(cache) == 2


def test_fake_translator_satisfies_port() -> None:
    translator: ProductTranslator = FakeProductTranslator("Hola")
    result = translator.translate(ProductTranslationRequest(text="Hello"))
    assert result.translated_text == "Hola"


def test_request_auto_source_language_normalizes_auto() -> None:
    request = ProductTranslationRequest(text="Hello", source_language="auto")
    assert request.source_language is None
    assert request.target_language == "es"
    assert request.target_market == "VE"


def test_sanitize_translation_errors_never_include_secrets() -> None:
    from bera_price_tracker.application.ports import (
        ProductTranslationEmptyTextError,
        ProductTranslatorHTTPError,
        ProductTranslatorInvalidResponseError,
        ProductTranslatorNotConfiguredError,
        ProductTranslatorQuotaError,
        ProductTranslatorRateLimitError,
        ProductTranslatorTimeoutError,
        ProductTranslatorUnavailableError,
    )

    secret = "azure-test-key-never-print"
    cases = [
        ProductTranslatorNotConfiguredError(f"missing {secret}"),
        ProductTranslationEmptyTextError("empty"),
        ProductTranslatorTimeoutError(f"timeout {secret}"),
        ProductTranslatorRateLimitError(),
        ProductTranslatorQuotaError(),
        ProductTranslatorHTTPError(500, f"boom {secret}"),
        ProductTranslatorInvalidResponseError(f"bad {secret}"),
        ProductTranslatorUnavailableError(f"down {secret}"),
        RuntimeError(f"unexpected {secret}"),
    ]
    for error in cases:
        message = gui_services.sanitize_translation_error(error)
        assert secret not in message
        assert "Traceback" not in message
        assert message


def test_build_product_translator_fails_closed_without_http() -> None:
    from bera_price_tracker.composition import (
        build_product_title_translator,
        build_product_translator,
    )
    from bera_price_tracker.config import Settings
    from bera_price_tracker.infrastructure.translation import DisabledTranslatorNotConfiguredError

    translator = build_product_translator(Settings())
    with pytest.raises(DisabledTranslatorNotConfiguredError):
        translator.translate(ProductTranslationRequest(text="Hello"))
    service = build_product_title_translator(Settings())
    with pytest.raises(DisabledTranslatorNotConfiguredError):
        service.execute(ProductTranslationRequest(text="Hello"))
