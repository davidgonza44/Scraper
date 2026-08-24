"""Unit tests for environment-backed settings."""

import pytest

from bera_price_tracker.config import (
    DEFAULT_APIFY_MERCADOLIBRE_ACTOR,
    DEFAULT_BRIGHTDATA_BASE_URL,
    DEFAULT_BRIGHTDATA_DATASET_ID,
    DEFAULT_FACEBOOK_CITY,
    DEFAULT_FACEBOOK_RECORD_LIMIT,
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_TIMEOUT_SECONDS,
    Settings,
    is_valid_mercadolibre_site_id,
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
    assert settings.apify_alibaba_refresh_actor == "xtracto/alibaba-product-scraper"
    assert settings.apify_alibaba_refresh_retries == 1
    assert settings.apify_alibaba_refresh_concurrency == 3
    assert settings.apify_mercadolibre_actor == DEFAULT_APIFY_MERCADOLIBRE_ACTOR
    assert "bright-secret" not in repr(settings)
    assert "apify-secret" not in repr(settings)


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
