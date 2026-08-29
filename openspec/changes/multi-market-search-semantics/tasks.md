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

- [ ] C.1 Instrument Facebook/Mercado Libre truthfully observable fetched/mapped/usable boundaries as specified for those providers. Alibaba SEARCH production instrumentation is owned by Z5, not by a memo23-only C.1 implementation.
- [ ] C.2 Preserve Facebook priced-only policy and instrument truthful optional Free/Gratis, invalid price, missing ID, duplicate ID, location, title, malformed URL, and other measurable rejection reasons.
- [ ] C.3 Add Mercado Libre safe mapper counters for missing ID/title, missing Venezuela evidence, explicit foreign evidence, and successful mapping where observable without weakening MLV provenance.
- [ ] C.4 Add aggregate-only schema-drift observability and verify raw payloads, actor JSON, credentials, cookies, tokens, stack traces, and sensitive parameters are neither persisted nor rendered.
- [ ] C.5 Implement compact **Ver detalles** with actual-request metrics, **No disponible** for unknowns, sanitized provider-not-configured copy, and mapping-loss copy distinct from zero fetched records.
- [ ] C.6 Add offline tests for Facebook mixed rejection pool, later valid MLV record, sanitized configuration error, and relevant EMPTY/ERROR details. Alibaba `fetched = 0` and `fetched > 0 && mapped = 0` proofs belong to Z5.8 after SEARCH instrumentation exists.

## Implementation PR D — Query routing and configurable Venezuela scope

- [ ] D.1 Route canonical query provenance plus requested scope into the provider-neutral contracts; generation-check every async translation/routing continuation before commit or downstream work.
- [ ] D.2 Route Alibaba to the original query or an independently derived safe international query; never reuse the Venezuela-localized query silently.
- [ ] D.3 Reuse existing query-generation/translation infrastructure with no language-detection AI or second subsystem, at most one shared Venezuela-localized generation, the deterministic outcome table in `design.md`, and no translation loop.
- [ ] D.4 Add offline translator fakes for no-translation-needed, unavailable, timeout/failure, empty/invalid, technical-token validation failure, output-identical-to-original, and successful shared Venezuela translation; prove DeepL call count is zero.
- [ ] D.5 Own the concrete Facebook Venezuela strategy: finite partition catalog, per-call composition, aliases, `requested_geographic_scope`, `effective_geographic_scope`, `coverage_status`, sanitized diagnostics, foreign rejection, and unchanged MLV evidence.
- [ ] D.6 Add Facebook-specific tests for genuine nationwide acquisition, all partitions `COMPLETE`, failed subset with useful `PARTIAL` results, partial zero results, scope provenance, missing location, foreign evidence, and narrower scopes.

## Implementation PR E — Currency, export, lifecycle, and browser compatibility gate

- [ ] E.1 Remove remaining Alibaba unknown-currency-as-USD fallbacks, retain visible published prices when allowed, and explain unconfirmed currency/unavailable USD statistics. Regression-test no implicit FX, that `$` and bare `US` do not prove USD, and that all other unconfirmed Alibaba currency stays out of USD statistics. Before Z5, preserve the authorized memo23 SEARCH raw `price` marker `US $` / `US$` → internal ISO `USD` contract. After Z5, E.1 MUST use the Zen currency contract and MUST NOT re-authorize memo23 SEARCH `US $` as the production SEARCH rule.
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
- [x] Z0.4 Specify the closed Zen input contract, one execution, `build=<exact buildNumber>`, `max_items=acquisition_budget`, `restart_on_error=False`, no BERA restart/retry/resurrect/reboot, no `proxyConfiguration`, no `sales_volume` default, and proposed budget `min(display_limit * 2, 20)`.
- [x] Z0.5 Specify the independent semantic-validation port, closed decisions/reason codes, concrete field/batch limits, exact tool-response fields, and 1:1 `candidate_ref` batch rules.
- [x] Z0.6 Specify RELEVANT/REVIEW/IRRELEVANT membership, EMPTY/ERROR/SUCCESS-with-semantic-incidence, known-batch unavailable counters, exclusive session-label precedence, and explicit semantic metrics that do not reuse coverage.
- [x] Z0.7 Specify the separate Zen currency fields and precedence, and retire memo23 `US $` for post-Z5 SEARCH.
- [x] Z0.8 Record that the exact Zen build and the five named benchmark files are blocked until their existing metadata/contents are supplied; do not invent them.
- [x] Z0.9 Specify the deterministic category resolver: versioned Zen enum snapshot, local exact aliases, no LLM/embeddings/fuzzy matching, and omit-on-unknown/ambiguous/out-of-snapshot.
- [x] Z0.10 Specify zero real validator calls when `mapped == 0` or local construction fails, exactly one batch after a constructed 1..20 request, and no empty-batch no-op call.
- [x] Z0.11 Reorder the Z-track so Z1 incorporates sanitized structural fixtures without labels, Z4 is the offline quality gate, and Z5 is the only production cutover.
- [x] Z0.12 Reconcile validator call-count with local batch construction, permitted decision/reason pairs, `not_run` for mapped-zero, untrusted marketplace fields, deterministic ladder extrema, whitespace-preserving sanitization, and label-based Z4 fail conditions without a numeric SLA.
- [x] Z0.13 Reconcile Z4 loopback-validator measurement, Z4/Z5 model-and-prompt pin, adapter-only failure reasons, closed tool envelope, deterministic spec-pair order, generation-bound review/excluded collections, inverted range rejection, all-RELEVANT gate failure, and move Alibaba fetched/mapped-zero proofs from C.6 to Z5.
- [x] Z0.14 Reconcile the shared 256 code-point query without divergent truncation, shared resolver/validator normalization, last-8 category-path suffix, canonical UTF-8 batch-byte cap, human-REVIEW Z4 coverage, startable-only Zen execution, single shared five-run build, post-cutover Z5 quality gate, and Z4 evaluated-model call-budget wording.

