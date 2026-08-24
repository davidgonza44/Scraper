"""Offline translator provider selection. Never contacts DeepL or Azure."""

from __future__ import annotations

import httpx
import pytest

from bera_price_tracker.application import ProductTranslationRequest
from bera_price_tracker.composition import build_product_translator
from bera_price_tracker.config import (
    TRANSLATOR_PROVIDER_AZURE,
    TRANSLATOR_PROVIDER_DEEPL,
    TRANSLATOR_PROVIDER_DISABLED,
    Settings,
)
from bera_price_tracker.infrastructure.translation import (
    AzureProductTranslator,
    AzureTranslatorNotConfiguredError,
    DeepLProductTranslator,
    DeepLTranslatorNotConfiguredError,
    DisabledProductTranslator,
    DisabledTranslatorNotConfiguredError,
)


def test_provider_deepl_selects_deepl() -> None:
    translator = build_product_translator(
        Settings(translator_provider="deepl", deepl_api_key="deepl-test-key-never-print")
    )
    assert isinstance(translator, DeepLProductTranslator)
    assert translator.provider == TRANSLATOR_PROVIDER_DEEPL


def test_provider_azure_selects_azure() -> None:
    translator = build_product_translator(
        Settings(translator_provider="azure", azure_translator_key="azure-test-key-never-print")
    )
    assert isinstance(translator, AzureProductTranslator)
    assert translator.provider == TRANSLATOR_PROVIDER_AZURE


def test_provider_disabled_selects_no_translator() -> None:
    translator = build_product_translator(
        Settings(
            translator_provider="disabled",
            deepl_api_key="deepl-test-key-never-print",
            azure_translator_key="azure-test-key-never-print",
        )
    )
    assert isinstance(translator, DisabledProductTranslator)
    with pytest.raises(DisabledTranslatorNotConfiguredError, match="disabled"):
        translator.translate(ProductTranslationRequest(text="Hello"))


def test_invalid_provider_fails_closed() -> None:
    with pytest.raises(ValueError, match="translator_provider"):
        Settings.from_env({"BERA_TRACKER_TRANSLATOR_PROVIDER": "google"})
    with pytest.raises(ValueError, match="translator_provider"):
        Settings(translator_provider=" openai ")


def test_provider_is_normalized_for_case_and_whitespace() -> None:
    settings = Settings.from_env({"BERA_TRACKER_TRANSLATOR_PROVIDER": " DeepL "})
    assert settings.translator_provider == TRANSLATOR_PROVIDER_DEEPL
    assert settings.resolved_translator_provider() == TRANSLATOR_PROVIDER_DEEPL


def test_unset_provider_keeps_azure_when_azure_is_configured() -> None:
    settings = Settings(azure_translator_key="azure-test-key-never-print")
    assert settings.translator_provider is None
    assert settings.resolved_translator_provider() == TRANSLATOR_PROVIDER_AZURE
    translator = build_product_translator(settings)
    assert isinstance(translator, AzureProductTranslator)


def test_unset_provider_stays_disabled_even_if_deepl_key_is_present() -> None:
    settings = Settings(deepl_api_key="deepl-test-key-never-print")
    assert settings.resolved_translator_provider() == TRANSLATOR_PROVIDER_DISABLED
    translator = build_product_translator(settings)
    assert isinstance(translator, DisabledProductTranslator)


def test_no_automatic_fallback_from_deepl_to_azure() -> None:
    azure_calls: list[httpx.Request] = []

    def azure_handler(request: httpx.Request) -> httpx.Response:
        azure_calls.append(request)
        raise AssertionError("Azure must not be called when provider is deepl")

    settings = Settings(
        translator_provider="deepl",
        deepl_api_key=None,
        azure_translator_key="azure-test-key-never-print",
    )
    translator = build_product_translator(
        settings, client=httpx.Client(transport=httpx.MockTransport(azure_handler))
    )
    assert isinstance(translator, DeepLProductTranslator)
    with pytest.raises(DeepLTranslatorNotConfiguredError):
        translator.translate(ProductTranslationRequest(text="Hello"))
    assert azure_calls == []


def test_no_automatic_fallback_from_azure_to_deepl() -> None:
    deepl_calls: list[httpx.Request] = []

    def deepl_handler(request: httpx.Request) -> httpx.Response:
        deepl_calls.append(request)
        raise AssertionError("DeepL must not be called when provider is azure")

    settings = Settings(
        translator_provider="azure",
        azure_translator_key=None,
        deepl_api_key="deepl-test-key-never-print",
    )
    translator = build_product_translator(
        settings, client=httpx.Client(transport=httpx.MockTransport(deepl_handler))
    )
    assert isinstance(translator, AzureProductTranslator)
    with pytest.raises(AzureTranslatorNotConfiguredError):
        translator.translate(ProductTranslationRequest(text="Hello"))
    assert deepl_calls == []


def test_disabled_provider_does_not_call_http() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise AssertionError("disabled translator must not perform HTTP")

    translator = build_product_translator(
        Settings(translator_provider="disabled"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert isinstance(translator, DisabledProductTranslator)
    with pytest.raises(DisabledTranslatorNotConfiguredError):
        translator.translate(ProductTranslationRequest(text="Hello"))
    assert calls == []
    assert translator.is_configured is False
    assert "DisabledProductTranslator" in repr(translator)
    with pytest.raises(TypeError, match="ProductTranslationRequest"):
        translator.translate("Hello")  # type: ignore[arg-type]
