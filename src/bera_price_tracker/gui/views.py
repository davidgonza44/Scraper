# mypy: disable-error-code="index,attr-defined,type-arg,arg-type,no-untyped-def"
"""Single dashboard / search page."""

from __future__ import annotations

from typing import cast

import reflex as rx

from bera_price_tracker.gui import styles
from bera_price_tracker.gui.state import TrackerState

INK = "#1a1814"
PAPER = styles.PAPER
CARD = "#faf7f0"
BRICK = "#9b2c2c"
GREEN = "#2f5d50"
RULE = "#c9c1b2"
MUTED = "#5c564c"


def _header() -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.vstack(
                rx.heading(
                    "BERA Price Tracker",
                    size="8",
                    weight="medium",
                    style={
                        "font_family": "'Fraunces', Georgia, serif",
                        "letter_spacing": "-0.02em",
                    },
                ),
                rx.text(
                    "Seguimiento de precios de pastillas de freno",
                    color=MUTED,
                    size="3",
                ),
                spacing="1",
                align_items="start",
            ),
            rx.spacer(),
            rx.box(
                rx.text("Facebook Marketplace · Apify", size="1", weight="medium"),
                padding="6px 10px",
                border=f"1px solid {GREEN}",
                color=GREEN,
                style={"letter_spacing": "0.04em", "text_transform": "uppercase"},
            ),
            width="100%",
            align="center",
        ),
        border_bottom=f"1px solid {RULE}",
        padding_bottom="18px",
        margin_bottom="28px",
    )


def _form() -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.vstack(
                    rx.text("Consulta", size="1", color=styles.TEXT_SECONDARY, weight="medium"),
                    rx.input(
                        value=TrackerState.query,
                        on_change=TrackerState.set_query,
                        placeholder="pastillas sbr",
                        width="100%",
                        **styles.INPUT_STYLE,
                    ),
                    spacing="1",
                    width="100%",
                    align_items="start",
                ),
                rx.vstack(
                    rx.text("Ciudad", size="1", color=styles.TEXT_SECONDARY, weight="medium"),
                    rx.input(
                        value=TrackerState.city,
                        on_change=TrackerState.set_city,
                        placeholder="caracas",
                        width="100%",
                        **styles.INPUT_STYLE,
                    ),
                    spacing="1",
                    width="180px",
                    align_items="start",
                ),
                rx.vstack(
                    rx.text("Límite", size="1", color=styles.TEXT_SECONDARY, weight="medium"),
                    rx.select(
                        ["1", "2", "3", "4", "5"],
                        value=TrackerState.limit.to_string(),
                        on_change=TrackerState.set_limit,
                        width="88px",
                        **styles.SELECT_STYLE,
                    ),
                    spacing="1",
                    align_items="start",
                ),
                spacing="4",
                width="100%",
                align="end",
            ),
            rx.hstack(
                rx.box(
                    rx.text("Proveedor", size="1", color=styles.TEXT_SECONDARY),
                    rx.text("Facebook Marketplace", size="3", weight="medium"),
                    spacing="1",
                ),
                rx.spacer(),
                rx.button(
                    rx.cond(
                        TrackerState.is_loading,
                        rx.hstack(
                            rx.spinner(size="1"),
                            rx.text("Buscando en Facebook Marketplace..."),
                            spacing="2",
                        ),
                        rx.text("Buscar precios"),
                    ),
                    on_click=TrackerState.search,
                    disabled=TrackerState.is_loading,
                    **styles.BUTTON_STYLE,
                    padding_x="18px",
                    padding_y="10px",
                ),
                width="100%",
                align="center",
            ),
            spacing="5",
            width="100%",
        ),
        background_color=CARD,
        border=f"1px solid {RULE}",
        padding="22px",
        width="100%",
    )


def _summary() -> rx.Component:
    return rx.cond(
        TrackerState.ui_status == "SUCCESS",
        rx.hstack(
            rx.box(
                rx.text("Encontrados", size="1", color=MUTED),
                rx.text(TrackerState.summary["encontrados"], size="5", weight="medium"),
            ),
            rx.box(
                rx.text("Guardados", size="1", color=MUTED),
                rx.text(TrackerState.summary["guardados"], size="5", weight="medium"),
            ),
            rx.box(
                rx.text("Mínimo", size="1", color=MUTED),
                rx.text(TrackerState.summary["min"], size="5", weight="medium", color=BRICK),
            ),
            rx.box(
                rx.text("Promedio", size="1", color=MUTED),
                rx.text(TrackerState.summary["avg"], size="5", weight="medium", color=BRICK),
            ),
            rx.box(
                rx.text("Máximo", size="1", color=MUTED),
                rx.text(TrackerState.summary["max"], size="5", weight="medium", color=BRICK),
            ),
            spacing="6",
            padding_y="16px",
            width="100%",
            wrap="wrap",
        ),
    )


