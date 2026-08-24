# mypy: disable-error-code="index,attr-defined,type-arg,arg-type,no-untyped-def,call-arg,func-returns-value"
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


def _alibaba_venezuela_cell(row: rx.Var) -> rx.Component:
    return rx.cond(
        row["product_id"] != "",
        rx.button(
            "Buscar comparables en Venezuela",
            on_click=TrackerState.prepare_ml_comparables_from_alibaba_result(row["product_id"]),
            size="1",
            variant="outline",
        ),
        rx.text("Sin ID", size="1", color=MUTED),
    )


def _alibaba_follow_cell(row: rx.Var) -> rx.Component:
    return rx.cond(
        row["product_id"] != "",
        rx.cond(
            row["is_followed"],
            rx.button(
                "Dejar de seguir",
                on_click=TrackerState.unfollow_alibaba_product(row["product_id"]),
                size="1",
                variant="outline",
            ),
            rx.cond(
                row["representative"] != "",
                rx.button(
                    "Seguir precio",
                    on_click=TrackerState.follow_alibaba_product(row["product_id"]),
                    size="1",
                    variant="outline",
                ),
                rx.text("Sin precio", size="1", color=MUTED),
            ),
        ),
        rx.text("Sin ID", size="1", color=MUTED),
    )


def _alibaba_tracking() -> rx.Component:
    return rx.box(
        rx.text("Seguimiento", size="3", weight="medium", color=styles.TEXT_PRIMARY),
        rx.text(
            "Solo se guardan los productos que eliges seguir, usando el precio ya cargado.",
            size="1",
            color=MUTED,
            padding_top="4px",
        ),
        rx.cond(
            TrackerState.alibaba_tracking_error != "",
            rx.text(
                TrackerState.alibaba_tracking_error,
                size="2",
                color=BRICK,
                padding_top="8px",
            ),
        ),
        rx.cond(
            TrackerState.alibaba_refresh_confirm_open,
            rx.box(
                rx.text(
                    TrackerState.alibaba_refresh_confirm_intro,
                    size="2",
                    color=styles.TEXT_PRIMARY,
                ),
                rx.text(
                    "Productos seleccionados: " + TrackerState.alibaba_refresh_confirm_count,
                    size="2",
                    color=styles.TEXT_PRIMARY,
                    padding_top="6px",
                ),
                rx.text("Actor runs previstos: 1", size="2", color=styles.TEXT_PRIMARY),
                rx.hstack(
                    rx.button(
                        "Cancelar",
                        on_click=TrackerState.cancel_alibaba_refresh,
                        size="1",
                        variant="outline",
                    ),
                    rx.button(
                        "Actualizar",
                        on_click=TrackerState.confirm_alibaba_refresh,
                        size="1",
                    ),
                    spacing="2",
                    padding_top="8px",
                ),
                padding="12px 14px",
                margin_top="10px",
                background_color=PAPER,
                border=f"1px solid {RULE}",
                width="100%",
            ),
        ),
        rx.cond(
            TrackerState.alibaba_refresh_has_summary,
            rx.box(
                rx.text("Resultado de la actualización", size="2", weight="medium"),
                rx.text(
                    "Solicitados: " + TrackerState.alibaba_refresh_summary["requested"],
                    size="1",
                    color=MUTED,
                ),
                rx.text(
                    "Precio cambió: " + TrackerState.alibaba_refresh_summary["updated"],
                    size="1",
                    color=MUTED,
                ),
                rx.text(
                    "Sin cambio: " + TrackerState.alibaba_refresh_summary["unchanged"],
                    size="1",
                    color=MUTED,
                ),
                rx.text(
                    "No encontrados: " + TrackerState.alibaba_refresh_summary["not_found"],
                    size="1",
                    color=MUTED,
                ),
                rx.text(
                    "Identity mismatch: "
                    + TrackerState.alibaba_refresh_summary["identity_mismatch"],
                    size="1",
                    color=MUTED,
                ),
                rx.text(
                    "Precio inválido: " + TrackerState.alibaba_refresh_summary["invalid_price"],
                    size="1",
                    color=MUTED,
                ),
                rx.text(
                    "Errores: " + TrackerState.alibaba_refresh_summary["failed"],
                    size="1",
                    color=MUTED,
                ),
                padding_top="10px",
            ),
        ),
        rx.cond(
            TrackerState.alibaba_has_tracked_rows,
            rx.vstack(
                rx.hstack(
                    rx.button(
                        "Seleccionar todos visibles",
                        on_click=TrackerState.select_visible_alibaba_tracked,
                        size="1",
                        variant="outline",
                    ),
                    rx.button(
                        "Actualizar seleccionados",
                        on_click=TrackerState.request_alibaba_refresh_selected,
                        size="1",
                        variant="outline",
                    ),
                    spacing="2",
                    padding_top="8px",
                ),
                rx.foreach(
                    TrackerState.alibaba_tracked_view_rows,
                    lambda item: rx.box(
                        rx.checkbox(
                            checked=item["selected"],
                            on_change=lambda _checked: (
                                TrackerState.toggle_alibaba_refresh_selection(item["product_id"])
                            ),
                        ),
                        rx.text(
                            item["title"], size="2", weight="medium", color=styles.TEXT_PRIMARY
                        ),
                        rx.text(
                            "Proveedor: " + item["supplier_name"],
                            size="1",
                            color=MUTED,
                        ),
                        rx.text(
                            "Último precio: " + item["last_price"],
                            size="2",
                            color=BRICK,
                            weight="medium",
                        ),
                        rx.cond(
                            item["published_range"] != "",
                            rx.text(
                                "Rango publicado: " + item["published_range"],
                                size="1",
                                color=MUTED,
                            ),
                        ),
                        rx.cond(
                            item["first_price_tag"] != "",
                            rx.tooltip(
                                rx.text(
                                    "Precio observado al seguir: "
                                    + item["first_price"]
                                    + " · Discovery",
                                    size="1",
                                    color=MUTED,
                                ),
                                content=(
                                    "Este precio proviene de la búsqueda inicial y puede "
                                    "representar un rango. Las variaciones comienzan cuando se "
                                    "obtiene un precio comparable mediante seguimiento."
                                ),
                            ),
                            rx.text(
                                "Precio observado al seguir: " + item["first_price"],
                                size="1",
                                color=MUTED,
                            ),
                        ),
                        rx.text(
                            "Baseline de seguimiento: " + item["baseline"],
                            size="1",
                            color=MUTED,
                        ),
                        rx.text(
                            "Última actualización: " + item["last_updated"],
                            size="1",
                            color=MUTED,
                        ),
                        rx.cond(
                            item["variation"] == "—",
                            rx.tooltip(
                                rx.text("Variación: —", size="1", color=styles.TEXT_PRIMARY),
                                content=(
                                    "Se necesita una segunda comprobación comparable para "
                                    "calcular la variación."
                                ),
                            ),
                            rx.text(
                                "Variación: " + item["variation"],
                                size="1",
                                color=styles.TEXT_PRIMARY,
                            ),
                        ),
                        rx.text(
                            "Historial (" + item["snapshot_count"] + " snapshots)",
                            size="1",
                            weight="medium",
                            color=styles.TEXT_PRIMARY,
                        ),
                        rx.text(item["history"], size="1", color=MUTED, white_space="pre-line"),
                        rx.hstack(
                            rx.button(
                                "Actualizar",
                                on_click=TrackerState.request_alibaba_refresh_one(
                                    item["product_id"]
                                ),
                                size="1",
                                variant="outline",
                            ),
                            rx.button(
                                "Dejar de seguir",
                                on_click=TrackerState.unfollow_alibaba_product(item["product_id"]),
                                size="1",
                                variant="outline",
                            ),
                            rx.button(
                                "Buscar comparables en Venezuela",
                                on_click=TrackerState.prepare_ml_comparables_from_alibaba_tracked(
                                    item["product_id"]
                                ),
                                size="1",
                                variant="outline",
                            ),
                            spacing="2",
                        ),
                        padding="12px 14px",
                        background_color=CARD,
                        border=f"1px solid {RULE}",
                        width="100%",
                    ),
                ),
                spacing="3",
                width="100%",
                padding_top="10px",
            ),
            rx.text(
                "Aún no hay productos en seguimiento.",
                size="2",
                color=MUTED,
                padding_top="8px",
            ),
        ),
        padding="14px 16px",
        background_color=CARD,
        border=f"1px solid {RULE}",
        width="100%",
        margin_top="16px",
    )