## Implementation PR Z1 — Disconnected Zen input/mapper and structural fixtures

Z1 MUST NOT change the production SEARCH Actor, `.env` defaults, or GUI path. Production remains `memo23/alibaba-scraper` until Z5. Z1 incorporates sanitized structural fixtures without semantic labels so later PRs are not blocked on Z5.

- [ ] Z1.1 Recover `runId`, `buildId`, and `buildNumber` from the five existing benchmark runs. All five SHALL share exactly the same `buildId` and `buildNumber`. That single shared build is the only allowed pin for the taxonomy snapshot, fixtures, Z4, and Z5. If any run differs, stop; do not choose majority, last, or default; do not mix fixtures as validation of an arbitrary build; block Z1/Z4/Z5 and require a new OpenSpec decision plus authoritative benchmarks from one build. If metadata are still unavailable, stop; do not pin `latest`/`default` or invent a build.
- [ ] Z1.2 Implement the closed Zen run-input builder behind tests only: `resultType="products"`, `keywords=[normalized query]`, optional resolver-safe `category`, `sortBy="relevance"`, `shipToCountry="US"`, `marketplace="standard"`, all listed filters false, `includeReviews=false`, `includeSupplierReport=false`, `maxResults=acquisition_budget`, client `max_items=acquisition_budget`, client `build=<exact buildNumber>`, `restart_on_error=False`, no `proxyConfiguration`, and no BERA restart/retry/resurrect/reboot.
- [ ] Z1.3 Incorporate sanitized structural versions of the five named benchmark files after tokens, HTML, contacts, and tracking are removed. Do not add semantic labels and do not fabricate missing files.
- [ ] Z1.4 Add a disconnected Zen mapper from those structural fixtures to the safe Alibaba model, including `localized_currency`, `source_currency`, `price_provenance`, and `ship_to_country`. Do not reuse the memo23 `US $` SEARCH exception.
- [ ] Z1.5 Prove `soldOrder=null` stays unknown, product ratings stay distinct from supplier `serviceScore`, and raw HTML/tokens/contacts/tracking are not retained.
- [ ] Z1.6 Add offline tests for omitted category, exact-safe category, one-keyword array, no second execution, deterministic ladder min/max, conflicting ladder/range remaining unknown, inverted `dollarPriceRangeLow > dollarPriceRangeHigh` remaining unknown, and display/fallback price that cannot enter USD statistics.
- [ ] Z1.7 Keep `xtracto/alibaba-product-scraper` as the refresh Actor.

## Implementation PR Z2 — Semantic-validation port and batch adapter

Z2 MUST remain disconnected from production SEARCH and MUST NOT reuse the H0019 classifier, prompt, tool, or domain.

