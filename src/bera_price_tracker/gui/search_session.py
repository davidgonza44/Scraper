"""Search-session presentation. Display-only; no provider I/O and no FX."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from bera_price_tracker.application.alibaba_reputation import parse_rating_0_5
from bera_price_tracker.gui.analysis import boxplot_geometry, parse_decimal_text
from bera_price_tracker.gui.brands import PLATFORM_ALIBABA, PLATFORM_FACEBOOK, PLATFORM_ML
from bera_price_tracker.gui.search_scope import (
    MODE_LABELS,
    MODE_MULTI,
    PLATFORM_LABELS,
)

PHASE_IDLE = "IDLE"
PHASE_RUNNING = "RUNNING"
PHASE_COMPLETE = "COMPLETE"
PHASE_PARTIAL = "PARTIAL"
PHASE_ERROR = "ERROR"

FINISHED_OK = frozenset({"SUCCESS", "EMPTY"})
SEARCH_SETUP_SUBTITLE = "Encuentra y compara precios en diferentes plataformas"
SEARCH_MODE_LAYOUT = "two-columns"
EMPTY_STAT = "—"
USD_BASIS = "USD"


def should_render_search_fixtures(environ: Mapping[str, str] | None = None) -> bool:
    source: Mapping[str, str] = os.environ if environ is None else environ
    return str(source.get("BERA_UI_FIXTURES", "")) == "1"


def session_phase(
    *,
    session_active: bool,
    providers: Sequence[str],
    loading: Mapping[str, bool],
    statuses: Mapping[str, str],
) -> str:
    if not session_active:
        return PHASE_IDLE
    selected = tuple(providers)
    if any(loading.get(provider, False) for provider in selected):
        return PHASE_RUNNING
    ok = [provider for provider in selected if statuses.get(provider, "") in FINISHED_OK]
    failed = [provider for provider in selected if statuses.get(provider, "") == "ERROR"]
    if failed and ok:
        return PHASE_PARTIAL
    if failed and not ok:
        return PHASE_ERROR
    if ok:
        return PHASE_COMPLETE
    return PHASE_RUNNING


def shows_setup(phase: str) -> bool:
    return phase in {PHASE_IDLE, PHASE_RUNNING}


def shows_results(phase: str) -> bool:
    return phase in {PHASE_COMPLETE, PHASE_PARTIAL, PHASE_ERROR}


def completion_status_copy(phase: str) -> dict[str, str]:
    if phase == PHASE_COMPLETE:
        return {"tone": "success", "label": "Búsqueda completada"}
    if phase == PHASE_PARTIAL:
        return {"tone": "warning", "label": "Búsqueda completada con incidencias"}
    if phase == PHASE_ERROR:
        return {"tone": "danger", "label": "Búsqueda con error"}
    if phase == PHASE_RUNNING:
        return {"tone": "neutral", "label": "Buscando..."}
    return {"tone": "neutral", "label": ""}


def format_session_duration(elapsed_ms: int) -> str:
    if elapsed_ms <= 0:
        return EMPTY_STAT
    seconds = elapsed_ms / 1000
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes = int(seconds // 60)
    rest = int(round(seconds % 60))
    if rest == 60:
        minutes += 1
        rest = 0
    return f"{minutes} min {rest} s"


def format_session_timestamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M")


def seller_rating(raw: object) -> dict[str, str | int | bool]:
    """Genuine 0–5 numeric rating only. Never treat relevance or opportunity as stars."""

    parsed = parse_rating_0_5(raw)
    if parsed is None:
        return {
            "available": False,
            "value": "",
            "label": "Sin calificación",
            "filled": 0,
        }
    filled = int(parsed.to_integral_value())
    filled = max(0, min(5, filled))
    text = f"{parsed.normalize()}".rstrip("0").rstrip(".") if "." in str(parsed) else str(parsed)
    if parsed == parsed.to_integral_value():
        text = str(int(parsed))
    else:
        text = f"{parsed:.1f}"
    return {
        "available": True,
        "value": text,
        "label": f"{text}/5",
        "filled": filled,
    }


def product_rating_display(
    raw: object, *, review_count: object = ""
) -> dict[str, str | int | bool]:
    """Product/listing 0–5 rating. Never a seller, relevance, or opportunity score."""

    rating = seller_rating(raw)
    count = str(review_count or "").strip()
    if rating["available"] and count:
        rating["label"] = f"{rating['value']} · {count} reseñas"
    elif rating["available"]:
        rating["label"] = str(rating["value"])
    rating["caption"] = "Calificación del producto" if rating["available"] else ""
    return rating


def opportunity_gauge(score_value: object, score_text: object = "") -> dict[str, str | int | bool]:
    """Alibaba opportunity score 0–100. Not a cross-market invention."""

    try:
        if isinstance(score_value, bool):
            score = 0
        elif isinstance(score_value, int):
            score = score_value
        else:
            score = int(str(score_value))
    except (TypeError, ValueError):
        score = 0
    has_text = bool(str(score_text or "").strip())
    if score <= 0 and not has_text:
        return {
            "available": False,
            "score": 0,
            "percent": "0%",
            "label": "Análisis no disponible",
        }
    score = max(0, min(100, score))
    return {
        "available": True,
        "score": score,
        "percent": f"{score}%",
        "label": "Oportunidad Alibaba",
    }


def parse_stat_number(text: object) -> Decimal | None:
    parsed = parse_decimal_text(text)
    if parsed is not None:
        return parsed
    if not isinstance(text, str):
        return None
    cleaned = (
        text.replace("USD", " ")
        .replace("VES", " ")
        .replace("US$", " ")
        .replace("$", " ")
        .replace(",", "")
        .strip()
    )
    token = cleaned.split()[0] if cleaned.split() else ""
    try:
        value = Decimal(token)
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite():
        return None
    return value


def _usd_basis(currency: object, basis: object = "") -> str | None:
    currency_text = str(currency or "").strip().upper()
    basis_text = str(basis or "").strip().upper()
    if currency_text == USD_BASIS:
        return USD_BASIS
    if USD_BASIS in basis_text and "VES" not in currency_text:
        return USD_BASIS
    return None


def boxplot_track(
    *,
    platform: str,
    minimum: object,
    p25: object,
    median: object,
    p75: object,
    maximum: object,
    currency: object = "",
    basis: object = "",
) -> dict[str, str]:
    label = PLATFORM_LABELS.get(platform, platform)
    comparable = _usd_basis(currency, basis)
    values = (
        parse_stat_number(minimum),
        parse_stat_number(p25),
        parse_stat_number(median),
        parse_stat_number(p75),
        parse_stat_number(maximum),
    )
    if comparable != USD_BASIS or any(item is None for item in values):
        return {
            "platform": platform,
            "label": label,
            "available": "",
            "currency": str(currency or ""),
            "basis": str(basis or ""),
            "minimum": "",
            "p25": "",
            "median": "",
            "p75": "",
            "maximum": "",
            "box_left": "0%",
            "box_width": "0%",
            "median_left": "0%",
            "box_class": f"bera-boxplot-box bera-boxplot-{platform}",
        }
    low, q1, mid, q3, high = values
    return {
        "platform": platform,
        "label": label,
        "available": "1",
        "currency": USD_BASIS,
        "basis": str(basis or USD_BASIS),
        "minimum": str(low),
        "p25": str(q1),
        "median": str(mid),
        "p75": str(q3),
        "maximum": str(high),
        "box_class": f"bera-boxplot-box bera-boxplot-{platform}",
        **boxplot_geometry(low, q1, mid, q3, high),
    }


def align_boxplot_tracks(tracks: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    """Share one numeric scale across USD tracks. Never mix other currencies."""

    usable = [dict(track) for track in tracks if track.get("available") == "1"]
    if not usable:
        return [dict(track) for track in tracks]
    numbers: list[Decimal] = []
    for track in usable:
        for key in ("minimum", "p25", "median", "p75", "maximum"):
            parsed = parse_stat_number(track.get(key, ""))
            if parsed is not None:
                numbers.append(parsed)
    if not numbers:
        return [dict(track) for track in tracks]
    scale_low = min(numbers)
    scale_high = max(numbers)
    aligned: list[dict[str, str]] = []
    for source in tracks:
        row = dict(source)
        if row.get("available") != "1":
            aligned.append(row)
            continue
        row.update(
            _geometry_on_scale(
                parse_stat_number(row["minimum"]),
                parse_stat_number(row["p25"]),
                parse_stat_number(row["median"]),
                parse_stat_number(row["p75"]),
                parse_stat_number(row["maximum"]),
                scale_low,
                scale_high,
            )
        )
        aligned.append(row)
    return aligned


def _geometry_on_scale(
    minimum: Decimal | None,
    p25: Decimal | None,
    median: Decimal | None,
    p75: Decimal | None,
    maximum: Decimal | None,
    scale_low: Decimal,
    scale_high: Decimal,
) -> dict[str, str]:
    values = (minimum, p25, median, p75, maximum)
    if any(item is None for item in values):
        return {"available": "", "box_left": "0%", "box_width": "0%", "median_left": "0%"}
    q1 = p25
    q3 = p75
    mid = median
    assert q1 is not None and q3 is not None and mid is not None

    def percent(value: Decimal) -> str:
        span = scale_high - scale_low
        if span == 0:
            return "50.00%"
        ratio = (value - scale_low) / span * Decimal("100")
        return f"{ratio:.2f}%"

    span = scale_high - scale_low
    width = "0.00%" if span == 0 else f"{((q3 - q1) / span * Decimal('100')):.2f}%"
    return {
        "available": "1",
        "box_left": percent(q1),
        "box_width": width,
        "median_left": percent(mid),
    }


def quick_insight(tracks: Sequence[Mapping[str, str]]) -> str:
    """Deterministic median comparison on a shared USD basis only."""

    usable = [
        track
        for track in tracks
        if track.get("available") == "1" and parse_stat_number(track.get("median")) is not None
    ]
    if len(usable) < 2:
        return ""
    ranked = sorted(usable, key=lambda item: parse_stat_number(item["median"]) or Decimal("0"))
    cheaper = ranked[0]
    costlier = ranked[-1]
    low = parse_stat_number(cheaper["median"])
    high = parse_stat_number(costlier["median"])
    if low is None or high is None or high == 0 or cheaper["platform"] == costlier["platform"]:
        return ""
    if low >= high:
        return ""
    percent = ((high - low) / high * Decimal("100")).quantize(Decimal("1"))
    return f"{cheaper['label']} tiene una mediana {percent}% menor que {costlier['label']}"


def search_summary_view(
    *,
    mode: str,
    limit: int,
    counts: Mapping[str, int],
    duration_label: str,
) -> dict[str, str]:
    total = sum(max(0, int(counts.get(platform, 0))) for platform in PLATFORM_LABELS)
    return {
        "mode_label": MODE_LABELS.get(mode, MODE_LABELS[MODE_MULTI]),
        "limit_label": str(limit),
        "total_label": str(total),
        "duration_label": duration_label or EMPTY_STAT,
        "alibaba_count": str(counts.get(PLATFORM_ALIBABA, 0)),
        "facebook_count": str(counts.get(PLATFORM_FACEBOOK, 0)),
        "ml_count": str(counts.get(PLATFORM_ML, 0)),
    }


def best_opportunity_copy(alibaba_row: Any | None) -> dict[str, str]:
    if alibaba_row is None:
        return {"available": "", "heading": "Análisis no disponible", "detail": ""}
    gauge = opportunity_gauge(
        getattr(alibaba_row, "score_value", 0),
        getattr(alibaba_row, "score", ""),
    )
    if not gauge["available"]:
        return {"available": "", "heading": "Análisis no disponible", "detail": ""}
    title = str(getattr(alibaba_row, "title", "") or "").strip()
    price = str(getattr(alibaba_row, "price", "") or "").strip()
    detail_parts = [str(gauge["label"]), f"{gauge['score']}/100"]
    if title:
        detail_parts.append(title)
    if price:
        detail_parts.append(price)
    return {
        "available": "1",
        "heading": "Oportunidad Alibaba",
        "detail": " · ".join(detail_parts),
    }
