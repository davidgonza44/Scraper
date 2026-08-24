"""Offline Azure Translator HTTP contract. Never contacts Azure."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import cast

import httpx
import pytest

from bera_price_tracker.application import (
    ProductTranslationRequest,
    ProductTranslator,
)
from bera_price_tracker.infrastructure.translation import (
    AzureProductTranslator,
    AzureTranslatorHTTPError,
    AzureTranslatorInvalidResponseError,
    AzureTranslatorNotConfiguredError,
    AzureTranslatorRateLimitError,
    AzureTranslatorTimeoutError,
    AzureTranslatorUnavailableError,
)

_FAKE_KEY = "azure-test-key-never-print"
type Handler = Callable[[httpx.Request], httpx.Response]


def _azure_payload(
    text: str = "Hola",
    *,
    language: str = "en",
) -> list[dict[str, object]]:
    return [
        {
            "detectedLanguage": {"language": language, "score": 1.0},
            "translations": [{"text": text, "to": "es"}],
        }
    ]


def _response(
    request: httpx.Request,
    *,
    text: str = "Hola",
    language: str = "en",
    status_code: int = 200,
    payload: object | None = None,
) -> httpx.Response:
    body: object = _azure_payload(text, language=language) if payload is None else payload
    if isinstance(body, (bytes, str)):
        return httpx.Response(status_code, content=body, request=request)
    return httpx.Response(status_code, json=body, request=request)


def _translator(handler: Handler, **kwargs: object) -> tuple[AzureProductTranslator, httpx.Client]:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    translator = AzureProductTranslator(
        api_key=cast(str, kwargs.get("api_key", _FAKE_KEY)),
        endpoint=cast(str, kwargs.get("endpoint", "https://api.cognitive.microsofttranslator.com")),
        region=cast(str | None, kwargs.get("region")),
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
    assert result.provider == "azure"
    assert result.source_language == "en"
    assert result.target_language == "es"


def test_auto_source_language_omits_from_parameter() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(request, text="Hola")

    translator, client = _translator(handler)
    with client:
        translator.translate(ProductTranslationRequest(text="Hello"))
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/translate"
    assert requests[0].url.params["api-version"] == "3.0"
    assert requests[0].url.params["to"] == "es"
    assert "from" not in requests[0].url.params
    body = json.loads(requests[0].content)
    assert body == [{"Text": "Hello"}]
    assert requests[0].headers["Ocp-Apim-Subscription-Key"] == _FAKE_KEY


def test_explicit_source_language_is_sent() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(request, text="Hola", language="zh-Hans")

    translator, client = _translator(handler)
    with client:
        result = translator.translate(
            ProductTranslationRequest(text="你好", source_language="zh-Hans")
        )
    assert requests[0].url.params["from"] == "zh-hans"
    assert result.source_language == "zh-hans"


def test_unicode_round_trip() -> None:
    translator, client = _translator(
        lambda request: _response(request, text="Bomba Café 220V", language="zh-Hans")
    )
    with client:
        result = translator.translate(ProductTranslationRequest(text="泵 Café 220V"))
    assert "Café" in result.translated_text
    assert "220V" in result.translated_text


def test_empty_title_does_not_call_azure() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise AssertionError("Azure must not be called for an empty title")

    translator, client = _translator(handler)
    with client:
        with pytest.raises(Exception, match="empty"):
            translator.translate(ProductTranslationRequest(text="   "))
    assert requests == []


def test_missing_azure_config_fails_closed_without_http() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise AssertionError("Azure must not be called when unconfigured")

    translator, client = _translator(handler, api_key=None)
    with client:
        with pytest.raises(
            AzureTranslatorNotConfiguredError, match="BERA_TRACKER_AZURE_TRANSLATOR_KEY"
        ):
            translator.translate(ProductTranslationRequest(text="Hello"))
    assert requests == []
    assert _FAKE_KEY not in repr(translator)
    assert translator.is_configured is False


def test_timeout_is_a_timeout_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    translator, client = _translator(handler)
    with client:
        with pytest.raises(AzureTranslatorTimeoutError, match="timed out"):
            translator.translate(ProductTranslationRequest(text="Hello"))


def test_connection_failure_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    translator, client = _translator(handler)
    with client:
        with pytest.raises(AzureTranslatorUnavailableError, match="connection"):
            translator.translate(ProductTranslationRequest(text="Hello"))


@pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 503])
def test_http_error_status_fails_closed(status: int) -> None:
    translator, client = _translator(
        lambda request: _response(request, status_code=status, payload={})
    )
    with client:
        with pytest.raises(AzureTranslatorHTTPError) as error:
            translator.translate(ProductTranslationRequest(text="Hello"))
    assert error.value.status_code == status
    assert _FAKE_KEY not in str(error.value)


def test_rate_limit_is_explicit() -> None:
    translator, client = _translator(
        lambda request: _response(request, status_code=429, payload={})
    )
    with client:
        with pytest.raises(AzureTranslatorRateLimitError):
            translator.translate(ProductTranslationRequest(text="Hello"))


def test_invalid_json_fails_closed() -> None:
    translator, client = _translator(
        lambda request: _response(request, payload=b"not-json", status_code=200)
    )
    with client:
        with pytest.raises(AzureTranslatorInvalidResponseError, match="invalid JSON"):
            translator.translate(ProductTranslationRequest(text="Hello"))


def test_empty_translation_fails_closed() -> None:
    translator, client = _translator(lambda request: _response(request, text="   "))
    with client:
        with pytest.raises(AzureTranslatorInvalidResponseError, match="empty translation"):
            translator.translate(ProductTranslationRequest(text="Hello"))


def test_invalid_payload_shape_fails_closed() -> None:
    translator, client = _translator(lambda request: _response(request, payload={"text": "Hola"}))
    with client:
        with pytest.raises(AzureTranslatorInvalidResponseError):
            translator.translate(ProductTranslationRequest(text="Hello"))


def test_secrets_are_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    translator, client = _translator(lambda request: _response(request))
    with client:
        translator.translate(ProductTranslationRequest(text="Hello"))
    combined = caplog.text
    assert _FAKE_KEY not in combined
    assert "Ocp-Apim-Subscription-Key" not in combined


def test_repr_does_not_include_key() -> None:
    translator, client = _translator(lambda request: _response(request), region="eastus")
    with client:
        assert _FAKE_KEY not in repr(translator)
        assert translator.region == "eastus"
