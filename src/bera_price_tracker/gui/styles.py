"""Design tokens for the BERA executive marketplace dashboard.

Visual language: shadcn dashboard-01 + Cruip Mosaic density.
One system — no mixed radii, no decorative gradients.
"""

from __future__ import annotations

# Sidebar — light shell (reference A/B)
SIDEBAR_BG = "#F8FAFC"
SIDEBAR_SURFACE = "#EEF2FF"
SIDEBAR_TEXT = "#0F172A"
SIDEBAR_MUTED = "#64748B"
SIDEBAR_ACTIVE_BG = "#EEF2FF"
SIDEBAR_ACTIVE_TEXT = "#4F46E5"
SIDEBAR_BORDER = "#E5E7EB"
SIDEBAR_WIDTH = "220px"
SIDEBAR_WIDTH_COLLAPSED = "72px"
TOPBAR_HEIGHT = "56px"
TOPBAR_BG = "#FFFFFF"

# Workspace
WORKSPACE_BG = "#F8FAFC"
SURFACE = "#FFFFFF"
BORDER = "#E5E7EB"
BORDER_STRONG = "#D1D5DB"
SHADOW = "0 1px 2px rgba(15, 23, 42, 0.04)"
RADIUS = "8px"
RADIUS_SM = "8px"
CONTROL_HEIGHT = "44px"
STAR = "#F59E0B"
STAR_EMPTY = "#D1D5DB"
RANGE_STRIP_BG = "#F1F5F9"

# Text
TEXT_PRIMARY = "#111827"
TEXT_SECONDARY = "#4B5563"
TEXT_MUTED = "#6B7280"

# BERA primary action (indigo / violet)
PRIMARY = "#4F46E5"
PRIMARY_HOVER = "#4338CA"
PRIMARY_TEXT = "#FFFFFF"
FOCUS = "#4F46E5"
ACCENT = PRIMARY
ACCENT_ACTIVE = "#3730A3"
TAB_HOVER_BG = "rgba(79, 70, 229, 0.06)"

# Semantic
POSITIVE = "#15803D"
POSITIVE_BG = "#DCFCE7"
DANGER = "#B91C1C"
DANGER_BG = "#FEE2E2"
WARNING = "#A16207"

# Marketplace accents — identification only, never full-card fills
ALIBABA = "#C2410C"
FACEBOOK = "#1D4ED8"
MERCADOLIBRE = "#A16207"

# Backward-compatible aliases used by existing views
PAPER = WORKSPACE_BG
BUTTON = PRIMARY
BUTTON_HOVER = PRIMARY_HOVER
BUTTON_TEXT = PRIMARY_TEXT

INPUT_STYLE: dict[str, object] = {
    "background_color": SURFACE,
    "color": TEXT_PRIMARY,
    "border": f"1px solid {BORDER_STRONG}",
    "border_radius": RADIUS_SM,
    "height": CONTROL_HEIGHT,
    "min_height": CONTROL_HEIGHT,
    "font_size": "14px",
    "padding_x": "12px",
    "_placeholder": {"color": TEXT_MUTED},
    "_focus": {
        "border_color": FOCUS,
        "box_shadow": f"0 0 0 2px {FOCUS}",
        "outline": "none",
    },
}

SELECT_STYLE: dict[str, object] = {
    "background_color": SURFACE,
    "color": TEXT_PRIMARY,
    "border": f"1px solid {BORDER_STRONG}",
    "border_radius": RADIUS_SM,
    "height": CONTROL_HEIGHT,
    "min_height": CONTROL_HEIGHT,
    "font_size": "14px",
    "_placeholder": {"color": TEXT_MUTED},
    "_focus": {
        "border_color": FOCUS,
        "box_shadow": f"0 0 0 2px {FOCUS}",
        "outline": "none",
    },
}

LABEL_STYLE: dict[str, object] = {
    "color": TEXT_SECONDARY,
    "font_size": "12px",
    "font_weight": "600",
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
    "border_radius": RADIUS_SM,
    "height": CONTROL_HEIGHT,
    "min_height": CONTROL_HEIGHT,
    "font_size": "14px",
    "font_weight": "600",
    "cursor": "pointer",
    "transition": "background-color 160ms ease",
    "_hover": {
        "background": BUTTON_HOVER,
    },
    "_focus": {
        "box_shadow": f"0 0 0 2px {WORKSPACE_BG}, 0 0 0 4px {FOCUS}",
        "outline": "none",
    },
}

OUTLINE_BUTTON_STYLE: dict[str, object] = {
    "background": SURFACE,
    "color": PRIMARY,
    "border": f"1px solid {PRIMARY}",
    "border_radius": RADIUS_SM,
    "height": CONTROL_HEIGHT,
    "min_height": CONTROL_HEIGHT,
    "font_size": "14px",
    "font_weight": "600",
    "cursor": "pointer",
    "transition": "background-color 160ms ease, border-color 160ms ease",
    "_hover": {
        "background": "#EEF2FF",
        "border_color": PRIMARY_HOVER,
        "color": PRIMARY_HOVER,
    },
    "_focus": {
        "box_shadow": f"0 0 0 2px {WORKSPACE_BG}, 0 0 0 4px {FOCUS}",
        "outline": "none",
    },
}

SECONDARY_BUTTON_STYLE: dict[str, object] = {
    "background": SURFACE,
    "color": TEXT_PRIMARY,
    "border": f"1px solid {BORDER_STRONG}",
    "border_radius": RADIUS_SM,
    "height": CONTROL_HEIGHT,
    "min_height": CONTROL_HEIGHT,
    "font_size": "14px",
    "font_weight": "600",
    "cursor": "pointer",
    "transition": "background-color 160ms ease, border-color 160ms ease",
    "_hover": {
        "background": WORKSPACE_BG,
        "border_color": TEXT_MUTED,
    },
    "_focus": {
        "box_shadow": f"0 0 0 2px {WORKSPACE_BG}, 0 0 0 4px {FOCUS}",
        "outline": "none",
    },
}

CARD_STYLE: dict[str, object] = {
    "background_color": SURFACE,
    "border": f"1px solid {BORDER}",
    "border_radius": RADIUS,
    "box_shadow": SHADOW,
    "padding": "14px 16px",
}

SURFACE_STYLE: dict[str, object] = {
    "background_color": SURFACE,
    "border": f"1px solid {BORDER}",
    "border_radius": RADIUS,
    "box_shadow": SHADOW,
}

SELECTED_CARD_STYLE: dict[str, object] = {
    "background_color": "rgba(79, 70, 229, 0.06)",
    "border": f"1px solid {PRIMARY}",
    "border_radius": RADIUS_SM,
    "box_shadow": "none",
}

UNSELECTED_CARD_STYLE: dict[str, object] = {
    "background_color": SURFACE,
    "border": f"1px solid {BORDER_STRONG}",
    "border_radius": RADIUS_SM,
    "box_shadow": "none",
}

CALLOUT_STYLE: dict[str, object] = {
    "background_color": "#EEF2FF",
    "border": "1px solid #C7D2FE",
    "border_radius": RADIUS_SM,
    "padding": "10px 12px",
}