def _details(row: rx.Var) -> rx.Component:
    return rx.accordion.root(
        rx.accordion.item(
            header="Detalles",
            content=rx.vstack(
                rx.foreach(
                    row["details_items"],
                    lambda item: rx.text(
                        item["label"],
                        ": ",
                        rx.text(item["value"], as_="span"),
                    ),
                ),
                spacing="1",
                align_items="start",
            ),
            value="details",
        ),
        type="multiple",
        collapsible=True,
        width="100%",
    )


def _table() -> rx.Component:
    return rx.box(
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("Producto", color=styles.TEXT_PRIMARY),
                    rx.table.column_header_cell("Precio", color=styles.TEXT_PRIMARY),
                    rx.table.column_header_cell("Compatibilidad", color=styles.TEXT_PRIMARY),
                    rx.table.column_header_cell("Ciudad", color=styles.TEXT_PRIMARY),
                    rx.table.column_header_cell("Fuente", color=styles.TEXT_PRIMARY),
                    rx.table.column_header_cell("Enlace", color=styles.TEXT_PRIMARY),
                    rx.table.column_header_cell("Detalles", color=styles.TEXT_PRIMARY),
                )
            ),
            rx.table.body(
                rx.foreach(
                    TrackerState.results,
                    lambda row: rx.table.row(
                        rx.table.cell(row["title"], color=styles.TEXT_PRIMARY),
                        rx.table.cell(
                            rx.text(row["price"], color=BRICK, weight="medium"),
                        ),
                        rx.table.cell(
                            rx.cond(
                                row["compatibility"] != "",
                                rx.box(
                                    rx.text(row["compatibility"], size="1"),
                                    border=f"1px solid {GREEN}",
                                    color=GREEN,
                                    padding="2px 8px",
                                ),
                                rx.text("—", color=MUTED),
                            )
                        ),
                        rx.table.cell(row["city"], color=styles.TEXT_PRIMARY),
                        rx.table.cell(rx.text("Facebook Marketplace", size="1", color=GREEN)),
                        rx.table.cell(
                            rx.link(
                                "Ver publicación",
                                href=row["url"],
                                is_external=True,
                                color=INK,
                                text_decoration="underline",
                            )
                        ),
                        rx.table.cell(_details(row)),
                    ),
                )
            ),
            width="100%",
        ),
        overflow_x="auto",
        width="100%",
    )


def _body() -> rx.Component:
    return rx.box(
        rx.cond(
            TrackerState.ui_status == "INITIAL",
            rx.text(
                "Indica una consulta y pulsa Buscar precios. Una recolección por clic.",
                color=MUTED,
            ),
        ),
        rx.cond(
            TrackerState.ui_status == "LOADING",
            rx.hstack(
                rx.spinner(),
                rx.text("Buscando en Facebook Marketplace..."),
                spacing="3",
                padding_y="20px",
            ),
        ),
        rx.cond(
            TrackerState.ui_status == "ERROR",
            rx.box(
                rx.text(TrackerState.error_message, color=BRICK),
                border=f"1px solid {BRICK}",
                padding="14px 16px",
                width="100%",
            ),
        ),
        rx.cond(
            TrackerState.ui_status == "EMPTY",
            rx.text("No hay publicaciones para esta consulta.", color=MUTED),
        ),
        rx.cond(
            TrackerState.ui_status == "SUCCESS",
            rx.vstack(_summary(), _table(), spacing="4", width="100%"),
        ),
        width="100%",
        padding_top="22px",
    )


