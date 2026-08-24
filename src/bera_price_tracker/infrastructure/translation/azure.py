"""Azure Translator adapter for generic product-title translation."""

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
    ProductTranslatorTimeoutError,
    ProductTranslatorUnavailableError,
)
from bera_price_tracker.application.product_translation import (
    AZURE_TRANSLATOR_PROVIDER,
    ProductTranslationRequest,
    ProductTranslationResult,
    require_non_empty_product_text,
)
from bera_price_tracker.config import (
    DEFAULT_AZURE_TRANSLATOR_ENDPOINT,
    DEFAULT_AZURE_TRANSLATOR_TIMEOUT_SECONDS,
    azure_translator_is_configured,
    normalize_azure_translator_endpoint,
    normalize_azure_translator_timeout_seconds,
)

_logger = logging.getLogger(__name__)
_AZURE_API_VERSION = "3.0"
_NOT_CONFIGURED_MESSAGE = (
    "Azure Translator is not configured. Set BERA_TRACKER_AZURE_TRANSLATOR_KEY."
)


class AzureTranslatorNotConfiguredError(ProductTranslatorNotConfiguredError):
    """Raised when the Azure Translator key is missing locally."""


class AzureTranslatorTimeoutError(ProductTranslatorTimeoutError):
    """Raised when the Azure Translator request exceeds its timeout."""


class AzureTranslatorUnavailableError(ProductTranslatorUnavailableError):
    """Raised when Azure Translator cannot be reached."""


class AzureTranslatorHTTPError(ProductTranslatorHTTPError):
    """Raised for a non-success Azure Translator HTTP status."""


class AzureTranslatorRateLimitError(AzureTranslatorHTTPError):
    """Raised when Azure Translator returns HTTP 429."""

    def __init__(self) -> None:
        super().__init__(429, "Azure Translator rate limit was reached")


class AzureTranslatorInvalidResponseError(ProductTranslatorInvalidResponseError):
    """Raised when Azure Translator JSON cannot satisfy the contract."""


def _reject_json_constant(value: str) -> NoReturn:
    raise ValueError(f"non-standard JSON constant is not allowed: {value}")


def _strict_json_loads(value: str | bytes) -> object:
    try:
        return json.loads(value, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, RecursionError, UnicodeDecodeError, TypeError, ValueError):
        raise AzureTranslatorInvalidResponseError(
            "Azure Translator returned invalid JSON"
        ) from None


