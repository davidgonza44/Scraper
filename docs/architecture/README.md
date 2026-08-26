# BERA Architecture Diagrams

## Multi-market generic search

- `multi-market-search-core.puml`
  Static relationships for the generic multi-market search session core.
  It distinguishes the implemented PR A application core, implemented PR B
  positional comparison, existing `TrackerState` / provider-operation
  boundaries, and deferred integration edges that are not wired yet.
- `multi-market-search-sequence.puml`
  Runtime sequence for one logical provider search composed from bounded
  existing provider operations. That sequence is the implemented PR A
  core (tests today; future GUI wiring). It is not the current
  `TrackerState` GUI search path.

## Implemented now versus deferred wiring

Implementation PR A delivers the search-session contracts in
`src/bera_price_tracker/application/search_session.py`. Implementation PR B
adds `SearchPositionComparisonRow`, exact-product isolation, and generic
Búsquedas positional GUI rows. The current GUI still uses the existing
`TrackerState` search path. `TrackerState` does not yet create
`SearchIntent`, invoke `AcquisitionBudgetPolicy`, call
`execute_bounded_provider_search()`, or commit `SearchSessionSnapshot`.
It serializes positional rows from canonical GUI result lists.

Dashed diagram edges labeled deferred are intended integration, not
current runtime behavior. Implementation PR B positional comparison is
implemented in the application core and generic Búsquedas GUI. PRs C–E
remain unimplemented.

## Source of truth

1. OpenSpec
2. repository implementation/contracts
3. architecture docs
4. AI schemas/golden fixtures
5. `context.md` / implementation convenience

The diagrams sit at architecture docs. They are explanatory and must be
updated when architecture changes.

The active OpenSpec change `multi-market-search-semantics` is planned as
staged implementation PRs A through E. Implementation PRs A and B are currently
implemented on main. PRs C–E remain unimplemented. A diagram must never be
used to justify behavior that contradicts OpenSpec or existing provider
contracts, and must not document unimplemented wiring as current architecture.
