# Implementation tasks: Multi-market search semantics

> Do not execute these tasks while proposing this change. Implement this one OpenSpec change through staged implementation PRs rather than one enormous PR. Every PR must remain compatible with current `main`, include its own offline regression tests, and make zero live marketplace, DeepL, or MiniMax calls.

## Implementation PR A — Search intent, snapshot, acquisition, metrics, and status

- [x] A.1 Introduce provider-neutral contracts with `requested_geographic_scope`, optional `effective_geographic_scope`, optional `coverage_status`, provider status, generation, and bounded `display_limit`.
- [x] A.2 Implement `AcquisitionBudgetPolicy` returning finite `acquisition_budget`; separately measure actual `acquisition_requested`. Keep these as the only acquisition-volume concepts.
- [x] A.3 Define the pure pipeline: acquired → mapped/policy-evaluated → ordered usable pool → frozen canonical session prefix → presentation projections. Verify `usable` counts the pool while `displayed` and canonical membership count only its `display_limit` prefix.
- [x] A.4 Evolve/consolidate existing `ProviderAcquisitionMetrics` and provider-specific acquisition metrics into one `ProviderRunMetrics` contract with aggregate internal-acquisition requested/fetched values, documented deduplication boundaries, and optional unknown-safe mapped/rejected values; do not maintain parallel sources of truth or impose arithmetic identities.
- [x] A.5 Define one logical generic operation that composes existing bounded single-acquisition provider operations; preserve Facebook's existing one-execute/one-Actor-run low-level contract and unrelated workflow semantics.
- [x] A.6 Derive provider status independently from coverage; ignore non-applicable coverage, test Alibaba-only normal completion, partial incidence, complete empty copy, and `ERROR` with unavailable coverage.
- [x] A.7 Keep deterministic rules in small pure application/GUI modules where practical; use `TrackerState` for orchestration, generation checks, and serialization rather than as a new domain/service layer.
- [x] A.8 Add provider-neutral fake multi-acquisition tests for COMPLETE/PARTIAL coverage, partial success/empty incidence copy, exhausted budgets, actual requested work, safe/identity-less deduplication, and acquisition 10 / usable 8 / display 3.

## Implementation PR B — Positional comparison and exact-identity isolation

- [x] B.1 Introduce `SearchPositionComparisonRow` with one-based rank, optional provider candidates, and immutable `identity_confirmed = false`; keep it structurally separate from exact-product contexts.
- [x] B.2 Preserve single-acquisition result order; deduplicate only on truthful stable identity and retain identity-less candidates. Only multi-acquisition searches without native global order use documented deterministic BERA aggregation. Freeze the result.
- [x] B.3 Ensure presentation sorting/filtering/ranking presets cannot change generic `Resultado #N`, totals, export membership, status, or snapshot; specialized views may independently project the frozen data.
- [x] B.4 Keep Alibaba opportunity/ranking/relevance, reputation, and price sorting as annotations or specialized projections that cannot reorder frozen generic results; add concise non-identity disclosure and no global score.
- [x] B.5 Preserve the existing exact workflow invariant for non-empty agreeing association/context IDs; prove native marketplace ID string equality and positional alignment cannot create association or authorize provenance workflows.
- [x] B.6 Render truthful provider-owned image, title, price/currency, URL, seller/supplier, genuine rating/reviews, reputation/service metadata, Alibaba MOQ, Mercado Libre condition, and other available fields; blank missing optional fields and fabricate nothing.
- [x] B.7 Add offline tests for provider-result order, deterministic partition aggregation, immutability under Alibaba/UI rankings, exact association IDs versus native listing IDs, available cell fields, missing optional fields, and no fabricated Facebook seller/rating.

## Maintenance PR after B — memo23 currency marker contract correction

This is a narrow provider-contract maintenance correction after Implementation PR B and before PRs C–E. It is not an early implementation of E.1.

- [x] M.1 Specify that for the configured Alibaba SEARCH Actor `memo23/alibaba-scraper`, the raw `price` marker `US $` / `US$` is authorized explicit USD evidence and is normalized internally to ISO `USD`.
- [x] M.2 Implement that actor- and field-specific normalization at the memo23 SEARCH provider mapping boundary without weakening statistics, FX, `priceMin`, `quantityPrices`, or other-Actor rules.
- [x] M.3 Add offline regressions for the observed memo23 `US $` ranges, plus bare `$` and bare `US` remaining unknown.

## Implementation PR C — Provider instrumentation and compact diagnostics

- [ ] C.1 Instrument Facebook/Mercado Libre truthfully observable fetched/mapped/usable boundaries as specified for those providers. Alibaba SEARCH production instrumentation is owned by Z4, not by a memo23-only C.1 implementation.
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

