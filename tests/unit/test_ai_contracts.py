"""Offline validation for the AI contract pack. No marketplace I/O."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema.validators import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "schemas" / "ai-contracts"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "ai-contracts"

_SECRET_RE = re.compile(
    r"(api[_-]?key|access[_-]?token|\bauthorization\b|bearer\s+[a-z0-9]|set-cookie|"
    r"cookie=|\bpassword\s*[:=]|\bprivate[_-]?key\b)",
    re.IGNORECASE,
)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return cast(dict[str, Any], payload)


def _schema_registry() -> Registry[Any]:
    resources: list[tuple[str, Resource[Any]]] = []
    for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        contents = _load_json(path)
        resources.append((path.name, Resource.from_contents(contents)))
    return Registry().with_resources(resources)


def _validator(schema_name: str) -> Draft202012Validator:
    schema = _load_json(SCHEMA_DIR / schema_name)
    return Draft202012Validator(schema, registry=_schema_registry())


def _iter_fixtures() -> Iterator[Path]:
    yield from sorted(FIXTURE_DIR.rglob("*.json"))


def _cases() -> list[tuple[str, Path, dict[str, Any]]]:
    return [(path.stem, path, _load_json(path)) for path in _iter_fixtures()]


CASES = _cases()
SEARCH_SESSION_CASES = [
    item for item in CASES if item[2].get("runtime_check") == "search_session_core"
]


@pytest.fixture(scope="module")
def case_schema() -> Draft202012Validator:
    return _validator("golden-search-case.schema.json")


def test_schema_documents_parse() -> None:
    names = sorted(path.name for path in SCHEMA_DIR.glob("*.schema.json"))
    assert names == [
        "bounded-acquisition-plan.schema.json",
        "golden-search-case.schema.json",
        "provider-run-metrics.schema.json",
        "provider-run-result.schema.json",
        "search-intent.schema.json",
    ]
    for name in names:
        schema = _load_json(SCHEMA_DIR / name)
        Draft202012Validator.check_schema(schema)


def test_fixture_ids_are_unique() -> None:
    ids = [case["id"] for _stem, _path, case in CASES]
    assert ids
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize(("stem", "path", "case"), CASES, ids=[item[0] for item in CASES])
def test_fixture_validates_and_is_safe(
    stem: str,
    path: Path,
    case: dict[str, Any],
    case_schema: Draft202012Validator,
) -> None:
    assert path.stem == case["id"] == stem
    case_schema.validate(case)
    text = path.read_text(encoding="utf-8")
    secret = _SECRET_RE.search(text)
    assert secret is None, f"possible secret in {path}: {secret.group(0) if secret else ''}"
    assert case["must_not"]
    for ref in case["source_refs"]:
        assert isinstance(ref, str) and not ref.startswith("http")
        target = ROOT / ref
        assert target.is_file(), f"missing source_ref {ref}"
    _validate_nested_contracts(case)


def _validate_nested_contracts(case: Mapping[str, Any]) -> None:
    given = case["given"]
    expected = case["expected"]
    if isinstance(given.get("intent"), dict):
        _validator("search-intent.schema.json").validate(given["intent"])
    for key in ("stale_intent", "current_intent"):
        if isinstance(given.get(key), dict):
            _validator("search-intent.schema.json").validate(given[key])
    metrics = expected.get("metrics")
    if isinstance(metrics, dict):
        _validator("provider-run-metrics.schema.json").validate(metrics)
        _assert_metrics_invariants(metrics)
    result = expected.get("result")
    if isinstance(result, dict):
        _validator("provider-run-result.schema.json").validate(result)


def _assert_metrics_invariants(metrics: Mapping[str, Any]) -> None:
    usable = int(metrics["usable"])
    display_requested = int(metrics["display_requested"])
    displayed = int(metrics["displayed"])
    assert displayed == min(usable, display_requested)
    assert int(metrics["acquisition_requested"]) <= int(metrics["acquisition_budget"])


def test_later_stage_fixtures_are_not_marked_implemented() -> None:
    later = [
        case for _stem, _path, case in CASES if case["implementation_stage"] in {"B", "C", "D", "E"}
    ]
    assert later
    for case in later:
        assert case.get("runtime_check") in {None, "null"} or case["runtime_check"] is None
        assert case["expected"].get("implemented") is not True


def test_alibaba_title_bearing_optional_fields_remain_usable() -> None:
    case = _load_json(
        FIXTURE_DIR / "validity" / "alibaba-title-bearing-optional-fields-absent.json"
    )
    from bera_price_tracker.infrastructure.providers.alibaba import map_alibaba_item

    product = map_alibaba_item(case["given"]["raw"])
    assert product is not None
    assert product.title == case["expected"]["title"]
    for field_name in case["expected"]["optional_absent"]:
        assert getattr(product, field_name) is None


def test_facebook_mixed_pool_priced_only_policy() -> None:
    case = _load_json(
        FIXTURE_DIR / "validity" / "facebook-mixed-free-invalid-valid-priced-pool.json"
    )
    from bera_price_tracker.application.facebook_products import (
        FacebookPriceDecision,
        classify_explicit_facebook_price,
    )

    usable: list[str] = []
    rejected: list[str] = []
    for item in case["given"]["pool"]:
        amount_raw = item["amount"]
        amount = None if amount_raw is None else Decimal(str(amount_raw))
        decision = classify_explicit_facebook_price(amount, item["formatted_price"])
        assert decision is FacebookPriceDecision(item["expected_decision"])
        if decision is FacebookPriceDecision.PRICED:
            usable.append(str(item["title"]))
        else:
            rejected.append(str(item["title"]))
    assert usable == case["expected"]["usable_titles"]
    assert rejected == case["expected"]["rejected"]


def test_mercadolibre_permalink_absence_does_not_reject() -> None:
    case = _load_json(FIXTURE_DIR / "validity" / "mercadolibre-valid-mlv-without-permalink.json")
    from bera_price_tracker.infrastructure.providers.mercadolibre_apify import (
        map_mercadolibre_item,
    )

    listing = map_mercadolibre_item(case["given"]["raw"])
    assert listing is not None
    assert listing.external_id == case["expected"]["external_id"]
    assert listing.permalink is None


def test_mercadolibre_later_valid_record_can_remain_usable() -> None:
    case = _load_json(
        FIXTURE_DIR / "validity" / "mercadolibre-later-valid-mlv-after-missing-venezuela.json"
    )
    from bera_price_tracker.infrastructure.providers.mercadolibre_apify import (
        map_mercadolibre_item,
    )

    mapped = [map_mercadolibre_item(item) for item in case["given"]["raw_items"]]
    assert mapped[0] is None
    assert mapped[1] is not None
    assert mapped[1].external_id == "MLV900000002"


def test_facebook_low_level_execute_remains_one_actor_run() -> None:
    from bera_price_tracker.application.facebook_products import (
        SearchFacebookMarketplaceProducts,
    )

    assert "one execute maps to one Actor run" in (SearchFacebookMarketplaceProducts.__doc__ or "")


@pytest.mark.parametrize(
    ("stem", "path", "case"),
    SEARCH_SESSION_CASES,
    ids=[item[0] for item in SEARCH_SESSION_CASES],
)
def test_search_session_core_fixtures_when_implemented(
    stem: str,
    path: Path,
    case: dict[str, Any],
) -> None:
    module = pytest.importorskip("bera_price_tracker.application.search_session")
    _assert_search_session_case(module, case)


def _assert_search_session_case(module: Any, case: Mapping[str, Any]) -> None:
    given = case["given"]
    expected = case["expected"]
    policy = _policy(module, given["policy"])
    provider = str(case.get("provider") or "alibaba")
    intent_payload = given.get("intent") or given.get("stale_intent")
    assert isinstance(intent_payload, dict)
    intent = _intent(module, intent_payload)
    plan = policy.create_plan(
        provider=provider,
        display_limit=intent.display_limit,
        steps=_steps(module, given["steps"]),
        requested_geographic_scope=given.get("scope", intent.requested_scope_for(provider)),
        complete_effective_geographic_scope=given.get("scope"),
        partial_effective_geographic_scope=(
            f"partial:{given['scope']}" if given.get("scope") else None
        ),
    )
    calls: list[str] = []

    def acquire(step: Any) -> Any:
        calls.append(step.key)
        payload = given["batches"][step.key]
        if "error" in payload:
            raise RuntimeError(str(payload["error"]))
        return _batch(module, payload)

    result = module.execute_bounded_provider_search(
        intent=intent,
        plan=plan,
        policy=policy,
        acquire=acquire,
        is_usable=lambda candidate: candidate.usable,
        stable_identity=lambda candidate: candidate.identity,
    )
    if "status" in expected:
        assert result.status.value == expected["status"]
    if "metrics" in expected:
        _assert_result_metrics(result.metrics, expected["metrics"])
    if "canonical_titles" in expected:
        assert [item.title for item in result.canonical_session_results] == expected[
            "canonical_titles"
        ]
    if "ordered_titles" in expected:
        assert [item.title for item in result.ordered_usable_pool] == expected["ordered_titles"]
    if "usable" in expected:
        assert result.metrics.usable == expected["usable"]
    if "coverage_status" in expected:
        coverage = None if result.coverage_status is None else result.coverage_status.value
        assert coverage == expected["coverage_status"]
    if "effective_geographic_scope" in expected:
        assert result.effective_geographic_scope == expected["effective_geographic_scope"]
    if "executed_steps" in expected:
        assert calls == expected["executed_steps"]
    snapshot = module.SearchSessionSnapshot(intent=intent)
    if case["id"] == "stale-generation-cannot-mutate-or-relabel":
        current = _intent(module, given["current_intent"])
        current_snapshot = module.SearchSessionSnapshot(intent=current)
        committed = current_snapshot.commit(result)
        assert committed is current_snapshot
        assert committed.provider_results == ()
        assert result.generation == expected["stale_result_generation"]
        return
    committed = snapshot.commit(result)
    if expected.get("commit") == "accepted":
        assert committed is not snapshot
        assert committed.result_for(provider) is result
    if "completion_label" in expected or "has_incidents" in expected:
        if "has_incidents" in expected:
            assert committed.has_incidents is expected["has_incidents"]
        if "completion_label" in expected:
            assert committed.completion_label == expected["completion_label"]


def _assert_result_metrics(metrics: Any, expected: Mapping[str, Any]) -> None:
    for name, value in expected.items():
        assert getattr(metrics, name) == value


def _policy(module: Any, rules: Mapping[str, Any]) -> Any:
    provider_rules = {
        name: module.ProviderBudgetRule(
            maximum_internal_acquisitions=int(rule["maximum_internal_acquisitions"]),
            maximum_acquisition_budget=int(rule["maximum_acquisition_budget"]),
            candidate_buffer_multiplier=int(rule["candidate_buffer_multiplier"]),
        )
        for name, rule in rules.items()
    }
    return module.AcquisitionBudgetPolicy(provider_rules=provider_rules)


def _intent(module: Any, payload: Mapping[str, Any]) -> Any:
    scopes = tuple(
        (str(item["provider"]), item["scope"])
        for item in payload.get("requested_geographic_scopes") or ()
    )
    return module.SearchIntent(
        original_user_query=str(payload["original_user_query"]),
        display_limit=int(payload["display_limit"]),
        selected_providers=tuple(payload["selected_providers"]),
        generation=int(payload["generation"]),
        requested_geographic_scopes=scopes,
    )


def _steps(module: Any, raw_steps: list[Mapping[str, Any]]) -> tuple[Any, ...]:
    return tuple(
        module.InternalAcquisitionStep(
            key=str(step["key"]),
            candidate_limit=int(step["candidate_limit"]),
            required_for_complete_coverage=bool(step.get("required_for_complete_coverage", True)),
        )
        for step in raw_steps
    )


def _batch(module: Any, payload: Mapping[str, Any]) -> Any:
    candidates = tuple(_Candidate.from_mapping(item) for item in payload.get("candidates") or [])
    fetched = payload["fetched"] if "fetched" in payload else len(candidates)
    mapped = payload["mapped"] if "mapped" in payload else len(candidates)
    rejected = payload["rejected"] if "rejected" in payload else 0
    return module.AcquisitionBatch(
        candidates=candidates,
        fetched=fetched,
        mapped=mapped,
        rejected=rejected,
    )


@dataclass(frozen=True, slots=True)
class _Candidate:
    title: str
    identity: str | None = None
    image: str = ""
    price: str = ""
    usable: bool = True

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> _Candidate:
        identity = payload.get("identity")
        return cls(
            title=str(payload["title"]),
            identity=None if identity is None else str(identity),
            image=str(payload.get("image") or ""),
            price=str(payload.get("price") or ""),
            usable=bool(payload.get("usable", True)),
        )
