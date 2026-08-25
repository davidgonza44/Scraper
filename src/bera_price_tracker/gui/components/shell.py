# mypy: disable-error-code="index,attr-defined,type-arg,arg-type,no-untyped-def,call-arg,func-returns-value,operator"
"""Light sidebar + compact top bar matching the search references."""

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
        "padding": "8px 10px",
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
                rx.icon(icon, size=16, color=styles.PRIMARY),
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
                rx.icon(icon, size=16, color=styles.SIDEBAR_MUTED),
                rx.text(label, class_name="bera-nav-label"),
                spacing="3",
                align="center",
            ),
            on_click=_nav_click(view),
            background_color="transparent",
            color=styles.SIDEBAR_TEXT,
            _hover={"background_color": styles.SIDEBAR_ACTIVE_BG, "color": styles.PRIMARY},
            **base,
        ),
    )


def sidebar() -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.center(
                    rx.icon("box", size=16, color=styles.PRIMARY_TEXT),
                    width="28px",
                    height="28px",
                    background=styles.PRIMARY,
                    border_radius="6px",
                ),
                rx.vstack(
                    rx.text(
                        "BERA Tracker",
                        weight="bold",
                        color=styles.SIDEBAR_TEXT,
                        class_name="bera-nav-label",
                        style={"font_size": "15px", "letter_spacing": "-0.02em"},
                    ),
                    spacing="0",
                    align_items="start",
                ),
                spacing="2",
                align="center",
                padding_bottom="16px",
                border_bottom=f"1px solid {styles.SIDEBAR_BORDER}",
                width="100%",
            ),
            rx.vstack(
                *[nav_item(item.view, item.label, item.icon) for item in NAV_ITEMS],
                spacing="1",
                width="100%",
                padding_top="12px",
                align_items="stretch",
            ),
            rx.spacer(),
            rx.box(
                rx.hstack(
                    rx.box(
                        width="8px",
                        height="8px",
                        border_radius="999px",
                        background_color=styles.POSITIVE,
                    ),
                    rx.text(
                        "Offline", size="1", color=styles.SIDEBAR_MUTED, class_name="bera-nav-label"
                    ),
                    spacing="2",
                    align="center",
                ),
                padding_top="12px",
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
        padding="16px 12px",
        height="100vh",
        position="sticky",
        top="0",
        border_right=f"1px solid {styles.SIDEBAR_BORDER}",
        class_name="bera-sidebar",
    )


def topbar() -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.hstack(
                rx.center(
                    rx.icon("box", size=14, color=styles.PRIMARY_TEXT),
                    width="24px",
                    height="24px",
                    background=styles.PRIMARY,
                    border_radius="6px",
                ),
                rx.text("BERA Tracker", weight="bold", color=styles.TEXT_PRIMARY, size="3"),
                spacing="2",
                align="center",
            ),
            rx.spacer(),
            width="100%",
            align="center",
            height=styles.TOPBAR_HEIGHT,
            padding_x="20px",
        ),
        background_color=styles.TOPBAR_BG,
        border_bottom=f"1px solid {styles.BORDER}",
        height=styles.TOPBAR_HEIGHT,
        width="100%",
        class_name="bera-topbar",
    )


def app_shell(*children: rx.Component) -> rx.Component:
    return rx.box(
        sidebar(),
        rx.box(
            topbar(),
            rx.box(
                *children,
                width="100%",
                max_width="1440px",
                margin="0 auto",
                padding="16px 20px 28px",
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
