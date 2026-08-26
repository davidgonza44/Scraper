# Implementation tasks: Multi-market search semantics

> Do not execute these tasks while proposing this change. Implement this one OpenSpec change through staged implementation PRs rather than one enormous PR. Every PR must remain compatible with current `main`, include its own offline regression tests, and make zero live marketplace, DeepL, or MiniMax calls.

## Implementation PR A — Search intent, snapshot, acquisition, metrics, and status

- [ ] A.1 Introduce `SearchIntent`/equivalent with canonical `original_user_query`, selected providers, provider-local market/geographic scopes, generation, and a validated positive configurable `display_limit` supporting values such as 10; label the control **Máximo por plataforma**.
- [ ] A.2 Introduce explicit aggregate `acquisition_limit` and a centralized deterministic scaling strategy by provider, display limit, scope, and hard caps. Support display 10, document bounded internal-acquisition cost/termination, and prohibit Alibaba 500 as a routine pool.
- [ ] A.3 Define the pure pipeline: acquired → mapped/policy-evaluated → ordered usable pool → frozen canonical session prefix → presentation projections. Verify `usable` counts the pool while `displayed` and canonical membership count only its `display_limit` prefix.
- [ ] A.4 Evolve/consolidate existing `ProviderAcquisitionMetrics` and provider-specific acquisition metrics into one `ProviderRunMetrics` contract with aggregate internal-acquisition requested/fetched values, documented deduplication boundaries, and optional unknown-safe mapped/rejected values; do not maintain parallel sources of truth or impose arithmetic identities.
- [ ] A.5 Define one logical generic **Búsquedas** operation per selected provider per generation. Permit deterministic bounded provider-internal Actor/API acquisitions for pagination, partitioning, or geographic coverage; prevent an orchestrator-started second logical operation for refill. Preserve unrelated workflow semantics.
- [ ] A.6 Derive `SUCCESS`, `EMPTY`, and `ERROR` from execution and ordered usable-pool outcome. Treat selected-but-unconfigured providers as sanitized `ERROR`, never `EMPTY`.
- [ ] A.7 Keep deterministic rules in small pure application/GUI modules where practical; use `TrackerState` for orchestration, generation checks, and serialization rather than as a new domain/service layer.
- [ ] A.8 Add offline tests for display 1 with an invalid first/later valid candidate; display 3 with only 2 usable; single-market parity; display 10 and provider caps; missing configuration; no second logical refill operation; bounded multi-acquisition scope coverage; and acquisition 10 / usable 8 / canonical display 3.

## Implementation PR B — Positional comparison and exact-identity isolation

- [ ] B.1 Introduce `SearchPositionComparisonRow` with one-based rank, optional provider candidates, and immutable `identity_confirmed = false`; keep it structurally separate from exact-product contexts.
- [ ] B.2 Freeze provider ordering when `ProviderRunResult` commits to the current-generation snapshot; build generic rows only from frozen canonical prefixes, with maximum displayed row count, empty cells, and no duplicate/fill behavior.
- [ ] B.3 Ensure presentation sorting/filtering/ranking presets cannot change generic `Resultado #N`, totals, export membership, status, or snapshot; specialized views may independently project the frozen data.
- [ ] B.4 Add concise non-identity disclosure, preserve provider-specific ordering, and isolate Alibaba opportunity to Alibaba candidates without a global score.
- [ ] B.5 Audit exact/provenance workflows so position cannot authorize landed cost, negotiation, profitability, tracking, refresh, history, persistence, or association; retain two non-empty exactly equal product IDs.
- [ ] B.6 Preserve marketplace-owned images and genuine provider-specific rating rules without cross-market copying.
- [ ] B.7 Add offline tests for uneven 3/2/1 rows, position-not-identity, landed-cost isolation, canonical result hidden by presentation filtering, total sum semantics, and presentation sorting that cannot change `Resultado #1`, and unrelated-looking first results retained without cross-market filtering.

## Implementation PR C — Provider instrumentation and compact diagnostics

