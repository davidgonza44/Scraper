"""Provider-neutral generic-search session contracts and bounded orchestration.

This module has no provider, network, persistence, GUI, or translation dependencies.
Existing single-acquisition use cases can be composed as planned internal steps.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from bera_price_tracker.application.provider_acquisition import ProviderRunMetrics

MAX_DISPLAY_LIMIT = 10
SUPPORTED_DISPLAY_LIMITS = frozenset({1, 3, 5, 10})


class ProviderStatus(StrEnum):
    SUCCESS = "SUCCESS"
    EMPTY = "EMPTY"
    ERROR = "ERROR"


class CoverageStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"


@dataclass(frozen=True, slots=True)
class ProviderBudgetRule:
    """Finite provider-neutral limits used to calculate an acquisition budget."""

    maximum_internal_acquisitions: int
    maximum_acquisition_budget: int
    candidate_buffer_multiplier: int = 1

    def __post_init__(self) -> None:
        for name, value in (
            ("maximum_internal_acquisitions", self.maximum_internal_acquisitions),
            ("maximum_acquisition_budget", self.maximum_acquisition_budget),
            ("candidate_buffer_multiplier", self.candidate_buffer_multiplier),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if value < 1:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True, slots=True)
class AcquisitionBudgetPolicy:
    """Central finite display validation and acquisition-budget calculation."""

    provider_rules: Mapping[str, ProviderBudgetRule]
    supported_display_limits: frozenset[int] = SUPPORTED_DISPLAY_LIMITS
    max_display_limit: int = MAX_DISPLAY_LIMIT

    def __post_init__(self) -> None:
        rules = dict(self.provider_rules)
        if not rules:
            raise ValueError("provider_rules must not be empty")
        if self.max_display_limit < 10:
            raise ValueError("max_display_limit must support 10")
        if 10 not in self.supported_display_limits:
            raise ValueError("supported_display_limits must include 10")
        if any(
            value < 1 or value > self.max_display_limit for value in self.supported_display_limits
        ):
            raise ValueError("supported display limits must be positive and finite")
        object.__setattr__(self, "provider_rules", MappingProxyType(rules))

    def validate_display_limit(self, value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("display_limit must be an integer")
        if value not in self.supported_display_limits or value > self.max_display_limit:
            raise ValueError("display_limit is not supported")
        return value

    def acquisition_budget(self, provider: str, display_limit: int) -> int:
        normalized = self.validate_display_limit(display_limit)
        try:
            rule = self.provider_rules[provider]
        except KeyError as exc:
            raise ValueError(f"unsupported provider: {provider}") from exc
        proposed = normalized * rule.candidate_buffer_multiplier
        return min(rule.maximum_acquisition_budget, max(normalized, proposed))

    def maximum_internal_acquisitions(self, provider: str) -> int:
        try:
            return self.provider_rules[provider].maximum_internal_acquisitions
        except KeyError as exc:
            raise ValueError(f"unsupported provider: {provider}") from exc


@dataclass(frozen=True, slots=True)
class SearchIntent:
    original_user_query: str
    display_limit: int
    selected_providers: tuple[str, ...]
    generation: int
    requested_geographic_scopes: tuple[tuple[str, str | None], ...] = ()

    def __post_init__(self) -> None:
        query = " ".join(self.original_user_query.strip().split())
        if not query:
            raise ValueError("original_user_query must not be blank")
        if isinstance(self.generation, bool) or not isinstance(self.generation, int):
            raise TypeError("generation must be an integer")
        if self.generation < 0:
            raise ValueError("generation must not be negative")
        if self.display_limit not in SUPPORTED_DISPLAY_LIMITS:
            raise ValueError("display_limit is not supported")
        if not self.selected_providers or len(set(self.selected_providers)) != len(
            self.selected_providers
        ):
            raise ValueError("selected_providers must be non-empty and unique")
        if set(provider for provider, _scope in self.requested_geographic_scopes) - set(
            self.selected_providers
        ):
            raise ValueError("requested scopes must belong to selected providers")
        if len({provider for provider, _scope in self.requested_geographic_scopes}) != len(
            self.requested_geographic_scopes
        ):
            raise ValueError("requested scopes must be unique per provider")
        object.__setattr__(self, "original_user_query", query)

    def requested_scope_for(self, provider: str) -> str | None:
        return dict(self.requested_geographic_scopes).get(provider)


@dataclass(frozen=True, slots=True)
class InternalAcquisitionStep:
    key: str
    candidate_limit: int
    required_for_complete_coverage: bool = True

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("step key must not be blank")
        if isinstance(self.candidate_limit, bool) or not isinstance(self.candidate_limit, int):
            raise TypeError("candidate_limit must be an integer")
        if self.candidate_limit < 1:
            raise ValueError("candidate_limit must be positive")


@dataclass(frozen=True, slots=True)
class AcquisitionBatch[CandidateT]:
    candidates: tuple[CandidateT, ...]
    fetched: int | None = None
    mapped: int | None = None
    rejected: int | None = None
    effective_geographic_scope: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("fetched", self.fetched),
            ("mapped", self.mapped),
            ("rejected", self.rejected),
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer or None")


@dataclass(frozen=True, slots=True)
class BoundedAcquisitionPlan:
    provider: str
    acquisition_budget: int
    maximum_internal_acquisitions: int
    steps: tuple[InternalAcquisitionStep, ...]
    requested_geographic_scope: str | None = None
    complete_effective_geographic_scope: str | None = None
    partial_effective_geographic_scope: str | None = None
    allow_early_termination: bool = True

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("provider must not be blank")
        for name, value in (
            ("acquisition_budget", self.acquisition_budget),
            ("maximum_internal_acquisitions", self.maximum_internal_acquisitions),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if value < 1:
                raise ValueError(f"{name} must be positive")
        if not self.steps:
            raise ValueError("steps must not be empty")
        if len({step.key for step in self.steps}) != len(self.steps):
            raise ValueError("step keys must be unique")
        if any(step.candidate_limit > self.acquisition_budget for step in self.steps):
            raise ValueError("each step candidate limit must fit the acquisition budget")
        if self.coverage_applicable and (
            not self.complete_effective_geographic_scope
            or not self.partial_effective_geographic_scope
        ):
            raise ValueError("geographic plans require complete and partial effective scopes")

    @property
    def coverage_applicable(self) -> bool:
        return self.requested_geographic_scope is not None


@dataclass(frozen=True, slots=True)
class ProviderRunResult[CandidateT]:
    provider: str
    status: ProviderStatus
    ordered_usable_pool: tuple[CandidateT, ...]
    canonical_session_results: tuple[CandidateT, ...]
    metrics: ProviderRunMetrics
    requested_geographic_scope: str | None = None
    effective_geographic_scope: str | None = None
    coverage_status: CoverageStatus | None = None
    failure: str | None = None

    def __post_init__(self) -> None:
        if self.canonical_session_results != self.ordered_usable_pool[: self.metrics.displayed]:
            raise ValueError("canonical results must be the frozen displayed prefix")
        if self.status is ProviderStatus.SUCCESS and self.metrics.usable < 1:
            raise ValueError("SUCCESS requires at least one usable candidate")
        if self.status is ProviderStatus.EMPTY and self.metrics.usable != 0:
            raise ValueError("EMPTY requires zero usable candidates")
        if self.status is ProviderStatus.ERROR:
            if self.ordered_usable_pool or self.canonical_session_results:
                raise ValueError("ERROR cannot expose provider candidates")
            if self.coverage_status is not None or self.effective_geographic_scope is not None:
                raise ValueError("ERROR cannot invent geographic coverage")
        if self.requested_geographic_scope is None:
            if self.coverage_status is not None or self.effective_geographic_scope is not None:
                raise ValueError("non-applicable coverage must remain unavailable")
        elif self.status is not ProviderStatus.ERROR:
            if self.coverage_status is None or self.effective_geographic_scope is None:
                raise ValueError("successful geographic execution requires truthful coverage")
        if self.coverage_status is CoverageStatus.PARTIAL and not self.effective_geographic_scope:
            raise ValueError("PARTIAL requires an effective geographic scope")


@dataclass(frozen=True, slots=True)
class SearchSessionSnapshot:
    intent: SearchIntent
    provider_results: tuple[ProviderRunResult[Any], ...] = ()

    def result_for(self, provider: str) -> ProviderRunResult[Any] | None:
        return next(
            (result for result in self.provider_results if result.provider == provider), None
        )

    def commit(
        self,
        result: ProviderRunResult[Any],
        *,
        generation: int,
    ) -> SearchSessionSnapshot:
        """Return a new snapshot, ignoring stale or duplicate provider completions."""

        if generation != self.intent.generation:
            return self
        if result.provider not in self.intent.selected_providers:
            raise ValueError("result provider was not selected")
        if self.result_for(result.provider) is not None:
            return self
        return replace(self, provider_results=(*self.provider_results, result))

    @property
    def settled(self) -> bool:
        return len(self.provider_results) == len(self.intent.selected_providers)

    @property
    def has_incidents(self) -> bool:
        return any(
            result.status is ProviderStatus.ERROR
            or result.coverage_status is CoverageStatus.PARTIAL
            for result in self.provider_results
        )

    @property
    def completion_label(self) -> str:
        if not self.settled:
            return "Buscando..."
        statuses = tuple(result.status for result in self.provider_results)
        if all(status is ProviderStatus.ERROR for status in statuses):
            return "Búsqueda con error"
        if self.has_incidents:
            return "Búsqueda completada con incidencias"
        if all(status is ProviderStatus.EMPTY for status in statuses):
            return "Búsqueda completada · Sin resultados"
        return "Búsqueda completada"


def execute_bounded_provider_search[CandidateT](
    *,
    intent: SearchIntent,
    plan: BoundedAcquisitionPlan,
    acquire: Callable[[InternalAcquisitionStep], AcquisitionBatch[CandidateT]],
    is_usable: Callable[[CandidateT], bool] = lambda _candidate: True,
    stable_identity: Callable[[CandidateT], str | None] = lambda _candidate: None,
) -> ProviderRunResult[CandidateT]:
    """Execute one logical provider operation composed of bounded planned steps.

    Every step is attempted at most once. A failed step is never re-run to refill
    rejected or mapping-lost candidates. Existing low-level calls remain unchanged.
    """

    if plan.provider not in intent.selected_providers:
        raise ValueError("plan provider was not selected")
    if plan.requested_geographic_scope != intent.requested_scope_for(plan.provider):
        raise ValueError("plan scope does not match search intent")
    if intent.display_limit > plan.acquisition_budget:
        raise ValueError("acquisition_budget must cover display_limit")

    requested = 0
    successful_steps: set[str] = set()
    failed_steps: set[str] = set()
    candidates: list[CandidateT] = []
    seen_identities: set[str] = set()
    fetched_values: list[int | None] = []
    mapped_values: list[int | None] = []
    rejected_values: list[int | None] = []

    for step in plan.steps[: plan.maximum_internal_acquisitions]:
        if requested + step.candidate_limit > plan.acquisition_budget:
            break
        if (
            plan.allow_early_termination
            and not plan.coverage_applicable
            and len(candidates) >= intent.display_limit
        ):
            break
        requested += step.candidate_limit
        try:
            batch = acquire(step)
        except Exception:  # noqa: BLE001 - converted to a provider outcome below
            failed_steps.add(step.key)
            continue
        successful_steps.add(step.key)
        fetched_values.append(batch.fetched)
        mapped_values.append(batch.mapped)
        rejected_values.append(batch.rejected)
        for candidate in batch.candidates:
            if not is_usable(candidate):
                continue
            identity = stable_identity(candidate)
            normalized_identity = identity.strip() if isinstance(identity, str) else ""
            if normalized_identity:
                if normalized_identity in seen_identities:
                    continue
                seen_identities.add(normalized_identity)
            candidates.append(candidate)

    required_steps = {step.key for step in plan.steps if step.required_for_complete_coverage}
    usable_pool = tuple(candidates)
    displayed = min(len(usable_pool), intent.display_limit)
    coverage_status: CoverageStatus | None = None
    effective_scope: str | None = None
    if plan.coverage_applicable and successful_steps:
        if required_steps.issubset(successful_steps) and not (required_steps & failed_steps):
            coverage_status = CoverageStatus.COMPLETE
            effective_scope = plan.complete_effective_geographic_scope
        else:
            coverage_status = CoverageStatus.PARTIAL
            effective_scope = plan.partial_effective_geographic_scope

    no_truthful_execution = not successful_steps and (
        bool(failed_steps) or plan.coverage_applicable
    )
    status = (
        ProviderStatus.ERROR
        if no_truthful_execution
        else ProviderStatus.SUCCESS
        if usable_pool
        else ProviderStatus.EMPTY
    )
    if status is ProviderStatus.ERROR:
        coverage_status = None
        effective_scope = None
        usable_pool = ()
        displayed = 0

    metrics = ProviderRunMetrics(
        display_requested=intent.display_limit,
        acquisition_budget=plan.acquisition_budget,
        acquisition_requested=requested,
        fetched=_sum_if_known(fetched_values),
        mapped=_sum_if_known(mapped_values),
        rejected=_sum_if_known(rejected_values),
        usable=len(usable_pool),
        displayed=displayed,
    )
    return ProviderRunResult(
        provider=plan.provider,
        status=status,
        ordered_usable_pool=usable_pool,
        canonical_session_results=usable_pool[:displayed],
        metrics=metrics,
        requested_geographic_scope=plan.requested_geographic_scope,
        effective_geographic_scope=effective_scope,
        coverage_status=coverage_status,
        failure="provider operation failed" if status is ProviderStatus.ERROR else None,
    )


def _sum_if_known(values: Sequence[int | None]) -> int | None:
    if not values or any(value is None for value in values):
        return None
    return sum(value for value in values if value is not None)


__all__ = [
    "MAX_DISPLAY_LIMIT",
    "SUPPORTED_DISPLAY_LIMITS",
    "AcquisitionBatch",
    "AcquisitionBudgetPolicy",
    "BoundedAcquisitionPlan",
    "CoverageStatus",
    "InternalAcquisitionStep",
    "ProviderBudgetRule",
    "ProviderRunResult",
    "ProviderStatus",
    "SearchIntent",
    "SearchSessionSnapshot",
    "execute_bounded_provider_search",
]
