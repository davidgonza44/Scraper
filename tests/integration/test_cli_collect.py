"""Offline integration coverage for CLI composition and collection."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from bera_price_tracker.application import MarketplaceProvider
from bera_price_tracker.cli import ExitCode, main
from bera_price_tracker.config import Settings
from bera_price_tracker.domain import ListingKey, MarketplaceSource
from bera_price_tracker.infrastructure.persistence import (
    PersistenceError,
    SQLiteListingHistoryRepository,
    SQLiteListingRepository,
)
from bera_price_tracker.infrastructure.providers import MercadoLibreProvider

QUERY = "pastillas de freno bera"
TOKEN = "offline-cli-secret-token"
FIRST_TIME = datetime(2026, 8, 21, 15, 0, tzinfo=UTC)
SECOND_TIME = datetime(2026, 8, 22, 15, 0, tzinfo=UTC)


def _payload(price_a: str = "19.99", price_b: str = "25.50") -> bytes:
    return (
        '{"paging":{"total":2},"results":['
        '{"id":"MLV-A","title":"Producto A","price":'
        f'{price_a},"currency_id":"VES","permalink":"https://example.test/MLV-A"}},'
        '{"id":"MLV-B","title":"Producto B","price":'
        f'{price_b},"currency_id":"VES","permalink":"https://example.test/MLV-B"}}'
        "]}"
    ).encode()


_EMPTY_PAYLOAD = b'{"paging":{"total":0},"results":[]}'


@dataclass(frozen=True, slots=True)
class ResponseSpec:
    collected_at: datetime
    content: bytes = _EMPTY_PAYLOAD
    status_code: int = 200
    timeout: bool = False


@dataclass(slots=True)
class OfflineProviderFactory:
    specs: list[ResponseSpec]
    clients: list[httpx.Client] = field(default_factory=list)
    calls: int = 0

    def __call__(self, settings: Settings) -> MarketplaceProvider:
        spec = self.specs[self.calls]
        self.calls += 1

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["q"] == QUERY
            if spec.timeout:
                raise httpx.ReadTimeout("offline timeout", request=request)
            return httpx.Response(
                spec.status_code,
                content=spec.content,
                headers={"Content-Type": "application/json"},
                request=request,
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        self.clients.append(client)

        def clock() -> datetime:
            return spec.collected_at

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
            clock=clock,
        )

    def close(self) -> None:
        for client in self.clients:
            client.close()


def _configure(
    monkeypatch: pytest.MonkeyPatch,
    database_path: Path,
    *,
    include_token: bool = True,
) -> None:
    monkeypatch.setenv("BERA_TRACKER_MERCADOLIBRE_SITE_ID", "MLV")
    if include_token:
        monkeypatch.setenv("BERA_TRACKER_MERCADOLIBRE_ACCESS_TOKEN", TOKEN)
    else:
        monkeypatch.delenv("BERA_TRACKER_MERCADOLIBRE_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("BERA_TRACKER_MERCADOLIBRE_MAX_RETRIES", "0")
    monkeypatch.setenv("BERA_TRACKER_DATABASE_PATH", str(database_path))


def test_invalid_settings_do_not_create_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "invalid-settings.db"
    _configure(monkeypatch, database_path)
    monkeypatch.setenv("BERA_TRACKER_MERCADOLIBRE_PAGE_SIZE", "0")

    exit_code = main(["collect", QUERY])

    captured = capsys.readouterr()
    assert exit_code == ExitCode.USAGE_OR_CONFIGURATION
    assert "Configuration error" in captured.err
    assert not database_path.exists()


def test_missing_token_is_validated_before_database_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "missing-token.db"
    _configure(monkeypatch, database_path, include_token=False)

    exit_code = main(["collect", QUERY])

    captured = capsys.readouterr()
    assert exit_code == ExitCode.USAGE_OR_CONFIGURATION
    assert "ACCESS_TOKEN" in captured.err
    assert not database_path.exists()


def test_search_remains_read_only_and_does_not_create_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "must-not-exist.db"
    _configure(monkeypatch, database_path)
    factory = OfflineProviderFactory([ResponseSpec(FIRST_TIME, _payload())])

    try:
        exit_code = main(["search", QUERY], provider_factory=factory)
    finally:
        factory.close()

    captured = capsys.readouterr()
    assert exit_code == ExitCode.SUCCESS
    assert "Producto A" in captured.out
    assert "19.99 VES" in captured.out
    assert not database_path.exists()


def test_collect_cli_wires_mock_http_application_and_sqlite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "collect.db"
    _configure(monkeypatch, database_path)
    factory = OfflineProviderFactory([ResponseSpec(FIRST_TIME, _payload())])

    try:
        exit_code = main(["collect", QUERY], provider_factory=factory)
    finally:
        factory.close()

    captured = capsys.readouterr()
    assert exit_code == ExitCode.SUCCESS
    assert database_path.is_file()
    assert "Query: pastillas de freno bera" in captured.out
    assert "Source: Mercado Libre" in captured.out
    assert "Collected: 2 listings" in captured.out
    assert str(database_path) in captured.out

    with SQLiteListingRepository(database_path) as repository:
        key_a = ListingKey(MarketplaceSource.MERCADO_LIBRE, "MLV-A")
        key_b = ListingKey(MarketplaceSource.MERCADO_LIBRE, "MLV-B")
        history_a = repository.get_price_history(key_a)
        history_b = repository.get_price_history(key_b)
        assert repository.count_listings() == 2
        assert repository.count_collection_runs() == 1
        assert repository.count_price_snapshots() == 2
        assert history_a[0].query.text == QUERY
        assert history_a[0].snapshot.listing_key.source is MarketplaceSource.MERCADO_LIBRE
        assert history_a[0].snapshot.price == Decimal("19.99")
        assert str(history_a[0].snapshot.price) == "19.99"
        assert history_b[0].snapshot.price == Decimal("25.50")
        assert str(history_b[0].snapshot.price) == "25.50"


def test_two_runs_preserve_changed_and_unchanged_prices_and_exact_retry_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "history.db"
    _configure(monkeypatch, database_path)
    factory = OfflineProviderFactory(
        [
            ResponseSpec(FIRST_TIME, _payload("19.99", "25.50")),
            ResponseSpec(SECOND_TIME, _payload("21.99", "25.50")),
            ResponseSpec(SECOND_TIME, _payload("21.99", "25.50")),
        ]
    )

    try:
        exit_codes = [
            main(["collect", QUERY], provider_factory=factory),
            main(["collect", QUERY], provider_factory=factory),
            main(["collect", QUERY], provider_factory=factory),
        ]
    finally:
        factory.close()

    capsys.readouterr()
    assert exit_codes == [ExitCode.SUCCESS, ExitCode.SUCCESS, ExitCode.SUCCESS]
    with SQLiteListingRepository(database_path) as repository:
        history_a = repository.get_price_history(
            ListingKey(MarketplaceSource.MERCADO_LIBRE, "MLV-A")
        )
        history_b = repository.get_price_history(
            ListingKey(MarketplaceSource.MERCADO_LIBRE, "MLV-B")
        )
        assert repository.count_listings() == 2
        assert repository.count_collection_runs() == 2
        assert repository.count_price_snapshots() == 4
        assert [entry.snapshot.price for entry in history_a] == [
            Decimal("19.99"),
            Decimal("21.99"),
        ]
        assert [entry.snapshot.price for entry in history_b] == [
            Decimal("25.50"),
            Decimal("25.50"),
        ]
        assert [entry.snapshot.collected_at for entry in history_a] == [
            FIRST_TIME,
            SECOND_TIME,
        ]


def test_zero_results_is_success_with_an_empty_collection_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "empty.db"
    _configure(monkeypatch, database_path)
    factory = OfflineProviderFactory([ResponseSpec(FIRST_TIME)])

    try:
        exit_code = main(
            ["collect", QUERY],
            provider_factory=factory,
            collection_clock=lambda: FIRST_TIME,
        )
    finally:
        factory.close()

    captured = capsys.readouterr()
    assert exit_code == ExitCode.SUCCESS
    assert "Collected: 0 listings" in captured.out
    with SQLiteListingRepository(database_path) as repository:
        assert repository.count_listings() == 0
        assert repository.count_collection_runs() == 1
        assert repository.count_price_snapshots() == 0


def test_nonempty_then_empty_cli_collections_preserve_both_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "nonempty-then-empty.db"
    _configure(monkeypatch, database_path)
    factory = OfflineProviderFactory(
        [
            ResponseSpec(FIRST_TIME, _payload()),
            ResponseSpec(SECOND_TIME),
        ]
    )

    try:
        first_exit = main(
            ["collect", QUERY],
            provider_factory=factory,
            collection_clock=lambda: SECOND_TIME,
        )
        empty_exit = main(
            ["collect", QUERY],
            provider_factory=factory,
            collection_clock=lambda: SECOND_TIME,
        )
    finally:
        factory.close()

    captured = capsys.readouterr()
    assert first_exit == ExitCode.SUCCESS
    assert empty_exit == ExitCode.SUCCESS
    assert "Collected: 2 listings" in captured.out
    assert "Collected: 0 listings" in captured.out
    with SQLiteListingRepository(database_path) as repository:
        assert repository.count_collection_runs() == 2
        assert repository.count_listings() == 2
        assert repository.count_price_snapshots() == 2


def test_http_401_maps_to_provider_exit_code_without_leaking_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    database_path = tmp_path / "unauthorized.db"
    _configure(monkeypatch, database_path)
    factory = OfflineProviderFactory([ResponseSpec(FIRST_TIME, status_code=401)])
    caplog.set_level(logging.DEBUG)

    try:
        exit_code = main(["collect", QUERY], provider_factory=factory)
    finally:
        factory.close()

    captured = capsys.readouterr()
    assert exit_code == ExitCode.PROVIDER_ERROR
    assert "authentication or authorization" in captured.err
    assert TOKEN not in captured.out
    assert TOKEN not in captured.err
    assert TOKEN not in caplog.text


def test_http_timeout_maps_to_provider_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "timeout.db"
    _configure(monkeypatch, database_path)
    factory = OfflineProviderFactory([ResponseSpec(FIRST_TIME, timeout=True)])

    try:
        exit_code = main(["collect", QUERY], provider_factory=factory)
    finally:
        factory.close()

    captured = capsys.readouterr()
    assert exit_code == ExitCode.PROVIDER_ERROR
    assert "timed out" in captured.err


def test_persistence_error_maps_to_distinct_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "persistence-error.db"
    _configure(monkeypatch, database_path)
    factory = OfflineProviderFactory([ResponseSpec(FIRST_TIME, _payload())])

    def failing_repository(_: Settings) -> SQLiteListingRepository:
        raise PersistenceError("forced offline persistence failure")

    try:
        exit_code = main(
            ["collect", QUERY],
            provider_factory=factory,
            repository_factory=failing_repository,
        )
    finally:
        factory.close()

    captured = capsys.readouterr()
    assert exit_code == ExitCode.PERSISTENCE_ERROR
    assert "Persistence error" in captured.err
    assert not database_path.exists()


def test_owned_http_client_and_sqlite_repository_are_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "owned-resources.db"
    _configure(monkeypatch, database_path)
    real_client = httpx.Client
    clients: list[httpx.Client] = []
    repositories: list[SQLiteListingRepository] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_EMPTY_PAYLOAD,
            headers={"Content-Type": "application/json"},
            request=request,
        )

    def client_factory(**_: object) -> httpx.Client:
        client = real_client(transport=httpx.MockTransport(handler))
        clients.append(client)
        return client

    def repository_factory(settings: Settings) -> SQLiteListingRepository:
        repository = SQLiteListingRepository(settings.database_path)
        repositories.append(repository)
        return repository

    monkeypatch.setattr(httpx, "Client", client_factory)

    exit_code = main(
        ["collect", QUERY],
        repository_factory=repository_factory,
    )

    assert exit_code == ExitCode.SUCCESS
    assert len(clients) == 1
    assert clients[0].is_closed
    assert len(repositories) == 1
    with pytest.raises(PersistenceError, match="closed"):
        repositories[0].count_listings()


def test_unexpected_error_has_stable_exit_code_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure(monkeypatch, tmp_path / "unexpected.db")

    def failing_provider(_: Settings) -> MarketplaceProvider:
        raise RuntimeError("internal test detail")

    exit_code = main(["collect", QUERY], provider_factory=failing_provider)

    captured = capsys.readouterr()
    assert exit_code == ExitCode.UNEXPECTED_ERROR
    assert "Unexpected error" in captured.err
    assert "Traceback" not in captured.err
    assert "internal test detail" not in captured.err


def test_facebook_collect_wires_bright_data_h0019_metrics_and_sqlite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "facebook.db"
    bright_data_token = "offline-bright-data-secret"
    monkeypatch.setenv("BERA_TRACKER_BRIGHTDATA_API_TOKEN", bright_data_token)
    monkeypatch.setenv("BERA_TRACKER_FACEBOOK_BACKEND", "brightdata")
    monkeypatch.setenv("BERA_TRACKER_DATABASE_PATH", str(database_path))
    real_client = httpx.Client
    requests: list[httpx.Request] = []
    clients: list[httpx.Client] = []
    payload = [
        {
            "product_id": "FB-1",
            "title": "Pastillas Honda CG125 ES4",
            "description": "Pastillas de freno H0019",
            "final_price": "10.25",
            "currency": "USD",
            "country_code": "VE",
            "url": "https://facebook.example/FB-1-old",
        },
        {
            "product_id": "FB-1",
            "title": "Pastillas Honda CG125 ES4 nuevas",
            "description": "Pastillas de freno compatibles",
            "final_price": "11.50",
            "currency": "VEF",
            "country_code": "VE",
            "url": "https://facebook.example/FB-1",
        },
        {
            "product_id": "FB-2",
            "title": "Faro Honda CG125 ES4",
            "final_price": "5",
            "currency": "USD",
            "country_code": "VE",
            "url": "https://facebook.example/FB-2",
        },
        {
            "product_id": "FB-3",
            "title": "Pastillas Kawasaki KLX125",
            "final_price": "7",
            "currency": "USD",
            "country_code": "CO",
            "url": "https://facebook.example/FB-3",
        },
        {"error": "Redirect to login page.", "error_code": "bad_input"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == f"Bearer {bright_data_token}"
        return httpx.Response(200, json=payload, request=request)

    def client_factory(**_: object) -> httpx.Client:
        client = real_client(transport=httpx.MockTransport(handler))
        clients.append(client)
        return client

    monkeypatch.setattr(httpx, "Client", client_factory)

    exit_code = main(
        [
            "collect",
            "pastilla bera sbr",
            "--provider",
            "facebook",
            "--city",
            "caracas",
            "--limit",
            "5",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == ExitCode.SUCCESS
    assert sum(request.method == "POST" for request in requests) == 1
    assert clients[0].is_closed
    assert "Source: Facebook Marketplace" in captured.out
    assert "fetched: 5" in captured.out
    assert "source_errors: 1" in captured.out
    assert "non_ve: 1" in captured.out
    assert "deterministic_relevant: 1" in captured.out
    assert "deterministic_irrelevant: 1" in captured.out
    assert "ai_requested: 0" in captured.out
    assert "duplicates: 1" in captured.out
    assert "persisted: 1" in captured.out
    assert bright_data_token not in captured.out
    assert bright_data_token not in captured.err

    with SQLiteListingRepository(database_path) as repository:
        key = ListingKey(MarketplaceSource.FACEBOOK_MARKETPLACE, "FB-1")
        history = repository.get_price_history(key)
        assert repository.count_collection_runs() == 1
        assert repository.count_listings() == 1
        assert repository.count_price_snapshots() == 1
        assert history[0].snapshot.price == Decimal("11.50")
        assert history[0].snapshot.currency == "VEF"
    with SQLiteListingHistoryRepository(database_path) as history_repository:
        listing_history = history_repository.get_history(key)
        assert listing_history is not None
        assert listing_history.title == "Pastillas Honda CG125 ES4 nuevas"
        assert not hasattr(listing_history, "description")


def _facebook_explain_payload() -> list[dict[str, object]]:
    return [
        {
            "product_id": "FB-1",
            "title": "Pastillas Honda CG125 ES4 escribe a ventas@example.test",
            "description": "Vendedor privado con perfil reservado",
            "final_price": "10.25",
            "currency": "USD",
            "country_code": "VE",
            "url": "https://facebook.example/FB-1",
            "cookies": "must-not-cross-boundary",
            "profile_id": "private-profile",
        },
        {
            "product_id": "FB-2",
            "title": "Faro Honda CG125 ES4",
            "final_price": "0",
            "currency": "USD",
            "country_code": "VE",
            "url": "https://facebook.example/FB-2",
        },
        {"error": "Redirect to login page.", "error_code": "bad_input"},
    ]


def test_facebook_explain_prints_sanitized_candidate_decisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "explain.db"
    bright_data_token = "offline-bright-data-secret"
    monkeypatch.setenv("BERA_TRACKER_BRIGHTDATA_API_TOKEN", bright_data_token)
    monkeypatch.setenv("BERA_TRACKER_FACEBOOK_BACKEND", "brightdata")
    monkeypatch.setenv("BERA_TRACKER_DATABASE_PATH", str(database_path))
    real_client = httpx.Client
    payload = _facebook_explain_payload()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    def client_factory(**_: object) -> httpx.Client:
        return real_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "Client", client_factory)

    exit_code = main(["collect", "pastilla bera sbr", "--provider", "facebook", "--explain"])

    captured = capsys.readouterr()
    assert exit_code == ExitCode.SUCCESS
    assert "Facebook candidate explanations:" in captured.out
    assert "decision: RELEVANT" in captured.out
    assert "price: 10.25 USD" in captured.out
    assert "source: deterministic" in captured.out
    assert "product_type: brake_pad" in captured.out
    assert "h0019_match: CG125 ES4" in captured.out
    assert "decision: SKIPPED" in captured.out
    assert "reason: invalid_price" in captured.out
    assert "reason: source_error: bad_input" in captured.out
    assert "[redacted]" in captured.out
    assert "ventas@example.test" not in captured.out
    assert "Vendedor privado" not in captured.out
    assert "must-not-cross-boundary" not in captured.out
    assert "private-profile" not in captured.out
    assert bright_data_token not in captured.out
    assert bright_data_token not in captured.err


def test_facebook_explain_leaves_classification_and_persistence_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plain_database = tmp_path / "plain.db"
    explained_database = tmp_path / "explained.db"
    monkeypatch.setenv("BERA_TRACKER_BRIGHTDATA_API_TOKEN", "offline-bright-data-secret")
    monkeypatch.setenv("BERA_TRACKER_FACEBOOK_BACKEND", "brightdata")
    real_client = httpx.Client
    requests: list[httpx.Request] = []
    payload = _facebook_explain_payload()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=payload, request=request)

    def client_factory(**_: object) -> httpx.Client:
        return real_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "Client", client_factory)

    monkeypatch.setenv("BERA_TRACKER_DATABASE_PATH", str(plain_database))
    plain_exit = main(["collect", "pastilla bera sbr", "--provider", "facebook"])
    plain_output = capsys.readouterr().out

    monkeypatch.setenv("BERA_TRACKER_DATABASE_PATH", str(explained_database))
    explained_exit = main(["collect", "pastilla bera sbr", "--provider", "facebook", "--explain"])
    explained_output = capsys.readouterr().out

    assert plain_exit == ExitCode.SUCCESS
    assert explained_exit == ExitCode.SUCCESS
    assert sum(request.method == "POST" for request in requests) == 2
    assert "Facebook candidate explanations:" not in plain_output
    assert "Facebook candidate explanations:" in explained_output
    assert "persisted: 1" in plain_output
    assert "persisted: 1" in explained_output
    assert "invalid_price: 1" in plain_output
    assert "invalid_price: 1" in explained_output
    with SQLiteListingRepository(plain_database) as repository:
        plain_counts = (repository.count_listings(), repository.count_price_snapshots())
    with SQLiteListingRepository(explained_database) as repository:
        explained_counts = (
            repository.count_listings(),
            repository.count_price_snapshots(),
        )
    assert plain_counts == explained_counts == (1, 1)


def test_facebook_cli_rejects_limit_above_mvp_cap_before_http_or_sqlite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "must-not-exist.db"
    monkeypatch.setenv("BERA_TRACKER_DATABASE_PATH", str(database_path))

    with pytest.raises(SystemExit) as raised:
        main(
            [
                "collect",
                "pastillas",
                "--provider",
                "facebook",
                "--limit",
                "6",
            ]
        )

    captured = capsys.readouterr()
    assert raised.value.code == ExitCode.USAGE_OR_CONFIGURATION
    assert "Facebook limit must be between 1 and 5" in captured.err
    assert not database_path.exists()
