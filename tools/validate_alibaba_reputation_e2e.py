"""One-shot end-to-end validation of the Alibaba supplier reputation flow.

Drives the REAL application path:

    run_alibaba_search -> SearchAlibabaProducts -> ApifyAlibabaClient
        -> map_alibaba_item -> AlibabaProduct -> reputation -> GUI rows

Live mode (no arguments) creates exactly ONE Actor run, with no retries.
Replay mode (``python tools/validate_alibaba_reputation_e2e.py <run_id>``)
creates ZERO Actor runs: it reads the already-succeeded run and its dataset
via GET requests only, so the same dataset is reused for the whole
validation. Prints a sanitized report only: never the token, raw JSON items,
chatToken, contactSupplier, supplierHref, supplierHomeHref, companyId or
trackInfo.
"""

from __future__ import annotations

import dataclasses
import re
import statistics
import sys
from collections.abc import Mapping
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parents[1]

QUERY = "wireless mouse"
LIMIT = 20

REPUTATION_RAW_FIELDS = (
    "goldSupplierYears",
    "supplierServiceScore",
    "reviewScore",
    "reviewCount",
)

FORBIDDEN_REPORT_FIELDS = (
    "chatToken",
    "contactSupplier",
    "supplierHref",
    "supplierHomeHref",
    "companyId",
    "trackInfo",
)

# Keys previously observed on SUCCEEDED runs (mirrors tests/unit/test_alibaba.py).
PREVIOUSLY_OBSERVED_ACTOR_KEYS = frozenset(
    {
        "badges",
        "certifications",
        "chatToken",
        "companyId",
        "companyLogo",
        "companyName",
        "contactSupplier",
        "countryCode",
        "customGroup",
        "displayStarLevel",
        "eurl",
        "goldSupplierYears",
        "id",
        "isShowAd",
        "loopSellingPoints",
        "lyb",
        "mainImage",
        "moq",
        "moqV2",
        "multiImage",
        "pcLoopSellingPoints",
        "price",
        "productId",
        "productScore",
        "productUrl",
        "reviewCount",
        "reviewScore",
        "shippingScore",
        "showAddToCart",
        "showCrown",
        "soldOrder",
        "supplierHomeHref",
        "supplierHref",
        "supplierService",
        "supplierServiceScore",
        "title",
        "tmlid",
        "trackInfo",
    }
)


def load_dotenv_without_printing(path: Path) -> None:
    from bera_price_tracker.config import load_local_environment

    load_local_environment(dotenv_path=path)


class RecordingActorClient:
    """Counts real Actor run creations before delegating."""

    def __init__(self, inner: Any, record: dict[str, Any]) -> None:
        self._inner = inner
        self._record = record

    def call(self, *, run_input: dict[str, object]) -> Any:
        self._record["actor_calls_created"] += 1
        run = self._inner.call(run_input=run_input)
        if isinstance(run, Mapping):
            self._record["run_status"] = run.get("status")
            self._record["run_id"] = run.get("id")
        return run


class ReplayActorClient:
    """Returns an existing run via GET. Never creates a new Actor run."""

    def __init__(self, runs_client: Any, record: dict[str, Any]) -> None:
        self._runs_client = runs_client
        self._record = record

    def call(self, *, run_input: dict[str, object]) -> Any:
        del run_input
        run = self._runs_client.get()
        if isinstance(run, Mapping):
            self._record["run_status"] = run.get("status")
            self._record["run_id"] = run.get("id")
        return run


class RecordingDatasetClient:
    def __init__(self, inner: Any, record: dict[str, Any]) -> None:
        self._inner = inner
        self._record = record

    def list_items(self, *, limit: int) -> Any:
        page = self._inner.list_items(limit=limit)
        self._record["raw_items"] = list(page.items)
        return page


class RecordingApifyClient:
    def __init__(self, token: str, record: dict[str, Any], replay_run_id: str | None) -> None:
        from apify_client import ApifyClient

        self._inner = ApifyClient(token)
        self._record = record
        self._replay_run_id = replay_run_id

    def actor(self, actor_id: str) -> RecordingActorClient | ReplayActorClient:
        self._record["actor_id"] = actor_id
        if self._replay_run_id is not None:
            return ReplayActorClient(self._inner.run(self._replay_run_id), self._record)
        return RecordingActorClient(self._inner.actor(actor_id), self._record)

    def dataset(self, dataset_id: str) -> RecordingDatasetClient:
        return RecordingDatasetClient(self._inner.dataset(dataset_id), self._record)


