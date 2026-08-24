"""Offline DeepL Translator HTTP contract. Never contacts DeepL."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from decimal import Decimal
from typing import cast

import httpx
import pytest

from bera_price_tracker.application import (
    InMemoryProductTranslationCache,
    ProductTranslationRequest,
    ProductTranslator,
    TranslateProductTitle,
    validate_technical_tokens,
)
from bera_price_tracker.infrastructure.translation import (
    DeepLProductTranslator,
    DeepLTranslatorHTTPError,
    DeepLTranslatorInvalidResponseError,
    DeepLTranslatorNotConfiguredError,
    DeepLTranslatorQuotaError,
    DeepLTranslatorRateLimitError,
    DeepLTranslatorTimeoutError,
    DeepLTranslatorUnavailableError,
)

_FAKE_KEY = "deepl-test-key-never-print"
type Handler = Callable[[httpx.Request], httpx.Response]


def _deepl_payload(
    text: str = "Hola",
    *,
    detected_source_language: str = "EN",
) -> dict[str, object]:
    return {
        "translations": [
            {
                "detected_source_language": detected_source_language,
                "text": text,
            }
        ]
    }


def _response(
    request: httpx.Request,
    *,
    text: str = "Hola",
    detected_source_language: str = "EN",
    status_code: int = 200,
    payload: object | None = None,
) -> httpx.Response:
    body: object = (
        _deepl_payload(text, detected_source_language=detected_source_language)
        if payload is None
        else payload
    )
    if isinstance(body, (bytes, str)):
        return httpx.Response(status_code, content=body, request=request)
    return httpx.Response(status_code, json=body, request=request)


def _translator(handler: Handler, **kwargs: object) -> tuple[DeepLProductTranslator, httpx.Client]:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    translator = DeepLProductTranslator(
        api_key=cast(str | None, kwargs.get("api_key", _FAKE_KEY)),
        endpoint=cast(str, kwargs.get("endpoint", "https://api-free.deepl.com")),
        timeout_seconds=cast(float, kwargs.get("timeout_seconds", 10.0)),
        client=client,
    )
    return translator, client


def test_adapter_satisfies_product_translator_protocol() -> None:
    translator, client = _translator(lambda request: _response(request))
    with client:
        typed: ProductTranslator = translator
        result = typed.translate(ProductTranslationRequest(text="Hello"))
    assert result.translated_text == "Hola"
    assert result.provider == "deepl"
    assert result.source_language == "en"
    assert result.target_language == "es"
    assert not hasattr(result, "price")
    assert not isinstance(result.translated_text, Decimal)


def test_auto_source_language_omits_source_lang() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(request, text="Hola")

    translator, client = _translator(handler)
    with client:
        translator.translate(ProductTranslationRequest(text="Hello"))
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/v2/translate"
    body = json.loads(requests[0].content)
    assert body["text"] == ["Hello"]
    assert body["target_lang"] == "ES"
    assert "source_lang" not in body
    assert requests[0].headers["Authorization"] == f"DeepL-Auth-Key {_FAKE_KEY}"
    assert "auth_key" not in str(requests[0].url)
    assert _FAKE_KEY not in str(requests[0].url)


def test_explicit_source_language_is_sent() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(request, text="Hola", detected_source_language="ZH")

    translator, client = _translator(handler)
    with client:
        result = translator.translate(ProductTranslationRequest(text="你好", source_language="zh"))
    body = json.loads(requests[0].content)
    assert body["source_lang"] == "ZH"
    assert result.source_language == "zh"


def test_detected_source_language_is_preserved_on_auto() -> None:
    translator, client = _translator(
        lambda request: _response(request, detected_source_language="ZH")
    )
    with client:
        result = translator.translate(ProductTranslationRequest(text="泵"))
    assert result.source_language == "zh"


def test_unicode_round_trip() -> None:
    translator, client = _translator(
        lambda request: _response(request, text="Bomba Café 220V", detected_source_language="ZH")
    )
    with client:
        result = translator.translate(ProductTranslationRequest(text="泵 Café 220V"))
    assert "Café" in result.translated_text
    assert "220V" in result.translated_text


def test_empty_title_does_not_call_deepl() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise AssertionError("DeepL must not be called for an empty title")

    translator, client = _translator(handler)
    with client:
        with pytest.raises(Exception, match="empty"):
            translator.translate(ProductTranslationRequest(text="   "))
    assert requests == []


def test_missing_deepl_config_fails_closed_without_http() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise AssertionError("DeepL must not be called when unconfigured")

    translator, client = _translator(handler, api_key=None)
    with client:
        with pytest.raises(DeepLTranslatorNotConfiguredError, match="BERA_TRACKER_DEEPL_API_KEY"):
            translator.translate(ProductTranslationRequest(text="Hello"))
    assert requests == []
    assert _FAKE_KEY not in repr(translator)
    assert translator.is_configured is False


def test_timeout_is_a_timeout_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    translator, client = _translator(handler)
    with client:
        with pytest.raises(DeepLTranslatorTimeoutError, match="timed out"):
            translator.translate(ProductTranslationRequest(text="Hello"))


def test_connection_failure_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    translator, client = _translator(handler)
    with client:
        with pytest.raises(DeepLTranslatorUnavailableError, match="connection"):
            translator.translate(ProductTranslationRequest(text="Hello"))


@pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 503])
def test_http_error_status_fails_closed(status: int) -> None:
    translator, client = _translator(
        lambda request: _response(request, status_code=status, payload={})
    )
    with client:
        with pytest.raises(DeepLTranslatorHTTPError) as error:
            translator.translate(ProductTranslationRequest(text="Hello"))
    assert error.value.status_code == status
    assert _FAKE_KEY not in str(error.value)
    assert "Authorization" not in str(error.value)


def test_rate_limit_is_explicit() -> None:
    translator, client = _translator(
        lambda request: _response(request, status_code=429, payload={})
    )
    with client:
        with pytest.raises(DeepLTranslatorRateLimitError) as error:
            translator.translate(ProductTranslationRequest(text="Hello"))
    assert error.value.status_code == 429
    assert _FAKE_KEY not in str(error.value)


def test_alternate_rate_limit_529_is_explicit() -> None:
    translator, client = _translator(
        lambda request: _response(request, status_code=529, payload={})
    )
    with client:
        with pytest.raises(DeepLTranslatorRateLimitError) as error:
            translator.translate(ProductTranslationRequest(text="Hello"))
    assert error.value.status_code == 529


def test_quota_limit_456_is_explicit() -> None:
    translator, client = _translator(
        lambda request: _response(request, status_code=456, payload={"message": "Quota exceeded"})
    )
    with client:
        with pytest.raises(DeepLTranslatorQuotaError) as error:
            translator.translate(ProductTranslationRequest(text="Hello"))
    assert error.value.status_code == 456
    assert _FAKE_KEY not in str(error.value)


def test_invalid_json_fails_closed() -> None:
    translator, client = _translator(
        lambda request: _response(request, payload=b"not-json", status_code=200)
    )
    with client:
        with pytest.raises(DeepLTranslatorInvalidResponseError, match="invalid JSON"):
            translator.translate(ProductTranslationRequest(text="Hello"))


def test_empty_translation_fails_closed() -> None:
    translator, client = _translator(lambda request: _response(request, text="   "))
    with client:
        with pytest.raises(DeepLTranslatorInvalidResponseError, match="empty translation"):
            translator.translate(ProductTranslationRequest(text="Hello"))


def test_empty_translations_array_fails_closed() -> None:
    translator, client = _translator(
        lambda request: _response(request, payload={"translations": []})
    )
    with client:
        with pytest.raises(DeepLTranslatorInvalidResponseError, match="no translations"):
            translator.translate(ProductTranslationRequest(text="Hello"))


def test_invalid_payload_shape_fails_closed() -> None:
    translator, client = _translator(lambda request: _response(request, payload={"text": "Hola"}))
    with client:
        with pytest.raises(DeepLTranslatorInvalidResponseError):
            translator.translate(ProductTranslationRequest(text="Hello"))


def test_malformed_translation_item_fails_closed() -> None:
    translator, client = _translator(
        lambda request: _response(request, payload={"translations": ["Hola"]})
    )
    with client:
        with pytest.raises(DeepLTranslatorInvalidResponseError):
            translator.translate(ProductTranslationRequest(text="Hello"))


def test_secrets_are_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    translator, client = _translator(lambda request: _response(request))
    with client:
        translator.translate(ProductTranslationRequest(text="Hello"))
    combined = caplog.text
    assert _FAKE_KEY not in combined
    assert "Authorization" not in combined
    assert "DeepL-Auth-Key" not in combined


def test_repr_does_not_include_key() -> None:
    translator, client = _translator(lambda request: _response(request))
    with client:
        assert _FAKE_KEY not in repr(translator)
        assert translator.endpoint == "https://api-free.deepl.com"


def test_override_endpoint_appends_v2_translate() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(request)

    translator, client = _translator(handler, endpoint="https://api.deepl.com")
    with client:
        translator.translate(ProductTranslationRequest(text="Hello"))
    assert str(requests[0].url).startswith("https://api.deepl.com/v2/translate")
    assert translator.timeout_seconds == 10.0


def test_endpoint_already_containing_translate_is_kept() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(request)

    translator, client = _translator(handler, endpoint="https://api-free.deepl.com/v2/translate")
    with client:
        translator.translate(ProductTranslationRequest(text="Hello"))
    assert requests[0].url.path == "/v2/translate"


def test_non_string_translation_text_fails_closed() -> None:
    translator, client = _translator(
        lambda request: _response(
            request, payload={"translations": [{"text": 1, "detected_source_language": "EN"}]}
        )
    )
    with client:
        with pytest.raises(DeepLTranslatorInvalidResponseError, match="string"):
            translator.translate(ProductTranslationRequest(text="Hello"))


def test_technical_tokens_are_preserved_through_deepl() -> None:
    translator, client = _translator(
        lambda request: _response(
            request,
            text="Llave de impacto 21V 800Nm USB-C Bluetooth 5.3",
        )
    )
    with client:
        result = translator.translate(
            ProductTranslationRequest(text="Impact wrench 21V 800Nm USB-C Bluetooth 5.3")
        )
        outcome = TranslateProductTitle(translator=translator).execute(
            ProductTranslationRequest(text="Impact wrench 21V 800Nm USB-C Bluetooth 5.3")
        )
    assert result.translated_text == "Llave de impacto 21V 800Nm USB-C Bluetooth 5.3"
    assert outcome.is_technically_reliable is True
    validation = validate_technical_tokens(
        "Impact wrench 21V 800Nm USB-C Bluetooth 5.3",
        result.translated_text,
    )
    assert validation.missing_tokens == ()
    assert validation.changed_tokens == ()


def test_technical_token_mutation_is_detected_after_deepl() -> None:
    translator, client = _translator(lambda request: _response(request, text="Bomba 110V M8"))
    with client:
        outcome = TranslateProductTitle(translator=translator).execute(
            ProductTranslationRequest(text="Pump 220V M10")
        )
    assert outcome.is_technically_reliable is False
    changed = {
        issue.original_token: issue.translated_token
        for issue in outcome.technical_tokens.changed_tokens
    }
    assert "220V" in changed
    assert changed["220V"] == "110V"
    assert "M10" in changed
    assert changed["M10"] == "M8"
    assert outcome.translation.translated_text == "Bomba 110V M8"


def test_deepl_cache_avoids_duplicate_http_call() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _response(request, text="Llave de impacto 21V")

    translator, client = _translator(handler)
    cache = InMemoryProductTranslationCache()
    with client:
        first = TranslateProductTitle(translator=translator, cache=cache).execute(
            ProductTranslationRequest(text="Impact wrench 21V")
        )
        second = TranslateProductTitle(translator=translator, cache=cache).execute(
            ProductTranslationRequest(text="Impact wrench 21V")
        )
    assert len(calls) == 1
    assert second.translation.translated_text == first.translation.translated_text
    assert second.translation.provider == "deepl"
