# Change: Multi-market search semantics

## Why

BERA's generic marketplace search currently risks using one ambiguous result limit for both provider acquisition and user-visible output, conflating presentation-filtered rows with provider truth, and overloading exact-product comparison structures for unrelated search results. That ambiguity can hide valid later candidates, misreport empty searches as errors, produce misleading summary counts, and accidentally suggest that listings at the same search position share product identity.

This change defines one coherent, bounded, observable search-session contract for Alibaba, Facebook Marketplace Venezuela, and Mercado Libre Venezuela. The contract preserves provider provenance, monetary safety, and exact-product safeguards while allowing one logical search operation per selected provider to acquire enough candidates to fill a configurable display maximum when valid candidates exist.

## What Changes

- Define `display_limit` as a positive supported maximum bounded by one centralized finite `MAX_DISPLAY_LIMIT` (which supports at least 10), labelled **Máximo por plataforma**. Values such as 10 mean the first up to 10 valid results in the provider's documented canonical order; they are ceilings, not guarantees or raw acquisition counts.
- Separate `display_limit` from centralized finite `acquisition_budget` and actual `acquisition_requested`; these are the only acquisition-volume domain concepts.
- In generic **Búsquedas**, permit one logical marketplace search operation per selected provider per search generation. A provider may use multiple bounded internal acquisitions to implement that operation or cover a broad scope; this is not a retry. The orchestrator cannot start a second logical operation merely to refill rejected candidates.
- Introduce truthful provider pipeline metrics, rejection reasons, `SUCCESS`/`EMPTY`/`ERROR` semantics, compact **Ver detalles** diagnostics, and aggregate schema-drift observability.
- Build generic comparison rows purely by provider result position using a dedicated `SearchPositionComparisonRow`; never cross-filter, discard, reorder, or match one provider's valid results based on similarity to another provider. Provider-integrity/safety validation alone determines validity. Positional alignment cannot establish identity, equivalence, compatibility, or provenance authorization.
- Freeze the displayed prefix of the ordered usable pool as canonical session results; derive comparison, summary cards, total results, exports, and session labels from that prefix rather than the extra acquisition buffer or presentation projections.
- Route provider-specific queries while retaining query provenance plus separate requested geographic scope, truthful effective scope, and coverage status (`COMPLETE`, `PARTIAL`, or unavailable when coverage was not established). Partial fulfillment remains useful but becomes an incidence; unavailable coverage never overrides `ERROR`.
- Define configurable provider geographic scope. **Toda Venezuela** is used only for a genuine nationwide search or the complete finite configured nationwide partition set; bounded subsets use accurate partial/broad-scope copy. Supported narrower city/market scopes include Caracas.
- Preserve fail-closed currency behavior (no implicit FX, no generic `$`→USD, no generic unknown-currency→USD). The memo23 SEARCH raw `price` marker `US $` / `US$` remains the pre-Z5 SEARCH exception only. After Z5, Alibaba SEARCH uses a separate Zen currency contract (`localized_currency`, `source_currency`, `price_provenance`, `ship_to_country`) and SHALL NOT reuse the memo23 marker rule.
- After Z5, migrate Alibaba SEARCH from `memo23/alibaba-scraper` to a pinned build of `zen-studio/alibaba-scraper`, keep `xtracto/alibaba-product-scraper` for exact refresh, and apply one provider-internal semantic-validation batch to Alibaba Zen listings before freezing the canonical pool.
- Preserve marketplace-specific ordering, images, ratings, CSV security, stale-response protection, and exact-product workflows.

## Capabilities

### New capabilities

- `bounded-provider-search`: configurable display limits and acquisition budgets, one logical operation per provider/generation, bounded internal-acquisition strategy, frozen canonical session results, consolidated metrics, status, and single-market parity.
- `positional-market-comparison`: position-based generic rows, canonical summaries and totals, disclosure, and strict separation from exact-product identity.
- `provider-search-diagnostics`: compact safe diagnostics, provider rejection counters, schema-drift signals, session status copy, and unknown-currency explanations.
- `marketplace-query-routing`: original/provider query provenance, shared Venezuela query generation, fallback behavior, and configurable deterministic Venezuela scope.
- `search-session-export-safety`: current-session CSV semantics, query/metric provenance, stale-response clearing, and preserved export safety.
- `alibaba-zen-semantic-validation`: pinned Zen SEARCH Actor input, one execution, validator called only after a constructed 1..20 batch, deterministic category resolver, concrete validator limits, closed `classify_alibaba_zen_candidates` envelope, RELEVANT/REVIEW/IRRELEVANT split with generation-bound collections, closed reason codes, Zen currency provenance, Z4 loopback quality gate, and sanitized offline fixtures.

### Modified capabilities

- None represented by pre-existing OpenSpec files. The new specifications constrain and preserve existing application behavior described under Compatibility.

## Impact

