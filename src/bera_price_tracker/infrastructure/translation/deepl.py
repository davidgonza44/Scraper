"""DeepL Translator adapter for generic product-title translation."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, NoReturn, cast

import httpx

from bera_price_tracker import __version__
from bera_price_tracker.application.ports import (
    ProductTranslationEmptyTextError,
    ProductTranslatorHTTPError,
    ProductTranslatorInvalidResponseError,
    ProductTranslatorNotConfiguredError,
    ProductTranslatorQuotaError,
    ProductTranslatorTimeoutError,
    ProductTranslatorUnavailableError,
)
from bera_price_tracker.application.product_translation import (
    DEEPL_TRANSLATOR_PROVIDER,
    ProductTranslationRequest,
    ProductTranslationResult,
    require_non_empty_product_text,
)
from bera_price_tracker.config import (
    DEFAULT_DEEPL_API_ENDPOINT,
    DEFAULT_DEEPL_TIMEOUT_SECONDS,
    deepl_translator_is_configured,
    normalize_deepl_api_endpoint,
    normalize_deepl_timeout_seconds,
)

_logger = logging.getLogger(__name__)
_NOT_CONFIGURED_MESSAGE = "DeepL Translator is not configured. Set BERA_TRACKER_DEEPL_API_KEY."
_TRANSLATE_SUFFIXES = ("/v2/translate", "/translate")


class DeepLTranslatorNotConfiguredError(ProductTranslatorNotConfiguredError):
    """Raised when the DeepL API key is missing locally."""


class DeepLTranslatorTimeoutError(ProductTranslatorTimeoutError):
    """Raised when the DeepL request exceeds its timeout."""


class DeepLTranslatorUnavailableError(ProductTranslatorUnavailableError):
    """Raised when DeepL cannot be reached."""


class DeepLTranslatorHTTPError(ProductTranslatorHTTPError):
    """Raised for a non-success DeepL HTTP status."""


class DeepLTranslatorRateLimitError(DeepLTranslatorHTTPError):
    """Raised when DeepL returns HTTP 429 or 529."""

    def __init__(self, status_code: int = 429) -> None:
        super().__init__(status_code, "DeepL Translator rate limit was reached")


class DeepLTranslatorQuotaError(ProductTranslatorQuotaError):
    """Raised when DeepL returns HTTP 456 quota exceeded."""

    def __init__(self) -> None:
        super().__init__(456)


class DeepLTranslatorInvalidResponseError(ProductTranslatorInvalidResponseError):
    """Raised when DeepL JSON cannot satisfy the contract."""


def _reject_json_constant(value: str) -> NoReturn:
    raise ValueError(f"non-standard JSON constant is not allowed: {value}")


def _strict_json_loads(value: str | bytes) -> object:
    try:
        return json.loads(value, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, RecursionError, UnicodeDecodeError, TypeError, ValueError):
        raise DeepLTranslatorInvalidResponseError(
            "DeepL Translator returned invalid JSON"
        ) from None


def _translate_url(endpoint: str) -> str:
    base = endpoint.rstrip("/")
    if any(base.endswith(suffix) for suffix in _TRANSLATE_SUFFIXES):
        return base
    return f"{base}/v2/translate"


class DeepLProductTranslator:
    """Translate product text through DeepL text translation. No money fields."""

    provider = DEEPL_TRANSLATOR_PROVIDER

    def __init__(
        self,
        *,
        api_key: str | None,
        endpoint: str = DEFAULT_DEEPL_API_ENDPOINT,
        timeout_seconds: float = DEFAULT_DEEPL_TIMEOUT_SECONDS,
        client: httpx.Client | None = None,
    ) -> None:
        key = None if api_key is None else api_key.strip() or None
        self._api_key = key
        self._endpoint = normalize_deepl_api_endpoint(endpoint)
        self._timeout_seconds = normalize_deepl_timeout_seconds(timeout_seconds)
        self._timeout = httpx.Timeout(self._timeout_seconds)
        self._client = client
        self._url = _translate_url(self._endpoint)

    def __repr__(self) -> str:
        return (
            f"DeepLProductTranslator(endpoint={self._endpoint!r}, configured={self.is_configured})"
        )

    @property
    def is_configured(self) -> bool:
        return deepl_translator_is_configured(api_key=self._api_key)

    @property
    def endpoint(self) -> str:
        return self._endpoint

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    def translate(self, request: ProductTranslationRequest) -> ProductTranslationResult:
        if not isinstance(request, ProductTranslationRequest):
            raise TypeError("request must be a ProductTranslationRequest")
        text = require_non_empty_product_text(request.text)
        if not self.is_configured or self._api_key is None:
            raise DeepLTranslatorNotConfiguredError(_NOT_CONFIGURED_MESSAGE)

        payload: dict[str, object] = {
            "text": [text],
            "target_lang": request.target_language.upper(),
        }
        if request.source_language is not None:
            payload["source_lang"] = request.source_language.upper()

        started_at = time.perf_counter()
        _logger.info(
            "provider=deepl_translator target=%s auto_source=%s started",
            request.target_language,
            request.source_language is None,
        )
        try:
            response = self._execute_once(payload)
            self._validate_http_status(response)
            translated_text, detected = _parse_deepl_translation(response)
        except (
            DeepLTranslatorTimeoutError,
            DeepLTranslatorUnavailableError,
            DeepLTranslatorHTTPError,
            DeepLTranslatorQuotaError,
            DeepLTranslatorInvalidResponseError,
            ProductTranslationEmptyTextError,
        ) as error:
            _logger.warning(
                "provider=deepl_translator outcome=failure error_type=%s duration_seconds=%.3f",
                type(error).__name__,
                time.perf_counter() - started_at,
            )
            raise

        _logger.info(
            "provider=deepl_translator outcome=success duration_seconds=%.3f",
            time.perf_counter() - started_at,
        )
        return ProductTranslationResult(
            original_text=text,
            translated_text=translated_text,
            source_language=detected
            if request.source_language is None
            else request.source_language,
            target_language=request.target_language,
            provider=DEEPL_TRANSLATOR_PROVIDER,
        )

    def _headers(self) -> dict[str, str]:
        assert self._api_key is not None
        return {
            "Accept": "application/json",
            "Authorization": f"DeepL-Auth-Key {self._api_key}",
            "Content-Type": "application/json",
            "User-Agent": f"bera-price-tracker/{__version__}",
        }

    def _execute_once(self, payload: dict[str, object]) -> httpx.Response:
        if self._client is not None:
            return self._post(self._client, payload)
        transport = httpx.HTTPTransport(retries=0)
        with httpx.Client(
            transport=transport,
            timeout=self._timeout,
            trust_env=False,
        ) as client:
            return self._post(client, payload)

    def _post(self, client: httpx.Client, payload: dict[str, object]) -> httpx.Response:
        try:
            return client.post(
                self._url,
                headers=self._headers(),
                json=payload,
                timeout=self._timeout,
            )
        except httpx.TimeoutException:
            raise DeepLTranslatorTimeoutError("DeepL Translator request timed out") from None
        except httpx.TransportError:
            raise DeepLTranslatorUnavailableError("DeepL Translator connection failed") from None

    def _validate_http_status(self, response: httpx.Response) -> None:
        status = response.status_code
        if status == 200:
            return
        if status in {429, 529}:
            raise DeepLTranslatorRateLimitError(status)
        if status == 456:
            raise DeepLTranslatorQuotaError()
        if 400 <= status <= 499 or 500 <= status <= 599:
            raise DeepLTranslatorHTTPError(
                status, f"DeepL Translator request failed with HTTP {status}"
            )
        raise DeepLTranslatorHTTPError(
            status, f"DeepL Translator request failed with HTTP {status}"
        )


def _parse_deepl_translation(response: httpx.Response) -> tuple[str, str | None]:
    payload = _strict_json_loads(response.content)
    if not isinstance(payload, dict):
        raise DeepLTranslatorInvalidResponseError("DeepL Translator returned an invalid payload")
    body = cast(dict[str, Any], payload)
    translations = body.get("translations")
    if not isinstance(translations, list):
        raise DeepLTranslatorInvalidResponseError("DeepL Translator returned an invalid payload")
    if not translations:
        raise DeepLTranslatorInvalidResponseError("DeepL Translator returned no translations")
    first_translation = translations[0]
    if not isinstance(first_translation, dict):
        raise DeepLTranslatorInvalidResponseError(
            "DeepL Translator returned an invalid translation"
        )
    text = first_translation.get("text")
    if not isinstance(text, str):
        raise DeepLTranslatorInvalidResponseError(
            "DeepL Translator translation text must be a string"
        )
    translated = text.strip()
    if not translated:
        raise DeepLTranslatorInvalidResponseError("DeepL Translator returned an empty translation")
    detected: str | None = None
    detected_language = first_translation.get("detected_source_language")
    if isinstance(detected_language, str) and detected_language.strip():
        detected = detected_language.strip().casefold()
    return translated, detected
