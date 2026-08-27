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
GENERIC_SESSION_UNSET_GENERATION = -1


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
    """Central finite display validation and acquisition-budget calculation.

    This policy is the only source of truth for supported display limits,
    ``acquisition_budget``, and maximum internal acquisitions. A
    :class:`BoundedAcquisitionPlan` is executable only after
    :meth:`create_plan` or :meth:`validate_plan` proves those values.
    """

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

    def validate_intent(self, intent: SearchIntent) -> SearchIntent:
        """Approve ``intent.display_limit`` against this policy before acquisition."""

        self.validate_display_limit(intent.display_limit)
        return intent

    def create_plan(
        self,
        *,
        provider: str,
        display_limit: int,
        steps: tuple[InternalAcquisitionStep, ...],
        requested_geographic_scope: str | None = None,
        complete_effective_geographic_scope: str | None = None,
        partial_effective_geographic_scope: str | None = None,
        allow_early_termination: bool = True,
    ) -> BoundedAcquisitionPlan:
        """Derive a finite plan. Budget and acquisition caps come only from policy."""

        plan = BoundedAcquisitionPlan(
            provider=provider,
            acquisition_budget=self.acquisition_budget(provider, display_limit),
            maximum_internal_acquisitions=self.maximum_internal_acquisitions(provider),
            steps=steps,
            requested_geographic_scope=requested_geographic_scope,
            complete_effective_geographic_scope=complete_effective_geographic_scope,
            partial_effective_geographic_scope=partial_effective_geographic_scope,
            allow_early_termination=allow_early_termination,
        )
        return self.validate_plan(plan, display_limit=display_limit)

    def validate_plan(
        self,
        plan: BoundedAcquisitionPlan,
        *,
        display_limit: int,
    ) -> BoundedAcquisitionPlan:
        """Reject plans whose provider, display limit, or budgets disagree with policy."""

        self.validate_display_limit(display_limit)
        if plan.provider not in self.provider_rules:
            raise ValueError(f"unsupported provider: {plan.provider}")
        expected_budget = self.acquisition_budget(plan.provider, display_limit)
        if plan.acquisition_budget != expected_budget:
            raise ValueError("plan acquisition_budget does not match policy")
        expected_maximum = self.maximum_internal_acquisitions(plan.provider)
        if plan.maximum_internal_acquisitions != expected_maximum:
            raise ValueError("plan maximum_internal_acquisitions does not match policy")
        if len(plan.steps) > expected_maximum:
            raise ValueError("plan exceeds maximum_internal_acquisitions")
        if any(step.candidate_limit > expected_budget for step in plan.steps):
            raise ValueError("each step candidate limit must fit the acquisition budget")
        if display_limit > expected_budget:
            raise ValueError("acquisition_budget must cover display_limit")
        return plan


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
        if isinstance(self.display_limit, bool) or not isinstance(self.display_limit, int):
            raise TypeError("display_limit must be an integer")
        if self.display_limit < 1:
            raise ValueError("display_limit must be positive")
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
    """Safe output of one existing bounded provider operation.

    Geographic coverage is not a batch concern. PR A derives
    ``requested_geographic_scope``, ``effective_geographic_scope``, and
    ``coverage_status`` from :class:`BoundedAcquisitionPlan` onto
    :class:`ProviderRunResult`. Concrete Facebook partition aggregation is PR D.
    """

    candidates: tuple[CandidateT, ...]
    fetched: int | None = None
    mapped: int | None = None
    rejected: int | None = None

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
        if len(self.steps) > self.maximum_internal_acquisitions:
            raise ValueError("plan exceeds maximum_internal_acquisitions")
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
    generation: int
    status: ProviderStatus
    ordered_usable_pool: tuple[CandidateT, ...]
    canonical_session_results: tuple[CandidateT, ...]
    metrics: ProviderRunMetrics
    requested_geographic_scope: str | None = None
    effective_geographic_scope: str | None = None
    coverage_status: CoverageStatus | None = None
    failure: str | None = None

    def __post_init__(self) -> None:
        if type(self.status) is not ProviderStatus:
            raise TypeError("status must be a ProviderStatus")
        if self.coverage_status is not None and type(self.coverage_status) is not CoverageStatus:
            raise TypeError("coverage_status must be a CoverageStatus or None")
        if isinstance(self.generation, bool) or not isinstance(self.generation, int):
            raise TypeError("generation must be an integer")
        if self.generation < 0:
            raise ValueError("generation must not be negative")
        if self.metrics.usable != len(self.ordered_usable_pool):
            raise ValueError("metrics.usable must equal the ordered usable pool size")
        if self.metrics.displayed != len(self.canonical_session_results):
            raise ValueError("metrics.displayed must equal the canonical session result count")
        if self.canonical_session_results != self.ordered_usable_pool[: self.metrics.displayed]:
            raise ValueError("canonical results must be the frozen displayed prefix")
        if self.status is ProviderStatus.SUCCESS and self.metrics.usable < 1:
            raise ValueError("SUCCESS requires at least one usable candidate")
        if self.status is ProviderStatus.EMPTY and self.metrics.usable != 0:
            raise ValueError("EMPTY requires zero usable candidates")
        if self.status is ProviderStatus.ERROR:
            if self.ordered_usable_pool or self.canonical_session_results:
                raise ValueError("ERROR cannot expose provider candidates")
            if self.metrics.usable != 0 or self.metrics.displayed != 0:
                raise ValueError("ERROR must expose zero usable and displayed counts")
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

    def commit(self, result: ProviderRunResult[Any]) -> SearchSessionSnapshot:
        """Return a new snapshot, ignoring stale or duplicate provider completions.

        Generation ownership is intrinsic to ``result``. A stale result cannot be
        relabelled by supplying a different generation argument.
        """

        if result.generation != self.intent.generation:
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
    policy: AcquisitionBudgetPolicy,
    acquire: Callable[[InternalAcquisitionStep], AcquisitionBatch[CandidateT]],
    is_usable: Callable[[CandidateT], bool] = lambda _candidate: True,
    stable_identity: Callable[[CandidateT], str | None] = lambda _candidate: None,
) -> ProviderRunResult[CandidateT]:
    """Execute one logical provider operation composed of bounded planned steps.

    Every step is attempted at most once. A failed step is never re-run to refill
    rejected or mapping-lost candidates. Existing low-level calls remain unchanged.
    The plan must be derived from or validated against ``policy``; arbitrary
    budget fields cannot bypass :class:`AcquisitionBudgetPolicy`. Supported
    display limits are approved only by that policy, never by a second
    module-level check on :class:`SearchIntent`.
    """

    policy.validate_intent(intent)
    policy.validate_plan(plan, display_limit=intent.display_limit)
    if plan.provider not in intent.selected_providers:
        raise ValueError("plan provider was not selected")
    if plan.requested_geographic_scope != intent.requested_scope_for(plan.provider):
        raise ValueError("plan scope does not match search intent")

    requested = 0
    successful_steps: set[str] = set()
    failed_steps: set[str] = set()
    candidates: list[CandidateT] = []
    seen_identities: set[str] = set()
    fetched_values: list[int | None] = []
    mapped_values: list[int | None] = []
    rejected_values: list[int | None] = []

    for step in plan.steps:
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
            fetched_values.append(None)
            mapped_values.append(None)
            rejected_values.append(None)
            continue
        successful_steps.add(step.key)
        fetched_values.append(batch.fetched)
        mapped_values.append(batch.mapped)
        rejected_values.append(batch.rejected)
        extend_ordered_usable_pool(
            candidates,
            seen_identities,
            batch.candidates,
            is_usable=is_usable,
            stable_identity=stable_identity,
        )

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
        generation=intent.generation,
        status=status,
        ordered_usable_pool=usable_pool,
        canonical_session_results=freeze_canonical_prefix(usable_pool, intent.display_limit),
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