class RecordingSearchService:
    """Delegates to the real SearchAlibabaProducts; only remembers products."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.products: list[Any] = []

    def execute(self, query: str, limit: int) -> list[Any]:
        self.products = list(self._inner.execute(query, limit))
        return self.products


def scalar_text(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (str, int)):
        normalized = str(value).strip()
        if normalized:
            return normalized
    return None


def row_field(row: object, name: str) -> object:
    if isinstance(row, Mapping):
        return cast(Mapping[str, object], row).get(name)
    return getattr(row, name, None)


def row_reputation_or_none(row: object) -> int | None:
    if not row_field(row, "reputation_available"):
        return None
    value = row_field(row, "reputation_value")
    return value if isinstance(value, int) else 0


# ---------------------------------------------------------------------------
# Independent Decimal recalculation (deliberately NOT importing the formulas).
# ---------------------------------------------------------------------------


def indep_rating(raw: object) -> Decimal | None:
    text = scalar_text(raw)
    if text is None:
        return None
    try:
        value = Decimal(text.replace(",", "."))
    except InvalidOperation:
        return None
    if not value.is_finite() or value < 0 or value > Decimal("5"):
        return None
    return value


def indep_years(raw: object) -> Decimal | None:
    text = scalar_text(raw)
    if text is None:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if match is None:
        return None
    try:
        value = Decimal(match.group(1))
    except InvalidOperation:
        return None
    if not value.is_finite() or value < 0:
        return None
    return value


def indep_count(raw: object) -> Decimal | None:
    text = scalar_text(raw)
    if text is None:
        return None
    try:
        value = Decimal(text.replace(",", ""))
    except InvalidOperation:
        return None
    if not value.is_finite() or value < 0:
        return None
    return value


def indep_count_points(count: Decimal) -> Decimal:
    if count <= 0:
        return Decimal("0")
    if count <= 9:
        return Decimal("3")
    if count <= 24:
        return Decimal("6")
    if count <= 49:
        return Decimal("9")
    if count <= 99:
        return Decimal("12")
    return Decimal("15")


def indep_reputation(raw_item: Mapping[str, object]) -> dict[str, object]:
    service = indep_rating(raw_item.get("supplierServiceScore"))
    review = indep_rating(raw_item.get("reviewScore"))
    years = indep_years(raw_item.get("goldSupplierYears"))
    count = indep_count(raw_item.get("reviewCount"))

    service_pts = None if service is None else (service / Decimal("5")) * Decimal("35")
    review_pts = None if review is None else (review / Decimal("5")) * Decimal("30")
    years_pts = (
        None if years is None else (min(years, Decimal("10")) / Decimal("10")) * Decimal("20")
    )
    count_pts = None if count is None else indep_count_points(count)

    weights = (Decimal("35"), Decimal("30"), Decimal("20"), Decimal("15"))
    points = (service_pts, review_pts, years_pts, count_pts)
    available = sum(
        (weight for weight, pts in zip(weights, points, strict=True) if pts is not None),
        Decimal("0"),
    )
    earned = sum((pts for pts in points if pts is not None), Decimal("0"))
    signals = sum(1 for pts in points if pts is not None)
    coverage = int(
        (available / Decimal("100") * Decimal("100")).quantize(
            Decimal("1"), rounding=ROUND_HALF_EVEN
        )
    )
    score: int | None = None
    if signals >= 2 and available >= Decimal("50") and available > 0:
        raw_score = (earned / available * Decimal("100")).quantize(
            Decimal("1"), rounding=ROUND_HALF_EVEN
        )
        score = max(0, min(100, int(raw_score)))
    return {
        "service": service,
        "review": review,
        "years": years,
        "count": count,
        "service_points": service_pts,
        "review_points": review_pts,
        "years_points": years_pts,
        "count_points": count_pts,
        "available_weight": available,
        "earned_points": earned,
        "score": score,
        "coverage": coverage,
    }


def main() -> int:  # noqa: PLR0915
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")
    load_dotenv_without_printing(REPO_ROOT / ".env")
    replay_run_id = sys.argv[1] if len(sys.argv) > 1 else None

    from bera_price_tracker.application.alibaba_ranking import calculate_alibaba_ranking
    from bera_price_tracker.application.alibaba_reputation import (
        LABEL_INSUFFICIENT,
        calculate_supplier_reputation,
        format_reputation_display,
        score_alibaba_reputation,
    )
    from bera_price_tracker.application.services import SearchAlibabaProducts
    from bera_price_tracker.config import Settings
    from bera_price_tracker.gui.analysis import (
        SORT_REPUTATION_DESC,
        annotate_ranking,
        apply_table_view,
        showing_counter,
        top_result_cards,
    )
    from bera_price_tracker.gui.services import run_alibaba_search, sanitize_alibaba_error
    from bera_price_tracker.infrastructure.providers.alibaba import (
        ApifyAlibabaClient,
        map_alibaba_item,
    )

    record: dict[str, Any] = {
        "actor_calls_created": 0,
        "raw_items": [],
        "run_status": None,
        "run_id": None,
        "actor_id": None,
    }

    settings = Settings.from_env()
    client = ApifyAlibabaClient(
        _api_token=settings.apify_api_token,
        actor_id=settings.apify_alibaba_actor,
        client_factory=lambda token: cast(Any, RecordingApifyClient(token, record, replay_run_id)),
    )
    service = RecordingSearchService(SearchAlibabaProducts(provider=client))

    mode = "REPLAY (dataset reutilizado, 0 runs nuevos)" if replay_run_id else "LIVE (1 run)"
    print(f"=== 1-2. RUN REAL — modo {mode} ===")
    try:
        payload = run_alibaba_search(QUERY, LIMIT, search_service=service)
    except BaseException as exc:  # noqa: BLE001 - sanitized stop, no retry
        print(f"Actor runs creados: {record['actor_calls_created']}")
        print(f"status: {record['run_status']}")
        print(f"ERROR (sanitizado): {sanitize_alibaba_error(exc)}")
        return 1

    products: list[Any] = service.products
    raw_items = [item for item in record["raw_items"] if isinstance(item, Mapping)]
    rows: list[dict[str, Any]] = payload["results"]
    print(f"Actor runs creados: {record['actor_calls_created']}")
    print(f"Actor: {record['actor_id']}")
    print(f"status: {record['run_status']}")
    print(f"run reutilizable: {record['run_id']}")
    print(f"items en dataset (reutilizado): {len(raw_items)}")
    print(f"productos mapeados: {len(products)}")
    print(f"ui_status: {payload['ui_status']}")

    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        mark = "OK " if condition else "FAIL"
        suffix = f" — {detail}" if detail else ""
        print(f"[{mark}] {name}{suffix}")
        if not condition:
            failures.append(name)

    total = len(raw_items)

    print("\n=== 5. COBERTURA REAL (valores no vacíos) ===")
    for field_name in REPUTATION_RAW_FIELDS:
        count = sum(1 for item in raw_items if scalar_text(item.get(field_name)) is not None)
        print(f"    {field_name:22s} {count}/{total}")

    print("\n=== 6. MAPPING raw -> AlibabaProduct ===")
    remapped_all = [map_alibaba_item(item) for item in raw_items]
    remapped = [item for item in remapped_all if item is not None]
    check("re-mapeo determinista coincide con productos del flujo", remapped == products)
    mapping_pairs = (
        ("goldSupplierYears", "gold_supplier_years"),
        ("supplierServiceScore", "supplier_service_score"),
        ("reviewScore", "review_score"),
        ("reviewCount", "review_count"),
    )
    mapping_ok = True
    mapped_raw = [item for item in raw_items if scalar_text(item.get("title")) is not None]
    for raw_item, product in zip(mapped_raw, products, strict=True):
        for raw_key, attr in mapping_pairs:
            if scalar_text(raw_item.get(raw_key)) != getattr(product, attr):
                mapping_ok = False
    check("los 4 campos reputacionales llegan al modelo", mapping_ok)

    print("\n=== 7. SCORES ===")
    reputations = score_alibaba_reputation(cast(list[object], products))
    valid = [rep.score for rep in reputations if rep.score is not None]
    insufficient = [rep for rep in reputations if rep.score is None]
    print(f"    reputation válida:    {len(valid)}/{len(reputations)}")
    print(f"    Datos insuficientes:  {len(insufficient)}/{len(reputations)}")
    if valid:
        print(f"    mínimo:  {min(valid)}")
        print(f"    mediana: {statistics.median(valid)}")
        print(f"    máximo:  {max(valid)}")
    labels_ok = all((rep.score is None) == (rep.label == LABEL_INSUFFICIENT) for rep in reputations)
    check("labels coherentes con score", labels_ok)
    rows_consistent = all(
        row["reputation"] == format_reputation_display(rep.score)
        for row, rep in zip(rows, reputations, strict=True)
    )
    check("filas GUI muestran el mismo score que el servicio", rows_consistent)

    print("\n=== 8. VALIDACIÓN INDEPENDIENTE (Decimal, <=5 proveedores) ===")
    seen_suppliers: set[str] = set()
    picked: list[int] = []
    for index, product in enumerate(products):
        supplier = product.supplier_name or f"(sin nombre #{index})"
        if supplier in seen_suppliers:
            continue
        seen_suppliers.add(supplier)
        picked.append(index)
        if len(picked) == 5:
            break
    indep_ok = True
    for index in picked:
        raw_item = mapped_raw[index]
        rep = reputations[index]
        indep = indep_reputation(raw_item)
        same = (
            indep["score"] == rep.score
            and indep["coverage"] == rep.evidence_coverage
            and indep["service_points"] == rep.service_points
            and indep["review_points"] == rep.review_score_points
            and indep["years_points"] == rep.years_points
            and indep["count_points"] == rep.review_count_points
            and indep["service"] == rep.service_value
            and indep["review"] == rep.review_score_value
            and indep["years"] == rep.years
            and indep["count"] == rep.review_count
        )
        if not same:
            indep_ok = False
        supplier_name = products[index].supplier_name or "—"
        print(
            f"    {supplier_name[:38]:38s} score app={rep.score} indep={indep['score']} "
            f"cov app={rep.evidence_coverage} indep={indep['coverage']} "
            f"{'==' if same else '!='}"
        )
    check("recalculo independiente == servicio (sin tolerancias)", indep_ok)

    print("\n=== 9. PROVEEDORES REPETIDOS ===")
    by_supplier: dict[str, list[int]] = {}
    for index, product in enumerate(products):
        if product.supplier_name:
            by_supplier.setdefault(product.supplier_name, []).append(index)
    repeated = {name: idxs for name, idxs in by_supplier.items() if len(idxs) > 1}
    print(f"    proveedores repetidos: {len(repeated)}")
    repeated_ok = True
    for name, idxs in repeated.items():
        signals = {
            (
                products[i].gold_supplier_years,
                products[i].supplier_service_score,
                products[i].review_score,
                products[i].review_count,
            )
            for i in idxs
        }
        scores = {(reputations[i].score, reputations[i].evidence_coverage) for i in idxs}
        same_signals = len(signals) == 1
        same_scores = len(scores) == 1
        if same_signals and not same_scores:
            repeated_ok = False
        print(
            f"    {name[:40]:40s} items={len(idxs)} señales_iguales={same_signals} "
            f"score_igual={same_scores}"
        )
    check("mismas señales => mismo score y cobertura", repeated_ok)

    print("\n=== 10. CAMPOS QUE NO DEBEN AFECTAR ===")
    excluded_attrs = (
        "display_star_level",
        "product_score",
        "shipping_score",
        "sold_order",
        "badges",
        "certifications",
        "show_crown",
    )
    check(
        "AlibabaProduct no transporta campos excluidos",
        all(not hasattr(products[0], attr) for attr in excluded_attrs),
    )
    sample = next((p for i, p in enumerate(products) if reputations[i].score is not None), None)
    if sample is not None:
        only_four = {
            "goldSupplierYears": sample.gold_supplier_years,
            "supplierServiceScore": sample.supplier_service_score,
            "reviewScore": sample.review_score,
            "reviewCount": sample.review_count,
        }
        check(
            "reputación depende SOLO de los 4 campos",
            calculate_supplier_reputation(only_four) == calculate_supplier_reputation(sample),
        )
        altered = dataclasses.replace(
            sample,
            price_display="$99999",
            min_price=Decimal("99999"),
            max_price=Decimal("99999"),
            moq="Min. order: 99999 pieces",
            supplier_country="XX",
            title="Producto totalmente distinto",
        )
        check(
            "precio/MOQ/país/título no alteran reputación",
            calculate_supplier_reputation(altered) == calculate_supplier_reputation(sample),
        )

    print("\n=== 11. GUI: read model / state ===")
    min_reputation_by_label: dict[str, int] = {"Todas": 0, "50+": 50, "70+": 70, "85+": 85}
    model_rows: list[Any]
    try:
        from bera_price_tracker.gui.state import (
            ALIBABA_MIN_REPUTATION_BY_LABEL,
            AlibabaResultRow,
        )

        min_reputation_by_label = dict(ALIBABA_MIN_REPUTATION_BY_LABEL)
        known_fields = set(AlibabaResultRow.__fields__)
        model_rows = [
            AlibabaResultRow(**{key: value for key, value in row.items() if key in known_fields})
            for row in rows
        ]
        state_import_ok = True
    except Exception as exc:  # noqa: BLE001
        print(f"    no se pudo importar el state de Reflex: {type(exc).__name__}")
        model_rows = list(rows)
        state_import_ok = False
    check("AlibabaResultRow construible desde payload", state_import_ok)
    annotated = annotate_ranking(model_rows)
    per_row_ok = True
    for row in annotated:
        opportunity = row_field(row, "score")
        relevance = row_field(row, "relevance")
        ranking = row_field(row, "ranking")
        reputation = row_field(row, "reputation")
        reputation_ok = reputation == "—" or (
            isinstance(reputation, str) and reputation.endswith("/100")
        )
        popover = all(
            isinstance(row_field(row, name), str) and str(row_field(row, name))
            for name in (
                "reputation_service",
                "reputation_reviews",
                "reputation_years",
                "reputation_volume",
                "reputation_coverage",
            )
        )
        if not (opportunity and relevance and ranking and reputation_ok and popover):
            per_row_ok = False
    check("cada fila expone Oportunidad/Relevancia/Ranking/Reputación + popover", per_row_ok)
    insufficient_rows = [
        row for row in annotated if row_field(row, "reputation_label") == LABEL_INSUFFICIENT
    ]
    check(
        "filas 'Datos insuficientes' muestran —",
        all(row_field(row, "reputation") == "—" for row in insufficient_rows),
        f"{len(insufficient_rows)} filas",
    )

    print("\n=== 12. FILTRO LOCAL (sin nuevas requests) ===")
    calls_before = record["actor_calls_created"]
    total_rows = len(model_rows)
    insufficient_count = len(insufficient_rows)
    filter_ok = True
    for label, threshold in min_reputation_by_label.items():
        visible = apply_table_view(model_rows, min_reputation=threshold)
        counter = showing_counter(len(visible), total_rows)
        visible_insufficient = sum(1 for row in visible if row_reputation_or_none(row) is None)
        if threshold == 0:
            ok = len(visible) == total_rows and visible_insufficient == insufficient_count
        else:
            ok = visible_insufficient == 0 and all(
                cast(int, row_reputation_or_none(row)) >= threshold for row in visible
            )
        if not ok:
            filter_ok = False
        print(f"    {label:6s} -> {counter}  (insuficientes visibles: {visible_insufficient})")
    check("filtro local correcto", filter_ok)
    check(
        "sin nuevas requests durante filtros",
        record["actor_calls_created"] == calls_before,
    )

    print("\n=== 13. ORDEN 'Mayor reputación' ===")
    snapshot = [row_field(row, "title") for row in model_rows]
    ordered = apply_table_view(model_rows, sort=SORT_REPUTATION_DESC)
    keys = [
        -1 if row_reputation_or_none(row) is None else cast(int, row_reputation_or_none(row))
        for row in ordered
    ]
    non_increasing = all(a >= b for a, b in zip(keys, keys[1:], strict=False))
    check("orden DESC con insuficientes al final", non_increasing)
    snapshot_after = [row_field(row, "title") for row in model_rows]
    ranking_untouched = all(
        row_field(row, "ranking") in ("", None) and not row_field(row, "ranking_value")
        for row in model_rows
    )
    check("alibaba_results original no mutado", snapshot == snapshot_after and ranking_untouched)

    print("\n=== 14. TOP 3 ===")
    visible_default = apply_table_view(model_rows)
    cards = top_result_cards(cast(list[object], visible_default))
    rankings_in_cards = [int(card["ranking"].removeprefix("Ranking ")) for card in cards]
    all_rankings = sorted(
        (
            int(cast(int, row_field(row, "ranking_value")) or 0)
            for row in apply_table_view(model_rows)
        ),
        reverse=True,
    )
    check(
        "Top 3 ordenado por el Ranking General (con reputación renormalizada)",
        rankings_in_cards == all_rankings[: len(rankings_in_cards)]
        and any(value > 0 for value in all_rankings),
    )
    check(
        "cards muestran 'Reputación NN' o 'Reputación: Datos insuficientes'",
        all(
            card["reputation"].startswith("Reputación ")
            or card["reputation"] == "Reputación: Datos insuficientes"
            for card in cards
        ),
    )

    print("\n=== 15. SCORES EXISTENTES INTACTOS ===")
    scores_ok = all(
        isinstance(row["score_value"], int) and 0 <= row["score_value"] <= 100 for row in rows
    )
    relevance_ok = all(
        isinstance(row["relevance_value"], int) and 0 <= row["relevance_value"] <= 100
        for row in rows
    )
    ranking_check = True
    for row in annotated:
        score_v = int(cast(int, row_field(row, "score_value")) or 0)
        relevance_v = int(cast(int, row_field(row, "relevance_value")) or 0)
        ranking_v = int(cast(int, row_field(row, "ranking_value")) or 0)
        reputation_v = row_reputation_or_none(row)
        expected = calculate_alibaba_ranking(score_v, relevance_v, reputation_v).ranking_score
        if ranking_v != expected:
            ranking_check = False
    check("opportunity_score presente y en rango", scores_ok)
    check("relevance_score presente y en rango", relevance_ok)
    check("ranking = 50/30/20 (renormalizado si falta reputación)", ranking_check)

    print("\n=== 16. SEGURIDAD ===")
    leaked = [
        field_name
        for field_name in FORBIDDEN_REPORT_FIELDS
        if any(hasattr(product, field_name) for product in products)
    ]
    check("modelo sin campos sensibles", not leaked)

    print("\n=== 17/22. SCHEMA OBSERVADO vs CONOCIDO ===")
    observed_keys: set[str] = set()
    for item in raw_items:
        observed_keys.update(str(key) for key in item)
    new_keys = sorted(observed_keys - PREVIOUSLY_OBSERVED_ACTOR_KEYS)
    missing_keys = sorted(PREVIOUSLY_OBSERVED_ACTOR_KEYS - observed_keys)
    schema_changed = bool(new_keys) or bool(missing_keys)
    print(f"    schema cambió: {'sí' if schema_changed else 'no'}")
    if new_keys:
        print(f"    claves nuevas: {new_keys}")
    if missing_keys:
        print(f"    claves ausentes en este run: {missing_keys}")

    print("\n=== EJEMPLOS SANITIZADOS (máx 5) ===")
    for index in picked[:5]:
        product = products[index]
        rep = reputations[index]
        print(
            f"    supplier={product.supplier_name or '—'} | "
            f"reputation={format_reputation_display(rep.score)} | "
            f"coverage={rep.evidence_coverage}% | "
            f"years={product.gold_supplier_years or '—'} | "
            f"service={product.supplier_service_score or '—'} | "
            f"review_score={product.review_score or '—'} | "
            f"review_count={product.review_count or '—'}"
        )

    print("\n=== RESULTADO ===")
    print(f"Actor runs creados en esta ejecución: {record['actor_calls_created']}")
    if failures:
        print(f"FALLOS: {failures}")
        return 2
    print("TODO OK — sin bugs demostrados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
