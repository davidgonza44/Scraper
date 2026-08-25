# mypy: disable-error-code="index,attr-defined,type-arg,arg-type,no-untyped-def,call-arg,func-returns-value"
"""Product thumbnail with a professional missing-image placeholder."""

from __future__ import annotations

import reflex as rx

from bera_price_tracker.gui import styles

PLACEHOLDER_LABEL = "Sin imagen"


def product_thumbnail(
    image_url: object,
    *,
    alt: object = "",
    size: str = "72px",
) -> rx.Component:
    return rx.box(
        rx.cond(
            image_url != "",
            rx.image(
                src=image_url,
                alt=alt,
                width=size,
                height=size,
                object_fit="cover",
                border_radius=styles.RADIUS_SM,
            ),
            rx.center(
                rx.text(PLACEHOLDER_LABEL, size="1", color=styles.TEXT_MUTED, weight="medium"),
                width=size,
                height=size,
                background_color=styles.WORKSPACE_BG,
                border=f"1px dashed {styles.BORDER_STRONG}",
                border_radius=styles.RADIUS_SM,
            ),
        ),
        width=size,
        height=size,
        flex_shrink="0",
    )