def _alibaba_negotiation() -> rx.Component:
    return rx.box(
        rx.text("Negociación", size="3", weight="medium", color=styles.TEXT_PRIMARY),
        rx.text(
            "Python calcula los precios. MiniMax solo redacta. Nada se envía a Alibaba.",
            size="1",
            color=MUTED,
            padding_top="4px",
        ),
        rx.cond(
            TrackerState.alibaba_negotiation_error != "",
            rx.text(
                TrackerState.alibaba_negotiation_error,
                size="2",
                color=BRICK,
                padding_top="8px",
            ),
        ),
        rx.cond(
            TrackerState.alibaba_has_negotiation_products,
            rx.vstack(
                rx.vstack(
                    rx.text("Producto", size="1", color=styles.TEXT_SECONDARY, weight="medium"),
                    rx.select(
                        TrackerState.alibaba_negotiation_option_labels,
                        value=TrackerState.alibaba_negotiation_selected_label,
                        on_change=TrackerState.set_alibaba_negotiation_product_key,
                        width="100%",
                        **styles.SELECT_STYLE,
                    ),
                    spacing="1",
                    width="100%",
                    align_items="start",
                ),
                rx.hstack(
                    rx.vstack(
                        rx.text(
                            "Cantidad deseada",
                            size="1",
                            color=styles.TEXT_SECONDARY,
                            weight="medium",
                        ),
                        rx.input(
                            value=TrackerState.alibaba_negotiation_quantity,
                            on_change=TrackerState.set_alibaba_negotiation_quantity,
                            width="100%",
                            **styles.INPUT_STYLE,
                        ),
                        spacing="1",
                        width="100%",
                        align_items="start",
                    ),
                    rx.vstack(
                        rx.text(
                            "Agresividad (0-100)",
                            size="1",
                            color=styles.TEXT_SECONDARY,
                            weight="medium",
                        ),
                        rx.input(
                            value=TrackerState.alibaba_negotiation_aggressiveness,
                            on_change=TrackerState.set_alibaba_negotiation_aggressiveness,
                            width="100%",
                            **styles.INPUT_STYLE,
                        ),
                        spacing="1",
                        width="100%",
                        align_items="start",
                    ),
                    spacing="3",
                    width="100%",
                ),
                rx.hstack(
                    rx.vstack(
                        rx.text(
                            "Precio venta esperado",
                            size="1",
                            color=styles.TEXT_SECONDARY,
                            weight="medium",
                        ),
                        rx.input(
                            value=TrackerState.alibaba_negotiation_resale,
                            on_change=TrackerState.set_alibaba_negotiation_resale,
                            placeholder="opcional",
                            width="100%",
                            **styles.INPUT_STYLE,
                        ),
                        spacing="1",
                        width="100%",
                        align_items="start",
                    ),
                    rx.vstack(
                        rx.text(
                            "Margen objetivo %",
                            size="1",
                            color=styles.TEXT_SECONDARY,
                            weight="medium",
                        ),
                        rx.input(
                            value=TrackerState.alibaba_negotiation_margin,
                            on_change=TrackerState.set_alibaba_negotiation_margin,
                            placeholder="opcional",
                            width="100%",
                            **styles.INPUT_STYLE,
                        ),
                        spacing="1",
                        width="100%",
                        align_items="start",
                    ),
                    spacing="3",
                    width="100%",
                ),
                rx.hstack(
                    rx.vstack(
                        rx.text(
                            "Envío / unidad",
                            size="1",
                            color=styles.TEXT_SECONDARY,
                            weight="medium",
                        ),
                        rx.input(
                            value=TrackerState.alibaba_negotiation_shipping,
                            on_change=TrackerState.set_alibaba_negotiation_shipping,
                            placeholder="opcional",
                            width="100%",
                            **styles.INPUT_STYLE,
                        ),
                        spacing="1",
                        width="100%",
                        align_items="start",
                    ),
                    rx.vstack(
                        rx.text(
                            "Aranceles / unidad",
                            size="1",
                            color=styles.TEXT_SECONDARY,
                            weight="medium",
                        ),
                        rx.input(
                            value=TrackerState.alibaba_negotiation_duties,
                            on_change=TrackerState.set_alibaba_negotiation_duties,
                            placeholder="opcional",
                            width="100%",
                            **styles.INPUT_STYLE,
                        ),
                        spacing="1",
                        width="100%",
                        align_items="start",
                    ),
                    rx.vstack(
                        rx.text(
                            "Otros costos / unidad",
                            size="1",
                            color=styles.TEXT_SECONDARY,
                            weight="medium",
                        ),
                        rx.input(
                            value=TrackerState.alibaba_negotiation_other,
                            on_change=TrackerState.set_alibaba_negotiation_other,
                            placeholder="opcional",
                            width="100%",
                            **styles.INPUT_STYLE,
                        ),
                        spacing="1",
                        width="100%",
                        align_items="start",
                    ),
                    spacing="3",
                    width="100%",
                ),
                rx.vstack(
                    rx.text(
                        "Tramos de precio (opcional)",
                        size="1",
                        color=styles.TEXT_SECONDARY,
                        weight="medium",
                    ),
                    rx.text_area(
                        value=TrackerState.alibaba_negotiation_ladder,
                        on_change=TrackerState.set_alibaba_negotiation_ladder,
                        placeholder="1-49:4.30\n50-199:4.00",
                        width="100%",
                        rows="3",
                    ),
                    spacing="1",
                    width="100%",
                    align_items="start",
                ),
                rx.button(
                    "Calcular estrategia",
                    on_click=TrackerState.calculate_alibaba_negotiation,
                    size="2",
                    **styles.BUTTON_STYLE,
                ),
                rx.cond(
                    TrackerState.alibaba_negotiation_has_plan,
                    rx.vstack(
                        rx.hstack(
                            rx.box(
                                rx.text("Precio publicado", size="1", color=MUTED),
                                rx.text(
                                    TrackerState.alibaba_negotiation_public,
                                    size="3",
                                    weight="medium",
                                    color=BRICK,
                                ),
                                padding="10px 12px",
                                background_color=PAPER,
                                border=f"1px solid {RULE}",
                                width="100%",
                            ),
                            rx.box(
                                rx.text("Oferta inicial", size="1", color=MUTED),
                                rx.text(
                                    TrackerState.alibaba_negotiation_opening,
                                    size="3",
                                    weight="medium",
                                    color=styles.TEXT_PRIMARY,
                                ),
                                padding="10px 12px",
                                background_color=PAPER,
                                border=f"1px solid {RULE}",
                                width="100%",
                            ),
                            rx.box(
                                rx.text("Precio objetivo", size="1", color=MUTED),
                                rx.text(
                                    TrackerState.alibaba_negotiation_target,
                                    size="3",
                                    weight="medium",
                                    color=styles.TEXT_PRIMARY,
                                ),
                                padding="10px 12px",
                                background_color=PAPER,
                                border=f"1px solid {RULE}",
                                width="100%",
                            ),
                            rx.box(
                                rx.text("Máximo aceptable", size="1", color=MUTED),
                                rx.text(
                                    TrackerState.alibaba_negotiation_ceiling,
                                    size="3",
                                    weight="medium",
                                    color=styles.TEXT_PRIMARY,
                                ),
                                padding="10px 12px",
                                background_color=PAPER,
                                border=f"1px solid {RULE}",
                                width="100%",
                            ),
                            spacing="3",
                            width="100%",
                        ),
                        rx.text(
                            "Cantidad deseada: " + TrackerState.alibaba_negotiation_quantity_shown,
                            size="1",
                            color=MUTED,
                        ),
                        rx.text(
                            "Próximo tramo: " + TrackerState.alibaba_negotiation_next_tier,
                            size="1",
                            color=MUTED,
                        ),
                        rx.text(
                            "Distancia al siguiente tramo: "
                            + TrackerState.alibaba_negotiation_proximity,
                            size="1",
                            color=MUTED,
                        ),
                        rx.cond(
                            TrackerState.alibaba_negotiation_is_unattractive,
                            rx.text(
                                "Trato económicamente poco atractivo con el margen indicado.",
                                size="2",
                                color=BRICK,
                            ),
                        ),
                        rx.text(
                            TrackerState.alibaba_negotiation_explanation,
                            size="2",
                            color=styles.TEXT_PRIMARY,
                        ),
                        rx.button(
                            "Aplicar rentabilidad a negociación",
                            on_click=TrackerState.apply_alibaba_profitability_ceiling,
                            size="1",
                            variant="outline",
                        ),
                        rx.cond(
                            TrackerState.alibaba_negotiation_profitability_hint != "",
                            rx.text(
                                TrackerState.alibaba_negotiation_profitability_hint,
                                size="2",
                                color=BRICK,
                            ),
                        ),
                        rx.cond(
                            TrackerState.alibaba_negotiation_has_profitability,
                            rx.vstack(
                                rx.hstack(
                                    _landed_card(
                                        "Máximo negociación",
                                        TrackerState.alibaba_negotiation_original_ceiling,
                                        styles.TEXT_PRIMARY,
                                    ),
                                    _landed_card(
                                        "Máximo por rentabilidad",
                                        TrackerState.alibaba_negotiation_profitability_ceiling,
                                        BRICK,
                                    ),
                                    _landed_card(
                                        "Máximo final",
                                        TrackerState.alibaba_negotiation_effective_ceiling,
                                        styles.TEXT_PRIMARY,
                                    ),
                                    spacing="3",
                                    width="100%",
                                ),
                                rx.text(
                                    "Techo basado en "
                                    + TrackerState.alibaba_negotiation_ceiling_provenance
                                    + ".",
                                    size="1",
                                    color=MUTED,
                                ),
                                rx.text(
                                    TrackerState.alibaba_negotiation_profitability_note,
                                    size="2",
                                    color=styles.TEXT_PRIMARY,
                                ),
                                spacing="2",
                                width="100%",
                            ),
                        ),
                        rx.hstack(
                            rx.button(
                                "Generar mensaje con MiniMax",
                                on_click=TrackerState.generate_alibaba_negotiation_opening,
                                size="1",
                                variant="outline",
                            ),
                            rx.button(
                                "Regenerar",
                                on_click=TrackerState.generate_alibaba_negotiation_opening,
                                size="1",
                                variant="outline",
                            ),
                            rx.button(
                                "Copiar",
                                on_click=rx.set_clipboard(TrackerState.alibaba_negotiation_message),
                                size="1",
                                variant="outline",
                            ),
                            spacing="2",
                        ),
                        rx.text_area(
                            value=TrackerState.alibaba_negotiation_message,
                            on_change=TrackerState.set_alibaba_negotiation_message,
                            placeholder="El mensaje propuesto aparecerá aquí. No se envía.",
                            width="100%",
                            rows="6",
                        ),
                        rx.text(
                            "Respuesta del proveedor (pega el texto; no se consulta Alibaba)",
                            size="1",
                            color=styles.TEXT_SECONDARY,
                            weight="medium",
                        ),
                        rx.text_area(
                            value=TrackerState.alibaba_negotiation_supplier_text,
                            on_change=TrackerState.set_alibaba_negotiation_supplier_text,
                            width="100%",
                            rows="4",
                        ),
                        rx.hstack(
                            rx.button(
                                "Analizar respuesta",
                                on_click=TrackerState.analyze_alibaba_supplier_reply,
                                size="1",
                                variant="outline",
                            ),
                            rx.button(
                                "Generar contraoferta",
                                on_click=TrackerState.generate_alibaba_negotiation_reply,
                                size="1",
                                variant="outline",
                            ),
                            spacing="2",
                        ),
                        rx.cond(
                            TrackerState.alibaba_negotiation_analysis_decision != "",
                            rx.box(
                                rx.text(
                                    "Decisión: "
                                    + TrackerState.alibaba_negotiation_analysis_decision,
                                    size="2",
                                    weight="medium",
                                    color=styles.TEXT_PRIMARY,
                                ),
                                rx.text(
                                    TrackerState.alibaba_negotiation_analysis_summary,
                                    size="1",
                                    color=MUTED,
                                ),
                                rx.text(
                                    TrackerState.alibaba_negotiation_analysis_notes,
                                    size="1",
                                    color=MUTED,
                                ),
                                padding_top="6px",
                            ),
                        ),
                        spacing="3",
                        width="100%",
                    ),
                ),
                spacing="3",
                width="100%",
                padding_top="10px",
            ),
            rx.text(
                "Sigue un producto o carga resultados de búsqueda para negociar.",
                size="2",
                color=MUTED,
                padding_top="8px",
            ),
        ),
        padding="14px 16px",
        background_color=CARD,
        border=f"1px solid {RULE}",
        width="100%",
        margin_top="16px",
    )


