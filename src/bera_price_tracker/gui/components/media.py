# mypy: disable-error-code="index,attr-defined,type-arg,arg-type,no-untyped-def,call-arg,func-returns-value"
"""Product thumbnail with a professional missing-image placeholder."""

from __future__ import annotations

import reflex as rx

from bera_price_tracker.gui import styles

PLACEHOLDER_LABEL = "Sin imagen"
DEFAULT_SIZE = "80px"


def product_thumbnail(
    image_url: object,
    *,
    alt: object = "",
    size: str = DEFAULT_SIZE,
) -> rx.Component:
    return rx.box(
        rx.cond(
            image_url != "",
            rx.el.img(
                src=image_url,
                alt=alt,
                class_name="bera-product-thumb-img",
                custom_attrs={
                    "onerror": (
                        "this.style.display='none';"
                        "if(this.nextElementSibling){this.nextElementSibling.style.display='flex';}"
                    )
                },
            ),
            rx.fragment(),
        ),
        rx.center(
            rx.text(PLACEHOLDER_LABEL, size="1", color=styles.TEXT_MUTED, weight="medium"),
            class_name="bera-product-thumb-fallback",
            display=rx.cond(image_url != "", "none", "flex"),
        ),
        class_name="bera-product-thumb",
        style={"width": size, "height": size, "min_width": size, "min_height": size},
        flex_shrink="0",
    )
