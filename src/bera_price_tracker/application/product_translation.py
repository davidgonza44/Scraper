"""Generic product-title translation, technical-token checks, and search queries.

This module has no marketplace or money authority. It never infers currency,
never changes prices, and never invents product attributes.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal

from bera_price_tracker.application.ports import (
    ProductSearchQueryGenerator,
    ProductTranslationEmptyTextError,
    ProductTranslator,
    ProductTranslatorInvalidResponseError,
)

DEFAULT_TARGET_LANGUAGE = "es"
DEFAULT_TARGET_MARKET = "VE"
AZURE_TRANSLATOR_PROVIDER = "azure"
DEEPL_TRANSLATOR_PROVIDER = "deepl"
DISABLED_TRANSLATOR_PROVIDER = "disabled"

_CURRENCY_ISO_CODES = frozenset(
    {
        "usd",
        "eur",
        "cny",
        "rmb",
        "ves",
        "gbp",
        "jpy",
        "cad",
        "aud",
        "brl",
        "mxn",
        "cop",
        "pen",
        "clp",
        "ars",
    }
)
_MONEY_FIELD_NAMES = frozenset(
    {
        "price",
        "currency",
        "moq",
        "quantity",
        "decimal",
        "landed",
        "margin",
        "profit",
        "fx",
        "exchange",
    }
)

_BLUETOOTH_PATTERN = re.compile(r"\bBluetooth\s*\d+(?:\.\d+)?\b", re.IGNORECASE)
_WIFI_PATTERN = re.compile(r"\bWi-?Fi\s*\d+\b", re.IGNORECASE)
_USB_PATTERN = re.compile(r"\bUSB(?:[-\s]?[ABC]|\s*\d+(?:\.\d+)?)\b", re.IGNORECASE)
_IP_RATING_PATTERN = re.compile(r"\bIP[0-9]{2}[A-Z]?\b", re.IGNORECASE)
_THREAD_PATTERN = re.compile(r"\bM\d{1,2}(?:\s*[xX×]\s*\d+(?:[.,]\d+)?)?\b")
_NUMBER_UNIT_PATTERN = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:"
    r"kWh|kW|mAh|Ah|rpm|DPI|GHz|MHz|kHz|Hz|"
    r"Nm|mm|cm|ml|kg|kV|VAC|VDC|"
    r"V|W|L|g|m|A|in"
    r")\b",
    re.IGNORECASE,
)
_MATERIAL_GRADE_PATTERN = re.compile(r"\b\d{3}L\b", re.IGNORECASE)
_STANDALONE_GRADE_PATTERN = re.compile(r"\b\d{3}\b")
_MODEL_CODE_PATTERN = re.compile(
    r"\b(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*\d)[A-Z]{1,5}\d{2,8}[A-Z0-9]{0,4}\b",
    re.IGNORECASE,
)
_VERSION_PATTERN = re.compile(r"\b(?:v|ver\.?|version)\s*\d+(?:\.\d+){0,3}\b", re.IGNORECASE)
_STANDARD_PATTERN = re.compile(r"\b(?:ISO|IEC|DIN|ASTM|EN|GB/T|GB)\s*[-/]?\s*\d+[A-Z0-9-]*\b")

_TOKEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    _BLUETOOTH_PATTERN,
    _WIFI_PATTERN,
    _USB_PATTERN,
    _IP_RATING_PATTERN,
    _NUMBER_UNIT_PATTERN,
    _THREAD_PATTERN,
    _MATERIAL_GRADE_PATTERN,
    _STANDARD_PATTERN,
    _VERSION_PATTERN,
    _MODEL_CODE_PATTERN,
    _STANDALONE_GRADE_PATTERN,
)

_PRICE_PATTERN = re.compile(r"(?<!\w)(?:US\s*)?\$\s*\d+(?:[.,]\d+)?")
_CURRENCY_CODE_PATTERN = re.compile(
    r"\b(?:USD|EUR|CNY|RMB|VES|GBP|JPY|CAD|AUD|BRL|MXN|COP|PEN|CLP|ARS)\b",
    re.IGNORECASE,
)
_MOQ_PATTERN = re.compile(r"\b(?:MOQ|min(?:imum)?\s*order(?:\s*qty|\s*quantity)?)\b[:\s]*\d*", re.I)
_YEAR_PATTERN = re.compile(r"\b20[2-3]\d\b")

_MARKETPLACE_NOISE_PHRASES: tuple[str, ...] = (
    "factory direct",
    "direct factory",
    "ready to ship",
    "free shipping",
    "fast shipping",
    "new arrivals",
    "new arrival",
    "best seller",
    "bestselling",
    "hot sale",
    "high quality",
    "high-quality",
    "top quality",
    "super quality",
    "brand new",
    "in stock",
    "dropshipping",
    "dropship",
    "wholesale",
    "venta al por mayor",
    "envío gratis",
    "envio gratis",
    "de fábrica",
    "de fabrica",
    "alta calidad",
    "listo para enviar",
    "nuevo ingreso",
    "100%",
    "oem",
    "odm",
    "customized",
    "customize",
    "personalized",
    "manufacturer",
    "supplier",
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProductTranslationRequest:
    """Provider-neutral translation input. Text only; no money fields."""

    text: str
    target_language: str = DEFAULT_TARGET_LANGUAGE
    source_language: str | None = None
    target_market: str | None = DEFAULT_TARGET_MARKET

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("text must be a string")
        if not isinstance(self.target_language, str) or not self.target_language.strip():
            raise ValueError("target_language must not be blank")
        object.__setattr__(self, "target_language", self.target_language.strip().casefold())
        source = self.source_language
        if source is not None:
            if not isinstance(source, str):
                raise TypeError("source_language must be a string")
            normalized = source.strip().casefold()
            object.__setattr__(
                self, "source_language", None if normalized in {"", "auto"} else normalized
            )
        market = self.target_market
        if market is not None:
            if not isinstance(market, str):
                raise TypeError("target_market must be a string")
            object.__setattr__(self, "target_market", market.strip() or None)
        _reject_money_fields(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProductTranslationResult:
    """Provider-neutral translation output. Never carries prices or currency."""

    original_text: str
    translated_text: str
    target_language: str
    provider: str
    source_language: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.original_text, str):
            raise TypeError("original_text must be a string")
        if not isinstance(self.translated_text, str):
            raise TypeError("translated_text must be a string")
        if not isinstance(self.target_language, str) or not self.target_language.strip():
            raise ValueError("target_language must not be blank")
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise ValueError("provider must not be blank")
        object.__setattr__(self, "target_language", self.target_language.strip().casefold())
        object.__setattr__(self, "provider", self.provider.strip().casefold())
        if self.source_language is not None:
            if not isinstance(self.source_language, str):
                raise TypeError("source_language must be a string")
            normalized = self.source_language.strip().casefold()
            object.__setattr__(self, "source_language", normalized or None)
        _reject_money_fields(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class TechnicalTokenIssue:
    """One original technical token that disappeared or changed in a translation."""

    original_token: str
    translated_token: str | None = None

    @property
    def changed(self) -> bool:
        return self.translated_token is not None


@dataclass(frozen=True, slots=True, kw_only=True)
class TechnicalTokenValidation:
    """Deterministic comparison of technical tokens. Language is not a spec."""

    original_tokens: tuple[str, ...]
    translated_tokens: tuple[str, ...]
    missing_tokens: tuple[str, ...]
    changed_tokens: tuple[TechnicalTokenIssue, ...]

    @property
    def is_reliable(self) -> bool:
        return not self.missing_tokens and not self.changed_tokens


@dataclass(frozen=True, slots=True, kw_only=True)
class ProductSearchTranslation:
    """Translation plus a conservative, user-editable search query."""

    translation: ProductTranslationResult
    search_query: str
    technical_tokens: TechnicalTokenValidation

    @property
    def is_technically_reliable(self) -> bool:
        return self.technical_tokens.is_reliable


class TechnicalTokenMismatchError(RuntimeError):
    """Raised when a translation drops or changes a critical technical token."""

    def __init__(self, validation: TechnicalTokenValidation, translated_text: str) -> None:
        self.validation = validation
        self.translated_text = translated_text
        missing = ", ".join(validation.missing_tokens) or "none"
        changed = (
            ", ".join(
                issue.original_token
                if issue.translated_token is None
                else f"{issue.original_token}→{issue.translated_token}"
                for issue in validation.changed_tokens
            )
            or "none"
        )
        super().__init__(
            f"Translation is not technically reliable (missing={missing}; changed={changed})"
        )


def _reject_money_fields(value: object) -> None:
    names = getattr(value, "__dataclass_fields__", {})
    for name in names:
        if name.casefold() in _MONEY_FIELD_NAMES:
            raise TypeError(f"{type(value).__name__} must not include money field {name!r}")
        field_value = getattr(value, name)
        if isinstance(field_value, Decimal):
            raise TypeError(f"{type(value).__name__} must not carry Decimal values")


def normalize_translation_cache_key(
    text: str, target_language: str, provider: str
) -> tuple[str, str, str]:
    """Session cache key: provider, normalized source text, and target language."""

    collapsed = unicodedata.normalize("NFC", " ".join(text.split()))
    return (
        provider.strip().casefold(),
        collapsed.casefold(),
        target_language.strip().casefold(),
    )


def translator_provider_name(translator: ProductTranslator) -> str:
    """Return the adapter provider id used for cache isolation. Never a secret."""

    provider = getattr(translator, "provider", "")
    if not isinstance(provider, str):
        return ""
    return provider.strip().casefold()


def extract_technical_tokens(text: object) -> tuple[str, ...]:
    """Return generic technical tokens. Not a product-category dictionary."""

    if not isinstance(text, str) or not text.strip():
        return ()
    occupied: list[tuple[int, int]] = []
    tokens: list[str] = []
    for pattern in _TOKEN_PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span()
            if _overlaps(start, end, occupied):
                continue
            token = match.group(0).strip()
            if not token or _looks_like_currency_amount(token):
                continue
            occupied.append((start, end))
            tokens.append(token)
    return tuple(tokens)


def _overlaps(start: int, end: int, occupied: list[tuple[int, int]]) -> bool:
    return any(not (end <= left or start >= right) for left, right in occupied)


def _looks_like_currency_amount(token: str) -> bool:
    stripped = token.strip().casefold()
    return stripped in _CURRENCY_ISO_CODES or stripped.startswith("$")


def normalize_technical_token(token: str) -> str:
    collapsed = re.sub(r"[\s\-_]+", "", token).casefold().replace(",", ".")
    return collapsed


def _token_signature(normalized: str) -> str:
    match = re.match(r"^(\d+(?:\.\d+)?)(.*)$", normalized)
    if match is not None and match.group(2):
        return match.group(2)
    match = re.match(r"^([a-z]+)(\d.*)$", normalized)
    if match is not None:
        return match.group(1)
    return normalized


def validate_technical_tokens(
    original_text: object, translated_text: object
) -> TechnicalTokenValidation:
    """Fail closed on lost or mutated technical tokens. Do not rewrite the translation."""

    original_tokens = extract_technical_tokens(original_text)
    translated_tokens = extract_technical_tokens(translated_text)
    translated_normalized = {normalize_technical_token(token): token for token in translated_tokens}
    translated_by_signature: dict[str, list[str]] = {}
    for token in translated_tokens:
        signature = _token_signature(normalize_technical_token(token))
        translated_by_signature.setdefault(signature, []).append(token)

    missing: list[str] = []
    changed: list[TechnicalTokenIssue] = []
    for token in original_tokens:
        normalized = normalize_technical_token(token)
        if normalized in translated_normalized:
            continue
        signature = _token_signature(normalized)
        candidates = [
            candidate
            for candidate in translated_by_signature.get(signature, ())
            if normalize_technical_token(candidate) != normalized
        ]
        if candidates:
            changed.append(
                TechnicalTokenIssue(original_token=token, translated_token=candidates[0])
            )
        else:
            missing.append(token)
    return TechnicalTokenValidation(
        original_tokens=original_tokens,
        translated_tokens=translated_tokens,
        missing_tokens=tuple(missing),
        changed_tokens=tuple(changed),
    )


def require_reliable_technical_tokens(
    validation: TechnicalTokenValidation, translated_text: str
) -> None:
    if not validation.is_reliable:
        raise TechnicalTokenMismatchError(validation, translated_text)


class ConservativeProductSearchQueryGenerator:
    """Strip marketplace noise. Preserve technical identifiers. Never invent attributes."""

    def generate(self, *, original_text: str, translated_text: str) -> str:
        source = translated_text if isinstance(translated_text, str) else ""
        query = _strip_commercial_noise(source)
        if not query:
            query = _strip_commercial_noise(original_text if isinstance(original_text, str) else "")
        original_tokens = extract_technical_tokens(original_text)
        present = {normalize_technical_token(token) for token in extract_technical_tokens(query)}
        missing = [
            token for token in original_tokens if normalize_technical_token(token) not in present
        ]
        if missing:
            query = " ".join([query, *missing]).strip()
        return query


def _strip_commercial_noise(text: str) -> str:
    cleaned = _PRICE_PATTERN.sub(" ", text)
    cleaned = _CURRENCY_CODE_PATTERN.sub(" ", cleaned)
    cleaned = _MOQ_PATTERN.sub(" ", cleaned)
    for phrase in sorted(_MARKETPLACE_NOISE_PHRASES, key=len, reverse=True):
        cleaned = re.sub(re.escape(phrase), " ", cleaned, flags=re.IGNORECASE)
    cleaned = _YEAR_PATTERN.sub(" ", cleaned)
    cleaned = re.sub(r"[|/]+", " ", cleaned)
    cleaned = re.sub(
        r"[^\w.+#\u00C0-\u024F\u0400-\u04FF\u4E00-\u9FFF\s-]", " ", cleaned, flags=re.UNICODE
    )
    return " ".join(cleaned.split()).strip(" -")


@dataclass(slots=True)
class InMemoryProductTranslationCache:
    """Process-local translation cache. Stores no secrets or provider headers."""

    _entries: dict[tuple[str, str, str], ProductTranslationResult] = field(default_factory=dict)

    def get(
        self, text: str, target_language: str, provider: str
    ) -> ProductTranslationResult | None:
        return self._entries.get(normalize_translation_cache_key(text, target_language, provider))

    def put(self, result: ProductTranslationResult) -> None:
        key = normalize_translation_cache_key(
            result.original_text, result.target_language, result.provider
        )
        self._entries[key] = result

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


def require_non_empty_product_text(text: object) -> str:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    normalized = text.strip()
    if not normalized:
        raise ProductTranslationEmptyTextError("Product title is empty")
    return normalized


@dataclass(frozen=True, slots=True)
class TranslateProductTitle:
    """Translate a product title, validate tokens, and derive an editable query."""

    translator: ProductTranslator
    query_generator: ProductSearchQueryGenerator = field(
        default_factory=ConservativeProductSearchQueryGenerator
    )
    cache: InMemoryProductTranslationCache | None = None

    def execute(self, request: ProductTranslationRequest) -> ProductSearchTranslation:
        if not isinstance(request, ProductTranslationRequest):
            raise TypeError("request must be a ProductTranslationRequest")
        normalized_text = require_non_empty_product_text(request.text)
        normalized_request = ProductTranslationRequest(
            text=normalized_text,
            source_language=request.source_language,
            target_language=request.target_language,
            target_market=request.target_market,
        )
        cached = (
            None
            if self.cache is None
            else self.cache.get(
                normalized_request.text,
                normalized_request.target_language,
                translator_provider_name(self.translator),
            )
        )
        translation = (
            cached if cached is not None else self.translator.translate(normalized_request)
        )
        if not isinstance(translation, ProductTranslationResult):
            raise ProductTranslatorInvalidResponseError("Translator returned an invalid result")
        if not translation.translated_text.strip():
            raise ProductTranslatorInvalidResponseError("Translator returned an empty translation")
        if self.cache is not None and cached is None:
            self.cache.put(translation)
        validation = validate_technical_tokens(
            translation.original_text, translation.translated_text
        )
        query = self.query_generator.generate(
            original_text=translation.original_text,
            translated_text=translation.translated_text,
        )
        return ProductSearchTranslation(
            translation=translation,
            search_query=query,
            technical_tokens=validation,
        )