def _alibaba_form() -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.vstack(
                    rx.text("Consulta", size="1", color=styles.TEXT_SECONDARY, weight="medium"),
                    rx.input(
                        value=TrackerState.alibaba_query,
                        on_change=TrackerState.set_alibaba_query,
                        placeholder="waterproof backpack",
                        width="100%",
                        **styles.INPUT_STYLE,
                    ),
                    spacing="1",
                    width="100%",
                    align_items="start",
                ),
                rx.vstack(
                    rx.text("Limite", size="1", color=styles.TEXT_SECONDARY, weight="medium"),
                    rx.input(
                        type="number",
                        min=1,
                        max=500,
                        value=TrackerState.alibaba_limit,
                        on_change=TrackerState.set_alibaba_limit,
                        width="100%",
                        **styles.INPUT_STYLE,
                    ),
                    spacing="1",
                    width="120px",
                    align_items="start",
                ),
                spacing="4",
                width="100%",
                align="end",
            ),
            rx.cond(
                TrackerState.alibaba_warning != "",
                rx.text(TrackerState.alibaba_warning, color=BRICK, size="2"),
            ),
            rx.hstack(
                rx.box(
                    rx.text("Proveedor", size="1", color=styles.TEXT_SECONDARY),
                    rx.text("Alibaba", size="3", weight="medium"),
                ),
                rx.spacer(),
                rx.button(
                    rx.cond(
                        TrackerState.alibaba_is_loading,
                        rx.hstack(
                            rx.spinner(size="1"),
                            rx.text("Buscando productos en Alibaba..."),
                            spacing="2",
                        ),
                        rx.text("Buscar productos"),
                    ),
                    on_click=TrackerState.search_alibaba,
                    disabled=TrackerState.alibaba_is_loading,
                    **styles.BUTTON_STYLE,
                    padding_x="18px",
                    padding_y="10px",
                ),
                width="100%",
                align="center",
            ),
            spacing="5",
            width="100%",
        ),
        background_color=CARD,
        border=f"1px solid {RULE}",
        padding="22px",
        width="100%",
    )


def _alibaba_stat_card(label: str, key: str, *, accent: bool = False) -> rx.Component:
    return rx.box(
        rx.text(label, size="1", color=MUTED),
        rx.text(
            TrackerState.alibaba_summary[key],
            size="5",
            weight="medium",
            color=BRICK if accent else styles.TEXT_PRIMARY,
        ),
        min_width="132px",
        padding="12px 14px",
        background_color=CARD,
        border=f"1px solid {RULE}",
    )


def _alibaba_typical_card() -> rx.Component:
    return rx.box(
        rx.text("Precio típico", size="1", color=MUTED),
        rx.text(
            TrackerState.alibaba_summary["precio_tipico"],
            size="5",
            weight="medium",
            color=BRICK,
        ),
        rx.text("Media recortada 10%", size="1", color=MUTED),
        min_width="132px",
        padding="12px 14px",
        background_color=CARD,
        border=f"1px solid {RULE}",
    )


def _alibaba_summary() -> rx.Component:
    return rx.cond(
        TrackerState.alibaba_ui_status == "SUCCESS",
        rx.vstack(
            rx.hstack(
                _alibaba_stat_card("Resultados", "resultados"),
                _alibaba_stat_card("Con precio", "con_precio"),
                _alibaba_stat_card("Mínimo", "minimo", accent=True),
                _alibaba_stat_card("Mediana", "mediana", accent=True),
                _alibaba_stat_card("Promedio estimado", "promedio", accent=True),
                _alibaba_stat_card("Máximo", "maximo", accent=True),
                spacing="3",
                padding_y="8px",
                width="100%",
                wrap="wrap",
            ),
            rx.hstack(
                _alibaba_stat_card("P25", "p25", accent=True),
                _alibaba_typical_card(),
                _alibaba_stat_card("P75", "p75", accent=True),
                _alibaba_stat_card("Outliers", "outliers"),
                spacing="3",
                padding_y="4px",
                width="100%",
                wrap="wrap",
            ),
            rx.hstack(
                rx.text("Rango típico:", size="2", color=MUTED),
                rx.text(
                    TrackerState.alibaba_summary["rango_tipico"],
                    size="2",
                    weight="medium",
                    color=styles.TEXT_PRIMARY,
                ),
                spacing="2",
                wrap="wrap",
            ),
            rx.cond(
                TrackerState.alibaba_summary["interpretacion"] != "",
                rx.text(TrackerState.alibaba_summary["interpretacion"], size="2", color=MUTED),
            ),
            rx.text(
                "Estadísticas de precios publicados en la búsqueda. No son costos finales de compra.",
                size="1",
                color=MUTED,
            ),
            spacing="2",
            width="100%",
        ),
    )