- **Domain/application models:** add requested scope to search/query intent and effective scope plus coverage outcome to provider/session results, alongside consolidated metrics, frozen snapshot, and positional comparison types.
- **Generic search orchestration:** start one logical provider search operation per selected provider and generation. Its centralized strategy may perform bounded internal acquisitions, deterministically deduplicate/aggregate them, and stop early only when doing so preserves truthful declared geographic coverage. Explicit **Toda Venezuela** requires a genuine nationwide search or the complete finite configured nationwide partition set.
- **Provider adapters/mappers:** expose safe aggregate counts and truthful rejection reasons without exposing or retaining raw actor payloads. After Z5, Alibaba SEARCH mapping and Actor input follow the Zen contract; refresh remains xtracto.
- **Alibaba semantic validation:** a dedicated port/adapter, independent of H0019, may exclude only Alibaba Zen listings that explicitly contradict the user query. REVIEW stays in a separate projection. This exception does not authorize cross-market identity, association by title/image/brand/model, or filtering other marketplaces.
- **Generic Reflex UI:** rename the limit control, render truthful provider-owned listing fields in positional cells, use canonical counts/statuses, add compact diagnostics, and explain unknown Alibaba currency. Missing optional fields render blank/`—` and never trigger fabrication.
- **Export:** require stable query/session/scope and defined provider-metric columns on every export row; unknown or non-applicable values remain blank/explicitly unavailable, never fabricated, and export waits for all selected providers to settle.
- **Tests:** add offline unit/integration fixtures and 1440x900 Playwright coverage; no live provider or translation calls.
- **Cost:** `AcquisitionBudgetPolicy` computes finite `acquisition_budget`; executed internal calls accumulate separate `acquisition_requested`. Larger limits/scopes can increase actual work, but all ceilings remain centralized/testable and Alibaba 500 is not a routine budget. After Z5 the proposed Alibaba SEARCH budget is `min(display_limit * 2, 20)` with one Zen execution.

## Compatibility

Implementation MUST remain compatible with current marketplace provider adapters, exact-product workflows, Alibaba tracking, landed cost, negotiation, profitability, the Facebook H0019 specialized flow, Facebook generic priced-only filtering, marketplace-owned images, genuine rating rules, CSV injection protection and UTF-8 BOM, monetary provenance, the search-generation guard, and the Reflex-native frontend. The Alibaba Zen validator MUST remain independent of H0019. Deterministic rules SHOULD live in small pure application/GUI modules where practical; `TrackerState` orchestrates and serializes them rather than becoming a replacement domain/service layer. Before Z5, production Alibaba SEARCH remains `memo23/alibaba-scraper`.

## External-call budget

- Generic **Búsquedas** logical provider search operations: exactly one per selected provider per search generation when configured and startable.
- Orchestrator-started second logical operations after rejection/mapping loss: zero. Bounded internal acquisitions within the original provider strategy are permitted and are not retries.
- After Z5, Alibaba SEARCH internal acquisitions: exactly one Zen Actor execution. Semantic-validation batch calls are exactly one after a local 1..20 batch is constructed within the size cap, and zero when `mapped == 0` or local construction fails. Zero refill executions. Zero validator retries. Zero second Zen runs.
- Provider executions during implementation and automated tests: zero.
- DeepL calls during automated tests and implementation: zero.
- MiniMax calls: zero.
- Z4 quality-gate exception: the same pinned loopback validator may be called against the five labeled datasets. Apify, marketplace, DeepL, MiniMax, and non-loopback Ollama remain zero. Automated unit/integration/Playwright suites do not use this exception.
- Live smoke calls are prohibited unless explicitly authorized after the implementation PR exists.

## Non-goals

- A second logical generic-search operation used to refill candidate loss, unbounded/deep pagination, or Alibaba's maximum 500 as a routine pool. Bounded provider-internal acquisition strategies and unrelated workflow retry/transport semantics are not redesigned away.
- Implicit foreign exchange, interpreting `$` alone as USD, or treating bare `US` as USD. The memo23 SEARCH `US $` / `US$` marker is a pre-Z5 SEARCH exception only and SHALL NOT be reused for Zen SEARCH.
- Using Alibaba semantic validation as cross-market identity, authenticity proof, landed-cost/negotiation/tracking authorization, or a filter on Facebook or Mercado Libre.
- A second Zen execution or validator retry to refill discarded Alibaba candidates.
- Pinning `latest`/`default` or inventing a Zen build when the five existing benchmark run metadata are unavailable.
- Weakening Mercado Libre Venezuela provenance or Facebook priced-only policy.
- A global cross-market score or AI-, fuzzy-title-, rank-, or image-based exact-product identity.
- Redesigning landed cost, negotiation, tracking, profitability, or the dashboard shell.
- Fake products, prices, images, seller ratings, or product ratings.
- React, Next.js, or Vite migration.
- Live provider calls, MiniMax use, or DeepL use in automated tests.

## Open Questions

Fundamental semantics are settled. Only these implementation-evidence details may be resolved before their respective implementation task begins:

1. The exact initial supported display options, finite `MAX_DISPLAY_LIMIT` value (at least 10), scaling function, provider caps, maximum internal acquisitions, and aggregate budgets needed without excessive cost.
2. The complete finite Facebook partition set that can truthfully support **Toda Venezuela**, and which narrower or explicitly partial/broad scopes and reviewed aliases current adapters/fixtures support.
3. Final compact Spanish diagnostic wording, provided it preserves every specified distinction and does not imply unavailable metrics are zero.
4. The exact validated `zen-studio/alibaba-scraper` build recovered from the five existing benchmark runs. Z0 cannot invent it. Public store/OpenAPI pointers are not a pin.
5. Sanitized structural contents of the five named Zen benchmark files for Z1, and independent human-reviewed golden labels for Z4. Z0 cannot invent either. Z5 cannot start until Z4 passed.
