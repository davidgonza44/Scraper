# mypy: disable-error-code="no-untyped-def,type-arg"
"""Offline GUI startup: import, local Reflex config, no live clients."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_gui_imports_without_token(monkeypatch):
    monkeypatch.delenv("BERA_TRACKER_APIFY_API_TOKEN", raising=False)
    monkeypatch.delenv("BERA_TRACKER_BRIGHTDATA_API_TOKEN", raising=False)
    from bera_price_tracker.gui.app import app
    from bera_price_tracker.gui.state import TrackerState

    assert app is not None
    state = TrackerState()
    assert state.query
    assert state.ui_status == "INITIAL"


def test_rxconfig_is_local_loopback():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    rxconfig = importlib.import_module("rxconfig")
    importlib.reload(rxconfig)
    cfg = rxconfig.config
    assert cfg.app_name == "gui"
    assert cfg.app_module_import == "bera_price_tracker.gui.app"
    assert cfg.frontend_port == 3000
    assert cfg.backend_port == 8000
    assert cfg.backend_host == "127.0.0.1"
    assert cfg.api_url == "http://127.0.0.1:8000"
    assert cfg.telemetry_enabled is False
    from reflex.plugins import SitemapPlugin

    assert SitemapPlugin in cfg.disable_plugins
    assert all(not isinstance(item, str) for item in cfg.disable_plugins)


def test_gui_row_models_are_pydantic_not_rx_base() -> None:
    import reflex as rx
    from pydantic import BaseModel

    from bera_price_tracker.gui.state import AlibabaResultRow, DetailItem, GuiModel

    assert issubclass(GuiModel, BaseModel)
    assert issubclass(DetailItem, GuiModel)
    assert issubclass(AlibabaResultRow, GuiModel)
    assert not issubclass(DetailItem, rx.Base)
    row = AlibabaResultRow(title="mouse", score_value=80)
    copied = row.model_copy(update={"score_value": 90})
    assert copied.score_value == 90
    assert row.score_value == 80


def test_node_lts_pin_files() -> None:
    nvmrc = (ROOT / ".nvmrc").read_text(encoding="utf-8").strip()
    node_version = (ROOT / ".node-version").read_text(encoding="utf-8").strip()
    assert nvmrc == "24"
    assert node_version == "24"


def test_import_does_not_construct_apify_client():
    code = """
from unittest.mock import patch
with patch('apify_client.ApifyClient') as client_cls:
    from bera_price_tracker.gui.app import app
    from bera_price_tracker.gui.state import TrackerState
    assert app is not None
    assert TrackerState is not None
    client_cls.assert_not_called()
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env.pop("BERA_TRACKER_APIFY_API_TOKEN", None)
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout


def test_empty_env_does_not_break_settings_or_gui_import():
    from bera_price_tracker.config import Settings
    from bera_price_tracker.gui.app import app

    settings = Settings.from_env({})
    assert settings.apify_api_token is None
    assert app is not None
