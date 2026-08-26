# Agent instructions

BERA is a Python 3.12 Ports & Adapters app with a Reflex-native GUI.
Do not migrate the frontend to React, Next.js, or Vite.

## Source of truth

1. Merged / active OpenSpec specifications
2. Existing repository contracts and architecture
3. Architecture documentation
4. AI contract schemas and golden fixtures
5. Implementation convenience

Golden fixtures are examples of the specification. They are not a competing
source of truth. If a fixture disagrees with OpenSpec, fix the fixture.
Never change OpenSpec merely to make a fixture or implementation pass.
Never modify a golden fixture solely to make a failing implementation pass.

## Before modifying generic search

Read these paths when they exist:

1. `openspec/changes/multi-market-search-semantics/**`
2. `docs/architecture/README.md`
3. `docs/architecture/*.puml`
4. `docs/ai-contracts/README.md`
5. `schemas/ai-contracts/**`
6. `tests/fixtures/ai-contracts/**`
7. Relevant existing implementation and tests

Staged OpenSpec work is PRs A through E. Do not implement later-stage work
early, and do not mark later-stage tasks complete.

## Permanent search rules

- Do not fabricate marketplace fields, prices, images, ratings, or identities.
- Do not infer exact product identity from title, image, price, rank, position,
  fuzzy similarity, or native listing-ID equality across marketplaces.
- Do not reject a generic provider candidate because another marketplace looks
  unrelated.
- Do not turn unknown metrics into zero. Unknown stays unknown / `null` /
  **No disponible**.
- `display_limit`, `acquisition_budget`, and `acquisition_requested` are the
  only acquisition-volume concepts. Do not treat `display_limit` as acquisition
  work, and do not invent `acquisition_limit`.
- Do not turn geographic `PARTIAL` into `COMPLETE`.
- Preserve provider-specific low-level contracts. Facebook's existing
  `execute()` remains one Actor run unless OpenSpec explicitly changes that.
- `TrackerState` orchestrates and serializes. Do not move budget policy,
  provider strategy, or identity rules into it.
