# Implementation tasks: Multi-market search semantics

> Do not execute these tasks while proposing this change. Implement this one OpenSpec change through staged implementation PRs rather than one enormous PR. Every PR must remain compatible with current `main`, include its own offline regression tests, and make zero live marketplace, DeepL, or MiniMax calls.

## Implementation PR A — Search intent, snapshot, acquisition, metrics, and status

- [ ] A.1 Introduce provider-neutral contracts with `requested_geographic_scope`, optional `effective_geographic_scope`, optional `coverage_status`, provider status, generation, and bounded `display_limit`.
- [ ] A.2 Implement `AcquisitionBudgetPolicy` returning finite `acquisition_budget`; separately measure actual `acquisition_requested`. Keep these as the only acquisition-volume concepts.
- [ ] A.3 Define the pure pipeline: acquired → mapped/policy-evaluated → ordered usable pool → frozen canonical session prefix → presentation projections. Verify `usable` counts the pool while `displayed` and canonical membership count only its `display_limit` prefix.
- [ ] A.4 Evolve/consolidate existing `ProviderAcquisitionMetrics` and provider-specific acquisition metrics into one `ProviderRunMetrics` contract with aggregate internal-acquisition requested/fetched values, documented deduplication boundaries, and optional unknown-safe mapped/rejected values; do not maintain parallel sources of truth or impose arithmetic identities.
- [ ] A.5 Define one logical generic operation that composes existing bounded single-acquisition provider operations; preserve Facebook's existing one-execute/one-Actor-run low-level contract and unrelated workflow semantics.
- [ ] A.6 Derive provider status independently from coverage; ignore non-applicable coverage, test Alibaba-only normal completion, partial incidence, complete empty copy, and `ERROR` with unavailable coverage.
- [ ] A.7 Keep deterministic rules in small pure application/GUI modules where practical; use `TrackerState` for orchestration, generation checks, and serialization rather than as a new domain/service layer.
- [ ] A.8 Add provider-neutral fake multi-acquisition tests for COMPLETE/PARTIAL coverage, partial success/empty incidence copy, exhausted budgets, actual requested work, safe/identity-less deduplication, and acquisition 10 / usable 8 / display 3.

## Implementation PR B — Positional comparison and exact-identity isolation

- [ ] B.1 Introduce `SearchPositionComparisonRow` with one-based rank, optional provider candidates, and immutable `identity_confirmed = false`; keep it structurally separate from exact-product contexts.
- [ ] B.2 Preserve single-acquisition result order; deduplicate only on truthful stable identity and retain identity-less candidates. Only multi-acquisition searches without native global order use documented deterministic BERA aggregation. Freeze the result.
- [ ] B.3 Ensure presentation sorting/filtering/ranking presets cannot change generic `Resultado #N`, totals, export membership, status, or snapshot; specialized views may independently project the frozen data.
- [ ] B.4 Keep Alibaba opportunity/ranking/relevance, reputation, and price sorting as annotations or specialized projections that cannot reorder frozen generic results; add concise non-identity disclosure and no global score.
- [ ] B.5 Preserve the existing exact workflow invariant for non-empty agreeing association/context IDs; prove native marketplace ID string equality and positional alignment cannot create association or authorize provenance workflows.
- [ ] B.6 Render truthful provider-owned image, title, price/currency, URL, seller/supplier, genuine rating/reviews, reputation/service metadata, Alibaba MOQ, Mercado Libre condition, and other available fields; blank missing optional fields and fabricate nothing.
- [ ] B.7 Add offline tests for provider-result order, deterministic partition aggregation, immutability under Alibaba/UI rankings, exact association IDs versus native listing IDs, available cell fields, missing optional fields, and no fabricated Facebook seller/rating.

## Implementation PR C — Provider instrumentation and compact diagnostics