def _nonempty_id(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def extend_ordered_usable_pool[CandidateT](
    pool: list[CandidateT],
    seen_identities: set[str],
    incoming: Sequence[CandidateT],
    *,
    is_usable: Callable[[CandidateT], bool],
    stable_identity: Callable[[CandidateT], str | None],
) -> None:
    """Append usable incoming candidates using deterministic BERA aggregate order.

    A genuine single acquisition is one incoming sequence: provider order is
    preserved after integrity filtering. Multiple acquisitions without a truthful
    native global order are concatenated in caller order. Deduplication uses only
    a truthful non-blank stable identity. Identity-less valid candidates remain
    distinct even when title, image, price, or rank look similar.
    """

    for candidate in incoming:
        if not is_usable(candidate):
            continue
        identity = stable_identity(candidate)
        normalized_identity = identity.strip() if isinstance(identity, str) else ""
        if normalized_identity:
            if normalized_identity in seen_identities:
                continue
            seen_identities.add(normalized_identity)
        pool.append(candidate)


def ordered_usable_pool_from_batches[CandidateT](
    batches: Sequence[Sequence[CandidateT]],
    *,
    is_usable: Callable[[CandidateT], bool] = lambda _candidate: True,
    stable_identity: Callable[[CandidateT], str | None] = lambda _candidate: None,
) -> tuple[CandidateT, ...]:
    """Freeze deterministic BERA aggregate provider ordering from acquisition batches."""

    pool: list[CandidateT] = []
    seen_identities: set[str] = set()
    for batch in batches:
        extend_ordered_usable_pool(
            pool,
            seen_identities,
            batch,
            is_usable=is_usable,
            stable_identity=stable_identity,
        )
    return tuple(pool)


@dataclass(frozen=True, slots=True)
class SearchPositionComparisonRow[CandidateT]:
    """Generic search row aligned by one-based provider result position.

    Same rank never implies the same product. ``identity_confirmed`` is invariant
    false and is not user-settable. Exact-product workflows use
    :class:`ExactProductContext` instead of this type.
    """

    rank: int
    alibaba_candidate: CandidateT | None = None
    facebook_candidate: CandidateT | None = None
    mercadolibre_candidate: CandidateT | None = None
    identity_confirmed: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.rank, bool) or not isinstance(self.rank, int):
            raise TypeError("rank must be a one-based integer")
        if self.rank < 1:
            raise ValueError("rank must be a one-based integer")
        if self.identity_confirmed is not False:
            raise ValueError("identity_confirmed is invariant false")
        if (
            self.alibaba_candidate is None
            and self.facebook_candidate is None
            and self.mercadolibre_candidate is None
        ):
            raise ValueError("positional row requires at least one candidate")


