# Agent instructions

BERA is a Python 3.12 Ports & Adapters app with a Reflex-native GUI.
Do not migrate the frontend to React, Next.js, or Vite.

## Source of truth

1. OpenSpec
2. repository implementation/contracts
3. architecture docs
4. AI schemas/golden fixtures
5. `context.md` / implementation convenience

This precedence is independent of reading order. Golden fixtures are examples
of the specification. They are not a competing source of truth. If a fixture
disagrees with OpenSpec, fix the fixture. Never change OpenSpec merely to make
a fixture or implementation pass. Never modify a golden fixture solely to make
a failing implementation pass.

`context.md` is orientation only and is not authoritative.

## Before modifying generic search

Read in this order:

1. `context.md` — orientation only; not authoritative
2. active OpenSpec: `openspec/changes/multi-market-search-semantics/**`
3. repository implementation/contracts
4. architecture docs: `docs/architecture/README.md` and `docs/architecture/*.puml`
5. AI contracts/fixtures: `docs/ai-contracts/README.md`, `schemas/ai-contracts/**`,
   `tests/fixtures/ai-contracts/**`
6. relevant tests/code

The change is planned as staged implementation PRs A–E. Only Implementation
PR A is currently implemented on main. PRs B–E remain unimplemented. Do not
implement later-stage work early, and do not mark later-stage tasks complete.

## Permanent search rules

- Do not fabricate marketplace fields, prices, images, ratings, or identities.
- Do not infer exact product identity from title, image, price, rank, position,
  fuzzy similarity, or native listing-ID equality across marketplaces.
- Do not reject a generic provider candidate because another marketplace looks
  unrelated.
- Do not turn unknown metrics into zero. Unknown stays unknown / `null` /
  **No disponible**.
- `display_limit` is the separate visible maximum. The acquisition-volume
  concepts are `acquisition_budget` and `acquisition_requested`. Do not treat
  `display_limit` as acquisition work, and do not invent `acquisition_limit`.
- Do not turn geographic `PARTIAL` into `COMPLETE`.
- Preserve provider-specific low-level contracts. Facebook's existing
  `execute()` remains one Actor run unless OpenSpec explicitly changes that.
- `TrackerState` orchestrates and serializes. Do not move budget policy,
  provider strategy, or identity rules into it.