def _alibaba_boxplot() -> rx.Component:
    return rx.box(
        rx.text("Distribución estadística", size="2", weight="medium", color=styles.TEXT_PRIMARY),
        rx.cond(
            TrackerState.alibaba_boxplot_available,
            rx.box(
                rx.box(
                    rx.box(
                        position="absolute",
                        top="16px",
                        left="0",
                        width="100%",
                        height="2px",
                        background_color=RULE,
                    ),
                    rx.box(
                        position="absolute",
                        top="6px",
                        left=TrackerState.alibaba_boxplot["box_left"],
                        width=TrackerState.alibaba_boxplot["box_width"],
                        min_width="2px",
                        height="22px",
                        background_color="rgba(47, 93, 80, 0.22)",
                        border=f"1px solid {GREEN}",
                    ),
                    rx.box(
                        position="absolute",
                        top="3px",
                        left=TrackerState.alibaba_boxplot["median_left"],
                        width="3px",
                        height="28px",
                        background_color=BRICK,
                    ),
                    position="relative",
                    height="34px",
                    width="100%",
                ),
                rx.hstack(
                    rx.text("Mín " + TrackerState.alibaba_summary["minimo"], size="1", color=MUTED),
                    rx.spacer(),
                    rx.text("P25 " + TrackerState.alibaba_summary["p25"], size="1", color=GREEN),
                    rx.spacer(),
                    rx.text(
                        "Mediana " + TrackerState.alibaba_summary["mediana"],
                        size="1",
                        color=BRICK,
                        weight="medium",
                    ),
                    rx.spacer(),
                    rx.text("P75 " + TrackerState.alibaba_summary["p75"], size="1", color=GREEN),
                    rx.spacer(),
                    rx.text("Máx " + TrackerState.alibaba_summary["maximo"], size="1", color=MUTED),
                    width="100%",
                    wrap="wrap",
                ),
                width="100%",
            ),
            rx.text("Sin datos suficientes para el resumen visual.", size="2", color=MUTED),
        ),
        padding="14px 16px",
        background_color=CARD,
        border=f"1px solid {RULE}",
        width="100%",
    )


def _alibaba_histogram() -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.text(
                "Distribución de precios", size="2", weight="medium", color=styles.TEXT_PRIMARY
            ),
            rx.spacer(),
            rx.select(
                ["Todos los precios", "Rango típico"],
                value=TrackerState.alibaba_chart_scope_label,
                on_change=TrackerState.set_alibaba_chart_scope,
                size="1",
                **styles.SELECT_STYLE,
            ),
            width="100%",
            align="center",
            wrap="wrap",
        ),
        rx.cond(
            TrackerState.alibaba_histogram_has_data,
            rx.vstack(
                rx.foreach(
                    TrackerState.alibaba_histogram,
                    lambda item: rx.hstack(
                        rx.text(
                            item["label"],
                            size="1",
                            color=MUTED,
                            min_width="130px",
                            text_align="right",
                        ),
                        rx.box(
                            rx.box(
                                height="14px",
                                width=item["width"],
                                min_width="2px",
                                background_color=GREEN,
                            ),
                            flex="1",
                            background_color="#eae5d8",
                        ),
                        rx.text(item["count"], size="1", color=styles.TEXT_PRIMARY, width="34px"),
                        spacing="2",
                        width="100%",
                        align="center",
                    ),
                ),
                spacing="1",
                width="100%",
                padding_top="10px",
            ),
            rx.text(
                "Sin precios USD válidos para graficar.",
                size="2",
                color=MUTED,
                padding_top="10px",
            ),
        ),
        padding="14px 16px",
        background_color=CARD,
        border=f"1px solid {RULE}",
        width="100%",
    )


