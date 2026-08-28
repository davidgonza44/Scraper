"""Unit tests for environment-backed settings."""

import pytest

from bera_price_tracker.config import (
    DEFAULT_APIFY_ALIBABA_ACTOR,
    DEFAULT_APIFY_MERCADOLIBRE_ACTOR,
    DEFAULT_AZURE_TRANSLATOR_ENDPOINT,
    DEFAULT_AZURE_TRANSLATOR_TIMEOUT_SECONDS,
    DEFAULT_BRIGHTDATA_BASE_URL,
    DEFAULT_BRIGHTDATA_DATASET_ID,
    DEFAULT_DEEPL_API_ENDPOINT,
    DEFAULT_DEEPL_TIMEOUT_SECONDS,
    DEFAULT_FACEBOOK_CITY,
    DEFAULT_FACEBOOK_RECORD_LIMIT,
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_TIMEOUT_SECONDS,
    Settings,
    is_valid_mercadolibre_site_id,
    normalize_alibaba_search_actor,
)


def test_settings_are_read_from_a_mapping_without_loading_files() -> None:
    settings = Settings.from_env(
        {
            "BERA_TRACKER_LOG_LEVEL": "debug",
            "BERA_TRACKER_MERCADOLIBRE_SITE_ID": "mlv",
            "BERA_TRACKER_MERCADOLIBRE_CLIENT_ID": "client-id",
            "BERA_TRACKER_MERCADOLIBRE_CLIENT_SECRET": "secret-value",
            "BERA_TRACKER_MERCADOLIBRE_ACCESS_TOKEN": "token-value",
            "BERA_TRACKER_MERCADOLIBRE_PAGE_SIZE": "25",
            "BERA_TRACKER_MERCADOLIBRE_MAX_PAGES": "4",
            "BERA_TRACKER_MERCADOLIBRE_TIMEOUT_SECONDS": "7.5",
            "BERA_TRACKER_MERCADOLIBRE_MAX_RETRIES": "1",
            "BERA_TRACKER_DATABASE_PATH": "var/test.db",
            "BERA_TRACKER_OLLAMA_BASE_URL": "http://127.0.0.1:11435/",
            "BERA_TRACKER_OLLAMA_MODEL": "custom-model:cloud",
            "BERA_TRACKER_OLLAMA_TIMEOUT_SECONDS": "75.5",
            "BERA_TRACKER_BRIGHTDATA_API_TOKEN": " bright-secret ",
            "BERA_TRACKER_BRIGHTDATA_BASE_URL": "https://api.example.test/",
            "BERA_TRACKER_BRIGHTDATA_DATASET_ID": " custom-dataset ",
            "BERA_TRACKER_BRIGHTDATA_TIMEOUT_SECONDS": "21.5",
            "BERA_TRACKER_BRIGHTDATA_POLL_INTERVAL_SECONDS": "2.5",
            "BERA_TRACKER_BRIGHTDATA_POLL_TIMEOUT_SECONDS": "600",
            "BERA_TRACKER_FACEBOOK_CITY": " Caracas ",
            "BERA_TRACKER_FACEBOOK_RECORD_LIMIT": "4",
            "BERA_TRACKER_APIFY_API_TOKEN": " apify-secret ",
            "BERA_TRACKER_AZURE_TRANSLATOR_KEY": " azure-secret ",
            "BERA_TRACKER_AZURE_TRANSLATOR_ENDPOINT": "https://translator.example.test/",
            "BERA_TRACKER_AZURE_TRANSLATOR_REGION": " eastus ",
            "BERA_TRACKER_AZURE_TRANSLATOR_TIMEOUT_SECONDS": "8.5",
            "BERA_TRACKER_TRANSLATOR_PROVIDER": "deepl",
            "BERA_TRACKER_DEEPL_API_KEY": " deepl-secret ",
            "BERA_TRACKER_DEEPL_API_ENDPOINT": "https://api.deepl.com/",
            "BERA_TRACKER_DEEPL_TIMEOUT_SECONDS": "9.5",
        }
    )

    assert settings.log_level == "DEBUG"
    assert settings.mercadolibre_site_id == "MLV"
    assert settings.mercadolibre_client_id == "client-id"
    assert settings.mercadolibre_client_secret == "secret-value"
    assert settings.mercadolibre_access_token == "token-value"
    assert settings.mercadolibre_page_size == 25
    assert settings.mercadolibre_max_pages == 4
    assert settings.mercadolibre_timeout_seconds == 7.5
    assert settings.mercadolibre_max_retries == 1
    assert settings.database_path == "var/test.db"
    assert settings.ollama_base_url == "http://127.0.0.1:11435"
    assert settings.ollama_model == "custom-model:cloud"
    assert settings.ollama_timeout_seconds == 75.5
    assert settings.brightdata_api_token == "bright-secret"
    assert settings.brightdata_base_url == "https://api.example.test"
    assert settings.brightdata_dataset_id == "custom-dataset"
    assert settings.brightdata_timeout_seconds == 21.5
    assert settings.brightdata_poll_interval_seconds == 2.5
    assert settings.brightdata_poll_timeout_seconds == 600.0
    assert settings.facebook_city == "caracas"
    assert settings.facebook_record_limit == 4
    assert settings.apify_api_token == "apify-secret"
    assert settings.azure_translator_key == "azure-secret"
    assert settings.azure_translator_endpoint == "https://translator.example.test"
    assert settings.azure_translator_region == "eastus"
    assert settings.azure_translator_timeout_seconds == 8.5
    assert settings.azure_translator_configured() is True
    assert settings.translator_provider == "deepl"
    assert settings.deepl_api_key == "deepl-secret"
    assert settings.deepl_api_endpoint == "https://api.deepl.com"
    assert settings.deepl_timeout_seconds == 9.5
    assert settings.deepl_translator_configured() is True
    assert settings.resolved_translator_provider() == "deepl"
    assert settings.product_translator_configured() is True
    assert settings.apify_alibaba_actor == DEFAULT_APIFY_ALIBABA_ACTOR
    assert settings.apify_alibaba_refresh_actor == "xtracto/alibaba-product-scraper"
    assert settings.apify_alibaba_refresh_retries == 1
    assert settings.apify_alibaba_refresh_concurrency == 3
    assert settings.apify_mercadolibre_actor == DEFAULT_APIFY_MERCADOLIBRE_ACTOR
    assert "bright-secret" not in repr(settings)
    assert "apify-secret" not in repr(settings)
    assert "azure-secret" not in repr(settings)
    assert "deepl-secret" not in repr(settings)