@dataclass(frozen=True, slots=True)
class ExactProductContext:
    """Exact-product association. Never derived from position or native listing IDs."""

    product_id: str

    def __post_init__(self) -> None:
        product_id = _nonempty_id(self.product_id)
        if not product_id:
            raise ValueError("exact product context requires a non-empty product id")
        object.__setattr__(self, "product_id", product_id)


def exact_product_context(
    *,
    facebook_association_id: object = "",
    ml_association_id: object = "",
    context_id: object = "",
) -> ExactProductContext | None:
    """Return exact context only when non-empty association/context IDs agree.

    Native marketplace listing IDs occupy independent namespaces and must not be
    supplied here as a substitute for explicit association IDs.
    """

    facebook_id = _nonempty_id(facebook_association_id)
    ml_id = _nonempty_id(ml_association_id)
    selected_id = _nonempty_id(context_id)
    if not facebook_id or not ml_id or not selected_id:
        return None
    if facebook_id == ml_id == selected_id:
        return ExactProductContext(product_id=selected_id)
    return None


def native_listing_ids_establish_cross_market_identity(
    left_native_id: object,
    right_native_id: object,
) -> bool:
    """Native listing-ID string equality never establishes cross-market identity."""

    del left_native_id, right_native_id
    return False


def positional_row_authorizes_exact_workflows(
    row: SearchPositionComparisonRow[Any],
) -> bool:
    """Position, rank, and positional alignment never authorize exact workflows."""

    del row
    return False


