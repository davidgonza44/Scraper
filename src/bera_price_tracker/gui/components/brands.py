# mypy: disable-error-code="index,attr-defined,type-arg,arg-type,no-untyped-def,call-arg,func-returns-value,operator"
"""Local marketplace brand marks. Images from /brands only."""

from __future__ import annotations

import reflex as rx

from bera_price_tracker.gui import styles
from bera_price_tracker.gui.brands import (
    PLATFORM_ALIBABA,
    PLATFORM_FACEBOOK,
    PLATFORM_ML,
    brand_spec,
)


def marketplace_brand(
    platform: str,
    *,
    size: int = 24,
    show_name: bool = True,
    name_weight: str = "medium",
) -> rx.Component:
    spec = brand_spec(platform)
    mark = (
        rx.image(
            src=spec.src,
            alt=spec.alt,
            width=f"{size}px",
            height=f"{size}px",
            min_width=f"{size}px",
            object_fit="contain",
        )
        if spec.kind == "image"
        else rx.text(
            spec.label,
            size="2",
            weight="bold",
            color="#2D3277",
            line_height="1.2",
            white_space="nowrap",
        )
    )
    if spec.kind == "text":
        return mark
    if not show_name:
        return mark
    return rx.hstack(
        mark,
        rx.text(
            spec.label,
            size="2",
            weight=name_weight,
            color=styles.TEXT_PRIMARY,
            white_space="nowrap",
        ),
        spacing="2",
        align="center",
    )


def marketplace_brand_alibaba(*, size: int = 24, show_name: bool = True) -> rx.Component:
    return marketplace_brand(PLATFORM_ALIBABA, size=size, show_name=show_name)


def marketplace_brand_facebook(*, size: int = 24, show_name: bool = True) -> rx.Component:
    return marketplace_brand(PLATFORM_FACEBOOK, size=size, show_name=show_name)


def marketplace_brand_ml(*, size: int = 24, show_name: bool = True) -> rx.Component:
    return marketplace_brand(PLATFORM_ML, size=size, show_name=show_name)


def marketplace_brand_switch(platform_id: object, *, size: int = 24) -> rx.Component:
    return rx.cond(
        platform_id == PLATFORM_ALIBABA,
        marketplace_brand_alibaba(size=size),
        rx.cond(
            platform_id == PLATFORM_FACEBOOK,
            marketplace_brand_facebook(size=size),
            marketplace_brand_ml(size=size),
        ),
    )


def _tile_card(
    *,
    selected: object,
    on_click: object,
    mark: rx.Component,
    title: str,
    detail: str = "",
) -> rx.Component:
    inner = rx.hstack(
        mark,
        rx.vstack(
            rx.cond(
                title != "",
                rx.text(title, size="2", weight="medium", color=styles.TEXT_PRIMARY),
                rx.fragment(),
            ),
            rx.cond(
                detail != "",
                rx.text(detail, size="1", color=styles.TEXT_MUTED),
                rx.fragment(),
            ),
            spacing="0",
            align_items="start",
            min_width="0",
        ),
        rx.spacer(),
        rx.cond(
            selected,
            rx.center(
                rx.icon("check", size=12, color=styles.PRIMARY_TEXT),
                width="20px",
                height="20px",
                background=styles.PRIMARY,
                border_radius="999px",
            ),
            rx.box(
                width="20px",
                height="20px",
                border=f"1px solid {styles.BORDER_STRONG}",
                border_radius="999px",
                background=styles.SURFACE,
            ),
        ),
        width="100%",
        align="center",
        spacing="3",
    )
    return rx.cond(
        selected,
        rx.box(
            inner,
            on_click=on_click,
            padding="12px 14px",
            cursor="pointer",
            width="100%",
            **styles.SELECTED_CARD_STYLE,
        ),
        rx.box(
            inner,
            on_click=on_click,
            padding="12px 14px",
            cursor="pointer",
            width="100%",
            **styles.UNSELECTED_CARD_STYLE,
        ),
    )
