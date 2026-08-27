# BERA AI contract pack

Machine-readable search-semantics contracts for Cursor, Codex, and other
agents. This pack exists so future changes to generic multi-market search make
fewer architectural and semantic mistakes.

It is documentation, schemas, and golden examples. It is not an application
layer and not a product feature.

## Purpose

Before changing generic search behavior, an agent should be able to answer:

- What is a valid `SearchIntent`, `ProviderRunMetrics`, and `ProviderRunResult`?
- What makes Alibaba, Facebook, and Mercado Libre candidates usable?
- Which fields are optional, and what must never be fabricated?
- What is stable identity, and what is not identity?
- How `display_limit` differs from acquisition work
- What `SUCCESS` / `EMPTY` / `ERROR` and `COMPLETE` / `PARTIAL` / unavailable
  coverage mean
- What a stale generation is
- How generic positional comparison differs from exact-product identity
- Which behaviors belong to later OpenSpec PRs and are not implemented yet

`display_limit` is the separate visible maximum. The acquisition-volume
concepts are `acquisition_budget` and `acquisition_requested`.

## Source of truth

1. OpenSpec
2. repository implementation/contracts
3. architecture docs
4. AI schemas/golden fixtures
5. `context.md` / implementation convenience

This precedence is independent of reading order. OpenSpec remains
authoritative. These JSON schemas are canonical fixture JSON representations
of public contracts. They are not `dataclasses.asdict()` dumps and must not be
treated as a second serialized shape when the Python contract uses tuples or
other in-memory types.

Structural PR A schemas (`SearchIntent`, `BoundedAcquisitionPlan`,
`ProviderRunResult`) are provider-neutral: provider identifiers are non-blank
strings. Current BERA marketplace vocabulary (`alibaba` / `facebook` /
`mercadolibre`) is constrained on `GoldenSearchCase` and concrete marketplace
fixtures. Execution and `AcquisitionBudgetPolicy` decide whether a provider is
supported.

If a fixture disagrees with OpenSpec, fix the fixture.
Never change OpenSpec merely to make a fixture or implementation pass.

**Never modify a golden fixture solely to make a failing implementation pass.
First determine whether the implementation or the specification changed.**

## Layout

- `schemas/ai-contracts/` — JSON Schema Draft 2020-12 documents
- `tests/fixtures/ai-contracts/` — compact golden examples
- `tests/unit/test_ai_contracts.py` — pack validation and runtime-check dispatch

## How agents should use this directory

1. Read `context.md` for orientation only; it is not authoritative.
2. Read the active OpenSpec change
   `openspec/changes/multi-market-search-semantics/`.
3. Read repository implementation/contracts.
4. Read architecture docs under `docs/architecture/`.
5. Inspect the relevant schema and golden fixtures.
6. Then read the existing tests and code.
7. Do not implement staged OpenSpec work early.

`implementation_stage` on a fixture is `A`, `B`, `C`, `D`, or `E`. Stages `A`
and `B` are implemented. A non-null `runtime_check` selects exactly one handler
in `tests/unit/test_ai_contracts.py`. Later stages are semantic fixtures, not
proof that the corresponding PR is implemented.

## How maintainers update this pack

When a specification legitimately changes:

1. Update OpenSpec first.
2. Update schemas only to match the new contract.
3. Update or add golden fixtures to match OpenSpec, not the old implementation.
4. Keep fixture `source_refs` pointing at repository-relative specification
   and architecture paths. Do not replace OpenSpec refs with diagram refs.
5. Update the explicit golden-ID and `search_session_core` inventories in
   `tests/unit/test_ai_contracts.py` when adding, removing, or reclassifying a
   case.
6. Run the offline AI-contract tests and the repository quality gates.

Do not add production Python that duplicates `AcquisitionBudgetPolicy`,
`ProviderRunResult` validation, provider mappers, geographic routing, or
deduplication. Those remain in application modules. Test-only JSON projections
of PR A objects are allowed in the contract tests.

## Safety

This pack contains no secrets, credentials, cookies, raw authenticated
marketplace payloads, or personal data. Examples are synthetic and minimal.