def _landed_field(label: str, value: object, on_change: object, placeholder: str = "") -> object:
    return rx.vstack(
        rx.text(label, size="1", color=styles.TEXT_SECONDARY, weight="medium"),
        rx.input(
            value=value,
            on_change=on_change,
            placeholder=placeholder,
            width="100%",
            **styles.INPUT_STYLE,
        ),
        spacing="1",
        width="100%",
        align_items="start",
    )


def _landed_card(label: str, value: object, color: str) -> object:
    return rx.box(
        rx.text(label, size="1", color=MUTED),
        rx.text(value, size="3", weight="medium", color=color),
        padding="10px 12px",
        background_color=PAPER,
        border=f"1px solid {RULE}",
        width="100%",
    )


def _alibaba_landed_cost() -> rx.Component:
    result = TrackerState.alibaba_landed_result
    return rx.box(
        rx.text(
            "Importación / Costo Venezuela",
            size="3",
            weight="medium",
            color=styles.TEXT_PRIMARY,
        ),
        rx.text(
            "Cálculo determinista de costo puesto en Venezuela (DTD Cargo, puerta a puerta). "
            "No se consulta DTD Cargo: la tarifa es un dato editable.",
            size="1",
            color=MUTED,
            padding_top="4px",
        ),
        rx.cond(
            TrackerState.alibaba_landed_error != "",
            rx.text(TrackerState.alibaba_landed_error, size="2", color=BRICK, padding_top="8px"),
        ),
        rx.vstack(
            rx.hstack(
                _landed_field(
                    "Cantidad",
                    TrackerState.alibaba_landed_quantity,
                    TrackerState.set_alibaba_landed_quantity,
                ),
                _landed_field(
                    "Precio proveedor (USD/unidad)",
                    TrackerState.alibaba_landed_supplier_price,
                    TrackerState.set_alibaba_landed_supplier_price,
                ),
                rx.vstack(
                    rx.text(" ", size="1", color=MUTED),
                    rx.button(
                        "Usar datos de negociación",
                        on_click=TrackerState.use_negotiation_values_for_landed_cost,
                        size="1",
                        variant="outline",
                    ),
                    spacing="1",
                    width="100%",
                    align_items="start",
                ),
                spacing="3",
                width="100%",
            ),
            rx.hstack(
                _landed_field(
                    "Número de cajas",
                    TrackerState.alibaba_landed_cartons,
                    TrackerState.set_alibaba_landed_cartons,
                ),
                _landed_field(
                    "Unidades por caja",
                    TrackerState.alibaba_landed_units_per_carton,
                    TrackerState.set_alibaba_landed_units_per_carton,
                ),
                _landed_field(
                    "Peso caja (kg)",
                    TrackerState.alibaba_landed_weight,
                    TrackerState.set_alibaba_landed_weight,
                ),
                spacing="3",
                width="100%",
            ),
            rx.hstack(
                _landed_field(
                    "Largo caja (cm)",
                    TrackerState.alibaba_landed_length,
                    TrackerState.set_alibaba_landed_length,
                ),
                _landed_field(
                    "Ancho caja (cm)",
                    TrackerState.alibaba_landed_width,
                    TrackerState.set_alibaba_landed_width,
                ),
                _landed_field(
                    "Alto caja (cm)",
                    TrackerState.alibaba_landed_height,
                    TrackerState.set_alibaba_landed_height,
                ),
                spacing="3",
                width="100%",
            ),
            rx.hstack(
                _landed_field(
                    "Tarifa DTD USD/CBM",
                    TrackerState.alibaba_landed_rate,
                    TrackerState.set_alibaba_landed_rate,
                    "estimada",
                ),
                rx.vstack(
                    rx.text(
                        "Cotización confirmada",
                        size="1",
                        color=styles.TEXT_SECONDARY,
                        weight="medium",
                    ),
                    rx.checkbox(
                        checked=TrackerState.alibaba_landed_rate_confirmed,
                        on_change=TrackerState.set_alibaba_landed_rate_confirmed,
                    ),
                    spacing="1",
                    width="100%",
                    align_items="start",
                ),
                rx.vstack(
                    rx.text(
                        "Tiene batería",
                        size="1",
                        color=styles.TEXT_SECONDARY,
                        weight="medium",
                    ),
                    rx.checkbox(
                        checked=TrackerState.alibaba_landed_has_battery,
                        on_change=TrackerState.set_alibaba_landed_has_battery,
                    ),
                    spacing="1",
                    width="100%",
                    align_items="start",
                ),
                _landed_field(
                    "Multiplicador batería",
                    TrackerState.alibaba_landed_battery_multiplier,
                    TrackerState.set_alibaba_landed_battery_multiplier,
                ),
                spacing="3",
                width="100%",
            ),
            rx.hstack(
                _landed_field(
                    "Recargo madera/paleta",
                    TrackerState.alibaba_landed_wood_surcharge,
                    TrackerState.set_alibaba_landed_wood_surcharge,
                    "opcional",
                ),
                _landed_field(
                    "Seguro",
                    TrackerState.alibaba_landed_insurance,
                    TrackerState.set_alibaba_landed_insurance,
                    "opcional",
                ),
                _landed_field(
                    "Otros gastos logísticos",
                    TrackerState.alibaba_landed_other_logistics,
                    TrackerState.set_alibaba_landed_other_logistics,
                    "opcional",
                ),
                _landed_field(
                    "Otros gastos importación",
                    TrackerState.alibaba_landed_other_import,
                    TrackerState.set_alibaba_landed_other_import,
                    "opcional",
                ),
                spacing="3",
                width="100%",
            ),
            rx.hstack(
                _landed_field(
                    "Precio venta esperado",
                    TrackerState.alibaba_landed_sale_price,
                    TrackerState.set_alibaba_landed_sale_price,
                    "opcional",
                ),
                _landed_field(
                    "Margen objetivo %",
                    TrackerState.alibaba_landed_margin,
                    TrackerState.set_alibaba_landed_margin,
                    "opcional",
                ),
                spacing="3",
                width="100%",
            ),
            rx.button(
                "Calcular costo puesto en Venezuela",
                on_click=TrackerState.calculate_alibaba_landed_cost,
                size="2",
                **styles.BUTTON_STYLE,
            ),
            rx.cond(
                TrackerState.alibaba_landed_has_result,
                rx.vstack(
                    rx.text(
                        result["rate_label"],
                        size="1",
                        weight="medium",
                        color=BRICK,
                    ),
                    rx.text(result["rate_display"], size="1", color=MUTED),
                    rx.hstack(
                        _landed_card("Producto", result["merchandise_cost"], styles.TEXT_PRIMARY),
                        _landed_card("Transporte estimado", result["shipping_total"], BRICK),
                        _landed_card(
                            "Costo total Venezuela",
                            result["total_landed_cost"],
                            styles.TEXT_PRIMARY,
                        ),
                        _landed_card(
                            "Costo por unidad",
                            result["landed_cost_per_unit"],
                            styles.TEXT_PRIMARY,
                        ),
                        spacing="3",
                        width="100%",
                    ),
                    rx.cond(
                        result["expected_sale_price"] != "",
                        rx.hstack(
                            _landed_card(
                                "Venta esperada",
                                result["expected_sale_price"],
                                styles.TEXT_PRIMARY,
                            ),
                            _landed_card(
                                "Ganancia/unidad",
                                result["gross_profit_per_unit"],
                                styles.TEXT_PRIMARY,
                            ),
                            _landed_card("Margen", result["margin_percent"], styles.TEXT_PRIMARY),
                            _landed_card(
                                "Máximo recomendable proveedor",
                                result["max_supplier_price"],
                                BRICK,
                            ),
                            spacing="3",
                            width="100%",
                        ),
                    ),
                    rx.cond(
                        result["unattractive"] == "1",
                        rx.text(
                            "Económicamente poco atractivo: el margen objetivo no deja "
                            "espacio para pagar al proveedor.",
                            size="2",
                            color=BRICK,
                        ),
                    ),
                    rx.text("CBM total: " + result["total_cbm"], size="1", color=MUTED),
                    rx.text("Peso total: " + result["total_weight"], size="1", color=MUTED),
                    rx.text("Flete base: " + result["freight_base"], size="1", color=MUTED),
                    rx.text(
                        "Flete ajustado: " + result["freight_adjusted"],
                        size="1",
                        color=MUTED,
                    ),
                    rx.text(
                        "Recargos logísticos: " + result["shipping_surcharges"],
                        size="1",
                        color=MUTED,
                    ),
                    rx.text(
                        "Otros gastos de importación: " + result["other_import_costs"],
                        size="1",
                        color=MUTED,
                    ),
                    rx.text(
                        "Precio mínimo de venta para no perder dinero: " + result["break_even"],
                        size="1",
                        color=MUTED,
                    ),
                    spacing="3",
                    width="100%",
                ),
            ),
            spacing="3",
            width="100%",
            padding_top="10px",
        ),
        padding="14px 16px",
        background_color=CARD,
        border=f"1px solid {RULE}",
        width="100%",
        margin_top="16px",
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
                    rx.table.column_header_cell("Seguimiento", color=styles.TEXT_PRIMARY),
                    rx.table.column_header_cell("Venezuela", color=styles.TEXT_PRIMARY),
                    rx.table.column_header_cell("Enlace", color=styles.TEXT_PRIMARY),
                )
            ),
            rx.table.body(
                rx.foreach(
                    TrackerState.alibaba_table_rows,
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
                        rx.table.cell(_alibaba_follow_cell(row)),
                        rx.table.cell(_alibaba_venezuela_cell(row)),
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


def _ml_form() -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.cond(
                TrackerState.ml_has_alibaba_context,
                rx.vstack(
                    rx.text("Título Alibaba", size="1", color=MUTED),
                    rx.text(
                        TrackerState.ml_alibaba_context["title"],
                        size="3",
                        weight="medium",
                        color=styles.TEXT_PRIMARY,
                    ),
                    rx.text(
                        "Proveedor: " + TrackerState.ml_alibaba_context["supplier"],
                        size="1",
                        color=MUTED,
                    ),
                    rx.text(
                        "Precio proveedor: " + TrackerState.ml_alibaba_context["supplier_price"],
                        size="2",
                        color=BRICK,
                    ),
                    rx.text("Traducción al español", size="1", color=MUTED, padding_top="8px"),
                    rx.cond(
                        TrackerState.ml_translation_is_loading,
                        rx.hstack(
                            rx.spinner(size="1"),
                            rx.text("Traduciendo título...", size="2", color=MUTED),
                            spacing="2",
                        ),
                        rx.cond(
                            TrackerState.ml_translated_title != "",
                            rx.text(
                                TrackerState.ml_translated_title,
                                size="3",
                                weight="medium",
                                color=styles.TEXT_PRIMARY,
                            ),
                            rx.text(
                                TrackerState.ml_translation_error,
                                size="2",
                                color=rx.cond(
                                    TrackerState.ml_translation_ui_status == "NOT_CONFIGURED",
                                    MUTED,
                                    BRICK,
                                ),
                            ),
                        ),
                    ),
                    rx.cond(
                        TrackerState.ml_translation_warning != "",
                        rx.text(
                            TrackerState.ml_translation_warning,
                            size="1",
                            color=BRICK,
                        ),
                    ),
                    spacing="1",
                    width="100%",
                    align_items="start",
                ),
            ),
            rx.hstack(
                rx.vstack(
                    rx.text(
                        "Consulta Mercado Libre",
                        size="1",
                        color=styles.TEXT_SECONDARY,
                        weight="medium",
                    ),
                    rx.input(
                        value=TrackerState.ml_query,
                        on_change=TrackerState.set_ml_query,
                        placeholder="mouse inalámbrico",
                        width="100%",
                        **styles.INPUT_STYLE,
                    ),
                    spacing="1",
                    width="100%",
                    align_items="start",
                ),
                rx.vstack(
                    rx.text(
                        "Cantidad de resultados",
                        size="1",
                        color=styles.TEXT_SECONDARY,
                        weight="medium",
                    ),
                    rx.input(
                        type="number",
                        min=1,
                        max=50,
                        value=TrackerState.ml_limit,
                        on_change=TrackerState.set_ml_limit,
                        width="100%",
                        **styles.INPUT_STYLE,
                    ),
                    spacing="1",
                    width="160px",
                    align_items="start",
                ),
                spacing="4",
                width="100%",
                align="end",
            ),
            rx.cond(
                TrackerState.ml_warning != "",
                rx.text(TrackerState.ml_warning, color=BRICK, size="2"),
            ),
            rx.hstack(
                rx.box(
                    rx.text("Proveedor", size="1", color=styles.TEXT_SECONDARY),
                    rx.text("Mercado Libre Venezuela", size="3", weight="medium"),
                ),
                rx.spacer(),
                rx.button(
                    rx.cond(
                        TrackerState.ml_is_loading,
                        rx.hstack(
                            rx.spinner(size="1"),
                            rx.text("Buscando publicaciones en Mercado Libre Venezuela..."),
                            spacing="2",
                        ),
                        rx.cond(
                            TrackerState.ml_has_alibaba_context,
                            rx.text("Buscar comparables"),
                            rx.text("Buscar precios publicados"),
                        ),
                    ),
                    on_click=TrackerState.search_mercadolibre,
                    disabled=TrackerState.ml_is_loading,
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


def _ml_stat_card(label: str, key: str, *, accent: bool = False) -> rx.Component:
    return rx.box(
        rx.text(label, size="1", color=MUTED),
        rx.text(
            TrackerState.ml_live_summary[key],
            size="5",
            weight="medium",
            color=BRICK if accent else styles.TEXT_PRIMARY,
        ),
        min_width="132px",
        padding="12px 14px",
        background_color=CARD,
        border=f"1px solid {RULE}",
    )


def _ml_summary() -> rx.Component:
    return rx.vstack(
        rx.text(
            "Precios publicados observados en Mercado Libre Venezuela",
            size="2",
            weight="medium",
            color=styles.TEXT_PRIMARY,
        ),
        rx.text(
            "No son precios de venta efectivos. Son precios publicados observados.",
            size="1",
            color=MUTED,
        ),
        rx.hstack(
            _ml_stat_card("Comparables", "comparables"),
            _ml_stat_card("Mínimo", "minimo", accent=True),
            _ml_stat_card("P25", "p25", accent=True),
            _ml_stat_card("Mediana", "mediana", accent=True),
            _ml_stat_card("Precio típico", "precio_tipico", accent=True),
            _ml_stat_card("P75", "p75", accent=True),
            _ml_stat_card("Máximo", "maximo", accent=True),
            spacing="3",
            padding_y="8px",
            width="100%",
            wrap="wrap",
        ),
        spacing="2",
        width="100%",
    )


def _ml_controls() -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.vstack(
                rx.text("Ordenar por", size="1", color=styles.TEXT_SECONDARY, weight="medium"),
                rx.select(
                    [
                        "Original",
                        "Precio: menor a mayor",
                        "Precio: mayor a menor",
                        "Mayor relevancia",
                    ],
                    value=TrackerState.ml_sort_label,
                    on_change=TrackerState.set_ml_sort,
                    **styles.SELECT_STYLE,
                ),
                spacing="1",
                align_items="start",
            ),
            rx.vstack(
                rx.text("Precio mínimo", size="1", color=styles.TEXT_SECONDARY, weight="medium"),
                rx.input(
                    value=TrackerState.ml_price_min,
                    on_change=TrackerState.set_ml_price_min,
                    placeholder="3.00",
                    width="120px",
                    **styles.INPUT_STYLE,
                ),
                spacing="1",
                align_items="start",
            ),
            rx.vstack(
                rx.text("Precio máximo", size="1", color=styles.TEXT_SECONDARY, weight="medium"),
                rx.input(
                    value=TrackerState.ml_price_max,
                    on_change=TrackerState.set_ml_price_max,
                    placeholder="20.00",
                    width="120px",
                    **styles.INPUT_STYLE,
                ),
                spacing="1",
                align_items="start",
            ),
            rx.vstack(
                rx.text("Relevancia", size="1", color=styles.TEXT_SECONDARY, weight="medium"),
                rx.select(
                    ["Todos", "30+", "60+", "80+"],
                    value=TrackerState.ml_min_relevance_label,
                    on_change=TrackerState.set_ml_min_relevance,
                    **styles.SELECT_STYLE,
                ),
                spacing="1",
                align_items="start",
            ),
            rx.hstack(
                rx.switch(
                    checked=TrackerState.ml_hide_outliers,
                    on_change=TrackerState.set_ml_hide_outliers,
                ),
                rx.text("Ocultar outliers", size="2", color=styles.TEXT_PRIMARY),
                spacing="2",
                align="center",
                padding_bottom="6px",
            ),
            rx.button(
                "Limpiar filtros",
                on_click=TrackerState.clear_ml_filters,
                **styles.BUTTON_STYLE,
            ),
            spacing="4",
            width="100%",
            align="end",
            wrap="wrap",
        ),
        rx.cond(
            TrackerState.ml_filter_error != "",
            rx.text(TrackerState.ml_filter_error, color=BRICK, size="2"),
        ),
        rx.text(TrackerState.ml_counter, size="2", color=MUTED),
        width="100%",
        padding_y="8px",
    )


def _ml_relevance_cell(row: rx.Var) -> rx.Component:
    return rx.tooltip(
        rx.vstack(
            rx.text(row["relevance"], size="1", weight="medium", color=styles.TEXT_PRIMARY),
            rx.text(row["relevance_label"], size="1", color=MUTED),
            spacing="0",
        ),
        content=row["relevance_label"] + " · " + row["relevance_tokens"],
    )


def _ml_table() -> rx.Component:
    return rx.box(
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("Imagen", color=styles.TEXT_PRIMARY),
                    rx.table.column_header_cell("Producto", color=styles.TEXT_PRIMARY),
                    rx.table.column_header_cell("Precio", color=styles.TEXT_PRIMARY),
                    rx.table.column_header_cell("Moneda", color=styles.TEXT_PRIMARY),
                    rx.table.column_header_cell("Condición", color=styles.TEXT_PRIMARY),
                    rx.table.column_header_cell("Vendedor", color=styles.TEXT_PRIMARY),
                    rx.table.column_header_cell("Envío", color=styles.TEXT_PRIMARY),
                    rx.table.column_header_cell("Relevancia", color=styles.TEXT_PRIMARY),
                    rx.table.column_header_cell("Link", color=styles.TEXT_PRIMARY),
                )
            ),
            rx.table.body(
                rx.foreach(
                    TrackerState.ml_visible_rows,
                    lambda row: rx.table.row(
                        rx.table.cell(
                            rx.cond(
                                row["thumbnail_url"] != "",
                                rx.image(src=row["thumbnail_url"], width="48px", height="48px"),
                                rx.text("—", color=MUTED),
                            )
                        ),
                        rx.table.cell(row["title"], color=styles.TEXT_PRIMARY),
                        rx.table.cell(row["price"], color=styles.TEXT_PRIMARY),
                        rx.table.cell(row["currency"], color=styles.TEXT_PRIMARY),
                        rx.table.cell(row["condition"], color=styles.TEXT_PRIMARY),
                        rx.table.cell(row["seller_name"], color=styles.TEXT_PRIMARY),
                        rx.table.cell(row["shipping"], color=styles.TEXT_PRIMARY),
                        rx.table.cell(_ml_relevance_cell(row)),
                        rx.table.cell(
                            rx.cond(
                                row["permalink"] != "",
                                rx.link("Ver", href=row["permalink"], is_external=True),
                                rx.text("—", color=MUTED),
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


def _ml_landed_comparison() -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.text("Costo Venezuela", size="3", weight="medium", color=styles.TEXT_PRIMARY),
            rx.text(
                "Compara el costo puesto por unidad con precios publicados. "
                "No modifica la negociación.",
                size="1",
                color=MUTED,
            ),
            rx.button(
                "Comparar con costo Venezuela",
                on_click=TrackerState.compare_ml_with_landed_cost,
                **styles.BUTTON_STYLE,
            ),
            rx.cond(
                TrackerState.ml_has_comparison,
                rx.cond(
                    TrackerState.ml_comparison_comparable,
                    rx.vstack(
                        rx.text(
                            "Costo puesto / u: " + TrackerState.ml_comparison["landed"],
                            size="2",
                            weight="medium",
                        ),
                        rx.hstack(
                            rx.box(
                                rx.text("Conservador (P25)", size="1", color=MUTED),
                                rx.text(TrackerState.ml_comparison["conservative_price"], size="3"),
                                rx.text(
                                    TrackerState.ml_comparison["conservative_profit"] + "/u",
                                    size="2",
                                ),
                                rx.text(
                                    TrackerState.ml_comparison["conservative_margin"],
                                    size="2",
                                    color=MUTED,
                                ),
                            ),
                            rx.box(
                                rx.text("Típico (mediana)", size="1", color=MUTED),
                                rx.text(TrackerState.ml_comparison["typical_price"], size="3"),
                                rx.text(
                                    TrackerState.ml_comparison["typical_profit"] + "/u", size="2"
                                ),
                                rx.text(
                                    TrackerState.ml_comparison["typical_margin"],
                                    size="2",
                                    color=MUTED,
                                ),
                            ),
                            rx.box(
                                rx.text("Alto (P75)", size="1", color=MUTED),
                                rx.text(TrackerState.ml_comparison["high_price"], size="3"),
                                rx.text(TrackerState.ml_comparison["high_profit"] + "/u", size="2"),
                                rx.text(
                                    TrackerState.ml_comparison["high_margin"],
                                    size="2",
                                    color=MUTED,
                                ),
                            ),
                            spacing="5",
                            wrap="wrap",
                        ),
                        spacing="2",
                        width="100%",
                    ),
                    rx.text(TrackerState.ml_comparison["message"], color=BRICK, size="2"),
                ),
            ),
            spacing="3",
            width="100%",
        ),
        background_color=CARD,
        border=f"1px solid {RULE}",
        padding="22px",
        width="100%",
        margin_top="18px",
    )


def _ml_alibaba_association() -> rx.Component:
    result = TrackerState.ml_alibaba_association
    return rx.cond(
        TrackerState.ml_show_alibaba_association,
        rx.box(
            rx.vstack(
                rx.text("Producto Alibaba", size="3", weight="medium", color=styles.TEXT_PRIMARY),
                rx.text(result["product_title"], size="2", color=styles.TEXT_PRIMARY),
                rx.text("Precio proveedor: " + result["supplier_price"], size="2", color=BRICK),
                rx.cond(
                    result["landed"] != "",
                    rx.text(
                        "Costo puesto Venezuela: " + result["landed"] + " / unidad",
                        size="2",
                        weight="medium",
                    ),
                    rx.text(result["missing_landed_message"], size="2", color=MUTED),
                ),
                rx.text(
                    "Mercado Libre Venezuela",
                    size="2",
                    weight="medium",
                    color=styles.TEXT_PRIMARY,
                    padding_top="8px",
                ),
                rx.text(result["published_note"], size="1", color=MUTED),
                rx.text(result["quality_note"], size="1", color=MUTED),
                rx.cond(
                    result["sparse"] == "1",
                    rx.text(result["sparse_message"], size="2", color=BRICK),
                ),
                rx.hstack(
                    _landed_card("P25", result["p25"], BRICK),
                    _landed_card("Mediana", result["median"], BRICK),
                    _landed_card("P75", result["p75"], BRICK),
                    spacing="3",
                    wrap="wrap",
                ),
                rx.cond(
                    result["currency_message"] != "",
                    rx.text(result["currency_message"], size="2", color=BRICK),
                ),
                rx.cond(
                    result["has_profitability"] == "1",
                    rx.hstack(
                        rx.box(
                            rx.text("Escenario conservador", size="1", color=MUTED),
                            rx.text(result["conservative_price"], size="3"),
                            rx.text(result["conservative_profit"] + "/u", size="2"),
                            rx.text(result["conservative_margin"], size="2", color=MUTED),
                        ),
                        rx.box(
                            rx.text("Escenario típico", size="1", color=MUTED),
                            rx.text(result["typical_price"], size="3"),
                            rx.text(result["typical_profit"] + "/u", size="2"),
                            rx.text(result["typical_margin"], size="2", color=MUTED),
                        ),
                        rx.box(
                            rx.text("Escenario alto", size="1", color=MUTED),
                            rx.text(result["high_price"], size="3"),
                            rx.text(result["high_profit"] + "/u", size="2"),
                            rx.text(result["high_margin"], size="2", color=MUTED),
                        ),
                        spacing="5",
                        wrap="wrap",
                    ),
                ),
                spacing="2",
                width="100%",
            ),
            background_color=CARD,
            border=f"1px solid {RULE}",
            padding="22px",
            width="100%",
        ),
    )


def _ml_body() -> rx.Component:
    return rx.box(
        rx.cond(
            TrackerState.ml_ui_status == "LOADING",
            rx.hstack(
                rx.spinner(),
                rx.text("Buscando publicaciones en Mercado Libre Venezuela..."),
                spacing="3",
                padding_y="20px",
            ),
        ),
        rx.cond(
            TrackerState.ml_ui_status == "ERROR",
            rx.box(
                rx.text(TrackerState.ml_error, color=BRICK),
                border=f"1px solid {BRICK}",
                padding="14px 16px",
                width="100%",
            ),
        ),
        rx.cond(
            TrackerState.ml_ui_status == "EMPTY",
            rx.text("No se encontraron publicaciones en Mercado Libre Venezuela.", color=MUTED),
        ),
        rx.cond(
            TrackerState.ml_ui_status == "SUCCESS",
            rx.vstack(
                _ml_summary(),
                _ml_alibaba_association(),
                _ml_controls(),
                _ml_table(),
                _ml_landed_comparison(),
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
                _market_tab(
                    "Mercado Libre Venezuela",
                    "mercadolibre",
                    TrackerState.show_mercadolibre_tab,
                ),
                spacing="6",
                width="100%",
                border_bottom=f"1px solid {RULE}",
                margin_bottom="18px",
            ),
            rx.cond(
                TrackerState.marketplace_tab == "facebook",
                rx.vstack(_form(), _body(), spacing="0", width="100%"),
                rx.cond(
                    TrackerState.marketplace_tab == "alibaba",
                    rx.vstack(
                        _alibaba_form(),
                        _alibaba_body(),
                        _alibaba_tracking(),
                        _alibaba_negotiation(),
                        _alibaba_landed_cost(),
                        spacing="0",
                        width="100%",
                    ),
                    rx.vstack(_ml_form(), _ml_body(), spacing="0", width="100%"),
                ),
            ),
            max_width="1080px",
            width="100%",
            margin="0 auto",
            padding="36px 20px 64px",
        ),
        background_color=PAPER,
        min_height="100vh",
    )