- [ ] C.1 Instrument Alibaba's truthfully observable fetched/mapped/usable boundaries and distinguish fetched-zero, mapping loss, actual failure, and missing configuration.
- [ ] C.2 Preserve Facebook priced-only policy and instrument truthful optional Free/Gratis, invalid price, missing ID, duplicate ID, location, title, malformed URL, and other measurable rejection reasons.
- [ ] C.3 Add Mercado Libre safe mapper counters for missing ID/title, missing Venezuela evidence, explicit foreign evidence, and successful mapping where observable without weakening MLV provenance.
- [ ] C.4 Add aggregate-only schema-drift observability and verify raw payloads, actor JSON, credentials, cookies, tokens, stack traces, and sensitive parameters are neither persisted nor rendered.
- [ ] C.5 Implement compact **Ver detalles** with the seven pipeline metrics, **No disponible** for unknowns, sanitized provider-not-configured copy, and mapping-loss copy distinct from zero fetched records.
- [ ] C.6 Add offline tests for Facebook mixed rejection pool, later valid MLV record, Alibaba fetched zero, fetched-positive/mapped-zero, sanitized configuration error, and relevant EMPTY/ERROR details.

## Implementation PR D — Query routing and configurable Venezuela scope

- [ ] D.1 Add canonical `original_user_query`, `provider_query`, `provider_query_origin`, provider-local market/geographic scope, and generation provenance to session/provider contracts.
- [ ] D.2 Route Alibaba to the original query or an independently derived safe international query; never reuse the Venezuela-localized query silently.
- [ ] D.3 Reuse existing query-generation/translation infrastructure with no language-detection AI or second subsystem, at most one shared Venezuela-localized generation, the deterministic outcome table in `design.md`, and no translation loop.
- [ ] D.4 Add offline translator fakes for no-translation-needed, unavailable, timeout/failure, empty/invalid, technical-token validation failure, output-identical-to-original, and successful shared Venezuela translation; prove DeepL call count is zero.
- [ ] D.5 Implement **Toda Venezuela** as the default provider scope with truthful Venezuela evidence. Review fixtures and record supported narrower scopes/aliases before implementing them; use exact normalized/context-qualified membership and reject fuzzy matches, ambiguous tokens, foreign evidence, and insufficient evidence.
- [ ] D.6 Add query/market/generation provenance tests for default Toda Venezuela, outside-Caracas Venezuelan results, supported city scope, foreign evidence, ambiguity, normalization, and missing evidence.

## Implementation PR E — Currency, export, lifecycle, and browser compatibility gate

- [ ] E.1 Remove Alibaba unknown-currency-as-USD fallbacks, retain visible published prices when allowed, and explain unconfirmed currency/unavailable USD statistics. Regression-test no implicit FX and `$` not proving USD.
- [ ] E.2 Export exactly one row per real frozen canonical session result, never extra usable acquisition-buffer candidates or merged positional identities. Add safe query/market/generation and truthfully known metric columns.
- [ ] E.3 Preserve and regression-test CSV formula-injection protection and UTF-8 BOM.
- [ ] E.4 Ensure **Nueva búsqueda** clears results, diagnostics, provider query/market provenance, and export state while retaining tracking; reject stale responses before they can mutate ordering, provenance, totals, or export membership.
- [ ] E.5 At 1440x900 with network-blocked offline fixtures, verify: all providers one result; uneven 3/2/1; display 10 with unrelated-looking candidates retained positionally; Mercado Libre EMPTY with details; unknown Alibaba currency; all EMPTY; partial error; **Nueva búsqueda**; CSV; marketplace-specific ratings/images; and non-identity disclosure.
- [ ] E.6 Run the complete offline format, lint, type-check, unit/integration, and Playwright suites. Record marketplace, DeepL, and MiniMax live calls as zero.
- [ ] E.7 Run the final compatibility gate for provider adapters, exact-product workflows, Alibaba tracking, landed cost, negotiation, profitability, Facebook H0019, generic priced-only behavior, MLV evidence, monetary provenance, generation guard, CSV safety, and Reflex-native frontend.
- [ ] E.8 Confirm no React/Next/Vite migration, dashboard redesign, fake data, global cross-market score, fuzzy/image identity, an orchestrator-started second logical refill operation, or unbounded/deep pagination was introduced.