def _alibaba_controls() -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.vstack(
                rx.text("Ordenar por", size="1", color=styles.TEXT_SECONDARY, weight="medium"),
                rx.select(
                    [
                        "Relevancia original",
                        "Precio: menor a mayor",
                        "Precio: mayor a menor",
                        "Mejor puntuación",
                        "Mayor relevancia",
                        "Mejor ranking general",
                        "Mayor reputación",
                    ],
                    value=TrackerState.alibaba_sort_label,
                    on_change=TrackerState.set_alibaba_sort,
                    **styles.SELECT_STYLE,
                ),
                spacing="1",
                align_items="start",
            ),
            rx.vstack(
                rx.text(
                    "Precio mínimo (USD)", size="1", color=styles.TEXT_SECONDARY, weight="medium"
                ),
                rx.input(
                    value=TrackerState.alibaba_price_min,
                    on_change=TrackerState.set_alibaba_price_min,
                    placeholder="1.00",
                    width="120px",
                    **styles.INPUT_STYLE,
                ),
                spacing="1",
                align_items="start",
            ),
            rx.vstack(
                rx.text(
                    "Precio máximo (USD)", size="1", color=styles.TEXT_SECONDARY, weight="medium"
                ),
                rx.input(
                    value=TrackerState.alibaba_price_max,
                    on_change=TrackerState.set_alibaba_price_max,
                    placeholder="5.00",
                    width="120px",
                    **styles.INPUT_STYLE,
                ),
                spacing="1",
                align_items="start",
            ),
            rx.vstack(
                rx.text(
                    "Relevancia mínima", size="1", color=styles.TEXT_SECONDARY, weight="medium"
                ),
                rx.select(
                    ["Todas", "30+", "60+", "80+"],
                    value=TrackerState.alibaba_min_relevance_label,
                    on_change=TrackerState.set_alibaba_min_relevance,
                    **styles.SELECT_STYLE,
                ),
                spacing="1",
                align_items="start",
            ),
            rx.vstack(
                rx.text(
                    "Reputación mínima", size="1", color=styles.TEXT_SECONDARY, weight="medium"
                ),
                rx.select(
                    ["Todas", "50+", "70+", "85+"],
                    value=TrackerState.alibaba_min_reputation_label,
                    on_change=TrackerState.set_alibaba_min_reputation,
                    **styles.SELECT_STYLE,
                ),
                spacing="1",
                align_items="start",
            ),
            rx.hstack(
                rx.switch(
                    checked=TrackerState.alibaba_hide_outliers,
                    on_change=TrackerState.set_alibaba_hide_outliers,
                ),
                rx.text("Ocultar outliers", size="2", color=styles.TEXT_PRIMARY),
                spacing="2",
                align="center",
                padding_bottom="6px",
            ),
            rx.button(
                "Limpiar filtros",
                on_click=TrackerState.clear_alibaba_filters,
                **styles.BUTTON_STYLE,
            ),
            spacing="4",
            width="100%",
            align="end",
            wrap="wrap",
        ),
        rx.cond(
            TrackerState.alibaba_filter_error != "",
            rx.text(TrackerState.alibaba_filter_error, size="2", color=BRICK, padding_top="6px"),
        ),
        rx.text(TrackerState.alibaba_counter, size="2", color=MUTED, padding_top="8px"),
        rx.text(SCORE_NOTE, size="1", color=MUTED, padding_top="4px"),
        rx.text(RELEVANCE_NOTE, size="1", color=MUTED, padding_top="2px"),
        rx.text(RANKING_NOTE, size="1", color=MUTED, padding_top="2px"),
        rx.text(REPUTATION_NOTE, size="1", color=MUTED, padding_top="2px"),
        width="100%",
    )


SCORE_NOTE = (
    "El score compara precio, MOQ y calidad de la información dentro de los "
    "resultados actuales. No representa una evaluación de reputación o "
    "confiabilidad del proveedor."
)

RELEVANCE_NOTE = (
    "La relevancia mide cuánto coincide el título del producto con tu búsqueda. "
    "Es una métrica independiente del score de oportunidad."
)

RANKING_NOTE = (
    "El ranking combina relevancia, oportunidad y reputación utilizando los pesos "
    "seleccionados. Si no hay suficientes datos de reputación, sus pesos se "
    "redistribuyen entre las métricas disponibles."
)

WEIGHTS_TOTAL_NOTE = "Los pesos se aplican cuando el total es 100%."

REPUTATION_NOTE = (
    "Puntaje experimental basado en antigüedad y señales públicas de servicio "
    "y evaluaciones del proveedor disponibles en Alibaba. No garantiza "
    "confiabilidad, calidad, cumplimiento ni seguridad de una transacción."
)


def _score_breakdown_line(label: str, value: rx.Var) -> rx.Component:
    return rx.hstack(
        rx.text(label, size="1", color=MUTED, width="90px"),
        rx.text(value, size="1", weight="medium", color=styles.TEXT_PRIMARY),
        spacing="2",
        width="100%",
    )


def _alibaba_outlier_badge() -> rx.Component:
    return rx.box(
        rx.text("Precio atípico", size="1", color=MUTED),
        padding="1px 6px",
        border=f"1px solid {RULE}",
        background_color="#efe9db",
        width="fit-content",
    )


