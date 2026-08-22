"""Integration tests for the installed module entry point."""

import os
import subprocess
import sys

import httpx
import pytest

from bera_price_tracker.application import MarketplaceProvider
from bera_price_tracker.cli import main
from bera_price_tracker.config import Settings
from bera_price_tracker.infrastructure.providers import MercadoLibreProvider


def test_module_help_is_executable() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "bera_price_tracker", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "search" in completed.stdout
    assert "collect" in completed.stdout
    assert "doctor" in completed.stdout
    assert "inspect" in completed.stdout
    assert "history" in completed.stdout
    assert "stats" in completed.stdout


def test_doctor_help_is_executable() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "bera_price_tracker", "doctor", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "usage: bera-price-tracker doctor" in completed.stdout
    assert "--help" in completed.stdout


def test_collect_requires_a_query() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "bera_price_tracker", "collect"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "query" in completed.stderr


def test_inspect_help_is_executable() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "bera_price_tracker", "inspect", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "query" in completed.stdout
    assert "--source" in completed.stdout
    assert "--limit" in completed.stdout


def test_inspect_requires_a_query() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "bera_price_tracker", "inspect"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "query" in completed.stderr


def test_history_requires_an_external_id() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "bera_price_tracker", "history"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "external_id" in completed.stderr


def test_stats_requires_an_external_id() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "bera_price_tracker", "stats"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "external_id" in completed.stderr


def test_search_reports_that_providers_are_not_configured() -> None:
    environment = os.environ.copy()
    environment.pop("BERA_TRACKER_MERCADOLIBRE_SITE_ID", None)
    environment.pop("BERA_TRACKER_MERCADOLIBRE_ACCESS_TOKEN", None)
    completed = subprocess.run(
        [sys.executable, "-m", "bera_price_tracker", "search", "pastillas bera"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 2
    assert "Configuration error" in completed.stderr
    assert "SITE_ID" in completed.stderr


def test_cli_search_uses_real_provider_with_mock_http(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("BERA_TRACKER_MERCADOLIBRE_SITE_ID", "MLV")
    monkeypatch.setenv("BERA_TRACKER_MERCADOLIBRE_ACCESS_TOKEN", "offline-token")

    clients: list[httpx.Client] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["q"] == "pastillas de freno bera"
        return httpx.Response(
            200,
            json={
                "paging": {"total": 1},
                "results": [
                    {
                        "id": "MLV-CLI",
                        "title": "Pastillas BERA CLI",
                        "price": 19.99,
                        "currency_id": "USD",
                        "permalink": "https://articulo.example/MLV-CLI",
                    }
                ],
            },
            request=request,
        )

    def factory(settings: Settings) -> MarketplaceProvider:
        client = httpx.Client(transport=httpx.MockTransport(handler))
        clients.append(client)
        return MercadoLibreProvider(
            site_id=settings.mercadolibre_site_id,
            access_token=settings.mercadolibre_access_token,
            page_size=settings.mercadolibre_page_size,
            max_pages=settings.mercadolibre_max_pages,
            timeout_seconds=settings.mercadolibre_timeout_seconds,
            max_retries=settings.mercadolibre_max_retries,
            client=client,
            sleeper=lambda _: None,
            jitter=lambda: 0.0,
        )

    try:
        exit_code = main(
            ["search", "pastillas de freno bera"],
            provider_factory=factory,
        )
    finally:
        for client in clients:
            client.close()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "ID: MLV-CLI" in captured.out
    assert "Pastillas BERA CLI" in captured.out
    assert "19.99 USD" in captured.out
    assert "https://articulo.example/MLV-CLI" in captured.out
    assert captured.err == ""