- [ ] E.1 Remove remaining Alibaba unknown-currency-as-USD fallbacks, retain visible published prices when allowed, and explain unconfirmed currency/unavailable USD statistics. Regression-test no implicit FX, that `$` and bare `US` do not prove USD, and that all other unconfirmed Alibaba currency stays out of USD statistics. Before Z4, preserve the authorized memo23 SEARCH raw `price` marker `US $` / `US$` → internal ISO `USD` contract. After Z4, E.1 MUST use the Zen currency contract and MUST NOT re-authorize memo23 SEARCH `US $` as the production SEARCH rule.
- [ ] E.2 Require stable query/scope/generation/display/budget/requested-work and provider metric columns on every CSV row; preserve blank/not-applicable values and wait for all providers to become terminal.
- [ ] E.3 Preserve and regression-test CSV formula-injection protection and UTF-8 BOM.
- [ ] E.4 Ensure **Nueva búsqueda** clears transient state; reject stale routing, translation, and provider continuations before they mutate provenance, launch downstream work, or change export membership.
- [ ] E.5 At 1440x900 with network-blocked offline fixtures, verify: all providers one result; uneven 3/2/1; display 10 with unrelated-looking candidates retained positionally; Mercado Libre EMPTY with details; unknown Alibaba currency; all EMPTY; partial error; **Nueva búsqueda**; CSV; marketplace-specific ratings/images; and non-identity disclosure.
- [ ] E.6 Run the complete offline format, lint, type-check, unit/integration, and Playwright suites. Record marketplace, DeepL, and MiniMax live calls as zero.
- [ ] E.7 Run the final compatibility gate for provider adapters, exact-product workflows, Alibaba tracking, landed cost, negotiation, profitability, Facebook H0019, generic priced-only behavior, MLV evidence, monetary provenance, generation guard, CSV safety, and Reflex-native frontend.
- [ ] E.8 Confirm no React/Next/Vite migration, dashboard redesign, fake data, global cross-market score, fuzzy/image identity, an orchestrator-started second logical refill operation, or unbounded/deep pagination was introduced.

## Implementation PR Z0 — OpenSpec only

Z0 is this revision. Do not implement production code, change `.env` / `.env.example`, add dependencies, or call Apify / Ollama / DeepL / MiniMax.

- [x] Z0.1 Record the approved Alibaba SEARCH migration from `memo23/alibaba-scraper` to `zen-studio/alibaba-scraper` inside this same change, not as a parallel contradictory specification.
- [x] Z0.2 Carve the sole generic-search exception: provider-internal compatibility validation between the user query and a listing acquired by Alibaba Zen.
- [x] Z0.3 Forbid using that exception for cross-market identity, title/image/brand/model association, landed cost / negotiation / tracking without explicit IDs, filtering other marketplaces, or treating RELEVANT as authenticity.
- [x] Z0.4 Specify the closed Zen input contract, one execution, no `proxyConfiguration`, no `sales_volume` default, and proposed budget `min(display_limit * 2, 20)`.
- [x] Z0.5 Specify the independent semantic-validation port, closed decisions/reason codes, narrow model input, and 1:1 `candidate_ref` batch rules.
- [x] Z0.6 Specify RELEVANT/REVIEW/IRRELEVANT membership, EMPTY/ERROR/SUCCESS-with-semantic-incidence, and explicit semantic metrics that do not reuse coverage.
- [x] Z0.7 Specify the separate Zen currency fields and precedence, and retire memo23 `US $` for post-Z4 SEARCH.
- [x] Z0.8 Record that the exact Zen build and the five named benchmark files are blocked until their existing metadata/contents are supplied; do not invent them.

## Implementation PR Z1 — Zen contract, input, and mapper disconnected from production

Z1 MUST NOT change the production SEARCH Actor, `.env` defaults, or GUI path. Production remains `memo23/alibaba-scraper` until Z4.

- [ ] Z1.1 Recover the exact validated build from the five existing benchmark runs. If still unavailable, stop; do not pin `latest`/`default` or invent a build.
- [ ] Z1.2 Implement the closed Zen run-input builder behind tests only: `resultType="products"`, `keywords=[normalized query]`, optional exact-safe `category`, `sortBy="relevance"`, `shipToCountry="US"`, `marketplace="standard"`, all listed filters false, `includeReviews=false`, `includeSupplierReport=false`, `maxResults=acquisition_budget`, client `max_items=acquisition_budget`, no `proxyConfiguration`.
- [ ] Z1.3 Add a disconnected Zen mapper from sanitized fixtures to the safe Alibaba model, including `localized_currency`, `source_currency`, `price_provenance`, and `ship_to_country`. Do not reuse the memo23 `US $` SEARCH exception.
- [ ] Z1.4 Prove `soldOrder=null` stays unknown, product ratings stay distinct from supplier `serviceScore`, and raw HTML/tokens/contacts/tracking are not retained.
- [ ] Z1.5 Add offline tests for omitted category, exact-safe category, one-keyword array, no second execution, and display/fallback price that cannot enter USD statistics.
- [ ] Z1.6 Keep `xtracto/alibaba-product-scraper` as the refresh Actor.

