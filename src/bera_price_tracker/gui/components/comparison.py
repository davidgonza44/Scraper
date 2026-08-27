# mypy: disable-error-code="index,attr-defined,type-arg,arg-type,no-untyped-def,call-arg,func-returns-value,operator"
"""Horizontal same-product comparison matrix."""

from __future__ import annotations

import reflex as rx

from bera_price_tracker.gui import styles
from bera_price_tracker.gui.components.brands import (
    marketplace_brand_alibaba,
    marketplace_brand_facebook,
    marketplace_brand_ml,
)
from bera_price_tracker.gui.components.media import product_thumbnail
from bera_price_tracker.gui.components.primitives import (
    empty_state,
    price_metric,
    rating_stars,
    status_badge,
)
from bera_price_tracker.gui.state import TrackerState


def _listing_link(url: object, label: str = "Ver publicación") -> rx.Component:
    return rx.cond(
        url != "",
        rx.link(
            rx.hstack(
                rx.text(label, size="1", weight="medium"),
                rx.icon("external-link", size=12),
                spacing="1",
                align="center",
            ),
            href=url,
            is_external=True,
            color=styles.PRIMARY,
            padding_top="8px",
        ),
        rx.fragment(),
    )


def _empty_cell(label: str) -> rx.Component:
    return rx.box(
        rx.text(label, size="2", color=styles.TEXT_MUTED),
        padding="8px 0",
    )


def product_cell(row: rx.Var) -> rx.Component:
    return rx.hstack(
        rx.cond(
            row["comparison_kind"] == "positional",
            rx.fragment(),
            product_thumbnail(row["product_image_url"], alt=row["product_title"]),
        ),
        rx.vstack(
            rx.text(row["product_title"], size="2", weight="medium", color=styles.TEXT_PRIMARY),
            rx.text(row["product_subtitle"], size="1", color=styles.TEXT_MUTED),
            rx.cond(
                row["product_id"] != "",
                rx.text(row["product_id"], size="1", color=styles.TEXT_MUTED),
            ),
            rx.cond(
                row["comparison_kind"] == "positional",
                rx.fragment(),
                _listing_link(row["alibaba_url"], "Ver detalles"),
            ),
            spacing="1",
            align_items="start",
            min_width="0",
        ),
        spacing="3",
        align="start",
        min_width="220px",
    )


def marketplace_cell(
    *,
    has_listing: object,
    image_url: object,
    title: object,
    price: object,
    price_color: str,
    line_one: object,
    line_two: object,
    line_three: object,
    relevance: object,
    match_label: object,
    url: object,
    empty_label: str,
    rating_available: object = False,
    rating_filled: object = 0,
    rating_label: object = "Sin calificación",
    rating_caption: object = "",
    trust_line: object = "",
) -> rx.Component:
    return rx.cond(
        has_listing,
        rx.vstack(
            product_thumbnail(image_url, alt=title, size="80px"),
            rx.cond(
                title != "",
                rx.text(title, size="2", weight="medium", color=styles.TEXT_PRIMARY),
            ),
            price_metric(price, color=price_color),
            rx.cond(line_one != "", rx.text(line_one, size="1", color=styles.TEXT_MUTED)),
            rx.cond(line_two != "", rx.text(line_two, size="1", color=styles.TEXT_SECONDARY)),
            rx.cond(line_three != "", rx.text(line_three, size="1", color=styles.TEXT_SECONDARY)),
            rx.cond(
                rating_caption != "",
                rx.text(rating_caption, size="1", color=styles.TEXT_MUTED),
            ),
            rating_stars(rating_available, rating_filled, rating_label),
            rx.cond(trust_line != "", rx.text(trust_line, size="1", color=styles.TEXT_SECONDARY)),
            rx.cond(
                match_label != "",
                status_badge(match_label, tone="neutral"),
            ),
            rx.cond(
                relevance != "",
                rx.hstack(
                    rx.text("Relevancia", size="1", color=styles.TEXT_MUTED),
                    rx.text(relevance, size="1", color=styles.TEXT_MUTED),
                    spacing="1",
                ),
            ),
            _listing_link(url),
            spacing="1",
            align_items="start",
            min_width="190px",
        ),
        _empty_cell(empty_label),
    )


