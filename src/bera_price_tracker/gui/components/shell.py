# mypy: disable-error-code="index,attr-defined,type-arg,arg-type,no-untyped-def,call-arg,func-returns-value,operator"
"""Dark sidebar + light workspace shell (shadcn dashboard-01 / Cruip Mosaic)."""

from __future__ import annotations

import reflex as rx

from bera_price_tracker.gui import styles
from bera_price_tracker.gui.navigation import NAV_ITEMS
from bera_price_tracker.gui.state import TrackerState


def _nav_click(view: str) -> object:
    return {
        "dashboard": TrackerState.show_dashboard,
        "searches": TrackerState.show_searches,
        "products": TrackerState.show_products,
        "comparisons": TrackerState.show_comparisons,
        "tracking": TrackerState.show_tracking,
        "import": TrackerState.show_import,
        "tools": TrackerState.show_tools,
        "settings": TrackerState.show_settings,
    }[view]


def nav_item(view: str, label: str, icon: str) -> rx.Component:
    active = TrackerState.workspace_view == view
    base = {
        "width": "100%",
        "justify_content": "flex-start",
        "padding": "9px 12px",
        "border_radius": styles.RADIUS_SM,
        "cursor": "pointer",
        "font_size": "14px",
        "font_weight": "500",
        "border": "none",
        "transition": "background-color 160ms ease",
    }
    return rx.cond(
        active,
        rx.button(
            rx.hstack(
                rx.icon(icon, size=16),
                rx.text(label, class_name="bera-nav-label"),
                spacing="3",
                align="center",
            ),
            on_click=_nav_click(view),
            background_color=styles.SIDEBAR_ACTIVE_BG,
            color=styles.SIDEBAR_ACTIVE_TEXT,
            **base,
        ),
        rx.button(
            rx.hstack(
                rx.icon(icon, size=16),
                rx.text(label, class_name="bera-nav-label"),
                spacing="3",
                align="center",
            ),
            on_click=_nav_click(view),
            background_color="transparent",
            color=styles.SIDEBAR_TEXT,
            _hover={"background_color": styles.SIDEBAR_SURFACE, "color": styles.SIDEBAR_TEXT},
            **base,
        ),
    )


def sidebar() -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.vstack(
                rx.text(
                    "BERA",
                    weight="bold",
                    color=styles.SIDEBAR_TEXT,
                    style={"font_size": "20px", "letter_spacing": "-0.03em"},
                ),
                rx.text(
                    "Inteligencia de compras e importación",
                    size="1",
                    color=styles.SIDEBAR_MUTED,
                    class_name="bera-nav-label",
                ),
                spacing="1",
                align_items="start",
                padding_bottom="18px",
                border_bottom=f"1px solid {styles.SIDEBAR_BORDER}",
                width="100%",
            ),
            rx.vstack(
                *[nav_item(item.view, item.label, item.icon) for item in NAV_ITEMS],
                spacing="1",
                width="100%",
                padding_top="14px",
                align_items="stretch",
            ),
            rx.spacer(),
            rx.box(
                rx.hstack(
                    rx.box(
                        rx.box(
                            width="8px",
                            height="8px",
                            border_radius="999px",
                            background_color=styles.POSITIVE,
                        ),
                        rx.text("Offline", size="1", color=styles.SIDEBAR_MUTED),
                        display="flex",
                        align_items="center",
                        gap="8px",
                    ),
                    width="100%",
                ),
                padding_top="16px",
                border_top=f"1px solid {styles.SIDEBAR_BORDER}",
                width="100%",
            ),
            spacing="0",
            height="100%",
            width="100%",
            align_items="stretch",
        ),
        background_color=styles.SIDEBAR_BG,
        color=styles.SIDEBAR_TEXT,
        width=styles.SIDEBAR_WIDTH,
        min_width=styles.SIDEBAR_WIDTH,
        padding="22px 16px",
        height="100vh",
        position="sticky",
        top="0",
        class_name="bera-sidebar",
    )


def app_shell(*children: rx.Component) -> rx.Component:
    return rx.box(
        sidebar(),
        rx.box(
            rx.box(
                *children,
                width="100%",
                max_width="1480px",
                margin="0 auto",
                padding="28px 28px 48px",
            ),
            background_color=styles.WORKSPACE_BG,
            min_height="100vh",
            flex="1",
            min_width="0",
            class_name="bera-workspace",
        ),
        display="flex",
        align_items="stretch",
        width="100%",
        min_height="100vh",
        background_color=styles.WORKSPACE_BG,
    )
