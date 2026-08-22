"""Reflex application entry for BERA Price Tracker."""

from __future__ import annotations

import reflex as rx

from bera_price_tracker.gui.views import dashboard

GOOGLE_FONTS = (
    "https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,650"
    "&family=IBM+Plex+Sans:wght@400;500;600&display=swap"
)

app = rx.App(
    stylesheets=[GOOGLE_FONTS],
    style={
        "font_family": "'IBM Plex Sans', 'Segoe UI', sans-serif",
        "background_color": "#f3eee4",
        "color": "#1a1814",
    },
)
app.add_page(dashboard, route="/", title="BERA Price Tracker")