def opportunity_gauge(row: rx.Var) -> rx.Component:
    return rx.cond(
        row["opportunity_available"],
        rx.vstack(
            rx.box(
                rx.box(
                    rx.text(
                        row["opportunity_score"], size="3", weight="bold", color=styles.TEXT_PRIMARY
                    ),
                    rx.text("/100", size="1", color=styles.TEXT_MUTED),
                    class_name="bera-opportunity-inner",
                ),
                class_name="bera-opportunity-ring",
                style={"background": row["opportunity_ring"]},
            ),
            rx.text("Oportunidad Alibaba", size="1", color=styles.TEXT_MUTED),
            rx.cond(
                row["analysis_detail"] != "",
                rx.text(row["analysis_detail"], size="1", color=styles.TEXT_SECONDARY),
            ),
            spacing="1",
            align_items="center",
            min_width="120px",
        ),
        rx.text("Análisis no disponible", size="2", color=styles.TEXT_MUTED),
    )


def analysis_cell(row: rx.Var) -> rx.Component:
    return opportunity_gauge(row)


def comparison_row(row: rx.Var) -> rx.Component:
    return rx.box(
        product_cell(row),
        marketplace_cell(
            has_listing=row["alibaba_has_listing"],
            image_url=row["alibaba_image_url"],
            title=row["alibaba_title"],
            price=row["alibaba_price"],
            price_color=styles.ALIBABA,
            line_one=row["alibaba_range"],
            line_two=row["alibaba_moq"],
            line_three=row["alibaba_supplier"],
            relevance=row["alibaba_relevance"],
            match_label=row["alibaba_match_label"],
            url=row["alibaba_url"],
            empty_label="Sin resultado Alibaba",
            rating_available=row["alibaba_rating_available"],
            rating_filled=row["alibaba_rating_filled"],
            rating_label=row["alibaba_rating_label"],
            rating_caption=row["alibaba_rating_caption"],
            trust_line=row["alibaba_trust_line"],
        ),
        marketplace_cell(
            has_listing=row["facebook_has_listing"],
            image_url=row["facebook_image_url"],
            title=row["facebook_title"],
            price=row["facebook_price"],
            price_color=styles.FACEBOOK,
            line_one=row["facebook_usd_note"],
            line_two=row["facebook_source_note"],
            line_three=row["facebook_location"],
            relevance=row["facebook_relevance"],
            match_label=row["facebook_match_label"],
            url=row["facebook_url"],
            empty_label="Sin resultado Facebook",
            rating_available=row["facebook_rating_available"],
            rating_filled=row["facebook_rating_filled"],
            rating_label=row["facebook_rating_label"],
        ),
        marketplace_cell(
            has_listing=row["ml_has_listing"],
            image_url=row["ml_image_url"],
            title=row["ml_title"],
            price=row["ml_price"],
            price_color=styles.MERCADOLIBRE,
            line_one=row["ml_condition"],
            line_two=row["ml_seller"],
            line_three="",
            relevance=row["ml_relevance"],
            match_label=row["ml_match_label"],
            url=row["ml_url"],
            empty_label="Sin resultado Mercado Libre",
            rating_available=row["ml_rating_available"],
            rating_filled=row["ml_rating_filled"],
            rating_label=row["ml_rating_label"],
            rating_caption=row["ml_rating_caption"],
            trust_line=row["ml_trust_line"],
        ),
        analysis_cell(row),
        display="grid",
        grid_template_columns="minmax(200px, 1.1fr) repeat(3, minmax(170px, 1fr)) minmax(130px, 0.7fr)",
        column_gap="16px",
        align_items="start",
        padding="14px 16px",
        border_top=f"1px solid {styles.BORDER}",
        min_width="1040px",
    )


def comparison_matrix() -> rx.Component:
    header = rx.box(
        rx.text("Producto", size="1", weight="medium", color=styles.TEXT_MUTED),
        marketplace_brand_alibaba(size=16),
        marketplace_brand_facebook(size=16),
        marketplace_brand_ml(size=16),
        rx.text("Oportunidad", size="1", weight="medium", color=styles.TEXT_MUTED),
        display="grid",
        grid_template_columns="minmax(200px, 1.1fr) repeat(3, minmax(170px, 1fr)) minmax(130px, 0.7fr)",
        column_gap="16px",
        padding="10px 16px",
        min_width="1040px",
        align_items="center",
    )
    return rx.box(
        rx.cond(
            TrackerState.has_comparison_rows,
            rx.box(
                header,
                rx.foreach(TrackerState.comparison_rows, comparison_row),
                overflow_x="auto",
                width="100%",
            ),
            empty_state(
                "Todavía no hay una comparación",
                "Busca un producto para ver resultados por plataforma.",
            ),
        ),
        **styles.SURFACE_STYLE,
        width="100%",
        overflow="hidden",
        class_name="bera-comparison-matrix",
    )


