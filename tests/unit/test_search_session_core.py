"""Offline tests for Implementation PR A generic-search session foundations."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, replace
from typing import Any

import pytest

from bera_price_tracker.application.provider_acquisition import ProviderRunMetrics
from bera_price_tracker.application.search_session import (
    MAX_DISPLAY_LIMIT,
    AcquisitionBatch,
    AcquisitionBudgetPolicy,
    BoundedAcquisitionPlan,
    CoverageStatus,
    InternalAcquisitionStep,
    ProviderBudgetRule,
    ProviderRunResult,
    ProviderStatus,
    SearchIntent,
    SearchSessionSnapshot,
    execute_bounded_provider_search,
)


@dataclass(frozen=True, slots=True)
class FakeCandidate:
    title: str
    identity: str | None = None
    image: str = ""
    price: str = ""
    usable: bool = True


def _intent(
    *,
    provider: str = "alibaba",
    display_limit: int = 3,
    generation: int = 7,
    scope: str | None = None,
    selected_providers: tuple[str, ...] | None = None,
) -> SearchIntent:
    providers = selected_providers or (provider,)
    scopes = ((provider, scope),) if scope is not None else ()
    return SearchIntent(
        original_user_query="  baseball   glove ",
        display_limit=display_limit,
        selected_providers=providers,
        generation=generation,
        requested_geographic_scopes=scopes,
    )


def _rule(
    *,
    max_acquisitions: int = 3,
    max_budget: int = 30,
    multiplier: int = 3,
) -> ProviderBudgetRule:
    return ProviderBudgetRule(
        maximum_internal_acquisitions=max_acquisitions,
        maximum_acquisition_budget=max_budget,
        candidate_buffer_multiplier=multiplier,
    )


def _policy(
    providers: dict[str, ProviderBudgetRule] | None = None,
    **overrides: Any,
) -> AcquisitionBudgetPolicy:
    return AcquisitionBudgetPolicy(provider_rules=providers or {"alibaba": _rule()}, **overrides)


def _steps(limits: tuple[int, ...]) -> tuple[InternalAcquisitionStep, ...]:
    return tuple(
        InternalAcquisitionStep(key=f"step-{index}", candidate_limit=limit)
        for index, limit in enumerate(limits, start=1)
    )


def _plan(
    *,
    policy: AcquisitionBudgetPolicy,
    display_limit: int,
    provider: str = "alibaba",
    limits: tuple[int, ...] = (5, 5),
    scope: str | None = None,
) -> BoundedAcquisitionPlan:
    return policy.create_plan(
        provider=provider,
        display_limit=display_limit,
        steps=_steps(limits),
        requested_geographic_scope=scope,
        complete_effective_geographic_scope=scope,
        partial_effective_geographic_scope=(f"partial:{scope}" if scope else None),
        allow_early_termination=True,
    )


def _batch(*candidates: FakeCandidate) -> AcquisitionBatch[FakeCandidate]:
    count = len(candidates)
    return AcquisitionBatch(candidates=tuple(candidates), fetched=count, mapped=count, rejected=0)


def _run(
    *,
    intent: SearchIntent,
    plan: BoundedAcquisitionPlan,
    policy: AcquisitionBudgetPolicy,
    batches: dict[str, AcquisitionBatch[FakeCandidate] | Exception],
    calls: list[str] | None = None,
) -> ProviderRunResult[FakeCandidate]:
    call_log = calls if calls is not None else []

    def acquire(step: InternalAcquisitionStep) -> AcquisitionBatch[FakeCandidate]:
        call_log.append(step.key)
        value = batches[step.key]
        if isinstance(value, Exception):
            raise value
        return value

    return execute_bounded_provider_search(
        intent=intent,
        plan=plan,
        policy=policy,
        acquire=acquire,
        is_usable=lambda candidate: candidate.usable,
        stable_identity=lambda candidate: candidate.identity,
    )


def _metrics(**overrides: Any) -> ProviderRunMetrics:
    values: dict[str, Any] = {
        "display_requested": 3,
        "acquisition_budget": 10,
        "acquisition_requested": 10,
        "fetched": None,
        "mapped": None,
        "rejected": None,
        "usable": 3,
        "displayed": 3,
    }
    values.update(overrides)
    return ProviderRunMetrics(**values)


def _result(
    *,
    pool: tuple[FakeCandidate, ...],
    canonical: tuple[FakeCandidate, ...] | None = None,
    status: ProviderStatus = ProviderStatus.SUCCESS,
    generation: int = 7,
    provider: str = "alibaba",
    metrics: ProviderRunMetrics | None = None,
    requested_geographic_scope: str | None = None,
    effective_geographic_scope: str | None = None,
    coverage_status: CoverageStatus | None = None,
) -> ProviderRunResult[FakeCandidate]:
    displayed_pool = canonical if canonical is not None else pool
    bound_metrics = metrics or _metrics(
        usable=len(pool),
        displayed=len(displayed_pool),
        display_requested=max(len(displayed_pool), 1),
    )
    return ProviderRunResult(
        provider=provider,
        generation=generation,
        status=status,
        ordered_usable_pool=pool,
        canonical_session_results=displayed_pool,
        metrics=bound_metrics,
        requested_geographic_scope=requested_geographic_scope,
        effective_geographic_scope=effective_geographic_scope,
        coverage_status=coverage_status,
    )


def test_budget_is_distinct_from_actual_requested_work() -> None:
    policy = _policy({"alibaba": _rule(max_acquisitions=2, max_budget=30, multiplier=3)})
    intent = _intent(display_limit=10)
    plan = _plan(policy=policy, display_limit=10, limits=(5, 5))
    result = _run(
        intent=intent,
        plan=plan,
        policy=policy,
        batches={"step-1": _batch(), "step-2": _batch()},
    )
    assert result.metrics.acquisition_budget == 30
    assert result.metrics.acquisition_requested == 10


def test_usable_pool_freezes_exact_display_prefix() -> None:
    candidates = tuple(FakeCandidate(f"item-{index}") for index in range(8))
    policy = _policy({"alibaba": _rule(max_acquisitions=1, max_budget=10, multiplier=4)})
    intent = _intent(display_limit=3)
    result = _run(
        intent=intent,
        plan=_plan(policy=policy, display_limit=3, limits=(10,)),
        policy=policy,
        batches={"step-1": _batch(*candidates)},
    )
    assert result.metrics.acquisition_requested == 10
    assert result.metrics.usable == 8
    assert result.metrics.displayed == 3
    assert result.canonical_session_results == candidates[:3]
    assert isinstance(result.canonical_session_results, tuple)


def test_provider_run_metrics_rejects_displayed_not_equal_to_min() -> None:
    with pytest.raises(ValueError, match="displayed must equal min"):
        _metrics(usable=3, display_requested=3, displayed=0)


def test_provider_run_result_rejects_usable_pool_size_mismatch() -> None:
    pool = tuple(FakeCandidate(f"item-{index}") for index in range(3))
    with pytest.raises(ValueError, match="ordered usable pool size"):
        ProviderRunResult(
            provider="alibaba",
            generation=1,
            status=ProviderStatus.SUCCESS,
            ordered_usable_pool=pool,
            canonical_session_results=pool,
            metrics=_metrics(usable=8, displayed=3, display_requested=3),
        )


def test_provider_run_result_rejects_displayed_count_mismatch() -> None:
    pool = tuple(FakeCandidate(f"item-{index}") for index in range(3))
    with pytest.raises(ValueError, match="canonical session result count"):
        ProviderRunResult(
            provider="alibaba",
            generation=1,
            status=ProviderStatus.SUCCESS,
            ordered_usable_pool=pool,
            canonical_session_results=pool[:2],
            metrics=_metrics(usable=3, displayed=3, display_requested=3),
        )


def test_provider_run_result_rejects_non_prefix_canonical_membership() -> None:
    pool = (
        FakeCandidate("first"),
        FakeCandidate("second"),
        FakeCandidate("third"),
    )
    with pytest.raises(ValueError, match="frozen displayed prefix"):
        ProviderRunResult(
            provider="alibaba",
            generation=1,
            status=ProviderStatus.SUCCESS,
            ordered_usable_pool=pool,
            canonical_session_results=(pool[0], pool[2]),
            metrics=_metrics(usable=3, displayed=2, display_requested=2),
        )


def test_provider_run_result_rejects_string_status_and_coverage_values() -> None:
    pool = (FakeCandidate("one"),)
    with pytest.raises(TypeError, match="status must be a ProviderStatus"):
        ProviderRunResult(
            provider="alibaba",
            generation=1,
            status="ERROR",  # type: ignore[arg-type]
            ordered_usable_pool=(),
            canonical_session_results=(),
            metrics=_metrics(usable=0, displayed=0, acquisition_requested=3),
        )
    with pytest.raises(TypeError, match="status must be a ProviderStatus"):
        ProviderRunResult(
            provider="alibaba",
            generation=1,
            status="SUCCESS",  # type: ignore[arg-type]
            ordered_usable_pool=pool,
            canonical_session_results=pool,
            metrics=_metrics(usable=1, displayed=1, display_requested=1),
        )
    with pytest.raises(TypeError, match="coverage_status must be a CoverageStatus or None"):
        ProviderRunResult(
            provider="alibaba",
            generation=1,
            status=ProviderStatus.SUCCESS,
            ordered_usable_pool=pool,
            canonical_session_results=pool,
            metrics=_metrics(usable=1, displayed=1, display_requested=1),
            requested_geographic_scope="Toda Venezuela",
            effective_geographic_scope="Toda Venezuela",
            coverage_status="PARTIAL",  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("status", "pool"),
    [
        (ProviderStatus.SUCCESS, (FakeCandidate("one"),)),
        (ProviderStatus.EMPTY, ()),
        (ProviderStatus.ERROR, ()),
    ],
)
def test_consistent_provider_run_values_remain_valid(
    status: ProviderStatus,
    pool: tuple[FakeCandidate, ...],
) -> None:
    displayed = min(len(pool), 3)
    result = ProviderRunResult(
        provider="alibaba",
        generation=4,
        status=status,
        ordered_usable_pool=pool,
        canonical_session_results=pool[:displayed],
        metrics=_metrics(
            usable=len(pool),
            displayed=displayed,
            display_requested=3,
            acquisition_requested=0 if status is ProviderStatus.ERROR else 5,
        ),
    )
    assert result.status is status
    assert result.generation == 4
    assert result.metrics.displayed == min(result.metrics.usable, result.metrics.display_requested)


def test_complete_geographic_coverage_requires_all_planned_steps() -> None:
    scope = "Toda Venezuela"
    policy = _policy({"facebook": _rule(max_acquisitions=2, max_budget=30, multiplier=4)})
    intent = _intent(provider="facebook", scope=scope)
    calls: list[str] = []
    result = _run(
        intent=intent,
        plan=_plan(policy=policy, provider="facebook", display_limit=3, scope=scope),
        policy=policy,
        batches={
            "step-1": _batch(FakeCandidate("one", "1")),
            "step-2": _batch(FakeCandidate("two", "2")),
        },
        calls=calls,
    )
    assert calls == ["step-1", "step-2"]
    assert result.metrics.acquisition_requested == 10
    assert result.status is ProviderStatus.SUCCESS
    assert result.coverage_status is CoverageStatus.COMPLETE
    assert result.effective_geographic_scope == scope
    assert result.requested_geographic_scope == scope


def test_partial_coverage_keeps_useful_results_and_is_incident() -> None:
    scope = "Toda Venezuela"
    policy = _policy({"facebook": _rule(max_acquisitions=2, max_budget=30, multiplier=4)})
    intent = _intent(provider="facebook", scope=scope)
    calls: list[str] = []
    result = _run(
        intent=intent,
        plan=_plan(policy=policy, provider="facebook", display_limit=3, scope=scope),
        policy=policy,
        batches={
            "step-1": _batch(FakeCandidate("one", "1")),
            "step-2": RuntimeError("partition unavailable"),
        },
        calls=calls,
    )
    assert calls == ["step-1", "step-2"]
    snapshot = SearchSessionSnapshot(intent=intent).commit(result)
    assert result.status is ProviderStatus.SUCCESS
    assert result.coverage_status is CoverageStatus.PARTIAL
    assert result.canonical_session_results[0].title == "one"
    assert snapshot.has_incidents is True
    assert snapshot.completion_label == "Búsqueda completada con incidencias"
    assert result.metrics.acquisition_requested == 10
    assert result.metrics.fetched is None
    assert result.metrics.mapped is None
    assert result.metrics.rejected is None


def test_partial_empty_does_not_claim_complete_nationwide_empty() -> None:
    scope = "Toda Venezuela"
    policy = _policy({"facebook": _rule(max_acquisitions=2, max_budget=30, multiplier=4)})
    intent = _intent(provider="facebook", scope=scope)
    calls: list[str] = []
    result = _run(
        intent=intent,
        plan=_plan(policy=policy, provider="facebook", display_limit=3, scope=scope),
        policy=policy,
        batches={"step-1": _batch(), "step-2": RuntimeError("failed")},
        calls=calls,
    )
    assert calls == ["step-1", "step-2"]
    snapshot = SearchSessionSnapshot(intent=intent).commit(result)
    assert result.status is ProviderStatus.EMPTY
    assert result.coverage_status is CoverageStatus.PARTIAL
    assert snapshot.completion_label == "Búsqueda completada con incidencias"


@pytest.mark.parametrize(
    ("candidates", "expected_status", "expected_label"),
    [
        ((_batch(FakeCandidate("one"))), ProviderStatus.SUCCESS, "Búsqueda completada"),
        ((_batch()), ProviderStatus.EMPTY, "Búsqueda completada · Sin resultados"),
    ],
)
def test_alibaba_non_applicable_coverage_completes_normally(
    candidates: AcquisitionBatch[FakeCandidate],
    expected_status: ProviderStatus,
    expected_label: str,
) -> None:
    policy = _policy({"alibaba": _rule(max_acquisitions=1)})
    intent = _intent(provider="alibaba")
    result = _run(
        intent=intent,
        plan=_plan(policy=policy, provider="alibaba", display_limit=3, limits=(5,)),
        policy=policy,
        batches={"step-1": candidates},
    )
    snapshot = SearchSessionSnapshot(intent=intent).commit(result)
    assert result.status is expected_status
    assert result.coverage_status is None
    assert result.effective_geographic_scope is None
    assert snapshot.completion_label == expected_label


def test_error_before_coverage_does_not_invent_coverage() -> None:
    scope = "Toda Venezuela"
    policy = _policy({"facebook": _rule(max_acquisitions=1)})
    intent = _intent(provider="facebook", scope=scope)
    result = _run(
        intent=intent,
        plan=_plan(policy=policy, provider="facebook", display_limit=3, limits=(5,), scope=scope),
        policy=policy,
        batches={"step-1": RuntimeError("not configured")},
    )
    assert result.status is ProviderStatus.ERROR
    assert result.coverage_status is None
    assert result.effective_geographic_scope is None
    assert result.metrics.usable == 0
    assert result.metrics.displayed == 0
    snapshot = SearchSessionSnapshot(intent=intent).commit(result)
    assert snapshot.completion_label == "Búsqueda con error"


def test_identity_less_similar_candidates_are_not_deduplicated() -> None:
    first = FakeCandidate("same title", image="same.jpg", price="10")
    second = FakeCandidate("same title", image="same.jpg", price="10")
    policy = _policy({"alibaba": _rule(max_acquisitions=1)})
    intent = _intent(display_limit=3)
    result = _run(
        intent=intent,
        plan=_plan(policy=policy, display_limit=3, limits=(5,)),
        policy=policy,
        batches={"step-1": _batch(first, second)},
    )
    assert result.ordered_usable_pool == (first, second)
    assert result.metrics.usable == 2


def test_truthful_stable_identity_is_deduplicated() -> None:
    first = FakeCandidate("first representation", identity="item-1")
    duplicate = FakeCandidate("duplicate representation", identity="item-1")
    policy = _policy({"alibaba": _rule(max_acquisitions=2, max_budget=30, multiplier=4)})
    calls: list[str] = []
    result = _run(
        intent=_intent(),
        plan=_plan(policy=policy, display_limit=3, limits=(5, 5)),
        policy=policy,
        batches={"step-1": _batch(first), "step-2": _batch(duplicate)},
        calls=calls,
    )
    assert calls == ["step-1", "step-2"]
    assert result.ordered_usable_pool == (first,)


def test_title_image_price_similarity_never_becomes_identity() -> None:
    similar = FakeCandidate("mouse", image="mouse.jpg", price="12")
    also_similar = FakeCandidate("mouse", image="mouse.jpg", price="12")
    identified = FakeCandidate("mouse", identity="sku-1", image="mouse.jpg", price="12")
    policy = _policy({"alibaba": _rule(max_acquisitions=1)})
    result = _run(
        intent=_intent(),
        plan=_plan(policy=policy, display_limit=3, limits=(5,)),
        policy=policy,
        batches={"step-1": _batch(similar, also_similar, identified)},
    )
    assert result.ordered_usable_pool == (similar, also_similar, identified)


def test_budget_exhaustion_returns_fewer_without_unbounded_calls() -> None:
    calls: list[str] = []
    policy = _policy({"alibaba": _rule(max_acquisitions=2, max_budget=5, multiplier=2)})
    result = _run(
        intent=_intent(display_limit=3),
        plan=_plan(policy=policy, display_limit=3, limits=(5, 5)),
        policy=policy,
        batches={
            "step-1": _batch(FakeCandidate("only")),
            "step-2": _batch(FakeCandidate("must not run")),
        },
        calls=calls,
    )
    assert calls == ["step-1"]
    assert result.status is ProviderStatus.SUCCESS
    assert result.metrics.displayed == 1
    assert result.metrics.acquisition_requested == 5
    assert result.metrics.acquisition_budget == 5


def test_one_logical_operation_composes_multiple_bounded_acquisitions() -> None:
    calls: list[str] = []
    policy = _policy({"alibaba": _rule(max_acquisitions=2, max_budget=10, multiplier=1)})
    result = _run(
        intent=_intent(display_limit=10),
        plan=_plan(policy=policy, display_limit=10, limits=(5, 5)),
        policy=policy,
        batches={"step-1": _batch(), "step-2": _batch()},
        calls=calls,
    )
    assert calls == ["step-1", "step-2"]
    assert result.metrics.acquisition_requested == 10


def test_rejection_loss_does_not_start_an_unplanned_refill_operation() -> None:
    calls: list[str] = []
    invalid = FakeCandidate("invalid", usable=False)
    policy = _policy({"alibaba": _rule(max_acquisitions=1)})
    result = _run(
        intent=_intent(),
        plan=_plan(policy=policy, display_limit=3, limits=(5,)),
        policy=policy,
        batches={"step-1": _batch(invalid)},
        calls=calls,
    )
    assert calls == ["step-1"]
    assert result.status is ProviderStatus.EMPTY
    assert result.metrics.usable == 0


def test_policy_approved_plan_executes() -> None:
    policy = _policy({"alibaba": _rule(max_acquisitions=2, max_budget=30, multiplier=3)})
    intent = _intent(display_limit=10)
    plan = policy.create_plan(
        provider="alibaba",
        display_limit=10,
        steps=_steps((5, 5)),
    )
    result = _run(
        intent=intent,
        plan=plan,
        policy=policy,
        batches={"step-1": _batch(FakeCandidate("one")), "step-2": _batch()},
    )
    assert plan.acquisition_budget == 30
    assert plan.maximum_internal_acquisitions == 2
    assert result.status is ProviderStatus.SUCCESS
    assert "acquisition_budget" not in inspect.signature(policy.create_plan).parameters
    assert "maximum_internal_acquisitions" not in inspect.signature(policy.create_plan).parameters


def test_plan_exceeding_policy_acquisition_budget_is_rejected() -> None:
    policy = _policy({"alibaba": _rule(max_budget=30, multiplier=3, max_acquisitions=2)})
    intent = _intent(display_limit=10)
    plan = BoundedAcquisitionPlan(
        provider="alibaba",
        acquisition_budget=100000,
        maximum_internal_acquisitions=2,
        steps=_steps((5, 5)),
    )
    with pytest.raises(ValueError, match="acquisition_budget does not match policy"):
        execute_bounded_provider_search(
            intent=intent,
            plan=plan,
            policy=policy,
            acquire=lambda _step: _batch(),
        )


def test_plan_exceeding_maximum_internal_acquisitions_is_rejected() -> None:
    policy = _policy({"alibaba": _rule(max_acquisitions=2, max_budget=30, multiplier=3)})
    intent = _intent(display_limit=10)
    plan = BoundedAcquisitionPlan(
        provider="alibaba",
        acquisition_budget=30,
        maximum_internal_acquisitions=5000,
        steps=_steps((5, 5)),
    )
    with pytest.raises(ValueError, match="maximum_internal_acquisitions does not match policy"):
        execute_bounded_provider_search(
            intent=intent,
            plan=plan,
            policy=policy,
            acquire=lambda _step: _batch(),
        )
    with pytest.raises(ValueError, match="plan exceeds maximum_internal_acquisitions"):
        BoundedAcquisitionPlan(
            provider="alibaba",
            acquisition_budget=30,
            maximum_internal_acquisitions=2,
            steps=_steps((5, 5, 5)),
        )


def test_display_limit_and_plan_budget_cannot_disagree_with_policy() -> None:
    policy = _policy({"alibaba": _rule(max_acquisitions=2, max_budget=30, multiplier=3)})
    intent = _intent(display_limit=3)
    plan = BoundedAcquisitionPlan(
        provider="alibaba",
        acquisition_budget=30,
        maximum_internal_acquisitions=2,
        steps=_steps((5, 5)),
    )
    with pytest.raises(ValueError, match="acquisition_budget does not match policy"):
        execute_bounded_provider_search(
            intent=intent,
            plan=plan,
            policy=policy,
            acquire=lambda _step: _batch(),
        )
    with pytest.raises(ValueError, match="not supported"):
        policy.validate_plan(plan, display_limit=11)


def test_unsupported_provider_plan_is_rejected() -> None:
    policy = _policy({"alibaba": _rule()})
    with pytest.raises(ValueError, match="unsupported provider"):
        policy.create_plan(
            provider="facebook",
            display_limit=3,
            steps=_steps((5,)),
        )
    intent = _intent(provider="facebook", selected_providers=("facebook",))
    plan = BoundedAcquisitionPlan(
        provider="facebook",
        acquisition_budget=9,
        maximum_internal_acquisitions=3,
        steps=_steps((5,)),
    )
    with pytest.raises(ValueError, match="unsupported provider"):
        execute_bounded_provider_search(
            intent=intent,
            plan=plan,
            policy=policy,
            acquire=lambda _step: _batch(),
        )


def test_provider_run_result_owns_generation() -> None:
    policy = _policy({"alibaba": _rule(max_acquisitions=1)})
    intent = _intent(generation=12)
    result = _run(
        intent=intent,
        plan=_plan(policy=policy, display_limit=3, limits=(5,)),
        policy=policy,
        batches={"step-1": _batch(FakeCandidate("one"))},
    )
    assert result.generation == intent.generation == 12


def test_current_generation_commit_succeeds() -> None:
    policy = _policy({"alibaba": _rule(max_acquisitions=1)})
    intent = _intent(generation=9)
    result = _run(
        intent=intent,
        plan=_plan(policy=policy, display_limit=3, limits=(5,)),
        policy=policy,
        batches={"step-1": _batch(FakeCandidate("one"))},
    )
    snapshot = SearchSessionSnapshot(intent=intent)
    current = snapshot.commit(result)
    assert current is not snapshot
    assert current.provider_results == (result,)
    assert current.result_for("alibaba") is result


def test_stale_generation_cannot_mutate_frozen_snapshot() -> None:
    policy = _policy({"alibaba": _rule(max_acquisitions=1)})
    stale_intent = _intent(generation=8)
    current_intent = _intent(generation=9)
    stale_result = _run(
        intent=stale_intent,
        plan=_plan(policy=policy, display_limit=3, limits=(5,)),
        policy=policy,
        batches={"step-1": _batch(FakeCandidate("stale"))},
    )
    snapshot = SearchSessionSnapshot(intent=current_intent)
    assert snapshot.commit(stale_result) is snapshot
    assert snapshot.provider_results == ()


def test_stale_result_cannot_be_relabelled_as_current() -> None:
    policy = _policy({"alibaba": _rule(max_acquisitions=1)})
    stale_intent = _intent(generation=1)
    current_intent = _intent(generation=2)
    stale_result = _run(
        intent=stale_intent,
        plan=_plan(policy=policy, display_limit=3, limits=(5,)),
        policy=policy,
        batches={"step-1": _batch(FakeCandidate("from-generation-a"))},
    )
    snapshot = SearchSessionSnapshot(intent=current_intent)
    assert "generation" not in inspect.signature(SearchSessionSnapshot.commit).parameters
    with pytest.raises(TypeError):
        snapshot.commit(stale_result, generation=current_intent.generation)  # type: ignore[call-arg]
    assert snapshot.commit(stale_result) is snapshot
    assert stale_result.generation == 1
    relabelled = replace(stale_result, generation=current_intent.generation)
    assert relabelled is not stale_result
    assert stale_result.generation == 1


def test_duplicate_provider_commit_is_idempotent() -> None:
    policy = _policy({"alibaba": _rule(max_acquisitions=1)})
    intent = _intent(generation=9)
    result = _run(
        intent=intent,
        plan=_plan(policy=policy, display_limit=3, limits=(5,)),
        policy=policy,
        batches={"step-1": _batch(FakeCandidate("one"))},
    )
    snapshot = SearchSessionSnapshot(intent=intent).commit(result)
    assert snapshot.commit(result) is snapshot
    later = _run(
        intent=intent,
        plan=_plan(policy=policy, display_limit=3, limits=(5,)),
        policy=policy,
        batches={"step-1": _batch(FakeCandidate("duplicate-ignored"))},
    )
    assert snapshot.commit(later) is snapshot
    assert snapshot.provider_results == (result,)


def test_unselected_provider_commit_is_rejected() -> None:
    intent = _intent(provider="alibaba")
    result = _result(pool=(FakeCandidate("fb"),), provider="facebook", generation=intent.generation)
    snapshot = SearchSessionSnapshot(intent=intent)
    with pytest.raises(ValueError, match="was not selected"):
        snapshot.commit(result)


def test_snapshot_remains_immutable() -> None:
    policy = _policy({"alibaba": _rule(max_acquisitions=1)})
    intent = _intent(generation=9)
    result = _run(
        intent=intent,
        plan=_plan(policy=policy, display_limit=3, limits=(5,)),
        policy=policy,
        batches={"step-1": _batch(FakeCandidate("one"))},
    )
    snapshot = SearchSessionSnapshot(intent=intent)
    current = snapshot.commit(result)
    assert snapshot.provider_results == ()
    with pytest.raises(AttributeError):
        snapshot.provider_results = (result,)  # type: ignore[misc]
    with pytest.raises(AttributeError):
        current.intent = intent  # type: ignore[misc]
    assert current.provider_results == (result,)


def test_acquisition_batch_does_not_own_effective_scope() -> None:
    assert "effective_geographic_scope" not in AcquisitionBatch.__dataclass_fields__


def test_central_budget_policy_is_finite_and_supports_ten() -> None:
    policy = AcquisitionBudgetPolicy(
        provider_rules={
            "fake": ProviderBudgetRule(
                maximum_internal_acquisitions=3,
                maximum_acquisition_budget=30,
                candidate_buffer_multiplier=3,
            )
        }
    )
    assert MAX_DISPLAY_LIMIT == 10
    assert policy.validate_display_limit(10) == 10
    assert policy.acquisition_budget("fake", 10) == 30
    assert policy.maximum_internal_acquisitions("fake") == 3
    with pytest.raises(ValueError, match="not supported"):
        policy.validate_display_limit(11)


def test_search_intent_does_not_enforce_policy_display_membership() -> None:
    intent = _intent(display_limit=11)
    assert intent.display_limit == 11
    with pytest.raises(TypeError, match="display_limit must be an integer"):
        _intent(display_limit=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="display_limit must be positive"):
        _intent(display_limit=0)


def test_effective_policy_is_the_only_display_limit_runtime_authority() -> None:
    intent = _intent(display_limit=3)
    custom = _policy({"alibaba": _rule()}, supported_display_limits=frozenset({10}))
    calls: list[str] = []

    def acquire(step: InternalAcquisitionStep) -> AcquisitionBatch[FakeCandidate]:
        calls.append(step.key)
        return _batch()

    assert intent.display_limit == 3
    with pytest.raises(ValueError, match="not supported"):
        custom.validate_intent(intent)
    with pytest.raises(ValueError, match="not supported"):
        custom.create_plan(provider="alibaba", display_limit=3, steps=_steps((5,)))

    default_policy = _policy()
    plan = default_policy.create_plan(provider="alibaba", display_limit=3, steps=_steps((5,)))
    with pytest.raises(ValueError, match="not supported"):
        execute_bounded_provider_search(
            intent=intent,
            plan=plan,
            policy=custom,
            acquire=acquire,
        )
    assert calls == []


def test_unsupported_display_limit_is_rejected_before_acquisition() -> None:
    intent = _intent(display_limit=11)
    policy = _policy()
    calls: list[str] = []
    plan = BoundedAcquisitionPlan(
        provider="alibaba",
        acquisition_budget=30,
        maximum_internal_acquisitions=3,
        steps=_steps((5,)),
    )

    def acquire(step: InternalAcquisitionStep) -> AcquisitionBatch[FakeCandidate]:
        calls.append(step.key)
        return _batch()

    with pytest.raises(ValueError, match="not supported"):
        execute_bounded_provider_search(
            intent=intent,
            plan=plan,
            policy=policy,
            acquire=acquire,
        )
    assert calls == []
    with pytest.raises(ValueError, match="not supported"):
        policy.create_plan(provider="alibaba", display_limit=11, steps=_steps((5,)))


def test_default_policy_supports_one_three_five_ten() -> None:
    policy = _policy()
    assert MAX_DISPLAY_LIMIT >= 10
    for display_limit in (1, 3, 5, 10):
        assert policy.validate_display_limit(display_limit) == display_limit
        assert _intent(display_limit=display_limit).display_limit == display_limit


def test_unknown_optional_metrics_are_not_fabricated_as_zero() -> None:
    policy = _policy({"alibaba": _rule(max_acquisitions=1)})
    result = _run(
        intent=_intent(),
        plan=_plan(policy=policy, display_limit=3, limits=(5,)),
        policy=policy,
        batches={
            "step-1": AcquisitionBatch(
                candidates=(FakeCandidate("one"),),
                fetched=None,
                mapped=None,
                rejected=None,
            )
        },
    )
    assert result.metrics.fetched is None
    assert result.metrics.mapped is None
    assert result.metrics.rejected is None
    assert result.status is ProviderStatus.SUCCESS


def test_failed_executed_step_keeps_optional_aggregates_unknown() -> None:
    candidates = tuple(FakeCandidate(f"ok-{index}") for index in range(5))
    known = AcquisitionBatch(
        candidates=candidates,
        fetched=5,
        mapped=5,
        rejected=0,
    )
    policy = _policy({"alibaba": _rule(max_acquisitions=2, max_budget=30, multiplier=3)})
    intent = _intent(display_limit=10)
    calls: list[str] = []
    result = _run(
        intent=intent,
        plan=_plan(policy=policy, display_limit=10, limits=(5, 5)),
        policy=policy,
        batches={"step-1": known, "step-2": RuntimeError("failed before metrics")},
        calls=calls,
    )
    assert calls == ["step-1", "step-2"]
    assert result.metrics.acquisition_requested == 10
    assert result.metrics.fetched is None
    assert result.metrics.mapped is None
    assert result.metrics.rejected is None
    assert result.metrics.fetched != 5
    assert result.metrics.mapped != 0
    assert result.metrics.rejected != 0
    assert result.status is ProviderStatus.SUCCESS
    assert result.metrics.usable == 5
    assert result.metrics.displayed == 5