def test_blank_optional_environment_values_become_none() -> None:
    settings = Settings.from_env({"BERA_TRACKER_MERCADOLIBRE_ACCESS_TOKEN": "  "})

    assert settings.log_level == "INFO"
    assert settings.mercadolibre_access_token is None
    assert settings.database_path == "data/bera_price_tracker.db"
    assert settings.ollama_base_url == DEFAULT_OLLAMA_BASE_URL
    assert settings.ollama_model == DEFAULT_OLLAMA_MODEL
    assert settings.ollama_timeout_seconds == DEFAULT_OLLAMA_TIMEOUT_SECONDS
    assert settings.brightdata_api_token is None
    assert settings.brightdata_base_url == DEFAULT_BRIGHTDATA_BASE_URL
    assert settings.brightdata_dataset_id == DEFAULT_BRIGHTDATA_DATASET_ID
    assert settings.facebook_city == DEFAULT_FACEBOOK_CITY
    assert settings.facebook_record_limit == DEFAULT_FACEBOOK_RECORD_LIMIT
    assert settings.apify_api_token is None
    assert settings.azure_translator_key is None
    assert settings.azure_translator_endpoint == DEFAULT_AZURE_TRANSLATOR_ENDPOINT
    assert settings.azure_translator_region is None
    assert settings.azure_translator_timeout_seconds == DEFAULT_AZURE_TRANSLATOR_TIMEOUT_SECONDS
    assert settings.azure_translator_configured() is False
    assert settings.translator_provider is None
    assert settings.deepl_api_key is None
    assert settings.deepl_api_endpoint == DEFAULT_DEEPL_API_ENDPOINT
    assert settings.deepl_timeout_seconds == DEFAULT_DEEPL_TIMEOUT_SECONDS
    assert settings.deepl_translator_configured() is False
    assert settings.resolved_translator_provider() == "disabled"
    assert settings.product_translator_configured() is False


def test_blank_database_path_is_rejected() -> None:
    with pytest.raises(ValueError, match="database_path"):
        Settings.from_env({"BERA_TRACKER_DATABASE_PATH": "  "})


def test_invalid_log_level_is_rejected() -> None:
    with pytest.raises(ValueError, match="log_level"):
        Settings.from_env({"BERA_TRACKER_LOG_LEVEL": "verbose"})


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("BERA_TRACKER_MERCADOLIBRE_PAGE_SIZE", "0"),
        ("BERA_TRACKER_MERCADOLIBRE_PAGE_SIZE", "101"),
        ("BERA_TRACKER_MERCADOLIBRE_MAX_PAGES", "0"),
        ("BERA_TRACKER_MERCADOLIBRE_TIMEOUT_SECONDS", "0"),
        ("BERA_TRACKER_MERCADOLIBRE_TIMEOUT_SECONDS", "nan"),
        ("BERA_TRACKER_MERCADOLIBRE_MAX_RETRIES", "-1"),
        ("BERA_TRACKER_MERCADOLIBRE_MAX_RETRIES", "6"),
        ("BERA_TRACKER_MERCADOLIBRE_PAGE_SIZE", "not-an-integer"),
    ],
)
def test_invalid_mercado_libre_settings_are_rejected(name: str, value: str) -> None:
    with pytest.raises(ValueError):
        Settings.from_env({name: value})


