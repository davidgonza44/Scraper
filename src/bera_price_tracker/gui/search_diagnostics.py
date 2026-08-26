"""Current-search provider diagnostics. Display-only; no provider I/O."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from bera_price_tracker.application.provider_acquisition import UNAVAILABLE, format_count
from bera_price_tracker.gui.brands import PLATFORM_ALIBABA, PLATFORM_FACEBOOK, PLATFORM_ML
from bera_price_tracker.gui.search_session import PHASE_PARTIAL, PHASE_RUNNING

UI_SUCCESS = "SUCCESS"
UI_EMPTY = "EMPTY"
UI_ERROR = "ERROR"
UI_LOADING = "LOADING"
UI_INITIAL = "INITIAL"

_FACEBOOK_REJECTION_LABELS: tuple[tuple[str, str], ...] = (
    ("invalid_price", "Precio inválido"),
    ("free_price", "Gratis"),
    ("out_of_scope_location", "Ubicación fuera de alcance"),
    ("missing_product_id", "Sin identificador"),
    ("empty_title", "Sin título"),
    ("duplicate_product_id", "Duplicado"),
    ("source_error", "Error de origen"),
)


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _int_or_none(value: object) -> int | None:
    text = _text(value)
    if not text:
        return None
    try:
        number = int(text)
    except ValueError:
        return None
    if number < 0:
        return None
    return number


def _metric_from_summary(summary: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        if key not in summary:
            continue
        raw = summary.get(key)
        if raw is None or raw == "":
            continue
        parsed = _int_or_none(raw)
        if parsed is None:
            text = _text(raw)
            if text in {UNAVAILABLE, "—"}:
                return UNAVAILABLE
            continue
        return str(parsed)
    return UNAVAILABLE


def _outcome(ui_status: str, usable: str) -> tuple[str, str]:
    if ui_status == UI_LOADING:
        return "loading", "Buscando..."
    if ui_status == UI_ERROR:
        return "error", "Error"
    if ui_status in {UI_SUCCESS, UI_EMPTY}:
        if usable in {"0", UNAVAILABLE} or ui_status == UI_EMPTY:
            if usable == "0" or ui_status == UI_EMPTY:
                return "empty", "Sin resultados"
        return "ready", "Resultados"
    return "idle", "Sin búsqueda"


def _lines(
    *,
    requested: str,
    fetched: str,
    usable: str,
    extra: Sequence[tuple[str, str]] = (),
) -> list[dict[str, str]]:
    rows = [
        {"label": "Solicitados", "value": requested},
        {"label": "Recibidos", "value": fetched},
        {"label": "Válidos", "value": usable},
    ]
    rows.extend(
        {"label": label, "value": value} for label, value in extra if value not in {"", "0"}
    )
    return rows


def alibaba_diagnostic(
    *,
    ui_status: str,
    summary: Mapping[str, object],
    requested_limit: int,
    usable_rows: int,
    error: str = "",
) -> dict[str, Any]:
    requested = _metric_from_summary(summary, "requested")
    if requested == UNAVAILABLE:
        requested = format_count(requested_limit)
    fetched = _metric_from_summary(summary, "fetched")
    usable = _metric_from_summary(summary, "usable")
    if usable == UNAVAILABLE:
        usable = format_count(usable_rows)
    rejected = _metric_from_summary(summary, "rejected")
    extra: list[tuple[str, str]] = []
    if rejected not in {UNAVAILABLE, "0", ""}:
        extra.append(("Rechazados", rejected))
    outcome, label = _outcome(ui_status, usable)
    detail = _text(error) if outcome == "error" else ""
    return {
        "platform": "Alibaba",
        "platform_id": PLATFORM_ALIBABA,
        "requested": requested,
        "fetched": fetched,
        "usable": usable,
        "rejected": rejected,
        "status": ui_status,
        "outcome": outcome,
        "outcome_label": label,
        "detail": detail,
        "lines": _lines(requested=requested, fetched=fetched, usable=usable, extra=extra),
    }


def facebook_diagnostic(
    *,
    ui_status: str,
    summary: Mapping[str, object],
    requested_limit: int,
    usable_rows: int,
    error: str = "",
) -> dict[str, Any]:
    requested = _metric_from_summary(summary, "requested")
    if requested == UNAVAILABLE:
        requested = format_count(requested_limit)
    fetched = _metric_from_summary(summary, "fetched")
    usable = _metric_from_summary(summary, "usable")
    if usable == UNAVAILABLE:
        usable = format_count(usable_rows)
    extra: list[tuple[str, str]] = []
    for key, label in _FACEBOOK_REJECTION_LABELS:
        value = _metric_from_summary(summary, key)
        if value not in {UNAVAILABLE, "0", ""}:
            extra.append((label, value))
    outcome, status_label = _outcome(ui_status, usable)
    detail = _text(error) if outcome == "error" else ""
    return {
        "platform": "Facebook Marketplace",
        "platform_id": PLATFORM_FACEBOOK,
        "requested": requested,
        "fetched": fetched,
        "usable": usable,
        "rejected": _metric_from_summary(summary, "rejected"),
        "status": ui_status,
        "outcome": outcome,
        "outcome_label": status_label,
        "detail": detail,
        "lines": _lines(requested=requested, fetched=fetched, usable=usable, extra=extra),
    }


def mercadolibre_diagnostic(
    *,
    ui_status: str,
    summary: Mapping[str, object],
    requested_limit: int,
    usable_rows: int,
    error: str = "",
) -> dict[str, Any]:
    requested = _metric_from_summary(summary, "requested")
    if requested == UNAVAILABLE:
        requested = format_count(requested_limit)
    fetched = _metric_from_summary(summary, "fetched")
    usable = _metric_from_summary(summary, "usable")
    if usable == UNAVAILABLE:
        usable = format_count(usable_rows)
    rejected = _metric_from_summary(summary, "rejected")
    extra: list[tuple[str, str]] = []
    if rejected not in {UNAVAILABLE, "0", ""}:
        extra.append(("Rechazados", rejected))
    outcome, label = _outcome(ui_status, usable)
    detail = _text(error) if outcome == "error" else ""
    return {
        "platform": "Mercado Libre",
        "platform_id": PLATFORM_ML,
        "requested": requested,
        "fetched": fetched,
        "usable": usable,
        "rejected": rejected,
        "status": ui_status,
        "outcome": outcome,
        "outcome_label": label,
        "detail": detail,
        "lines": _lines(requested=requested, fetched=fetched, usable=usable, extra=extra),
    }


def attach_diagnostics(
    cards: Sequence[Mapping[str, Any]],
    diagnostics: Sequence[Mapping[str, Any]],
    *,
    open_platforms: Sequence[str] = (),
) -> list[dict[str, Any]]:
    by_id = {str(item.get("platform_id")): item for item in diagnostics}
    open_set = {str(item) for item in open_platforms}
    attached: list[dict[str, Any]] = []
    for card in cards:
        row = dict(card)
        platform_id = str(row.get("platform_id") or "")
        diagnostic = by_id.get(platform_id, {})
        outcome = str(diagnostic.get("outcome") or row.get("status") or "")
        row["diagnostic_outcome"] = outcome
        row["diagnostic_lines"] = list(diagnostic.get("lines") or [])
        row["diagnostic_detail"] = str(diagnostic.get("detail") or "")
        row["details_open"] = platform_id in open_set
        row["details_available"] = outcome in {"empty", "error", "ready"}
        if outcome == "empty":
            row["status"] = "empty-results"
            row["status_label"] = "Sin resultados"
        elif outcome == "error":
            row["status"] = "error"
            row["status_label"] = "Error"
        attached.append(row)
    return attached


def export_enabled(*, phase: str, listing_count: int) -> bool:
    if listing_count <= 0:
        return False
    if phase == PHASE_RUNNING:
        return False
    return phase in {"COMPLETE", PHASE_PARTIAL}