def _alibaba_score_cell(row: rx.Var) -> rx.Component:
    color = rx.match(
        row["score_label"],
        ("Excelente oportunidad", GREEN),
        ("Buena oportunidad", "#55703d"),
        ("Intermedia", "#8a6d3b"),
        MUTED,
    )
    return rx.popover.root(
        rx.popover.trigger(
            rx.button(
                row["score"],
                size="1",
                variant="outline",
                cursor="pointer",
                color=color,
                border=f"1px solid {color}",
                background="transparent",
                font_weight="600",
            )
        ),
        rx.popover.content(
            rx.vstack(
                rx.hstack(
                    rx.text("Score:", size="2", color=MUTED),
                    rx.text(row["score"], size="2", weight="bold", color=styles.TEXT_PRIMARY),
                    spacing="2",
                ),
                rx.text(row["score_label"], size="1", weight="medium", color=color),
                rx.divider(),
                _score_breakdown_line("Precio", row["score_price"]),
                _score_breakdown_line("MOQ", row["score_moq"]),
                _score_breakdown_line("Información", row["score_info"]),
                _score_breakdown_line("Claridad", row["score_clarity"]),
                rx.cond(row["is_outlier"], _alibaba_outlier_badge()),
                rx.divider(),
                rx.text(SCORE_NOTE, size="1", color=MUTED),
                spacing="1",
                align_items="start",
                max_width="260px",
            ),
            size="1",
        ),
    )


def _alibaba_weight_slider(label: str, value: rx.Var, on_change: rx.EventHandler) -> rx.Component:
    return rx.vstack(
        rx.text(
            label + ": " + value.to_string() + "%",
            size="2",
            color=styles.TEXT_PRIMARY,
        ),
        rx.slider(
            min=0,
            max=100,
            step=1,
            value=cast("list[int]", [value]),
            on_change=on_change,
            width="100%",
            max_width="300px",
        ),
        spacing="1",
        align_items="start",
        min_width="220px",
        flex="1",
    )


def _alibaba_ranking_weights() -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.text(
                "Pesos del ranking",
                size="1",
                color=styles.TEXT_SECONDARY,
                weight="medium",
            ),
            rx.hstack(
                rx.button(
                    "Equilibrado",
                    on_click=TrackerState.apply_ranking_preset_balanced,
                    size="1",
                    variant="outline",
                ),
                rx.button(
                    "Más relevante",
                    on_click=TrackerState.apply_ranking_preset_more_relevant,
                    size="1",
                    variant="outline",
                ),
                rx.button(
                    "Mejor oportunidad",
                    on_click=TrackerState.apply_ranking_preset_more_opportunity,
                    size="1",
                    variant="outline",
                ),
                rx.button(
                    "Más reputación",
                    on_click=TrackerState.apply_ranking_preset_more_reputation,
                    size="1",
                    variant="outline",
                ),
                spacing="2",
                wrap="wrap",
            ),
            rx.hstack(
                _alibaba_weight_slider(
                    "Relevancia",
                    TrackerState.alibaba_relevance_weight,
                    TrackerState.set_alibaba_relevance_weight,
                ),
                _alibaba_weight_slider(
                    "Oportunidad",
                    TrackerState.alibaba_opportunity_weight,
                    TrackerState.set_alibaba_opportunity_weight,
                ),
                _alibaba_weight_slider(
                    "Reputación",
                    TrackerState.alibaba_reputation_weight,
                    TrackerState.set_alibaba_reputation_weight,
                ),
                spacing="4",
                width="100%",
                wrap="wrap",
            ),
            rx.text(
                "Total: " + TrackerState.alibaba_weights_total.to_string() + "%",
                size="2",
                weight="medium",
                color=rx.cond(TrackerState.alibaba_weights_valid, GREEN, BRICK),
            ),
            rx.cond(
                TrackerState.alibaba_weights_error != "",
                rx.text(
                    TrackerState.alibaba_weights_error
                    + " Se mantiene la última combinación válida.",
                    size="1",
                    color=BRICK,
                ),
            ),
            rx.text(WEIGHTS_TOTAL_NOTE, size="1", color=MUTED),
            spacing="2",
            width="100%",
            align_items="start",
        ),
        padding="12px 14px",
        background_color=CARD,
        border=f"1px solid {RULE}",
        width="100%",
    )