@pytest.mark.parametrize(
    "base_url",
    [
        "",
        "https://ollama.com",
        "https://example.test:11434",
        "http://localhost:11434/api",
        "http://user:password@localhost:11434",
        "http://localhost:11434?query=yes",
        "not-a-url",
    ],
)
def test_ollama_base_url_rejects_non_loopback_or_malformed_values(base_url: str) -> None:
    with pytest.raises(ValueError, match="ollama_base_url"):
        Settings(ollama_base_url=base_url)


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("http://localhost:11434/", "http://localhost:11434"),
        ("http://127.0.0.1:11434", "http://127.0.0.1:11434"),
        ("http://[::1]:11434/", "http://[::1]:11434"),
    ],
)
def test_ollama_base_url_accepts_only_normalized_loopback_hosts(
    base_url: str,
    expected: str,
) -> None:
    assert Settings(ollama_base_url=base_url).ollama_base_url == expected


@pytest.mark.parametrize("model", ["", "   ", "model with spaces", "bad$model"])
def test_invalid_ollama_model_is_rejected(model: str) -> None:
    with pytest.raises(ValueError, match="ollama_model"):
        Settings(ollama_model=model)


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_ollama_timeout_is_rejected(timeout: float) -> None:
    with pytest.raises(ValueError, match="ollama_timeout_seconds"):
        Settings(ollama_timeout_seconds=timeout)


def test_invalid_ollama_timeout_environment_value_is_rejected() -> None:
    with pytest.raises(ValueError, match="BERA_TRACKER_OLLAMA_TIMEOUT_SECONDS"):
        Settings.from_env({"BERA_TRACKER_OLLAMA_TIMEOUT_SECONDS": "not-a-number"})


def test_invalid_bright_data_and_facebook_settings_are_rejected() -> None:
    invalid_environments = (
        {"BERA_TRACKER_BRIGHTDATA_BASE_URL": "https://api.example.test/path"},
        {"BERA_TRACKER_BRIGHTDATA_DATASET_ID": "   "},
        {"BERA_TRACKER_BRIGHTDATA_TIMEOUT_SECONDS": "nan"},
        {"BERA_TRACKER_BRIGHTDATA_POLL_INTERVAL_SECONDS": "0"},
        {"BERA_TRACKER_BRIGHTDATA_POLL_TIMEOUT_SECONDS": "-1"},
        {"BERA_TRACKER_FACEBOOK_CITY": "   "},
        {"BERA_TRACKER_FACEBOOK_RECORD_LIMIT": "0"},
        {"BERA_TRACKER_FACEBOOK_RECORD_LIMIT": "6"},
    )

    for environment in invalid_environments:
        with pytest.raises((TypeError, ValueError)):
            Settings.from_env(environment)


def test_mercado_libre_result_limit_is_bounded() -> None:
    with pytest.raises(ValueError, match="1000"):
        Settings.from_env(
            {
                "BERA_TRACKER_MERCADOLIBRE_PAGE_SIZE": "100",
                "BERA_TRACKER_MERCADOLIBRE_MAX_PAGES": "11",
            }
        )


@pytest.mark.parametrize("site_id", ["MLV", "mlv", " MLV ", "MLB-TEST", "MCO_1"])
def test_valid_mercado_libre_site_ids_are_recognized(site_id: str) -> None:
    assert is_valid_mercadolibre_site_id(site_id) is True


@pytest.mark.parametrize("site_id", [None, "", "   ", "bad site", "MLV!", "MLV/"])
def test_invalid_mercado_libre_site_ids_are_rejected(site_id: str | None) -> None:
    assert is_valid_mercadolibre_site_id(site_id) is False


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://api.cognitive.microsofttranslator.com",
        "https://user:pass@translator.example.test",
        "https://translator.example.test?api-version=3.0",
        "not-a-url",
    ],
)
def test_invalid_azure_translator_endpoint_is_rejected(endpoint: str) -> None:
    with pytest.raises((TypeError, ValueError), match="azure_translator_endpoint"):
        Settings.from_env({"BERA_TRACKER_AZURE_TRANSLATOR_ENDPOINT": endpoint})