- [ ] Z2.1 Add an independent port/adapter with decisions `RELEVANT`, `IRRELEVANT`, and `REVIEW` and the closed reason-code set. Do not invent numeric confidence.
- [ ] Z2.2 Restrict model input to the documented sanitized-and-bounded fields and ephemeral `candidate_ref`. Enforce the concrete query/title/categoryPath/spec/candidate/batch limits.
- [ ] Z2.3 Accept exactly one tool call named `classify_alibaba_zen_candidates` whose arguments object is `{ "decisions": [items] }`. Each item has exactly `candidate_ref`, `decision`, and `reason_code`. Model REVIEW reasons are only `INSUFFICIENT_EVIDENCE` or `CONFLICTING_EVIDENCE`. Extra, missing, duplicate, extra-ref, mistyped, extra tool call, wrong tool name, or incompatible pairs invalidate the whole batch. The adapter synthesizes `VALIDATOR_UNAVAILABLE` and `INVALID_PROVIDER_RESPONSE`.
- [ ] Z2.4 Map validator outage against a known-size batch to REVIEW/`VALIDATOR_UNAVAILABLE`, `semantic_relevant = 0`, `semantic_irrelevant = 0`, `semantic_review = batch_size`, and never to IRRELEVANT.
- [ ] Z2.5 Record dedicated `model` and `prompt_version` provenance, ignore ordinary assistant content, use a loopback base URL, `trust_env=False`, and `ZEN_SEMANTIC_HTTP_TIMEOUT_SECONDS = 60`.
- [ ] Z2.6 Add offline fakes proving H0019 / `AIProductClassifier` is not called, title-token relevance cannot reject, untrusted seller text cannot flip sibling decisions, incompatible pairs invalidate the batch, model-emitted `VALIDATOR_UNAVAILABLE`/`INVALID_PROVIDER_RESPONSE` invalidate the batch, and a wrong tool name or second tool call invalidates the batch.

## Implementation PR Z3 — Category resolver and disconnected orchestration

Z3 stays disconnected from production. It composes Z1 input and Z2 validation into one logical Alibaba SEARCH plan.

- [ ] Z3.1 Record the versioned Zen category-enum snapshot that corresponds to the pinned build and implement the local deterministic resolver from that snapshot plus audited exact aliases. No LLM, embeddings, or fuzzy matching.
- [ ] Z3.2 Send `category` only on one unambiguous snapshot member; omit on unknown, ambiguous, or out-of-snapshot matches. Record `category`, `category_origin`, and `taxonomy_version`. Do not rewrite `keywords`.
- [ ] Z3.3 Compute `acquisition_budget = min(display_limit * 2, 20)` and `maximum_internal_acquisitions = 1` for Alibaba SEARCH.
- [ ] Z3.4 When configuration and preflight are valid, orchestrate exactly one Zen execution. When token, pinned build, or other required configuration is absent, or the query is invalid or oversized, finalize Alibaba as preflight ERROR with zero Zen executions and zero validator calls. No Actor condemned to fail SHALL be started. After a startable Zen run, call the validator exactly once only after a local batch of 1..20 candidates is constructed within `ZEN_SEMANTIC_MAX_BATCH_BYTES`. Call it zero times when `mapped == 0` (`not_run`) or when local construction fails (`invalid_response`). Prove fetched-zero, mapped-zero, constructed-positive, oversized-mapped, oversized-serialize, missing-config, and oversized-query cases. Prove no retry and no second Zen run.
- [ ] Z3.5 Split RELEVANT into `ordered_usable_pool`, REVIEW into immutable generation-bound `review_candidates`, and IRRELEVANT into immutable generation-bound `excluded_candidates`, preserving Zen order in each collection.
- [ ] Z3.6 Derive EMPTY when the validator completed with zero RELEVANT; ERROR when a known-size batch is unavailable or invalid; SUCCESS with semantic incidence when RELEVANT and REVIEW coexist.
- [ ] Z3.7 Keep `TrackerState` as orchestrator only; do not move budget, validator, or identity rules into it.

## Implementation PR Z4 — Labeled quality gate before cutover

Z4 MUST NOT change the production SEARCH Actor, `.env` defaults, or GUI path. It cannot start until Z1 structural fixtures exist. It adds independent human labels and MUST pass completely before Z5 may start.

