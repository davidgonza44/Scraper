"""Environment-backed application configuration."""

from __future__ import annotations

import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from ipaddress import ip_address
from urllib.parse import urlsplit

_LOG_LEVELS = frozenset({"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"})
_MERCADOLIBRE_MAX_PAGE_SIZE = 100
_MERCADOLIBRE_MAX_RESULTS = 1_000
_MERCADOLIBRE_MAX_RETRIES = 5
_MERCADOLIBRE_SITE_ID_PATTERN = re.compile(r"^[A-Z0-9_-]+$")
_OLLAMA_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "minimax-m3:cloud"
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 90.0
DEFAULT_BRIGHTDATA_BASE_URL = "https://api.brightdata.com"
DEFAULT_BRIGHTDATA_DATASET_ID = "gd_lvt9iwuh6fbcwmx1a"
DEFAULT_BRIGHTDATA_TIMEOUT_SECONDS = 70.0
DEFAULT_BRIGHTDATA_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_BRIGHTDATA_POLL_TIMEOUT_SECONDS = 900.0
DEFAULT_FACEBOOK_CITY = "caracas"
DEFAULT_FACEBOOK_BACKEND = "apify"
DEFAULT_APIFY_ALIBABA_ACTOR = "scraper-engine/alibaba-scraper"
DEFAULT_APIFY_ALIBABA_REFRESH_ACTOR = "xtracto/alibaba-product-scraper"
DEFAULT_APIFY_ALIBABA_REFRESH_RETRIES = 1
DEFAULT_APIFY_ALIBABA_REFRESH_CONCURRENCY = 3
MAX_APIFY_ALIBABA_REFRESH_RETRIES = 5
MAX_APIFY_ALIBABA_REFRESH_CONCURRENCY = 3
DEFAULT_FACEBOOK_RECORD_LIMIT = 5
MAX_FACEBOOK_RECORD_LIMIT = 5


def is_valid_mercadolibre_site_id(site_id: str | None) -> bool:
    """Return whether ``site_id`` is usable by the Mercado Libre provider."""

    if site_id is None:
        return False
    normalized = site_id.strip().upper()
    return bool(normalized) and _MERCADOLIBRE_SITE_ID_PATTERN.fullmatch(normalized) is not None


