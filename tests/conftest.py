"""Shared pytest fixtures. Isolate local ``.env`` from developer machines."""

from __future__ import annotations

import pytest

_TRANSLATOR_ENV = (
    "BERA_TRACKER_TRANSLATOR_PROVIDER",
    "BERA_TRACKER_DEEPL_API_KEY",
    "BERA_TRACKER_DEEPL_API_ENDPOINT",
    "BERA_TRACKER_DEEPL_TIMEOUT_SECONDS",
    "BERA_TRACKER_AZURE_TRANSLATOR_KEY",
    "BERA_TRACKER_AZURE_TRANSLATOR_ENDPOINT",
    "BERA_TRACKER_AZURE_TRANSLATOR_REGION",
    "BERA_TRACKER_AZURE_TRANSLATOR_TIMEOUT_SECONDS",
)
_ALIBABA_SEARCH_ACTOR_ENV = "_".join(("BERA_TRACKER", "APIFY", "ALIBABA", "ACTOR"))


@pytest.fixture(autouse=True)
def isolate_local_dotenv(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Keep tests off the developer ``.env`` and inherited translator secrets."""

    missing = tmp_path_factory.mktemp("dotenv-isolation") / "absent.env"
    monkeypatch.setenv("BERA_TRACKER_DOTENV_PATH", str(missing))
    for name in _TRANSLATOR_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv(_ALIBABA_SEARCH_ACTOR_ENV, raising=False)