- [ ] Z4.1 Add independent human-reviewed golden semantic labels for the five named datasets. The corpus SHALL include at least one real human RELEVANT, one real human IRRELEVANT, and one real human REVIEW label. Do not fabricate labels to satisfy coverage. Do not generate labels with the model under evaluation. If any class is missing, Z4 is incomplete and Z5 remains blocked.
- [ ] Z4.2 Benchmark the same loopback validator adapter and pinned prompt against those five labeled datasets. The benchmark MAY call only the evaluated `model` identifier and `prompt_version` through the loopback Ollama endpoint, and SHALL record that model, `prompt_version`, and call count. It SHALL NOT call Apify, a marketplace, DeepL, or any other model. If the evaluated model is `minimax-m3:cloud` or another cloud-backed identifier, do not record "MiniMax calls = 0" and do not describe the benchmark as completely offline. Automated unit/integration/Playwright suites remain fake/offline with zero Apify, marketplace, DeepL, and Ollama/model inference. Do not substitute fakes or prerecorded decisions for this gate.
- [ ] Z4.3 Run the complete format, lint, type-check, unit/integration, and applicable Playwright suites. Those automated suites stay fake/offline and make zero live model calls.
- [ ] Z4.4 Record automated-suite Apify, marketplace, DeepL, and model-inference counts as zero. For the Z4 benchmark, record the exact loopback `model` identifier, `prompt_version`, and call count that passed. Do not claim MiniMax calls were zero when the evaluated model is `minimax-m3:cloud`.
- [ ] Z4.5 Confirm the minimum acceptance criteria: identity-less listings remain distinct; unknowns stay null; `display_limit` remains separate from `acquisition_budget`; no cross-market identity; mapped-zero is `not_run` with zero validator calls; a constructed 1..20 batch makes exactly one call; no retry; no second Zen run; ALL-REVIEW is incidencias; every human label is compared to the validator and a complete confusion matrix is recorded; Z4 fails on any human-RELEVANT→IRRELEVANT, any human-IRRELEVANT→RELEVANT, any human-REVIEW→RELEVANT, any human-REVIEW→IRRELEVANT, any labeled dataset with human RELEVANT and zero validator RELEVANT, or any labeled dataset with human IRRELEVANT and zero validator IRRELEVANT; an all-REVIEW degenerate cannot pass datasets with human RELEVANT or human IRRELEVANT; an all-RELEVANT degenerate cannot pass; production Actor remains `memo23/alibaba-scraper`. No numeric accuracy SLA is invented.
- [ ] Z4.6 Treat any unmet Z4 criterion as a hard stop. Z5 SHALL NOT start.

## Implementation PR Z5 — Atomic production cutover, GUI, diagnostics, and export

Z5 is the only PR that switches production Alibaba SEARCH. It MAY start only after every Z4 item passed. It MUST NOT run both SEARCH Actors.

- [ ] Z5.1 Switch the production SEARCH Actor and pinned build to Zen. Reject leftover memo23 SEARCH overrides. Leave refresh on xtracto.
- [ ] Z5.2 Wire GUI generic Búsquedas, diagnostics, session-label precedence, and **Requiere revisión** to the generation-bound `review_candidates` / `excluded_candidates` collections. Clear those collections with **Nueva búsqueda** and reject stale-generation rows.
- [ ] Z5.3 Export only RELEVANT canonical listings and include semantic metric columns without reusing `coverage_status`.
- [ ] Z5.4 Apply the Zen currency contract in production SEARCH statistics. Do not reuse memo23 `US $`.
- [ ] Z5.5 Sanitize provider errors and persist no raw Zen payload, tokens, HTML, contacts, or tracking.
- [ ] Z5.6 Prove positional comparison uses only RELEVANT Alibaba cells and that Alibaba decisions cannot mutate Facebook or Mercado Libre lists.
- [ ] Z5.7 Update AGENTS.md and, at cutover, add the Zen SEARCH/validator flow to architecture diagrams and `docs/architecture/README.md` as then-current architecture. Z0 MUST NOT edit those diagrams.
- [ ] Z5.8 Prove Alibaba `fetched = 0` and `fetched > 0 && mapped = 0` with the Z5 SEARCH instrumentation. These cases are not C-stage work.
- [ ] Z5.9 Refuse production semantic validation and the Actor switch unless the configured model identifier and `prompt_version` equal the pair recorded by the passing Z4 gate. A floating `BERA_TRACKER_OLLAMA_MODEL` mismatch is a hard stop.
- [ ] Z5.10 After the Actor, GUI, diagnostics, currency, and export cutover, rerun format check, lint, mypy, unit, integration, applicable Playwright, the E.7-equivalent compatibility gate, and the tracking, refresh, landed-cost, negotiation, H0019, positional-comparison, generation-guard, CSV, and currency-provenance suites. Automated tests remain fake/offline and SHALL NOT execute Apify or real models. Z5 SHALL NOT complete or merge if that gate fails.