## Implementation PR Z2 — Semantic-validation port and batch adapter

Z2 MUST remain disconnected from production SEARCH and MUST NOT reuse the H0019 classifier.

- [ ] Z2.1 Add an independent port/adapter with decisions `RELEVANT`, `IRRELEVANT`, and `REVIEW` and the closed reason-code set. Do not invent numeric confidence.
- [ ] Z2.2 Restrict model input to sanitized query, title, resolved category, `categoryPath`, bounded specs, and ephemeral `candidate_ref`.
- [ ] Z2.3 Reject missing, duplicate, or extra `candidate_ref` values by converting the whole batch to REVIEW with `INVALID_PROVIDER_RESPONSE` and no retry.
- [ ] Z2.4 Map validator outage to REVIEW/`VALIDATOR_UNAVAILABLE` and never to IRRELEVANT.
- [ ] Z2.5 Add offline fakes proving H0019 / `AIProductClassifier` is not called and that title-token relevance cannot reject.

## Implementation PR Z3 — Category resolver and acquisition orchestration

Z3 stays disconnected from production. It composes Z1 input and Z2 validation into one logical Alibaba SEARCH plan.

- [ ] Z3.1 Implement the local category resolver so `category` is sent only when exact and sufficiently safe; otherwise omit the field.
- [ ] Z3.2 Compute `acquisition_budget = min(display_limit * 2, 20)` and `maximum_internal_acquisitions = 1` for Alibaba SEARCH.
- [ ] Z3.3 Orchestrate exactly one Zen execution and exactly one semantic batch; prove no refill execution after mapping or semantic loss.
- [ ] Z3.4 Split RELEVANT into the usable pool, REVIEW into **Requiere revisión**, and IRRELEVANT into excluded-with-reason storage while preserving Zen order among RELEVANT results.
- [ ] Z3.5 Derive EMPTY when the validator completed with zero RELEVANT; ERROR when the validator is down or wholly invalid and zero candidates are validated RELEVANT; SUCCESS with semantic incidence when RELEVANT and REVIEW coexist.
- [ ] Z3.6 Keep `TrackerState` as orchestrator only; do not move budget, validator, or identity rules into it.

## Implementation PR Z4 — Atomic production cutover, GUI, diagnostics, and export

Z4 is the only PR that switches production Alibaba SEARCH. It MUST NOT run both SEARCH Actors.

- [ ] Z4.1 Switch the production SEARCH Actor and pinned build to Zen. Reject leftover memo23 SEARCH overrides. Leave refresh on xtracto.
- [ ] Z4.2 Wire GUI generic Búsquedas, diagnostics, and the **Requiere revisión** projection to the Z3 result contract.
- [ ] Z4.3 Export only RELEVANT canonical listings and include semantic metric columns without reusing `coverage_status`.
- [ ] Z4.4 Apply the Zen currency contract in production SEARCH statistics. Do not reuse memo23 `US $`.
- [ ] Z4.5 Sanitize provider errors and persist no raw Zen payload, tokens, HTML, contacts, or tracking.
- [ ] Z4.6 Prove positional comparison uses only RELEVANT Alibaba cells and that Alibaba decisions cannot mutate Facebook or Mercado Libre lists.
- [ ] Z4.7 Update AGENTS.md / architecture notes so later agents do not implement memo23 SEARCH as current production.

## Implementation PR Z5 — Fully offline quality gate

Z5 cannot start until sanitized, human-labeled versions of the five named benchmark files exist. Do not fabricate their contents.

- [ ] Z5.1 Incorporate sanitized benchmark fixtures after tokens, HTML, contacts, and tracking are removed.
- [ ] Z5.2 Use only human-reviewed golden semantic labels; do not generate labels with the model under evaluation.
- [ ] Z5.3 Run the complete offline format, lint, type-check, unit/integration, and applicable Playwright suites.
- [ ] Z5.4 Record Apify, Ollama, DeepL, MiniMax, and marketplace live calls as zero.
- [ ] Z5.5 Confirm identity-less listings remain distinct, unknowns stay null, `display_limit` remains separate from `acquisition_budget`, and no cross-market identity was introduced.
