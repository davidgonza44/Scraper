"""Contrast tokens and reusable style dicts for the BERA Reflex GUI."""

from __future__ import annotations

TEXT_PRIMARY = "#1f2937"
TEXT_SECONDARY = "#374151"
TEXT_MUTED = "#6b7280"
ACCENT = "#0f766e"
ACCENT_ACTIVE = "#0f513f"
BORDER = "#d1d5db"
SURFACE = "#ffffff"
PAPER = "#f3eee4"
BUTTON = "#276749"
BUTTON_HOVER = "#1c4532"
BUTTON_TEXT = "#ffffff"
TAB_HOVER_BG = "rgba(15, 118, 110, 0.06)"
FOCUS = "#0f766e"

INPUT_STYLE: dict[str, object] = {
    "background_color": SURFACE,
    "color": TEXT_PRIMARY,
    "border": f"1px solid {BORDER}",
    "_placeholder": {"color": TEXT_MUTED},
    "_focus": {
        "border_color": FOCUS,
        "box_shadow": f"0 0 0 1px {FOCUS}",
    },
}

SELECT_STYLE: dict[str, object] = {
    "background_color": SURFACE,
    "color": TEXT_PRIMARY,
    "border": f"1px solid {BORDER}",
    "_placeholder": {"color": TEXT_MUTED},
    "_focus": {
        "border_color": FOCUS,
        "box_shadow": f"0 0 0 1px {FOCUS}",
    },
}

LABEL_STYLE: dict[str, object] = {
    "color": TEXT_SECONDARY,
}

TAB_TRIGGER_STYLE: dict[str, object] = {
    "color": TEXT_SECONDARY,
    "background": "transparent",
    "box_shadow": "none",
    "_hover": {
        "color": ACCENT,
        "background": TAB_HOVER_BG,
    },
}

TAB_TRIGGER_ACTIVE_STYLE: dict[str, object] = {
    "color": ACCENT_ACTIVE,
    "font_weight": "600",
    "border_bottom": f"3px solid {ACCENT}",
    "box_shadow": "none",
    "background": "transparent",
    "_hover": {
        "color": ACCENT,
        "background": TAB_HOVER_BG,
    },
}

BUTTON_STYLE: dict[str, object] = {
    "background": BUTTON,
    "color": BUTTON_TEXT,
    "_hover": {
        "background": BUTTON_HOVER,
    },
}