def positional_comparison_row(row: rx.Var) -> rx.Component:
    return rx.box(
        product_cell(row),
        marketplace_cell(
            has_listing=row["alibaba_has_listing"],
            image_url=row["alibaba_image_url"],
            title=row["alibaba_title"],
            price=row["alibaba_price"],
            price_color=styles.ALIBABA,
            line_one=row["alibaba_range"],
            line_two=row["alibaba_moq"],
            line_three=row["alibaba_supplier"],
            relevance=row["alibaba_relevance"],
            match_label=row["alibaba_match_label"],
            url=row["alibaba_url"],
            empty_label="—",
            rating_available=row["alibaba_rating_available"],
            rating_filled=row["alibaba_rating_filled"],
            rating_label=row["alibaba_rating_label"],
            rating_caption=row["alibaba_rating_caption"],
            trust_line=row["alibaba_trust_line"],
        ),
        marketplace_cell(
            has_listing=row["facebook_has_listing"],
            image_url=row["facebook_image_url"],
            title=row["facebook_title"],
            price=row["facebook_price"],
            price_color=styles.FACEBOOK,
            line_one=row["facebook_usd_note"],
            line_two=row["facebook_source_note"],
            line_three=row["facebook_location"],
            relevance=row["facebook_relevance"],
            match_label=row["facebook_match_label"],
            url=row["facebook_url"],
            empty_label="—",
            rating_available=row["facebook_rating_available"],
            rating_filled=row["facebook_rating_filled"],
            rating_label=row["facebook_rating_label"],
        ),
        marketplace_cell(
            has_listing=row["ml_has_listing"],
            image_url=row["ml_image_url"],
            title=row["ml_title"],
            price=row["ml_price"],
            price_color=styles.MERCADOLIBRE,
            line_one=row["ml_condition"],
            line_two=row["ml_seller"],
            line_three="",
            relevance=row["ml_relevance"],
            match_label=row["ml_match_label"],
            url=row["ml_url"],
            empty_label="—",
            rating_available=row["ml_rating_available"],
            rating_filled=row["ml_rating_filled"],
            rating_label=row["ml_rating_label"],
            rating_caption=row["ml_rating_caption"],
            trust_line=row["ml_trust_line"],
        ),
        analysis_cell(row),
        display="grid",
        grid_template_columns="minmax(200px, 1.1fr) repeat(3, minmax(170px, 1fr)) minmax(130px, 0.7fr)",
        column_gap="16px",
        align_items="start",
        padding="14px 16px",
        border_top=f"1px solid {styles.BORDER}",
        min_width="1040px",
    )


def positional_comparison_matrix() -> rx.Component:
    header = rx.box(
        rx.text("Resultado", size="1", weight="medium", color=styles.TEXT_MUTED),
        marketplace_brand_alibaba(size=16),
        marketplace_brand_facebook(size=16),
        marketplace_brand_ml(size=16),
        rx.text("Oportunidad", size="1", weight="medium", color=styles.TEXT_MUTED),
        display="grid",
        grid_template_columns="minmax(200px, 1.1fr) repeat(3, minmax(170px, 1fr)) minmax(130px, 0.7fr)",
        column_gap="16px",
        padding="10px 16px",
        min_width="1040px",
        align_items="center",
    )
    return rx.box(
        rx.cond(
            TrackerState.has_positional_comparison_rows,
            rx.vstack(
                rx.text(
                    "Comparables de la misma búsqueda · identidad exacta no confirmada",
                    size="1",
                    color=styles.TEXT_MUTED,
                    padding="10px 16px 0",
                ),
                rx.box(
                    header,
                    rx.foreach(TrackerState.positional_comparison_rows, positional_comparison_row),
                    overflow_x="auto",
                    width="100%",
                ),
                spacing="0",
                width="100%",
                align_items="stretch",
            ),
            empty_state(
                "Todavía no hay una comparación",
                "Busca un producto para ver resultados por plataforma.",
            ),
        ),
        **styles.SURFACE_STYLE,
        width="100%",
        overflow="hidden",
        class_name="bera-comparison-matrix",
    )
