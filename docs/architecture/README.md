# BERA Architecture Diagrams

## Multi-market generic search

- `multi-market-search-core.puml`
  Static component/class relationships for the generic multi-market search
  session core and staged boundaries.
- `multi-market-search-sequence.puml`
  Runtime sequence for one logical provider search composed from bounded
  existing provider operations.

## Source of truth

Architecture precedence:

1. OpenSpec specifications
2. repository implementation/contracts
3. these diagrams

The diagrams are explanatory and must be updated when architecture changes.

The active OpenSpec change `multi-market-search-semantics` defines staged
implementation PRs A through E. A diagram must never be used to justify
behavior that contradicts OpenSpec or existing provider contracts.