def test_blank_azure_translator_endpoint_uses_default() -> None:
    settings = Settings.from_env({"BERA_TRACKER_AZURE_TRANSLATOR_ENDPOINT": "  "})
    assert settings.azure_translator_endpoint == DEFAULT_AZURE_TRANSLATOR_ENDPOINT


def test_blank_azure_translator_key_is_not_configured() -> None:
    settings = Settings.from_env({"BERA_TRACKER_AZURE_TRANSLATOR_KEY": "  "})
    assert settings.azure_translator_key is None
    assert settings.azure_translator_configured() is False


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://api-free.deepl.com",
        "https://user:pass@api-free.deepl.com",
        "https://api-free.deepl.com?auth_key=secret",
        "not-a-url",
    ],
)
def test_invalid_deepl_endpoint_is_rejected(endpoint: str) -> None:
    with pytest.raises((TypeError, ValueError), match="deepl_api_endpoint"):
        Settings.from_env({"BERA_TRACKER_DEEPL_API_ENDPOINT": endpoint})


def test_blank_deepl_endpoint_uses_free_default() -> None:
    settings = Settings.from_env({"BERA_TRACKER_DEEPL_API_ENDPOINT": "  "})
    assert settings.deepl_api_endpoint == DEFAULT_DEEPL_API_ENDPOINT


def test_blank_deepl_key_is_not_configured() -> None:
    settings = Settings.from_env({"BERA_TRACKER_DEEPL_API_KEY": "  "})
    assert settings.deepl_api_key is None
    assert settings.deepl_translator_configured() is False


def _memo23_tilde_search_actor() -> str:
    return "~".join(("memo23", "alibaba-scraper"))


def _legacy_alibaba_search_actor(*, tilde: bool = False) -> str:
    separator = "~" if tilde else "/"
    return separator.join(("scraper-engine", "alibaba-scraper"))


def test_normalize_alibaba_search_actor_accepts_only_memo23() -> None:
    assert (
        normalize_alibaba_search_actor(f"  {DEFAULT_APIFY_ALIBABA_ACTOR}  ")
        == DEFAULT_APIFY_ALIBABA_ACTOR
    )
    with pytest.raises(ValueError, match="apify_alibaba_actor must not be blank"):
        normalize_alibaba_search_actor("  ")
    with pytest.raises(ValueError, match="Unsupported Alibaba SEARCH Actor"):
        normalize_alibaba_search_actor("custom/incompatible-alibaba-actor")
    with pytest.raises(ValueError, match="Unsupported Alibaba SEARCH Actor"):
        Settings.from_env({_alibaba_search_actor_env(): "custom/incompatible-alibaba-actor"})


def test_normalize_alibaba_search_actor_canonicalizes_supported_tilde_alias() -> None:
    tilde = _memo23_tilde_search_actor()
    assert normalize_alibaba_search_actor(tilde) == DEFAULT_APIFY_ALIBABA_ACTOR
    assert normalize_alibaba_search_actor(f"  {tilde}  ") == DEFAULT_APIFY_ALIBABA_ACTOR
    settings = Settings.from_env({_alibaba_search_actor_env(): f"  {tilde}  "})
    assert settings.apify_alibaba_actor == DEFAULT_APIFY_ALIBABA_ACTOR
    assert settings.apify_alibaba_actor != tilde


@pytest.mark.parametrize(
    "actor",
    [
        _legacy_alibaba_search_actor(),
        _legacy_alibaba_search_actor(tilde=True),
        "/".join(("other", "alibaba-scraper")),
        "~".join(("other", "alibaba-scraper")),
        "/".join(("memo23", "other")),
        "a1b2c3d4e5f6g7h8i9j0",
        "",
        "  ",
    ],
)
def test_normalize_alibaba_search_actor_rejects_unsupported_forms(actor: str) -> None:
    with pytest.raises(ValueError, match="apify_alibaba_actor must not be blank|Unsupported"):
        normalize_alibaba_search_actor(actor)
    if actor.strip():
        with pytest.raises(ValueError, match="Unsupported Alibaba SEARCH Actor"):
            Settings.from_env({_alibaba_search_actor_env(): actor})


def test_alibaba_refresh_actor_override_does_not_change_search_actor() -> None:
    settings = Settings.from_env(
        {"BERA_TRACKER_APIFY_ALIBABA_REFRESH_ACTOR": "custom/alibaba-refresh-actor"}
    )
    assert settings.apify_alibaba_actor == DEFAULT_APIFY_ALIBABA_ACTOR
    assert settings.apify_alibaba_refresh_actor == "custom/alibaba-refresh-actor"


def _alibaba_search_actor_env() -> str:
    return "_".join(("BERA_TRACKER", "APIFY", "ALIBABA", "ACTOR"))