def _optional_value(environ: Mapping[str, str], name: str) -> str | None:
    value = environ.get(name)
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _integer_value(environ: Mapping[str, str], name: str, default: int) -> int:
    raw_value = environ.get(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error


def _float_value(environ: Mapping[str, str], name: str, default: float) -> float:
    raw_value = environ.get(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError as error:
        raise ValueError(f"{name} must be a number") from error


def normalize_ollama_base_url(value: str) -> str:
    """Validate and normalize a loopback-only Ollama API base URL."""

    if not isinstance(value, str):
        raise TypeError("ollama_base_url must be a string")
    normalized = value.strip()
    if not normalized or any(character.isspace() for character in normalized):
        raise ValueError("ollama_base_url must not be blank or contain whitespace")

    parsed = urlsplit(normalized)
    if parsed.scheme.lower() not in {"http", "https"} or parsed.hostname is None:
        raise ValueError("ollama_base_url must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("ollama_base_url must not contain credentials")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("ollama_base_url must not contain a path, query, or fragment")
    try:
        _ = parsed.port
    except ValueError as error:
        raise ValueError("ollama_base_url contains an invalid port") from error

    hostname = parsed.hostname.casefold()
    if hostname != "localhost":
        try:
            address = ip_address(hostname)
        except ValueError:
            raise ValueError("ollama_base_url must use a loopback host") from None
        if not address.is_loopback:
            raise ValueError("ollama_base_url must use a loopback host")

    return f"{parsed.scheme.lower()}://{parsed.netloc}".rstrip("/")


def normalize_ollama_model(value: str) -> str:
    """Validate a local Ollama model identifier without interpreting it."""

    if not isinstance(value, str):
        raise TypeError("ollama_model must be a string")
    normalized = value.strip()
    if _OLLAMA_MODEL_PATTERN.fullmatch(normalized) is None:
        raise ValueError("ollama_model must be a non-blank Ollama model identifier")
    return normalized


def normalize_ollama_timeout_seconds(value: float) -> float:
    """Validate the bounded-request timeout used for cloud-backed local inference."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("ollama_timeout_seconds must be a number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0:
        raise ValueError("ollama_timeout_seconds must be finite and greater than zero")
    return normalized


def normalize_brightdata_base_url(value: str) -> str:
    """Validate the credential-bearing Bright Data API origin."""

    if not isinstance(value, str):
        raise TypeError("brightdata_base_url must be a string")
    normalized = value.strip()
    parsed = urlsplit(normalized)
    if parsed.scheme.lower() != "https" or parsed.hostname is None:
        raise ValueError("brightdata_base_url must be an absolute HTTPS URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("brightdata_base_url must not contain credentials")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("brightdata_base_url must not contain a path, query, or fragment")
    try:
        _ = parsed.port
    except ValueError as error:
        raise ValueError("brightdata_base_url contains an invalid port") from error
    return f"https://{parsed.netloc}".rstrip("/")


def _positive_finite(value: float, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0:
        raise ValueError(f"{field_name} must be finite and greater than zero")
    return normalized


@dataclass(frozen=True, slots=True)
class Settings:
    """Process configuration without implicit file or secret loading."""

    log_level: str = "INFO"
    mercadolibre_site_id: str | None = None
    mercadolibre_client_id: str | None = None
    mercadolibre_client_secret: str | None = None
    mercadolibre_access_token: str | None = None
    mercadolibre_page_size: int = 50
    mercadolibre_max_pages: int = 3
    mercadolibre_timeout_seconds: float = 10.0
    mercadolibre_max_retries: int = 2
    database_path: str = "data/bera_price_tracker.db"
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    ollama_timeout_seconds: float = DEFAULT_OLLAMA_TIMEOUT_SECONDS
    brightdata_api_token: str | None = field(default=None, repr=False)
    brightdata_base_url: str = DEFAULT_BRIGHTDATA_BASE_URL
    brightdata_dataset_id: str = DEFAULT_BRIGHTDATA_DATASET_ID
    brightdata_timeout_seconds: float = DEFAULT_BRIGHTDATA_TIMEOUT_SECONDS
    brightdata_poll_interval_seconds: float = DEFAULT_BRIGHTDATA_POLL_INTERVAL_SECONDS
    brightdata_poll_timeout_seconds: float = DEFAULT_BRIGHTDATA_POLL_TIMEOUT_SECONDS
    facebook_city: str = DEFAULT_FACEBOOK_CITY
    facebook_record_limit: int = DEFAULT_FACEBOOK_RECORD_LIMIT
    facebook_backend: str = DEFAULT_FACEBOOK_BACKEND
    apify_api_token: str | None = field(default=None, repr=False)
    apify_alibaba_actor: str = DEFAULT_APIFY_ALIBABA_ACTOR
    apify_alibaba_refresh_actor: str = DEFAULT_APIFY_ALIBABA_REFRESH_ACTOR
    apify_alibaba_refresh_retries: int = DEFAULT_APIFY_ALIBABA_REFRESH_RETRIES
    apify_alibaba_refresh_concurrency: int = DEFAULT_APIFY_ALIBABA_REFRESH_CONCURRENCY

    def __post_init__(self) -> None:
        level = self.log_level.strip().upper()
        if level not in _LOG_LEVELS:
            allowed = ", ".join(sorted(_LOG_LEVELS))
            raise ValueError(f"log_level must be one of: {allowed}")
        object.__setattr__(self, "log_level", level)

        site_id = self.mercadolibre_site_id
        if site_id is not None:
            object.__setattr__(self, "mercadolibre_site_id", site_id.strip().upper() or None)

        if self.mercadolibre_page_size <= 0:
            raise ValueError("mercadolibre_page_size must be greater than zero")
        if self.mercadolibre_page_size > _MERCADOLIBRE_MAX_PAGE_SIZE:
            raise ValueError(
                f"mercadolibre_page_size must not exceed {_MERCADOLIBRE_MAX_PAGE_SIZE}"
            )
        if self.mercadolibre_max_pages <= 0:
            raise ValueError("mercadolibre_max_pages must be greater than zero")
        if self.mercadolibre_page_size * self.mercadolibre_max_pages > _MERCADOLIBRE_MAX_RESULTS:
            raise ValueError("mercadolibre_page_size * mercadolibre_max_pages must not exceed 1000")
        if not math.isfinite(self.mercadolibre_timeout_seconds):
            raise ValueError("mercadolibre_timeout_seconds must be finite")
        if self.mercadolibre_timeout_seconds <= 0:
            raise ValueError("mercadolibre_timeout_seconds must be greater than zero")
        if self.mercadolibre_max_retries < 0:
            raise ValueError("mercadolibre_max_retries must be zero or greater")
        if self.mercadolibre_max_retries > _MERCADOLIBRE_MAX_RETRIES:
            raise ValueError(
                f"mercadolibre_max_retries must not exceed {_MERCADOLIBRE_MAX_RETRIES}"
            )
        database_path = self.database_path.strip()
        if not database_path:
            raise ValueError("database_path must not be blank")
        object.__setattr__(self, "database_path", database_path)
        object.__setattr__(
            self,
            "ollama_base_url",
            normalize_ollama_base_url(self.ollama_base_url),
        )
        object.__setattr__(self, "ollama_model", normalize_ollama_model(self.ollama_model))
        object.__setattr__(
            self,
            "ollama_timeout_seconds",
            normalize_ollama_timeout_seconds(self.ollama_timeout_seconds),
        )
        token = self.brightdata_api_token
        if token is not None:
            object.__setattr__(self, "brightdata_api_token", token.strip() or None)
        object.__setattr__(
            self,
            "brightdata_base_url",
            normalize_brightdata_base_url(self.brightdata_base_url),
        )
        dataset_id = self.brightdata_dataset_id.strip()
        if not dataset_id:
            raise ValueError("brightdata_dataset_id must not be blank")
        object.__setattr__(self, "brightdata_dataset_id", dataset_id)
        object.__setattr__(
            self,
            "brightdata_timeout_seconds",
            _positive_finite(self.brightdata_timeout_seconds, "brightdata_timeout_seconds"),
        )
        object.__setattr__(
            self,
            "brightdata_poll_interval_seconds",
            _positive_finite(
                self.brightdata_poll_interval_seconds,
                "brightdata_poll_interval_seconds",
            ),
        )
        object.__setattr__(
            self,
            "brightdata_poll_timeout_seconds",
            _positive_finite(
                self.brightdata_poll_timeout_seconds,
                "brightdata_poll_timeout_seconds",
            ),
        )
        token = self.apify_api_token
        if token is not None:
            object.__setattr__(self, "apify_api_token", token.strip() or None)
        city = " ".join(self.facebook_city.strip().split()).casefold()
        if not city:
            raise ValueError("facebook_city must not be blank")
        object.__setattr__(self, "facebook_city", city)
        if isinstance(self.facebook_record_limit, bool) or not isinstance(
            self.facebook_record_limit, int
        ):
            raise TypeError("facebook_record_limit must be an integer")
        if not 1 <= self.facebook_record_limit <= MAX_FACEBOOK_RECORD_LIMIT:
            raise ValueError(
                f"facebook_record_limit must be between 1 and {MAX_FACEBOOK_RECORD_LIMIT}"
            )
        backend = self.facebook_backend.strip().casefold()
        if backend not in {"apify", "brightdata"}:
            raise ValueError("facebook_backend must be apify or brightdata")
        object.__setattr__(self, "facebook_backend", backend)

        actor = self.apify_alibaba_actor.strip()
        if not actor:
            raise ValueError("apify_alibaba_actor must not be blank")
        object.__setattr__(self, "apify_alibaba_actor", actor)
        refresh_actor = self.apify_alibaba_refresh_actor.strip()
        if not refresh_actor:
            raise ValueError("apify_alibaba_refresh_actor must not be blank")
        object.__setattr__(self, "apify_alibaba_refresh_actor", refresh_actor)
        if isinstance(self.apify_alibaba_refresh_retries, bool) or not isinstance(
            self.apify_alibaba_refresh_retries, int
        ):
            raise TypeError("apify_alibaba_refresh_retries must be an integer")
        if not 0 <= self.apify_alibaba_refresh_retries <= MAX_APIFY_ALIBABA_REFRESH_RETRIES:
            raise ValueError(
                "apify_alibaba_refresh_retries must be between 0 and "
                f"{MAX_APIFY_ALIBABA_REFRESH_RETRIES}"
            )
        if isinstance(self.apify_alibaba_refresh_concurrency, bool) or not isinstance(
            self.apify_alibaba_refresh_concurrency, int
        ):
            raise TypeError("apify_alibaba_refresh_concurrency must be an integer")
        if not 1 <= self.apify_alibaba_refresh_concurrency <= MAX_APIFY_ALIBABA_REFRESH_CONCURRENCY:
            raise ValueError(
                "apify_alibaba_refresh_concurrency must be between 1 and "
                f"{MAX_APIFY_ALIBABA_REFRESH_CONCURRENCY}"
            )

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        """Create settings from a provided mapping or the process environment."""

        values = os.environ if environ is None else environ
        return cls(
            log_level=values.get("BERA_TRACKER_LOG_LEVEL", "INFO"),
            mercadolibre_site_id=_optional_value(values, "BERA_TRACKER_MERCADOLIBRE_SITE_ID"),
            mercadolibre_client_id=_optional_value(values, "BERA_TRACKER_MERCADOLIBRE_CLIENT_ID"),
            mercadolibre_client_secret=_optional_value(
                values, "BERA_TRACKER_MERCADOLIBRE_CLIENT_SECRET"
            ),
            mercadolibre_access_token=_optional_value(
                values, "BERA_TRACKER_MERCADOLIBRE_ACCESS_TOKEN"
            ),
            mercadolibre_page_size=_integer_value(
                values, "BERA_TRACKER_MERCADOLIBRE_PAGE_SIZE", 50
            ),
            mercadolibre_max_pages=_integer_value(values, "BERA_TRACKER_MERCADOLIBRE_MAX_PAGES", 3),
            mercadolibre_timeout_seconds=_float_value(
                values, "BERA_TRACKER_MERCADOLIBRE_TIMEOUT_SECONDS", 10.0
            ),
            mercadolibre_max_retries=_integer_value(
                values, "BERA_TRACKER_MERCADOLIBRE_MAX_RETRIES", 2
            ),
            database_path=values.get("BERA_TRACKER_DATABASE_PATH", "data/bera_price_tracker.db"),
            ollama_base_url=values.get(
                "BERA_TRACKER_OLLAMA_BASE_URL",
                DEFAULT_OLLAMA_BASE_URL,
            ),
            ollama_model=values.get("BERA_TRACKER_OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
            ollama_timeout_seconds=_float_value(
                values,
                "BERA_TRACKER_OLLAMA_TIMEOUT_SECONDS",
                DEFAULT_OLLAMA_TIMEOUT_SECONDS,
            ),
            brightdata_api_token=_optional_value(
                values,
                "BERA_TRACKER_BRIGHTDATA_API_TOKEN",
            ),
            brightdata_base_url=values.get(
                "BERA_TRACKER_BRIGHTDATA_BASE_URL",
                DEFAULT_BRIGHTDATA_BASE_URL,
            ),
            brightdata_dataset_id=values.get(
                "BERA_TRACKER_BRIGHTDATA_DATASET_ID",
                DEFAULT_BRIGHTDATA_DATASET_ID,
            ),
            brightdata_timeout_seconds=_float_value(
                values,
                "BERA_TRACKER_BRIGHTDATA_TIMEOUT_SECONDS",
                DEFAULT_BRIGHTDATA_TIMEOUT_SECONDS,
            ),
            brightdata_poll_interval_seconds=_float_value(
                values,
                "BERA_TRACKER_BRIGHTDATA_POLL_INTERVAL_SECONDS",
                DEFAULT_BRIGHTDATA_POLL_INTERVAL_SECONDS,
            ),
            brightdata_poll_timeout_seconds=_float_value(
                values,
                "BERA_TRACKER_BRIGHTDATA_POLL_TIMEOUT_SECONDS",
                DEFAULT_BRIGHTDATA_POLL_TIMEOUT_SECONDS,
            ),
            facebook_city=values.get("BERA_TRACKER_FACEBOOK_CITY", DEFAULT_FACEBOOK_CITY),
            facebook_record_limit=_integer_value(
                values,
                "BERA_TRACKER_FACEBOOK_RECORD_LIMIT",
                DEFAULT_FACEBOOK_RECORD_LIMIT,
            ),
            facebook_backend=values.get(
                "BERA_TRACKER_FACEBOOK_BACKEND",
                DEFAULT_FACEBOOK_BACKEND,
            ),
            apify_api_token=_optional_value(values, "BERA_TRACKER_APIFY_API_TOKEN"),
            apify_alibaba_actor=values.get(
                "BERA_TRACKER_APIFY_ALIBABA_ACTOR",
                DEFAULT_APIFY_ALIBABA_ACTOR,
            ),
            apify_alibaba_refresh_actor=values.get(
                "BERA_TRACKER_APIFY_ALIBABA_REFRESH_ACTOR",
                DEFAULT_APIFY_ALIBABA_REFRESH_ACTOR,
            ),
            apify_alibaba_refresh_retries=_integer_value(
                values,
                "BERA_TRACKER_APIFY_ALIBABA_REFRESH_RETRIES",
                DEFAULT_APIFY_ALIBABA_REFRESH_RETRIES,
            ),
            apify_alibaba_refresh_concurrency=_integer_value(
                values,
                "BERA_TRACKER_APIFY_ALIBABA_REFRESH_CONCURRENCY",
                DEFAULT_APIFY_ALIBABA_REFRESH_CONCURRENCY,
            ),
        )
