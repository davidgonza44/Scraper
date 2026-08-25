"""Reflex application entry for BERA Price Tracker."""

from __future__ import annotations

import reflex as rx

from bera_price_tracker.config import load_local_environment
from bera_price_tracker.gui.views import dashboard

load_local_environment()

GOOGLE_FONTS = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"

app = rx.App(
    stylesheets=[GOOGLE_FONTS, "/bera.css"],
    style={
        "font_family": "Inter, 'Segoe UI', system-ui, sans-serif",
        "background_color": "#F8F9FB",
        "color": "#111827",
        "font_size": "14px",
        "line_height": "1.45",
    },
)
app.add_page(dashboard, route="/", title="BERA Tracker")