def _alibaba_top_results() -> rx.Component:
    return rx.cond(
        TrackerState.alibaba_has_top_results,
        rx.box(
            rx.text("Mejores resultados", size="2", weight="medium", color=styles.TEXT_PRIMARY),
            rx.hstack(
                rx.foreach(
                    TrackerState.alibaba_top_results,
                    lambda item: rx.box(
                        rx.text(
                            item["place"] + ". " + item["title"],
                            size="2",
                            weight="medium",
                            color=styles.TEXT_PRIMARY,
                        ),
                        rx.text(item["price"], size="2", color=BRICK, weight="medium"),
                        rx.text(item["ranking"], size="1", color=styles.TEXT_PRIMARY),
                        rx.text(item["relevance"], size="1", color=MUTED),
                        rx.text(item["opportunity"], size="1", color=MUTED),
                        rx.text(item["reputation"], size="1", color=MUTED),
                        min_width="180px",
                        flex="1",
                        padding="10px 12px",
                        background_color=CARD,
                        border=f"1px solid {RULE}",
                    ),
                ),
                spacing="3",
                width="100%",
                wrap="wrap",
                padding_top="8px",
            ),
            width="100%",
        ),
    )


def _alibaba_low_match_badge() -> rx.Component:
    return rx.box(
        rx.text("Baja coincidencia", size="1", color=MUTED),
        padding="1px 6px",
        border=f"1px solid {RULE}",
        background_color="#efe9db",
        width="fit-content",
    )


def _alibaba_ranking_cell(row: rx.Var) -> rx.Component:
    return rx.tooltip(
        rx.vstack(
            rx.box(
                rx.text(row["ranking"], size="1", weight="medium", color=INK),
                padding="2px 8px",
                border=f"1px solid {INK}",
                width="fit-content",
            ),
            rx.cond(row["ranking_low_match"], _alibaba_low_match_badge()),
            spacing="1",
            align_items="start",
        ),
        content=row["ranking_tooltip"],
    )


def _alibaba_reputation_cell(row: rx.Var) -> rx.Component:
    color = rx.match(
        row["reputation_label"],
        ("Señales muy sólidas", GREEN),
        ("Señales sólidas", "#55703d"),
        ("Señales moderadas", "#8a6d3b"),
        MUTED,
    )
    return rx.popover.root(
        rx.popover.trigger(
            rx.button(
                row["reputation"],
                size="1",
                variant="outline",
                cursor="pointer",
                color=color,
                border=f"1px solid {color}",
                background="transparent",
                font_weight="600",
            )
        ),
        rx.popover.content(
            rx.vstack(
                rx.hstack(
                    rx.text("Reputación:", size="2", color=MUTED),
                    rx.text(row["reputation"], size="2", weight="bold", color=styles.TEXT_PRIMARY),
                    spacing="2",
                ),
                rx.text(row["reputation_label"], size="1", weight="medium", color=color),
                rx.text(row["reputation_coverage"], size="1", color=MUTED),
                rx.text(row["reputation_coverage_label"], size="1", color=MUTED),
                rx.divider(),
                _score_breakdown_line("Servicio", row["reputation_service"]),
                _score_breakdown_line("Evaluaciones", row["reputation_reviews"]),
                _score_breakdown_line("Antigüedad", row["reputation_years"]),
                _score_breakdown_line("Volumen reviews", row["reputation_volume"]),
                rx.divider(),
                rx.text(REPUTATION_NOTE, size="1", color=MUTED),
                spacing="1",
                align_items="start",
                max_width="280px",
            ),
            size="1",
        ),
    )


def _alibaba_relevance_cell(row: rx.Var) -> rx.Component:
    color = rx.match(
        row["relevance_label"],
        ("Muy relevante", GREEN),
        ("Relevante", "#55703d"),
        ("Parcialmente relevante", "#8a6d3b"),
        MUTED,
    )
    return rx.tooltip(
        rx.box(
            rx.text(row["relevance"], size="1", weight="medium", color=color),
            padding="2px 8px",
            border=f"1px solid {color}",
            width="fit-content",
        ),
        content=row["relevance_label"]
        + " · "
        + row["relevance_tokens"]
        + ". La relevancia mide cuánto coincide el título del producto con tu búsqueda.",
    )


