# Implementation tasks: Multi-market search semantics

> Do not execute these tasks while proposing this change. All provider and browser acceptance tests use offline fixtures; implementation makes zero live provider, DeepL, or MiniMax calls.

## Phase 1 — Search semantics core

- [ ] 1.1 Introduce `SearchIntent`/equivalent with `original_user_query`, selected providers, generation, and validated `display_limit` values 1/3/5; update the UI contract to **Máximo por plataforma**.
- [ ] 1.2 Introduce explicit `acquisition_limit` and one centralized provider-capped policy: Alibaba/ML 5/10/15 and Facebook 5/5/5. Add contract tests, cost comments/docs, and prohibit Alibaba 500 as a routine pool.
- [ ] 1.3 Add optional/unknown-safe `ProviderRunMetrics` fields with the specified definitions and serialization rules.
- [ ] 1.4 Refactor orchestration to execute each selected provider at most once, consume later candidates from that original bounded pool, and perform zero automatic retries in multi- and single-market modes.
- [ ] 1.5 Derive `SUCCESS`, `EMPTY`, and `ERROR` solely from actual execution outcome and canonical usable count; add status matrix tests.
- [ ] 1.6 Add offline acceptance tests A, B, P, and T, including exact provider execution counters.

## Phase 2 — Provider instrumentation and safe diagnostics

- [ ] 2.1 Instrument Alibaba's truthfully observable fetched/mapped/usable stages and distinguish fetched-zero, mapping-loss, and actual execution failure.
- [ ] 2.2 Preserve Facebook priced-only policy and instrument Free/Gratis, invalid price, missing ID, duplicate ID, location, title, malformed URL, and other measurable rejection reasons.
- [ ] 2.3 Add Mercado Libre safe mapper counters for missing ID/title, missing Venezuela evidence, explicit foreign evidence, and successful mapping where observable.
- [ ] 2.4 Add aggregate-only schema-drift diagnostics; verify raw payloads, actor JSON, credentials, cookies, tokens, and sensitive parameters are neither persisted nor rendered.
- [ ] 2.5 Implement compact **Ver detalles** metric rendering with **No disponible** for unknowns and mapping-loss copy distinct from zero fetched records.
- [ ] 2.6 Add offline acceptance tests C, D, E, F, and S.

## Phase 3 — Generic positional comparison

- [ ] 3.1 Introduce `SearchPositionComparisonRow` with one-based rank, optional provider candidates, and immutable `identity_confirmed = false`; keep it separate from exact-product contexts.
- [ ] 3.2 Build rows from each provider's displayed canonical order, with row count equal to the maximum provider displayed count and no duplicate/fill behavior.
- [ ] 3.3 Add the concise non-identity disclosure and ensure empty marketplace cells render clearly.
- [ ] 3.4 Change generic summary cards and **Total de resultados** to canonical session displayed data, independent of relevance/visible-row filters.
- [ ] 3.5 Preserve provider-specific ordering and isolate Alibaba opportunity to Alibaba candidates; do not introduce a global score.
- [ ] 3.6 Audit every exact/provenance-dependent workflow so positional data cannot authorize landed cost, negotiation, profitability, tracking, refresh, history, persistence, or association; retain non-empty exact-ID equality.
- [ ] 3.7 Add offline acceptance tests G, H, I, K, and L.

## Phase 4 — Marketplace query routing

- [ ] 4.1 Add `original_user_query`, `provider_query`, and enum `provider_query_origin` to session/provider contracts.
- [ ] 4.2 Route Alibaba's original/international query independently from a Venezuela-market query for Facebook and Mercado Libre.
- [ ] 4.3 Reuse existing query-generation/translation infrastructure with deterministic/original-first behavior, at most one shared Venezuela translation, original-query fallback, and no translation loops.
- [ ] 4.4 Add injected offline translator fakes and network guards proving automated tests invoke DeepL zero times.
- [ ] 4.5 Add acceptance test O for original and provider-specific query provenance.

