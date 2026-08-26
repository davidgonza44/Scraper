# BERA Architecture Diagrams

## Multi-market generic search

- `multi-market-search-core.puml`
  Static relationships for the generic multi-market search session core.
  It distinguishes three layers: the PR A application core that is
  implemented now, existing `TrackerState` / provider-operation
  boundaries, and deferred integration edges that are not wired yet.
- `multi-market-search-sequence.puml`
  Runtime sequence for one logical provider search composed from bounded
  existing provider operations. That sequence is the implemented PR A
  core (tests today; future GUI wiring). It is not the current
  `TrackerState` GUI search path.

## Implemented now versus deferred wiring

Implementation PR A delivers `src/bera_price_tracker/application/search_session.py`
and its offline tests. The current GUI still uses the existing
`TrackerState` search path. `TrackerState` does not yet create
`SearchIntent`, invoke `AcquisitionBudgetPolicy`, call
`execute_bounded_provider_search()`, or commit `SearchSessionSnapshot`.

Dashed diagram edges labeled deferred are intended integration, not
current runtime behavior. PRs B–E remain unimplemented.

## Source of truth

Architecture precedence:

1. OpenSpec specifications
2. repository implementation/contracts
3. these diagrams

The diagrams are explanatory and must be updated when architecture changes.

The active OpenSpec change `multi-market-search-semantics` defines staged
implementation PRs A through E. A diagram must never be used to justify
behavior that contradicts OpenSpec or existing provider contracts, and
must not document unimplemented wiring as current architecture.
