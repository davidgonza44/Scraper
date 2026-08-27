"""Offline validation for the AI contract pack. No marketplace I/O."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema.exceptions import ValidationError
from jsonschema.validators import Draft202012Validator
from referencing import Registry, Resource

from bera_price_tracker.application import search_session

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "schemas" / "ai-contracts"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "ai-contracts"

_SECRET_RE = re.compile(
    r"(api[_-]?key|access[_-]?token|\bauthorization\b|bearer\s+[a-z0-9]|set-cookie|"
    r"cookie=|\bpassword\s*[:=]|\bprivate[_-]?key\b)",
    re.IGNORECASE,
)

EXPECTED_FIXTURE_IDS = frozenset(
    {
        "acquisition-10-usable-8-display-3",
        "alibaba-geographic-coverage-not-applicable",
        "alibaba-identity-less-similar-candidates-remain-distinct",
        "alibaba-title-bearing-optional-fields-absent",
        "budget-30-two-executed-requests-of-5",
        "cross-market-native-id-equality-is-not-identity",
        "current-generation-result-can-commit",
        "error-before-coverage-is-unavailable",
        "exhausted-finite-acquisition-budget",
        "facebook-mixed-free-invalid-valid-priced-pool",
        "facebook-one-execute-one-actor-run",
        "fewer-usable-than-display-maximum",
        "geographic-complete-coverage",
        "geographic-partial-empty-is-incidence",
        "geographic-partial-with-useful-results",
        "mercadolibre-later-valid-mlv-after-missing-venezuela",
        "mercadolibre-valid-mlv-without-permalink",
        "mixed-known-and-unobserved-optional-metrics-stay-unknown",
        "positional-row-is-not-exact-product",
        "stable-provider-identity-deduplicates",
        "stale-generation-cannot-mutate-or-relabel",
        "title-image-price-are-not-identity",
        "unobservable-optional-metrics-are-null",
    }
)
EXPECTED_SEARCH_SESSION_CORE_IDS = frozenset(
    {
        "acquisition-10-usable-8-display-3",
        "alibaba-geographic-coverage-not-applicable",
        "alibaba-identity-less-similar-candidates-remain-distinct",
        "budget-30-two-executed-requests-of-5",
        "current-generation-result-can-commit",
        "error-before-coverage-is-unavailable",
        "exhausted-finite-acquisition-budget",
        "fewer-usable-than-display-maximum",
        "geographic-complete-coverage",
        "geographic-partial-empty-is-incidence",
        "geographic-partial-with-useful-results",
        "mixed-known-and-unobserved-optional-metrics-stay-unknown",
        "stable-provider-identity-deduplicates",
        "stale-generation-cannot-mutate-or-relabel",
        "title-image-price-are-not-identity",
        "unobservable-optional-metrics-are-null",
    }
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
RUNTIME_CASES = [item for item in CASES if item[2].get("runtime_check")]


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


def test_golden_fixture_inventory_is_exact() -> None:
    ids = {case["id"] for _stem, _path, case in CASES}
    assert ids == EXPECTED_FIXTURE_IDS
    assert len(EXPECTED_FIXTURE_IDS) == 23


def test_search_session_core_inventory_is_exact() -> None:
    ids = {case["id"] for _stem, _path, case in SEARCH_SESSION_CASES}
    assert ids == EXPECTED_SEARCH_SESSION_CORE_IDS
    assert len(EXPECTED_SEARCH_SESSION_CORE_IDS) == 16


def _assert_source_ref_stays_in_repo(ref: str) -> Path:
    assert isinstance(ref, str) and ref.strip()
    assert not ref.startswith("http")
    relative = Path(ref)
    assert not relative.is_absolute()
    assert ".." not in relative.parts
    target = (ROOT / relative).resolve()
    assert target.is_relative_to(ROOT.resolve()), f"source_ref escaped repository: {ref}"
    assert target.is_file(), f"missing source_ref {ref}"
    return target


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
    openspec_refs = [ref for ref in case["source_refs"] if ref.startswith("openspec/")]
    assert openspec_refs, f"{case['id']} must keep at least one OpenSpec source_ref"
    for ref in case["source_refs"]:
        _assert_source_ref_stays_in_repo(ref)
    _validate_nested_contracts(case)
    if isinstance(case["given"].get("intent"), dict):
        _assert_search_intent_application_invariants(case["given"]["intent"])
    for key in ("stale_intent", "current_intent"):
        if isinstance(case["given"].get(key), dict):
            _assert_search_intent_application_invariants(case["given"][key])


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


def _assert_search_intent_application_invariants(payload: Mapping[str, Any]) -> None:
    """Cross-field SearchIntent rules that JSON Schema does not encode."""

    selected = tuple(payload["selected_providers"])
    scopes = tuple(payload.get("requested_geographic_scopes") or ())
    providers_in_scopes = [str(item["provider"]) for item in scopes]
    assert not (set(providers_in_scopes) - set(selected))
    assert len(set(providers_in_scopes)) == len(providers_in_scopes)


def test_later_stage_fixtures_are_not_marked_implemented() -> None:
    later = [
        case for _stem, _path, case in CASES if case["implementation_stage"] in {"C", "D", "E"}
    ]
    for case in later:
        assert case.get("runtime_check") is None
        assert case["expected"].get("implemented") is not True


def _check_alibaba_mapper(case: Mapping[str, Any]) -> None:
    from bera_price_tracker.infrastructure.providers.alibaba import map_alibaba_item

    product = map_alibaba_item(case["given"]["raw"])
    assert product is not None
    assert product.title == case["expected"]["title"]
    for field_name in case["expected"]["optional_absent"]:
        assert getattr(product, field_name) is None


def _check_facebook_priced_only(case: Mapping[str, Any]) -> None:
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


def _check_mercadolibre_mapper(case: Mapping[str, Any]) -> None:
    from bera_price_tracker.infrastructure.providers.mercadolibre_apify import (
        map_mercadolibre_item,
    )

    listing = map_mercadolibre_item(case["given"]["raw"])
    assert listing is not None
    assert listing.external_id == case["expected"]["external_id"]
    assert listing.permalink is None


def _check_mercadolibre_search_boundary(case: Mapping[str, Any]) -> None:
    from bera_price_tracker.application.services import SearchMercadoLibreProducts
    from bera_price_tracker.infrastructure.providers.mercadolibre_apify import (
        ApifyMercadoLibreClient,
        map_mercadolibre_item,
    )

    raw_items = list(case["given"]["raw_items"])
    expected_mapped = list(case["expected"]["mapped"])
    expected_ids = [external_id for external_id in expected_mapped if external_id is not None]
    expected_searches = int(case["expected"]["logical_searches"])

    class FakeDataset:
        def list_items(self, *, limit: int) -> FakeDataset:
            page = FakeDataset()
            page.items = raw_items[:limit]
            return page

        items: list[object] = []

    class FakeActor:
        def __init__(self, client: CountingFakeApifyClient) -> None:
            self.client = client

        def call(self, *, run_input: dict[str, object]) -> dict[str, object]:
            self.client.actor_calls.append(run_input)
            return {"status": "SUCCEEDED", "defaultDatasetId": "fixture-dataset"}

    class CountingFakeApifyClient:
        def __init__(self) -> None:
            self.actor_calls: list[dict[str, object]] = []

        def actor(self, actor_id: str) -> FakeActor:
            assert actor_id
            return FakeActor(self)

        def dataset(self, dataset_id: str) -> FakeDataset:
            assert dataset_id == "fixture-dataset"
            return FakeDataset()

    actual_mapped = [
        None if mapped is None else mapped.external_id
        for mapped in (map_mercadolibre_item(item) for item in raw_items)
    ]
    assert actual_mapped == expected_mapped
    assert expected_mapped[0] is None
    assert expected_ids
    assert expected_ids[-1] == expected_mapped[-1]

    fake_client = CountingFakeApifyClient()
    provider = ApifyMercadoLibreClient(
        _api_token="offline-fixture-token",
        client_factory=lambda _token: fake_client,
    )
    returned = SearchMercadoLibreProducts(provider).execute("fixture query", len(raw_items))
    returned_ids = [listing.external_id for listing in returned]

    # These boundary assertions catch both early termination after a rejected row
    # and an attempted replacement search for that row.
    assert returned_ids == expected_ids
    assert actual_mapped[0] not in returned_ids
    assert actual_mapped[-1] in returned_ids
    assert len(fake_client.actor_calls) == expected_searches
    assert expected_searches == 1


def _check_search_session_core(case: Mapping[str, Any]) -> None:
    _assert_search_session_case(search_session, case)


def _check_facebook_one_execute(case: Mapping[str, Any]) -> None:
    from bera_price_tracker.application.facebook_products import (
        FacebookProductSearchMetrics,
        FacebookProductSearchResult,
        SearchFacebookMarketplaceProducts,
    )

    assert "one execute maps to one Actor run" in (SearchFacebookMarketplaceProducts.__doc__ or "")
    assert case["expected"]["facebook_execute_equals_one_actor_run"] is True

    class CountingFacebookProvider:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, int]] = []

        def search(self, query: str, city: str, limit: int) -> FacebookProductSearchResult:
            self.calls.append((query, city, limit))
            return FacebookProductSearchResult(
                listings=(),
                metrics=FacebookProductSearchMetrics(requested=limit, fetched=0, usable=0),
            )

    provider = CountingFacebookProvider()
    SearchFacebookMarketplaceProducts(provider).execute("baseball glove", "caracas", 5)
    assert provider.calls == [("baseball glove", "caracas", 5)]
    SearchFacebookMarketplaceProducts(provider).execute("second query", "maracaibo", 3)
    assert len(provider.calls) == 2


def _check_positional_comparison(case: Mapping[str, Any]) -> None:
    given = case["given"]
    expected = case["expected"]
    if "resultado" in given:
        alibaba = _PositionalCandidate(
            title=str(given["alibaba"]["title"]),
            native_id=str(given["alibaba"]["native_id"]),
        )
        facebook = _PositionalCandidate(
            title=str(given["facebook"]["title"]),
            native_id=str(given["facebook"]["native_id"]),
        )
        mercadolibre = _PositionalCandidate(
            title=str(given["mercadolibre"]["title"]),
            native_id=str(given["mercadolibre"]["native_id"]),
        )
        rows = search_session.build_search_position_comparison_rows(
            alibaba_candidates=(alibaba,),
            facebook_candidates=(facebook,),
            mercadolibre_candidates=(mercadolibre,),
        )
        assert len(rows) == 1
        row = rows[0]
        assert row.rank == int(given["resultado"])
        assert row.identity_confirmed is False is expected["identity_confirmed"]
        assert expected["comparison_kind"] == "positional"
        assert row.alibaba_candidate is alibaba
        assert row.facebook_candidate is facebook
        assert row.mercadolibre_candidate is mercadolibre
        assert search_session.positional_row_authorizes_exact_workflows(row) is False
        assert search_session.exact_product_context() is None
        return
    left = given["alibaba_native_id"]
    right = given["facebook_native_id"]
    assert search_session.native_listing_ids_establish_cross_market_identity(left, right) is False
    assert expected["cross_market_exact_identity"] is False
    assert expected["identity_confirmed"] is False
    rows = search_session.build_search_position_comparison_rows(
        alibaba_candidates=(_PositionalCandidate(title="Alibaba", native_id=str(left)),),
        facebook_candidates=(_PositionalCandidate(title="Facebook", native_id=str(right)),),
    )
    assert rows[0].identity_confirmed is False
    assert search_session.positional_row_authorizes_exact_workflows(rows[0]) is False
    assert search_session.exact_product_context(facebook_association_id=right, context_id=left) is (
        None
    )


@dataclass(frozen=True, slots=True)
class _PositionalCandidate:
    title: str
    native_id: str = ""
    identity: str | None = None


RUNTIME_HANDLERS: dict[str, Callable[[Mapping[str, Any]], None]] = {
    "alibaba_mapper": _check_alibaba_mapper,
    "facebook_priced_only": _check_facebook_priced_only,
    "mercadolibre_mapper": _check_mercadolibre_mapper,
    "mercadolibre_search_boundary": _check_mercadolibre_search_boundary,
    "search_session_core": _check_search_session_core,
    "facebook_one_execute": _check_facebook_one_execute,
    "positional_comparison": _check_positional_comparison,
}


def _run_runtime_check(case: Mapping[str, Any]) -> None:
    check = case.get("runtime_check")
    if check is None:
        raise ValueError("runtime_check is null")
    handler = RUNTIME_HANDLERS.get(str(check))
    if handler is None:
        raise ValueError(f"unknown runtime_check: {check}")
    handler(case)


def test_every_non_null_runtime_check_has_exactly_one_handler() -> None:
    schema = _load_json(SCHEMA_DIR / "golden-search-case.schema.json")
    allowed = {
        value for value in schema["properties"]["runtime_check"]["enum"] if value is not None
    }
    assert set(RUNTIME_HANDLERS) == allowed
    used = {str(case["runtime_check"]) for _stem, _path, case in RUNTIME_CASES}
    assert used == allowed


def test_unknown_runtime_check_fails() -> None:
    with pytest.raises(ValueError, match="unknown runtime_check"):
        _run_runtime_check({"runtime_check": "not-a-handler", "id": "synthetic", "given": {}})


@pytest.mark.parametrize(
    ("stem", "path", "case"),
    RUNTIME_CASES,
    ids=[item[0] for item in RUNTIME_CASES],
)
def test_runtime_check_dispatch(stem: str, path: Path, case: dict[str, Any]) -> None:
    _run_runtime_check(case)


def test_mixed_unknown_metrics_fixture_executes_search_session_core() -> None:
    case = _load_json(
        FIXTURE_DIR / "metrics" / "mixed-known-and-unobserved-optional-metrics-stay-unknown.json"
    )
    assert case["runtime_check"] == "search_session_core"
    _run_runtime_check(case)
    result_metrics = case["expected"]["metrics"]
    assert result_metrics["acquisition_requested"] == 10
    assert result_metrics["fetched"] is None
    assert result_metrics["mapped"] is None
    assert result_metrics["rejected"] is None


def _intent_fixture_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "original_user_query": "baseball glove",
        "display_limit": 3,
        "selected_providers": ["alibaba"],
        "generation": 7,
    }
    payload.update(overrides)
    return payload


def test_search_intent_schema_rejects_whitespace_only_query() -> None:
    payload = _intent_fixture_payload(original_user_query="   ")
    with pytest.raises(ValidationError):
        _validator("search-intent.schema.json").validate(payload)
    with pytest.raises(ValidationError):
        _validator("search-intent.schema.json").validate(
            _intent_fixture_payload(original_user_query=" \n\t ")
        )
    with pytest.raises(ValueError, match="must not be blank"):
        search_session.SearchIntent(
            original_user_query="   ",
            display_limit=3,
            selected_providers=("alibaba",),
            generation=7,
        )


def test_search_intent_schema_accepts_non_blank_multiline_query() -> None:
    payload = _intent_fixture_payload(original_user_query="baseball\n  glove")
    _validator("search-intent.schema.json").validate(payload)
    intent = _intent(search_session, payload)
    assert intent.original_user_query == "baseball glove"


def test_search_intent_schema_is_not_direct_dataclass_serialization() -> None:
    payload = _intent_fixture_payload(
        requested_geographic_scopes=[{"provider": "alibaba", "scope": None}]
    )
    _validator("search-intent.schema.json").validate(payload)
    intent = _intent(search_session, payload)
    assert intent.requested_geographic_scopes == (("alibaba", None),)
    assert not isinstance(intent.selected_providers, list)


def test_structural_search_intent_schema_is_provider_neutral() -> None:
    payload = _intent_fixture_payload(selected_providers=["custom-provider"])
    _validator("search-intent.schema.json").validate(payload)
    intent = _intent(search_session, payload)
    assert intent.selected_providers == ("custom-provider",)
    golden: dict[str, Any] = {
        "id": "synthetic-custom-provider",
        "description": "GoldenSearchCase keeps BERA marketplace vocabulary.",
        "provider": "custom-provider",
        "implementation_stage": "A",
        "runtime_check": None,
        "given": {},
        "expected": {},
        "must_not": ["treat custom-provider as a current marketplace fixture"],
        "source_refs": ["openspec/changes/multi-market-search-semantics/design.md"],
    }
    with pytest.raises(ValidationError):
        _validator("golden-search-case.schema.json").validate(golden)


def test_search_intent_rejects_scope_for_unselected_provider() -> None:
    payload = _intent_fixture_payload(
        selected_providers=["alibaba"],
        requested_geographic_scopes=[{"provider": "facebook", "scope": "Toda Venezuela"}],
    )
    _validator("search-intent.schema.json").validate(payload)
    with pytest.raises(ValueError, match="requested scopes must belong to selected providers"):
        _intent(search_session, payload)


def test_search_intent_rejects_duplicate_provider_scopes() -> None:
    payload = _intent_fixture_payload(
        selected_providers=["facebook"],
        requested_geographic_scopes=[
            {"provider": "facebook", "scope": "Caracas"},
            {"provider": "facebook", "scope": "Valencia"},
        ],
    )
    _validator("search-intent.schema.json").validate(payload)
    with pytest.raises(ValueError, match="requested scopes must be unique per provider"):
        _intent(search_session, payload)


def test_search_intent_display_limit_membership_is_owned_by_policy() -> None:
    payload = _intent_fixture_payload(display_limit=11)
    _validator("search-intent.schema.json").validate(payload)
    intent = _intent(search_session, payload)
    assert intent.display_limit == 11
    policy = search_session.AcquisitionBudgetPolicy(
        provider_rules={
            "alibaba": search_session.ProviderBudgetRule(
                maximum_internal_acquisitions=1,
                maximum_acquisition_budget=30,
                candidate_buffer_multiplier=1,
            )
        }
    )
    with pytest.raises(ValueError, match="not supported"):
        policy.validate_intent(intent)


def _plan_projection(plan: search_session.BoundedAcquisitionPlan) -> dict[str, Any]:
    return {
        "provider": plan.provider,
        "acquisition_budget": plan.acquisition_budget,
        "maximum_internal_acquisitions": plan.maximum_internal_acquisitions,
        "steps": [
            {
                "key": step.key,
                "candidate_limit": step.candidate_limit,
                "required_for_complete_coverage": step.required_for_complete_coverage,
            }
            for step in plan.steps
        ],
        "requested_geographic_scope": plan.requested_geographic_scope,
        "complete_effective_geographic_scope": plan.complete_effective_geographic_scope,
        "partial_effective_geographic_scope": plan.partial_effective_geographic_scope,
        "allow_early_termination": plan.allow_early_termination,
    }


def _candidate_projection(candidate: Any) -> dict[str, Any]:
    return {
        "title": str(getattr(candidate, "title", candidate)),
        "identity": getattr(candidate, "identity", None),
        "image": getattr(candidate, "image", ""),
        "price": getattr(candidate, "price", ""),
        "usable": bool(getattr(candidate, "usable", True)),
    }


def _metrics_projection(metrics: Any) -> dict[str, Any]:
    return {
        "display_requested": metrics.display_requested,
        "acquisition_budget": metrics.acquisition_budget,
        "acquisition_requested": metrics.acquisition_requested,
        "fetched": metrics.fetched,
        "mapped": metrics.mapped,
        "rejected": metrics.rejected,
        "usable": metrics.usable,
        "displayed": metrics.displayed,
    }


def _result_projection(result: search_session.ProviderRunResult[Any]) -> dict[str, Any]:
    coverage = None if result.coverage_status is None else result.coverage_status.value
    return {
        "provider": result.provider,
        "generation": result.generation,
        "status": result.status.value,
        "ordered_usable_pool": [_candidate_projection(item) for item in result.ordered_usable_pool],
        "canonical_session_results": [
            _candidate_projection(item) for item in result.canonical_session_results
        ],
        "metrics": _metrics_projection(result.metrics),
        "requested_geographic_scope": result.requested_geographic_scope,
        "effective_geographic_scope": result.effective_geographic_scope,
        "coverage_status": coverage,
        "failure": result.failure,
    }


def test_bounded_acquisition_plan_schema_accepts_real_pr_a_plans() -> None:
    alibaba = _policy(search_session, {"alibaba": _rule()})
    non_geo = alibaba.create_plan(
        provider="alibaba",
        display_limit=3,
        steps=_steps(search_session, [{"key": "step-1", "candidate_limit": 5}]),
    )
    facebook = _policy(search_session, {"facebook": _rule(max_acquisitions=2, multiplier=4)})
    geo = facebook.create_plan(
        provider="facebook",
        display_limit=3,
        steps=_steps(
            search_session,
            [
                {"key": "step-1", "candidate_limit": 5},
                {"key": "step-2", "candidate_limit": 5},
            ],
        ),
        requested_geographic_scope="Toda Venezuela",
        complete_effective_geographic_scope="Toda Venezuela",
        partial_effective_geographic_scope="partial:Toda Venezuela",
    )
    custom = search_session.AcquisitionBudgetPolicy(
        provider_rules={
            "custom-provider": search_session.ProviderBudgetRule(
                maximum_internal_acquisitions=1,
                maximum_acquisition_budget=30,
                candidate_buffer_multiplier=3,
            )
        }
    )
    custom_plan = custom.create_plan(
        provider="custom-provider",
        display_limit=3,
        steps=_steps(search_session, [{"key": "step-1", "candidate_limit": 5}]),
    )
    validator = _validator("bounded-acquisition-plan.schema.json")
    validator.validate(_plan_projection(non_geo))
    validator.validate(_plan_projection(geo))
    validator.validate(_plan_projection(custom_plan))
    assert non_geo.requested_geographic_scope is None
    assert geo.requested_geographic_scope == "Toda Venezuela"


def test_bounded_acquisition_plan_application_invariants() -> None:
    with pytest.raises(ValueError, match="step key must not be blank"):
        search_session.InternalAcquisitionStep(key="  ", candidate_limit=5)
    with pytest.raises(ValueError, match="step keys must be unique"):
        search_session.BoundedAcquisitionPlan(
            provider="alibaba",
            acquisition_budget=10,
            maximum_internal_acquisitions=2,
            steps=_steps(
                search_session,
                [
                    {"key": "step-1", "candidate_limit": 5},
                    {"key": "step-1", "candidate_limit": 3},
                ],
            ),
        )
    with pytest.raises(ValueError, match="plan exceeds maximum_internal_acquisitions"):
        search_session.BoundedAcquisitionPlan(
            provider="alibaba",
            acquisition_budget=30,
            maximum_internal_acquisitions=1,
            steps=_steps(
                search_session,
                [
                    {"key": "step-1", "candidate_limit": 5},
                    {"key": "step-2", "candidate_limit": 5},
                ],
            ),
        )
    with pytest.raises(ValueError, match="each step candidate limit must fit"):
        search_session.BoundedAcquisitionPlan(
            provider="alibaba",
            acquisition_budget=4,
            maximum_internal_acquisitions=1,
            steps=_steps(search_session, [{"key": "step-1", "candidate_limit": 5}]),
        )
    with pytest.raises(ValueError, match="geographic plans require complete and partial"):
        search_session.BoundedAcquisitionPlan(
            provider="facebook",
            acquisition_budget=12,
            maximum_internal_acquisitions=2,
            steps=_steps(search_session, [{"key": "step-1", "candidate_limit": 5}]),
            requested_geographic_scope="Toda Venezuela",
        )
    policy = _policy(search_session, {"alibaba": _rule()})
    intent = _intent(search_session, _intent_fixture_payload())
    mismatched = search_session.BoundedAcquisitionPlan(
        provider="alibaba",
        acquisition_budget=100,
        maximum_internal_acquisitions=3,
        steps=_steps(search_session, [{"key": "step-1", "candidate_limit": 5}]),
    )
    with pytest.raises(ValueError, match="acquisition_budget does not match policy"):
        search_session.execute_bounded_provider_search(
            intent=intent,
            plan=mismatched,
            policy=policy,
            acquire=lambda _step: _batch(search_session, {"candidates": []}),
        )


def _execute_named_result(kind: str) -> search_session.ProviderRunResult[Any]:
    if kind in {"SUCCESS", "EMPTY"}:
        policy = _policy(search_session, {"alibaba": _rule()})
        intent = _intent(search_session, _intent_fixture_payload())
        plan = policy.create_plan(
            provider="alibaba",
            display_limit=3,
            steps=_steps(search_session, [{"key": "step-1", "candidate_limit": 5}]),
        )
        candidates = [{"title": "one"}] if kind == "SUCCESS" else []
        return search_session.execute_bounded_provider_search(
            intent=intent,
            plan=plan,
            policy=policy,
            acquire=lambda _step: _batch(search_session, {"candidates": candidates}),
        )
    policy = _policy(search_session, {"facebook": _rule(max_acquisitions=2, multiplier=4)})
    intent = _intent(
        search_session,
        _intent_fixture_payload(
            selected_providers=["facebook"],
            requested_geographic_scopes=[{"provider": "facebook", "scope": "Toda Venezuela"}],
        ),
    )
    plan = policy.create_plan(
        provider="facebook",
        display_limit=3,
        steps=_steps(
            search_session,
            [
                {"key": "step-1", "candidate_limit": 5},
                {"key": "step-2", "candidate_limit": 5},
            ],
        ),
        requested_geographic_scope="Toda Venezuela",
        complete_effective_geographic_scope="Toda Venezuela",
        partial_effective_geographic_scope="partial:Toda Venezuela",
    )
    batches = {
        "ERROR": {
            "step-1": RuntimeError("not configured"),
            "step-2": RuntimeError("not configured"),
        },
        "COMPLETE": {
            "step-1": _batch(search_session, {"candidates": [{"title": "one", "identity": "1"}]}),
            "step-2": _batch(search_session, {"candidates": [{"title": "two", "identity": "2"}]}),
        },
        "PARTIAL": {
            "step-1": _batch(search_session, {"candidates": [{"title": "one", "identity": "1"}]}),
            "step-2": RuntimeError("partition unavailable"),
        },
    }[kind]

    def acquire(step: Any) -> Any:
        value = batches[step.key]
        if isinstance(value, Exception):
            raise value
        return value

    return search_session.execute_bounded_provider_search(
        intent=intent,
        plan=plan,
        policy=policy,
        acquire=acquire,
    )


@pytest.mark.parametrize(
    ("kind", "status", "coverage"),
    [
        ("SUCCESS", "SUCCESS", None),
        ("EMPTY", "EMPTY", None),
        ("ERROR", "ERROR", None),
        ("COMPLETE", "SUCCESS", "COMPLETE"),
        ("PARTIAL", "SUCCESS", "PARTIAL"),
    ],
)
def test_provider_run_result_schema_accepts_real_pr_a_results(
    kind: str,
    status: str,
    coverage: str | None,
) -> None:
    result = _execute_named_result(kind)
    payload = _result_projection(result)
    _validator("provider-run-result.schema.json").validate(payload)
    assert payload["status"] == status
    assert payload["coverage_status"] == coverage
    if kind == "ERROR":
        assert payload["failure"]
        assert payload["ordered_usable_pool"] == []


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


def _rule(
    *,
    max_acquisitions: int = 3,
    max_budget: int = 30,
    multiplier: int = 3,
) -> dict[str, int]:
    return {
        "maximum_internal_acquisitions": max_acquisitions,
        "maximum_acquisition_budget": max_budget,
        "candidate_buffer_multiplier": multiplier,
    }


def _policy(module: Any, rules: Mapping[str, Mapping[str, Any]]) -> Any:
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