## Phase 5 — Facebook Caracas location scope

- [ ] 5.1 Review existing offline fixtures against candidate Caracas metropolitan forms and record the final explicit normalized allowlist and ambiguity decisions in `design.md` before implementation.
- [ ] 5.2 Implement exact deterministic normalized membership with context-qualified ambiguous municipalities; do not accept all Venezuela or fuzzy locations and preserve missing-location behavior unless documented evidence approves a change.
- [ ] 5.3 Add positive, negative, ambiguous-token, accent/case normalization, missing-location, and non-Caracas Venezuela tests; document false-positive and false-negative risks.

## Phase 6 — Money and summary UX

- [ ] 6.1 Remove any Alibaba display fallback that labels unknown currency as USD while allowing a listing with an unconfirmed published price to remain visible.
- [ ] 6.2 Add compact explanations for published price with unconfirmed source currency and unavailable USD statistics.
- [ ] 6.3 Add regression tests for no implicit FX, `$` not implying USD, compatible-currency-only aggregates, and existing Facebook/ML monetary provenance.
- [ ] 6.4 Add offline acceptance test J.

## Phase 7 — Export, stale-session, and single-market integration

- [ ] 7.1 Export one row per canonical real marketplace listing for the current session, independent of presentation filters and positional row grouping.
- [ ] 7.2 Add query provenance and truthfully known provider metric columns; represent unknowns without invented zero.
- [ ] 7.3 Preserve and regression-test CSV injection protection and UTF-8 BOM.
- [ ] 7.4 Ensure **Nueva búsqueda** clears results, diagnostics, provider queries, and export state while retaining persistent tracking.
- [ ] 7.5 Extend the generation guard to all new session state and reject late previous-generation responses.
- [ ] 7.6 Verify single-market mode uses the same display/acquisition, status, metrics, diagnostics, and zero-retry contracts.
- [ ] 7.7 Add offline acceptance tests Q and R.

## Phase 8 — Browser acceptance and regression suite

- [ ] 8.1 Build offline browser fixtures; enforce network blocking for providers, DeepL, and MiniMax.
- [ ] 8.2 At 1440x900, verify all three providers with one result render `Resultado #1` and Alibaba | Facebook | Mercado Libre.
- [ ] 8.3 At 1440x900, verify uneven 3/2/1 positional results and empty cells without duplication.
- [ ] 8.4 Verify Mercado Libre `EMPTY` with expanded **Ver detalles**, including unknown-safe compact metrics.
- [ ] 8.5 Verify unknown Alibaba currency visibility, explanation, and unavailable USD aggregate.
- [ ] 8.6 Verify all-provider `EMPTY` and partial-provider-error session copy.
- [ ] 8.7 Verify **Nueva búsqueda** clears all transient session data and stale fixtures cannot repopulate it.
- [ ] 8.8 Verify CSV export row identity, canonical session inclusion, provenance fields, BOM, and injection safety.
- [ ] 8.9 Verify ratings and images remain marketplace-specific and are not copied across positional cells.
- [ ] 8.10 Verify disclosure copy and absence of duplicate/misleading exact-product association wording.
- [ ] 8.11 Run the repository's complete offline format, lint, type-check, unit/integration, and Playwright suites; record that external provider calls, DeepL calls, and MiniMax calls equal zero.

## Final compatibility gate

- [ ] 9.1 Regression-test current provider adapter contracts, exact-product workflows, Alibaba tracking, landed cost, negotiation, profitability, Facebook H0019, generic Facebook priced-only behavior, marketplace images, genuine ratings, monetary provenance, CSV safety, generation guard, and Reflex-native frontend.
- [ ] 9.2 Confirm no React/Next/Vite migration, dashboard-shell redesign, fake data, global cross-market score, fuzzy/image identity, provider retries, or deep pagination was introduced.