class AzureProductTranslator:
    """Translate product text through Azure Translator Text. No money fields."""

    provider = AZURE_TRANSLATOR_PROVIDER

    def __init__(
        self,
        *,
        api_key: str | None,
        endpoint: str = DEFAULT_AZURE_TRANSLATOR_ENDPOINT,
        region: str | None = None,
        timeout_seconds: float = DEFAULT_AZURE_TRANSLATOR_TIMEOUT_SECONDS,
        client: httpx.Client | None = None,
    ) -> None:
        key = None if api_key is None else api_key.strip() or None
        self._api_key = key
        self._endpoint = normalize_azure_translator_endpoint(endpoint)
        self._region = None if region is None else region.strip() or None
        self._timeout_seconds = normalize_azure_translator_timeout_seconds(timeout_seconds)
        self._timeout = httpx.Timeout(self._timeout_seconds)
        self._client = client
        base = self._endpoint.rstrip("/")
        self._url = base if base.endswith("/translate") else f"{base}/translate"

    def __repr__(self) -> str:
        return (
            "AzureProductTranslator("
            f"endpoint={self._endpoint!r}, "
            f"region={self._region!r}, "
            f"configured={self.is_configured}"
            ")"
        )

    @property
    def is_configured(self) -> bool:
        return azure_translator_is_configured(api_key=self._api_key)

    @property
    def endpoint(self) -> str:
        return self._endpoint

    @property
    def region(self) -> str | None:
        return self._region

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    def translate(self, request: ProductTranslationRequest) -> ProductTranslationResult:
        if not isinstance(request, ProductTranslationRequest):
            raise TypeError("request must be a ProductTranslationRequest")
        text = require_non_empty_product_text(request.text)
        if not self.is_configured or self._api_key is None:
            raise AzureTranslatorNotConfiguredError(_NOT_CONFIGURED_MESSAGE)

        params: dict[str, str] = {
            "api-version": _AZURE_API_VERSION,
            "to": request.target_language,
        }
        if request.source_language is not None:
            params["from"] = request.source_language

        started_at = time.perf_counter()
        _logger.info(
            "provider=azure_translator target=%s auto_source=%s started",
            request.target_language,
            request.source_language is None,
        )
        try:
            response = self._execute_once(params, text)
            self._validate_http_status(response)
            translated_text, detected = _parse_azure_translation(response)
        except (
            AzureTranslatorTimeoutError,
            AzureTranslatorUnavailableError,
            AzureTranslatorHTTPError,
            AzureTranslatorInvalidResponseError,
            ProductTranslationEmptyTextError,
        ) as error:
            _logger.warning(
                "provider=azure_translator outcome=failure error_type=%s duration_seconds=%.3f",
                type(error).__name__,
                time.perf_counter() - started_at,
            )
            raise

        _logger.info(
            "provider=azure_translator outcome=success duration_seconds=%.3f",
            time.perf_counter() - started_at,
        )
        return ProductTranslationResult(
            original_text=text,
            translated_text=translated_text,
            source_language=detected
            if request.source_language is None
            else request.source_language,
            target_language=request.target_language,
            provider=AZURE_TRANSLATOR_PROVIDER,
        )

    def _headers(self) -> dict[str, str]:
        assert self._api_key is not None
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json; charset=UTF-8",
            "Ocp-Apim-Subscription-Key": self._api_key,
            "User-Agent": f"bera-price-tracker/{__version__}",
        }
        if self._region is not None:
            headers["Ocp-Apim-Subscription-Region"] = self._region
        return headers

    def _execute_once(self, params: dict[str, str], text: str) -> httpx.Response:
        if self._client is not None:
            return self._post(self._client, params, text)
        transport = httpx.HTTPTransport(retries=0)
        with httpx.Client(
            transport=transport,
            timeout=self._timeout,
            trust_env=False,
        ) as client:
            return self._post(client, params, text)

    def _post(
        self,
        client: httpx.Client,
        params: dict[str, str],
        text: str,
    ) -> httpx.Response:
        try:
            return client.post(
                self._url,
                params=params,
                headers=self._headers(),
                json=[{"Text": text}],
                timeout=self._timeout,
            )
        except httpx.TimeoutException:
            raise AzureTranslatorTimeoutError("Azure Translator request timed out") from None
        except httpx.TransportError:
            raise AzureTranslatorUnavailableError("Azure Translator connection failed") from None

    def _validate_http_status(self, response: httpx.Response) -> None:
        status = response.status_code
        if status == 200:
            return
        if status == 429:
            raise AzureTranslatorRateLimitError()
        if 400 <= status <= 499:
            raise AzureTranslatorHTTPError(
                status, f"Azure Translator request failed with HTTP {status}"
            )
        if 500 <= status <= 599:
            raise AzureTranslatorHTTPError(
                status, f"Azure Translator request failed with HTTP {status}"
            )
        raise AzureTranslatorHTTPError(
            status, f"Azure Translator request failed with HTTP {status}"
        )


def _parse_azure_translation(response: httpx.Response) -> tuple[str, str | None]:
    payload = _strict_json_loads(response.content)
    if not isinstance(payload, list) or not payload:
        raise AzureTranslatorInvalidResponseError("Azure Translator returned an empty payload")
    first = payload[0]
    if not isinstance(first, dict):
        raise AzureTranslatorInvalidResponseError("Azure Translator returned an invalid payload")
    body = cast(dict[str, Any], first)
    translations = body.get("translations")
    if not isinstance(translations, list) or not translations:
        raise AzureTranslatorInvalidResponseError("Azure Translator returned no translations")
    first_translation = translations[0]
    if not isinstance(first_translation, dict):
        raise AzureTranslatorInvalidResponseError(
            "Azure Translator returned an invalid translation"
        )
    text = first_translation.get("text")
    if not isinstance(text, str):
        raise AzureTranslatorInvalidResponseError(
            "Azure Translator translation text must be a string"
        )
    translated = text.strip()
    if not translated:
        raise AzureTranslatorInvalidResponseError("Azure Translator returned an empty translation")
    detected: str | None = None
    detected_language = body.get("detectedLanguage")
    if isinstance(detected_language, dict):
        language = detected_language.get("language")
        if isinstance(language, str) and language.strip():
            detected = language.strip().casefold()
    return translated, detected
