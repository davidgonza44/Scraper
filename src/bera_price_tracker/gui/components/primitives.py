# mypy: disable-error-code="index,attr-defined,type-arg,arg-type,no-untyped-def,call-arg,func-returns-value,operator"
"""Compact buttons, prices, badges, and empty states."""

from __future__ import annotations

import reflex as rx

from bera_price_tracker.gui import styles


def price_metric(value: object, *, color: str = styles.TEXT_PRIMARY) -> rx.Component:
    return rx.text(
        value,
        weight="bold",
        color=color,
        style={"font_size": "24px", "line_height": "1.15", "letter_spacing": "-0.02em"},
    )


def status_badge(label: object, *, tone: str = "neutral") -> rx.Component:
    colors = {
        "positive": (styles.POSITIVE, styles.POSITIVE_BG),
        "danger": (styles.DANGER, styles.DANGER_BG),
        "alibaba": (styles.ALIBABA, "#FFF7ED"),
        "facebook": (styles.FACEBOOK, "#EFF6FF"),
        "mercadolibre": (styles.MERCADOLIBRE, "#FEF9C3"),
        "neutral": (styles.TEXT_SECONDARY, styles.WORKSPACE_BG),
    }
    foreground, background = colors.get(tone, colors["neutral"])
    return rx.text(
        label,
        size="1",
        weight="medium",
        color=foreground,
        background_color=background,
        padding="2px 8px",
        border_radius="6px",
        white_space="nowrap",
    )


def action_button(
    label: str,
    *,
    on_click: object | None = None,
    href: object | None = None,
    variant: str = "primary",
    disabled: object = False,
    icon: str | None = None,
) -> rx.Component:
    if variant == "primary":
        style = styles.BUTTON_STYLE
    elif variant == "outline":
        style = styles.OUTLINE_BUTTON_STYLE
    else:
        style = styles.SECONDARY_BUTTON_STYLE
    content = (
        rx.hstack(rx.icon(icon, size=16), rx.text(label), spacing="2", align="center")
        if icon
        else rx.text(label)
    )
    if href is not None:
        return rx.link(
            content,
            href=href,
            is_external=True,
            **style,
            display="inline-flex",
            align_items="center",
            text_decoration="none",
        )
    kwargs: dict[str, object] = {**style, "disabled": disabled}
    if on_click is not None:
        kwargs["on_click"] = on_click
    return rx.button(content, **kwargs)


def empty_state(title: str, detail: str) -> rx.Component:
    return rx.box(
        rx.text(title, size="3", weight="medium", color=styles.TEXT_PRIMARY),
        rx.text(detail, size="2", color=styles.TEXT_MUTED, padding_top="4px"),
        padding="28px 8px",
        width="100%",
    )


def rating_stars(available: object, filled: object, label: object) -> rx.Component:
    def star(index: int) -> rx.Component:
        return rx.cond(
            filled >= index,
            rx.icon("star", size=12, color=styles.STAR),
            rx.icon("star", size=12, color=styles.STAR_EMPTY),
        )

    return rx.hstack(
        star(1),
        star(2),
        star(3),
        star(4),
        star(5),
        rx.cond(
            available,
            rx.text(label, size="1", color=styles.TEXT_SECONDARY),
            rx.text("Sin calificación", size="1", color=styles.TEXT_MUTED),
        ),
        spacing="1",
        align="center",
    )
