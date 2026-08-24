"""Offline coverage for local ``.env`` bootstrap. Never contacts DeepL or Azure."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from bera_price_tracker.config import (
    DEFAULT_DEEPL_API_ENDPOINT,
    DEFAULT_DEEPL_TIMEOUT_SECONDS,
    Settings,
    default_dotenv_path,
    discover_project_root,
    load_local_environment,
    settings_from_process_env,
)

_PROVIDER_ENV = "BERA_TRACKER_TRANSLATOR_PROVIDER"
_DEEPL_KEY_ENV = "BERA_TRACKER_DEEPL_API_KEY"
_FILE_KEY = "file-deepl-key-never-print"
_PROCESS_KEY = "process-deepl-key-never-print"


def _write_env(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_missing_dotenv_does_not_fail(tmp_path: Path) -> None:
    missing = tmp_path / "absent.env"
    assert missing.is_file() is False
    assert load_local_environment(dotenv_path=missing) is None


def test_dotenv_provider_deepl_is_visible_after_bootstrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = _write_env(tmp_path / ".env", f"{_PROVIDER_ENV}=deepl\n")
    monkeypatch.delenv(_PROVIDER_ENV, raising=False)
    loaded = load_local_environment(dotenv_path=env_file)
    assert loaded == env_file
    settings = Settings.from_env()
    assert settings.translator_provider == "deepl"
    assert settings.resolved_translator_provider() == "deepl"


def test_dotenv_deepl_key_marks_translator_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = _write_env(
        tmp_path / ".env",
        f"{_PROVIDER_ENV}=deepl\n{_DEEPL_KEY_ENV}={_FILE_KEY}\n",
    )
    monkeypatch.delenv(_PROVIDER_ENV, raising=False)
    monkeypatch.delenv(_DEEPL_KEY_ENV, raising=False)
    load_local_environment(dotenv_path=env_file)
    settings = Settings.from_env()
    assert settings.deepl_translator_configured() is True
    assert settings.product_translator_configured() is True
    assert _FILE_KEY not in repr(settings)


def test_process_provider_wins_over_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = _write_env(tmp_path / ".env", f"{_PROVIDER_ENV}=deepl\n")
    monkeypatch.setenv(_PROVIDER_ENV, "azure")
    load_local_environment(dotenv_path=env_file)
    settings = Settings.from_env()
    assert settings.translator_provider == "azure"
    assert settings.resolved_translator_provider() == "azure"


def test_process_deepl_key_wins_over_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = _write_env(tmp_path / ".env", f"{_DEEPL_KEY_ENV}={_FILE_KEY}\n")
    monkeypatch.setenv(_DEEPL_KEY_ENV, _PROCESS_KEY)
    load_local_environment(dotenv_path=env_file)
    settings = Settings.from_env()
    assert settings.deepl_api_key == _PROCESS_KEY
    assert _FILE_KEY not in repr(settings)
    assert _PROCESS_KEY not in repr(settings)


def test_defaults_still_apply_after_comment_only_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = _write_env(tmp_path / ".env", "# local overrides only\n")
    monkeypatch.delenv(_PROVIDER_ENV, raising=False)
    monkeypatch.delenv(_DEEPL_KEY_ENV, raising=False)
    monkeypatch.delenv("BERA_TRACKER_DEEPL_API_ENDPOINT", raising=False)
    monkeypatch.delenv("BERA_TRACKER_DEEPL_TIMEOUT_SECONDS", raising=False)
    load_local_environment(dotenv_path=env_file)
    settings = Settings.from_env()
    assert settings.deepl_api_endpoint == DEFAULT_DEEPL_API_ENDPOINT
    assert settings.deepl_timeout_seconds == DEFAULT_DEEPL_TIMEOUT_SECONDS
    assert settings.translator_provider is None
    assert settings.resolved_translator_provider() == "disabled"


def test_secrets_stay_out_of_repr_logs_and_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    env_file = _write_env(
        tmp_path / ".env",
        f"{_PROVIDER_ENV}=deepl\n{_DEEPL_KEY_ENV}={_FILE_KEY}\n",
    )
    monkeypatch.delenv(_PROVIDER_ENV, raising=False)
    monkeypatch.delenv(_DEEPL_KEY_ENV, raising=False)
    with caplog.at_level(logging.DEBUG):
        load_local_environment(dotenv_path=env_file)
        settings = Settings.from_env()
    combined = caplog.text + repr(settings) + str(settings)
    assert _FILE_KEY not in combined
    with pytest.raises(ValueError, match="translator_provider"):
        Settings(translator_provider="not-a-provider")


def test_settings_from_env_does_not_read_dotenv_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = _write_env(
        tmp_path / ".env",
        f"{_PROVIDER_ENV}=deepl\n{_DEEPL_KEY_ENV}={_FILE_KEY}\n",
    )
    monkeypatch.setenv("BERA_TRACKER_DOTENV_PATH", str(env_file))
    monkeypatch.delenv(_PROVIDER_ENV, raising=False)
    monkeypatch.delenv(_DEEPL_KEY_ENV, raising=False)
    settings = Settings.from_env()
    assert settings.translator_provider is None
    assert settings.deepl_translator_configured() is False
    assert os.environ.get(_PROVIDER_ENV) is None
    assert os.environ.get(_DEEPL_KEY_ENV) is None


def test_importing_config_module_does_not_load_dotenv(tmp_path: Path) -> None:
    env_file = _write_env(tmp_path / ".env", f"{_PROVIDER_ENV}=deepl\n")
    code = (
        "import os\n"
        "from bera_price_tracker.config import Settings\n"
        "print('PROVIDER=' + str(os.environ.get('BERA_TRACKER_TRANSLATOR_PROVIDER')))\n"
        "print('SETTING=' + str(Settings.from_env().translator_provider))\n"
    )
    environment = os.environ.copy()
    environment["BERA_TRACKER_DOTENV_PATH"] = str(env_file)
    environment.pop(_PROVIDER_ENV, None)
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr
    assert "PROVIDER=None" in completed.stdout
    assert "SETTING=None" in completed.stdout


def test_settings_from_process_env_bootstraps_then_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = _write_env(
        tmp_path / ".env",
        f"{_PROVIDER_ENV}=deepl\n{_DEEPL_KEY_ENV}={_FILE_KEY}\n",
    )
    monkeypatch.setenv("BERA_TRACKER_DOTENV_PATH", str(env_file))
    monkeypatch.delenv(_PROVIDER_ENV, raising=False)
    monkeypatch.delenv(_DEEPL_KEY_ENV, raising=False)
    settings = settings_from_process_env()
    assert settings.resolved_translator_provider() == "deepl"
    assert settings.deepl_translator_configured() is True
    assert _FILE_KEY not in repr(settings)


def test_discover_project_root_walks_from_start(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='tmp'\n", encoding="utf-8")
    package = tmp_path / "src" / "bera_price_tracker"
    package.mkdir(parents=True)
    nested = package / "gui"
    nested.mkdir()
    assert discover_project_root(start=nested) == tmp_path
    assert discover_project_root(start=tmp_path / "missing") == tmp_path


def test_blank_dotenv_path_override_disables_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BERA_TRACKER_DOTENV_PATH", "  ")
    assert default_dotenv_path() is None
    assert load_local_environment() is None