@dataclass(frozen=True, slots=True)
class GenericSessionProviderSnapshot[CandidateT]:
    """Generation-owned provider payload for generic Búsquedas and export."""

    generation: int
    status: str
    rows: tuple[CandidateT, ...]
    summary: Mapping[str, str]
    error: str
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "summary", MappingProxyType(dict(self.summary)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


def empty_generic_session_provider_snapshot[CandidateT]() -> GenericSessionProviderSnapshot[
    CandidateT
]:
    return GenericSessionProviderSnapshot(
        generation=GENERIC_SESSION_UNSET_GENERATION,
        status="",
        rows=(),
        summary={},
        error="",
        metadata={},
    )


def owned_generic_session_provider[CandidateT](
    *,
    stored: GenericSessionProviderSnapshot[CandidateT],
    active_generation: int,
    live: GenericSessionProviderSnapshot[CandidateT],
) -> GenericSessionProviderSnapshot[CandidateT]:
    """Prefer the generation-owned snapshot over later specialized live copies."""

    if (
        stored.generation != GENERIC_SESSION_UNSET_GENERATION
        and stored.generation == active_generation
    ):
        return stored
    return live


def generic_session_owned_provider_view[CandidateT](
    *,
    stored_rows: Sequence[CandidateT],
    stored_status: str,
    stored_generation: int,
    active_generation: int,
    live_rows: Sequence[CandidateT],
    live_status: str,
) -> GenericSessionProviderSnapshot[CandidateT]:
    """Row/status adapter around the generation-owned provider snapshot."""

    return owned_generic_session_provider(
        stored=GenericSessionProviderSnapshot(
            generation=stored_generation,
            status=stored_status,
            rows=tuple(stored_rows),
            summary={},
            error="",
            metadata={},
        ),
        active_generation=active_generation,
        live=GenericSessionProviderSnapshot(
            generation=GENERIC_SESSION_UNSET_GENERATION,
            status=live_status,
            rows=tuple(live_rows),
            summary={},
            error="",
            metadata={},
        ),
    )


def freeze_canonical_prefix[CandidateT](
    ordered_usable_pool: Sequence[CandidateT],
    display_limit: int,
) -> tuple[CandidateT, ...]:
    if isinstance(display_limit, bool) or not isinstance(display_limit, int):
        raise TypeError("display_limit must be an integer")
    if display_limit < 1:
        raise ValueError("display_limit must be positive")
    return tuple(ordered_usable_pool)[:display_limit]


def displayed_listing_total(snapshot: SearchSessionSnapshot) -> int:
    """Sum of canonical displayed listings, not positional row count."""

    return sum(result.metrics.displayed for result in snapshot.provider_results)


def build_search_position_comparison_rows[CandidateT](
    *,
    alibaba_candidates: Sequence[CandidateT] = (),
    facebook_candidates: Sequence[CandidateT] = (),
    mercadolibre_candidates: Sequence[CandidateT] = (),
) -> tuple[SearchPositionComparisonRow[CandidateT], ...]:
    """Zip frozen canonical prefixes by one-based position. Never match identity."""

    alibaba = tuple(alibaba_candidates)
    facebook = tuple(facebook_candidates)
    mercadolibre = tuple(mercadolibre_candidates)
    row_count = max(len(alibaba), len(facebook), len(mercadolibre), 0)
    if row_count == 0:
        return ()
    return tuple(
        SearchPositionComparisonRow(
            rank=index + 1,
            alibaba_candidate=alibaba[index] if index < len(alibaba) else None,
            facebook_candidate=facebook[index] if index < len(facebook) else None,
            mercadolibre_candidate=mercadolibre[index] if index < len(mercadolibre) else None,
        )
        for index in range(row_count)
    )


def positional_rows_from_snapshot(
    snapshot: SearchSessionSnapshot,
) -> tuple[SearchPositionComparisonRow[Any], ...]:
    def canonical(provider: str) -> tuple[Any, ...]:
        result = snapshot.result_for(provider)
        if result is None:
            return ()
        return result.canonical_session_results

    return build_search_position_comparison_rows(
        alibaba_candidates=canonical("alibaba"),
        facebook_candidates=canonical("facebook"),
        mercadolibre_candidates=canonical("mercadolibre"),
    )


__all__ = [
    "GENERIC_SESSION_UNSET_GENERATION",
    "MAX_DISPLAY_LIMIT",
    "SUPPORTED_DISPLAY_LIMITS",
    "AcquisitionBatch",
    "AcquisitionBudgetPolicy",
    "BoundedAcquisitionPlan",
    "CoverageStatus",
    "ExactProductContext",
    "GenericSessionProviderSnapshot",
    "InternalAcquisitionStep",
    "ProviderBudgetRule",
    "ProviderRunResult",
    "ProviderStatus",
    "SearchIntent",
    "SearchPositionComparisonRow",
    "SearchSessionSnapshot",
    "build_search_position_comparison_rows",
    "displayed_listing_total",
    "exact_product_context",
    "empty_generic_session_provider_snapshot",
    "execute_bounded_provider_search",
    "extend_ordered_usable_pool",
    "freeze_canonical_prefix",
    "generic_session_owned_provider_view",
    "owned_generic_session_provider",
    "native_listing_ids_establish_cross_market_identity",
    "ordered_usable_pool_from_batches",
    "positional_row_authorizes_exact_workflows",
    "positional_rows_from_snapshot",
]
