"""Reflex config for the BERA Price Tracker GUI.

Run from this directory (or from D:\\Scraper after copy):

    PYTHONPATH=src reflex run

Typical URL: http://localhost:3000

Frontend requires Node.js 24 LTS. See README for Windows PowerShell steps.

Do not leave reflex run running after checks. Do not collect live data.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from bera_price_tracker.config import load_local_environment  # noqa: E402

load_local_environment()

import reflex as rx  # noqa: E402
from reflex.plugins import SitemapPlugin  # noqa: E402

config = rx.Config(
    app_name="gui",
    app_module_import="bera_price_tracker.gui.app",
    frontend_port=3000,
    backend_port=8000,
    backend_host="127.0.0.1",
    api_url="http://127.0.0.1:8000",
    telemetry_enabled=False,
    disable_plugins=[SitemapPlugin],
)