- [ ] C.1 Instrument Alibaba's truthfully observable fetched/mapped/usable boundaries and distinguish fetched-zero, mapping loss, actual failure, and missing configuration.
- [ ] C.2 Preserve Facebook priced-only policy and instrument truthful optional Free/Gratis, invalid price, missing ID, duplicate ID, location, title, malformed URL, and other measurable rejection reasons.
- [ ] C.3 Add Mercado Libre safe mapper counters for missing ID/title, missing Venezuela evidence, explicit foreign evidence, and successful mapping where observable without weakening MLV provenance.
- [ ] C.4 Add aggregate-only schema-drift observability and verify raw payloads, actor JSON, credentials, cookies, tokens, stack traces, and sensitive parameters are neither persisted nor rendered.
- [ ] C.5 Implement compact **Ver detalles** with actual-request metrics, **No disponible** for unknowns, sanitized provider-not-configured copy, and mapping-loss copy distinct from zero fetched records.
- [ ] C.6 Add offline tests for Facebook mixed rejection pool, later valid MLV record, Alibaba fetched zero, fetched-positive/mapped-zero, sanitized configuration error, and relevant EMPTY/ERROR details.

## Implementation PR D — Query routing and configurable Venezuela scope

- [ ] D.1 Route canonical query provenance plus requested scope into the provider-neutral contracts; generation-check every async translation/routing continuation before commit or downstream work.
- [ ] D.2 Route Alibaba to the original query or an independently derived safe international query; never reuse the Venezuela-localized query silently.
- [ ] D.3 Reuse existing query-generation/translation infrastructure with no language-detection AI or second subsystem, at most one shared Venezuela-localized generation, the deterministic outcome table in `design.md`, and no translation loop.
- [ ] D.4 Add offline translator fakes for no-translation-needed, unavailable, timeout/failure, empty/invalid, technical-token validation failure, output-identical-to-original, and successful shared Venezuela translation; prove DeepL call count is zero.
- [ ] D.5 Own the concrete Facebook Venezuela strategy: finite partition catalog, per-call composition, aliases, `requested_geographic_scope`, `effective_geographic_scope`, `coverage_status`, sanitized diagnostics, foreign rejection, and unchanged MLV evidence.
- [ ] D.6 Add Facebook-specific tests for genuine nationwide acquisition, all partitions `COMPLETE`, failed subset with useful `PARTIAL` results, partial zero results, scope provenance, missing location, foreign evidence, and narrower scopes.

## Implementation PR E — Currency, export, lifecycle, and browser compatibility gate

- [ ] E.1 Remove Alibaba unknown-currency-as-USD fallbacks, retain visible published prices when allowed, and explain unconfirmed currency/unavailable USD statistics. Regression-test no implicit FX and `$` not proving USD.
- [ ] E.2 Require stable query/scope/generation/display/budget/requested-work and provider metric columns on every CSV row; preserve blank/not-applicable values and wait for all providers to become terminal.
- [ ] E.3 Preserve and regression-test CSV formula-injection protection and UTF-8 BOM.
- [ ] E.4 Ensure **Nueva búsqueda** clears transient state; reject stale routing, translation, and provider continuations before they mutate provenance, launch downstream work, or change export membership.
- [ ] E.5 At 1440x900 with network-blocked offline fixtures, verify: all providers one result; uneven 3/2/1; display 10 with unrelated-looking candidates retained positionally; Mercado Libre EMPTY with details; unknown Alibaba currency; all EMPTY; partial error; **Nueva búsqueda**; CSV; marketplace-specific ratings/images; and non-identity disclosure.
- [ ] E.6 Run the complete offline format, lint, type-check, unit/integration, and Playwright suites. Record marketplace, DeepL, and MiniMax live calls as zero.
- [ ] E.7 Run the final compatibility gate for provider adapters, exact-product workflows, Alibaba tracking, landed cost, negotiation, profitability, Facebook H0019, generic priced-only behavior, MLV evidence, monetary provenance, generation guard, CSV safety, and Reflex-native frontend.
- [ ] E.8 Confirm no React/Next/Vite migration, dashboard redesign, fake data, global cross-market score, fuzzy/image identity, an orchestrator-started second logical refill operation, or unbounded/deep pagination was introduced.
