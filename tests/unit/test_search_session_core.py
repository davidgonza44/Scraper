"""Offline tests for Implementation PR A generic-search session foundations."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

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
) -> SearchIntent:
    scopes = ((provider, scope),) if scope is not None else ()
    return SearchIntent(
        original_user_query="  baseball   glove ",
        display_limit=display_limit,
        selected_providers=(provider,),
        generation=generation,
        requested_geographic_scopes=scopes,
    )


def _plan(
    *,
    provider: str = "alibaba",
    budget: int = 30,
    limits: tuple[int, ...] = (5, 5),
    scope: str | None = None,
    max_acquisitions: int | None = None,
) -> BoundedAcquisitionPlan:
    return BoundedAcquisitionPlan(
        provider=provider,
        acquisition_budget=budget,
        maximum_internal_acquisitions=max_acquisitions or len(limits),
        steps=tuple(
            InternalAcquisitionStep(key=f"step-{index}", candidate_limit=limit)
            for index, limit in enumerate(limits, start=1)
        ),
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
        acquire=acquire,
        is_usable=lambda candidate: candidate.usable,
        stable_identity=lambda candidate: candidate.identity,
    )


def test_budget_is_distinct_from_actual_requested_work() -> None:
    intent = _intent(display_limit=10)
    plan = _plan(budget=30, limits=(5, 5))
    result = _run(
        intent=intent,
        plan=plan,
        batches={"step-1": _batch(), "step-2": _batch()},
    )
    assert result.metrics.acquisition_budget == 30
    assert result.metrics.acquisition_requested == 10


def test_usable_pool_freezes_exact_display_prefix() -> None:
    candidates = tuple(FakeCandidate(f"item-{index}") for index in range(8))
    intent = _intent(display_limit=3)
    result = _run(
        intent=intent,
        plan=_plan(budget=10, limits=(10,)),
        batches={"step-1": _batch(*candidates)},
    )
    assert result.metrics.acquisition_requested == 10
    assert result.metrics.usable == 8
    assert result.metrics.displayed == 3
    assert result.canonical_session_results == candidates[:3]
    assert isinstance(result.canonical_session_results, tuple)


def test_complete_geographic_coverage_requires_all_planned_steps() -> None:
    scope = "Toda Venezuela"
    intent = _intent(provider="facebook", scope=scope)
    result = _run(
        intent=intent,
        plan=_plan(provider="facebook", scope=scope),
        batches={
            "step-1": _batch(FakeCandidate("one", "1")),
            "step-2": _batch(FakeCandidate("two", "2")),
        },
    )
    assert result.status is ProviderStatus.SUCCESS
    assert result.coverage_status is CoverageStatus.COMPLETE
    assert result.effective_geographic_scope == scope


def test_partial_coverage_keeps_useful_results_and_is_incident() -> None:
    scope = "Toda Venezuela"
    intent = _intent(provider="facebook", scope=scope)
    result = _run(
        intent=intent,
        plan=_plan(provider="facebook", scope=scope),
        batches={
            "step-1": _batch(FakeCandidate("one", "1")),
            "step-2": RuntimeError("partition unavailable"),
        },
    )
    snapshot = SearchSessionSnapshot(intent=intent).commit(result, generation=intent.generation)
    assert result.status is ProviderStatus.SUCCESS
    assert result.coverage_status is CoverageStatus.PARTIAL
    assert result.canonical_session_results[0].title == "one"
    assert snapshot.has_incidents is True
    assert snapshot.completion_label == "Búsqueda completada con incidencias"


def test_partial_empty_does_not_claim_complete_nationwide_empty() -> None:
    scope = "Toda Venezuela"
    intent = _intent(provider="facebook", scope=scope)
    result = _run(
        intent=intent,
        plan=_plan(provider="facebook", scope=scope),
        batches={"step-1": _batch(), "step-2": RuntimeError("failed")},
    )
    snapshot = SearchSessionSnapshot(intent=intent).commit(result, generation=intent.generation)
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
    intent = _intent(provider="alibaba")
    result = _run(
        intent=intent,
        plan=_plan(provider="alibaba", limits=(5,)),
        batches={"step-1": candidates},
    )
    snapshot = SearchSessionSnapshot(intent=intent).commit(result, generation=intent.generation)
    assert result.status is expected_status
    assert result.coverage_status is None
    assert result.effective_geographic_scope is None
    assert snapshot.completion_label == expected_label


def test_error_before_coverage_does_not_invent_coverage() -> None:
    scope = "Toda Venezuela"
    intent = _intent(provider="facebook", scope=scope)
    result = _run(
        intent=intent,
        plan=_plan(provider="facebook", scope=scope, limits=(5,)),
        batches={"step-1": RuntimeError("not configured")},
    )
    assert result.status is ProviderStatus.ERROR
    assert result.coverage_status is None
    assert result.effective_geographic_scope is None
    snapshot = SearchSessionSnapshot(intent=intent).commit(result, generation=intent.generation)
    assert snapshot.completion_label == "Búsqueda con error"


def test_identity_less_similar_candidates_are_not_deduplicated() -> None:
    first = FakeCandidate("same title", image="same.jpg", price="10")
    second = FakeCandidate("same title", image="same.jpg", price="10")
    intent = _intent(display_limit=3)
    result = _run(
        intent=intent,
        plan=_plan(limits=(5,)),
        batches={"step-1": _batch(first, second)},
    )
    assert result.ordered_usable_pool == (first, second)
    assert result.metrics.usable == 2


def test_truthful_stable_identity_is_deduplicated() -> None:
    first = FakeCandidate("first representation", identity="item-1")
    duplicate = FakeCandidate("duplicate representation", identity="item-1")
    result = _run(
        intent=_intent(),
        plan=_plan(limits=(5, 5)),
        batches={"step-1": _batch(first), "step-2": _batch(duplicate)},
    )
    assert result.ordered_usable_pool == (first,)


def test_budget_exhaustion_returns_fewer_without_unbounded_calls() -> None:
    calls: list[str] = []
    result = _run(
        intent=_intent(display_limit=3),
        plan=_plan(budget=5, limits=(5, 5)),
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


def test_one_logical_operation_composes_multiple_bounded_acquisitions() -> None:
    calls: list[str] = []
    result = _run(
        intent=_intent(display_limit=10),
        plan=_plan(budget=10, limits=(5, 5)),
        batches={"step-1": _batch(), "step-2": _batch()},
        calls=calls,
    )
    assert calls == ["step-1", "step-2"]
    assert result.metrics.acquisition_requested == 10


def test_rejection_loss_does_not_start_an_unplanned_refill_operation() -> None:
    calls: list[str] = []
    invalid = FakeCandidate("invalid", usable=False)
    result = _run(
        intent=_intent(),
        plan=_plan(budget=30, limits=(5,)),
        batches={"step-1": _batch(invalid)},
        calls=calls,
    )
    assert calls == ["step-1"]
    assert result.status is ProviderStatus.EMPTY
    assert result.metrics.usable == 0


def test_stale_generation_cannot_mutate_frozen_snapshot() -> None:
    intent = _intent(generation=9)
    result = _run(
        intent=intent,
        plan=_plan(limits=(5,)),
        batches={"step-1": _batch(FakeCandidate("one"))},
    )
    snapshot = SearchSessionSnapshot(intent=intent)
    assert snapshot.commit(result, generation=8) is snapshot
    current = snapshot.commit(result, generation=9)
    assert current is not snapshot
    assert current.provider_results == (result,)
    assert current.commit(result, generation=9) is current


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
