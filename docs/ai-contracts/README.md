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
- How `display_limit`, `acquisition_budget`, and `acquisition_requested` differ
- What `SUCCESS` / `EMPTY` / `ERROR` and `COMPLETE` / `PARTIAL` / unavailable
  coverage mean
- What a stale generation is
- How generic positional comparison differs from exact-product identity
- Which behaviors belong to later OpenSpec PRs and are not implemented yet

## Source of truth

1. Merged / active OpenSpec specifications
2. Existing repository contracts and architecture
3. Architecture documentation
4. Machine-readable schemas and golden fixtures
5. Implementation convenience

OpenSpec remains authoritative. These JSON schemas are canonical fixture JSON
representations of public contracts. They are not `dataclasses.asdict()` dumps
and must not be treated as a second serialized shape when the Python contract
uses tuples or other in-memory types.

If a fixture disagrees with OpenSpec, fix the fixture.
Never change OpenSpec merely to make a fixture or implementation pass.

**Never modify a golden fixture solely to make a failing implementation pass.
First determine whether the implementation or the specification changed.**

## Layout

- `schemas/ai-contracts/` — JSON Schema Draft 2020-12 documents
- `tests/fixtures/ai-contracts/` — compact golden examples
- `tests/unit/test_ai_contracts.py` — pack validation and selected runtime checks

## How agents should use this directory

1. Read this README and `AGENTS.md`.
2. Read the active OpenSpec change
   `openspec/changes/multi-market-search-semantics/`.
3. Read architecture docs under `docs/architecture/`.
4. Inspect the relevant schema before inventing fields.
5. Read golden fixtures in the matching concern folder.
6. Then read the existing implementation and tests.
7. Do not implement staged OpenSpec work early.

`implementation_stage` on a fixture is `A`, `B`, `C`, `D`, or `E`. Stage `A`
is the search-session core and is implemented. `runtime_check: search_session_core`
executes `bera_price_tracker.application.search_session`; a missing import fails.
Later stages are semantic fixtures, not proof that the corresponding PR is
implemented.

## How maintainers update this pack

When a specification legitimately changes:

1. Update OpenSpec first.
2. Update schemas only to match the new contract.
3. Update or add golden fixtures to match OpenSpec, not the old implementation.
4. Keep fixture `source_refs` pointing at repository-relative specification
   and architecture paths. Do not replace OpenSpec refs with diagram refs.
5. Run the offline AI-contract tests and the repository quality gates.

Do not add production Python that duplicates `AcquisitionBudgetPolicy`,
`ProviderRunResult` validation, provider mappers, geographic routing, or
deduplication. Those remain in application modules.

## Safety

This pack contains no secrets, credentials, cookies, raw authenticated
marketplace payloads, or personal data. Examples are synthetic and minimal.