def _alibaba_table() -> rx.Component:
    return rx.box(
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("Imagen", color=styles.TEXT_PRIMARY),
                    rx.table.column_header_cell("Producto", color=styles.TEXT_PRIMARY),
                    rx.table.column_header_cell("Precio", color=styles.TEXT_PRIMARY),
                    rx.table.column_header_cell("MOQ", color=styles.TEXT_PRIMARY),
                    rx.table.column_header_cell("Proveedor", color=styles.TEXT_PRIMARY),
                    rx.table.column_header_cell("Pais", color=styles.TEXT_PRIMARY),
                    rx.table.column_header_cell("Oportunidad", color=styles.TEXT_PRIMARY),
                    rx.table.column_header_cell("Relevancia", color=styles.TEXT_PRIMARY),
                    rx.table.column_header_cell("Ranking", color=styles.TEXT_PRIMARY),
                    rx.table.column_header_cell("Reputación", color=styles.TEXT_PRIMARY),
                    rx.table.column_header_cell("Enlace", color=styles.TEXT_PRIMARY),
                )
            ),
            rx.table.body(
                rx.foreach(
                    TrackerState.alibaba_visible_rows,
                    lambda row: rx.table.row(
                        rx.table.cell(
                            rx.cond(
                                row["image_url"] != "",
                                rx.image(
                                    src=row["image_url"],
                                    alt="",
                                    width="48px",
                                    height="48px",
                                    object_fit="cover",
                                ),
                                rx.box(width="48px", height="48px"),
                            )
                        ),
                        rx.table.cell(row["title"], color=styles.TEXT_PRIMARY),
                        rx.table.cell(
                            rx.vstack(
                                rx.text(row["price"], color=BRICK, weight="medium"),
                                rx.cond(row["is_outlier"], _alibaba_outlier_badge()),
                                spacing="1",
                                align_items="start",
                            )
                        ),
                        rx.table.cell(row["moq"], color=styles.TEXT_PRIMARY),
                        rx.table.cell(row["supplier_name"], color=styles.TEXT_PRIMARY),
                        rx.table.cell(row["supplier_country"], color=styles.TEXT_PRIMARY),
                        rx.table.cell(_alibaba_score_cell(row)),
                        rx.table.cell(_alibaba_relevance_cell(row)),
                        rx.table.cell(_alibaba_ranking_cell(row)),
                        rx.table.cell(_alibaba_reputation_cell(row)),
                        rx.table.cell(
                            rx.link(
                                "Ver producto",
                                href=row["url"],
                                is_external=True,
                                color=INK,
                                text_decoration="underline",
                            )
                        ),
                    ),
                )
            ),
            width="100%",
        ),
        overflow_x="auto",
        width="100%",
    )


def _alibaba_body() -> rx.Component:
    return rx.box(
        rx.cond(
            TrackerState.alibaba_ui_status == "LOADING",
            rx.hstack(
                rx.spinner(),
                rx.text("Buscando productos en Alibaba..."),
                spacing="3",
                padding_y="20px",
            ),
        ),
        rx.cond(
            TrackerState.alibaba_ui_status == "ERROR",
            rx.box(
                rx.text(TrackerState.alibaba_error, color=BRICK),
                border=f"1px solid {BRICK}",
                padding="14px 16px",
                width="100%",
            ),
        ),
        rx.cond(
            TrackerState.alibaba_ui_status == "EMPTY",
            rx.text("No se encontraron productos en Alibaba.", color=MUTED),
        ),
        rx.cond(
            TrackerState.alibaba_ui_status == "SUCCESS",
            rx.vstack(
                _alibaba_summary(),
                _alibaba_boxplot(),
                _alibaba_histogram(),
                _alibaba_controls(),
                _alibaba_ranking_weights(),
                _alibaba_top_results(),
                _alibaba_table(),
                spacing="4",
                width="100%",
            ),
        ),
        width="100%",
        padding_top="22px",
    )


def _market_tab(label: str, value: str, on_click: object) -> rx.Component:
    active = TrackerState.marketplace_tab == value
    extras = {"padding": "10px 4px 12px", "border_radius": "0", "cursor": "pointer"}
    return rx.cond(
        active,
        rx.button(label, on_click=on_click, **styles.TAB_TRIGGER_ACTIVE_STYLE, **extras),
        rx.button(label, on_click=on_click, **styles.TAB_TRIGGER_STYLE, **extras),
    )


def dashboard() -> rx.Component:
    return rx.box(
        rx.box(
            _header(),
            rx.hstack(
                _market_tab(
                    "Facebook Marketplace",
                    "facebook",
                    TrackerState.show_facebook_tab,
                ),
                _market_tab("Alibaba", "alibaba", TrackerState.show_alibaba_tab),
                spacing="6",
                width="100%",
                border_bottom=f"1px solid {RULE}",
                margin_bottom="18px",
            ),
            rx.cond(
                TrackerState.marketplace_tab == "facebook",
                rx.vstack(_form(), _body(), spacing="0", width="100%"),
                rx.vstack(_alibaba_form(), _alibaba_body(), spacing="0", width="100%"),
            ),
            max_width="1080px",
            width="100%",
            margin="0 auto",
            padding="36px 20px 64px",
        ),
        background_color=PAPER,
        min_height="100vh",
    )
