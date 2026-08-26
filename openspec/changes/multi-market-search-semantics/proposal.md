# Change: Multi-market search semantics

## Why

BERA's generic marketplace search currently risks using one ambiguous result limit for both provider acquisition and user-visible output, conflating presentation-filtered rows with provider truth, and overloading exact-product comparison structures for unrelated search results. That ambiguity can hide valid later candidates, misreport empty searches as errors, produce misleading summary counts, and accidentally suggest that listings at the same search position share product identity.

This change defines one coherent, bounded, observable search-session contract for Alibaba, Facebook Marketplace Venezuela, and Mercado Libre Venezuela. The contract preserves provider provenance, monetary safety, exact-product safeguards, and the one-execution budget while allowing a single provider run to acquire enough candidates to fill the requested display maximum when valid candidates exist.

## What Changes

- Define UI choices `1`, `3`, and `5` as a maximum number of usable/displayed listings per selected marketplace, labelled **Máximo por plataforma**. They are ceilings, not guarantees or raw actor request counts.
- Separate `display_limit` from a centralized, deterministic, provider-capped `acquisition_limit`.
- In generic **Búsquedas**, permit at most one marketplace acquisition execution per selected provider per search generation and zero automatic refill executions in both multi-market and single-market modes; unrelated collection/tracking workflows retain their own transport behavior.
- Introduce truthful provider pipeline metrics, rejection reasons, `SUCCESS`/`EMPTY`/`ERROR` semantics, compact **Ver detalles** diagnostics, and aggregate schema-drift observability.
- Build generic comparison rows by provider result position using a dedicated `SearchPositionComparisonRow`; explicitly prohibit positional alignment from establishing exact-product identity or authorizing provenance-dependent workflows.
- Freeze the displayed prefix of the ordered usable pool as canonical session results; derive comparison, summary cards, total results, exports, and session labels from that prefix rather than the extra acquisition buffer or presentation projections.
- Route provider-specific queries while retaining canonical `original_user_query`, `provider_query`, `provider_query_origin`, provider-local market/geographic scope, and generation, reusing existing query-generation/translation infrastructure with an offline-safe fallback.
- Define an explicit deterministic Caracas metropolitan-area location policy without broadening Facebook scope to all Venezuela, while retaining strict Mercado Libre Venezuela provenance.
- Preserve fail-closed currency behavior and add truthful UX for visible Alibaba prices whose source currency is unknown.
- Preserve marketplace-specific ordering, images, ratings, CSV security, stale-response protection, and exact-product workflows.

## Capabilities

### New capabilities

- `bounded-provider-search`: display/acquisition limits, per-generation acquisition-execution budget, frozen canonical session results, consolidated metrics, status, and single-market parity.
- `positional-market-comparison`: position-based generic rows, canonical summaries and totals, disclosure, and strict separation from exact-product identity.
- `provider-search-diagnostics`: compact safe diagnostics, provider rejection counters, schema-drift signals, session status copy, and unknown-currency explanations.
- `marketplace-query-routing`: original/provider query provenance, shared Venezuela query generation, fallback behavior, and deterministic Caracas scope.
- `search-session-export-safety`: current-session CSV semantics, query/metric provenance, stale-response clearing, and preserved export security.

### Modified capabilities

- None represented by pre-existing OpenSpec files. The new specifications constrain and preserve existing application behavior described under Compatibility.

## Impact

- **Domain/application models:** add explicit search intent (including provider-local market scope), provider execution result/metrics, provider query provenance, frozen session snapshot, and positional comparison types. Evolve existing acquisition metrics rather than creating a competing source of truth.
- **Generic search orchestration:** calculate bounded acquisition once, invoke one Actor/API marketplace search acquisition per selected provider per generation, and never launch a refill execution after mapping/policy loss. This does not redefine retry behavior for CLI collect, tracking, refresh, history, exact-product, or provider transport workflows outside generic **Búsquedas**.
- **Provider adapters/mappers:** expose safe aggregate counts and truthful rejection reasons without exposing or retaining raw actor payloads.
- **Generic Reflex UI:** rename the limit control, render positional comparison rows and disclosure, use canonical counts/statuses, add compact diagnostics, and explain unknown Alibaba currency.
- **Export:** retain one row per real canonical session result (not each extra usable buffer candidate), with truthful optional query, market-scope, generation, and metric provenance columns.
- **Tests:** add offline unit/integration fixtures and 1440x900 Playwright coverage; no live provider or translation calls.
- **Cost:** Alibaba and Mercado Libre normally request up to 5/10/15 candidates for display maxima 1/3/5. This may increase per-run records and processing relative to requesting exactly the display maximum, but remains deterministic and bounded. Facebook remains capped at 5, so display 5 has no rejection buffer. Alibaba's provider maximum of 500 is not a normal candidate pool.

## Compatibility

Implementation MUST remain compatible with current marketplace provider adapters, exact-product workflows, Alibaba tracking, landed cost, negotiation, profitability, the Facebook H0019 specialized flow, Facebook generic priced-only filtering, marketplace-owned images, genuine rating rules, CSV injection protection and UTF-8 BOM, monetary provenance, the search-generation guard, and the Reflex-native frontend. Deterministic rules SHOULD live in small pure application/GUI modules where practical; `TrackerState` orchestrates and serializes them rather than becoming a replacement domain/service layer.

## External-call budget

- Generic **Búsquedas** marketplace acquisition executions: at most one per selected provider per search generation.
- Automatic refill marketplace executions after rejection/mapping loss: zero.
- Provider executions during implementation and automated tests: zero.
- DeepL calls during automated tests and implementation: zero.
- MiniMax calls: zero.
- Live smoke calls are prohibited unless explicitly authorized after the implementation PR exists.

## Non-goals

- Generic **Búsquedas** refill executions/retries after candidate loss, infinite/deep pagination, or Alibaba's maximum 500 as a routine pool. Retry/transport semantics of unrelated workflows are not redesigned.
- Implicit foreign exchange or interpreting `$` alone as USD.
- Weakening Mercado Libre Venezuela provenance or Facebook priced-only policy.
- A global cross-market score or AI-, fuzzy-title-, rank-, or image-based exact-product identity.
- Redesigning landed cost, negotiation, tracking, profitability, or the dashboard shell.
- Fake products, prices, images, seller ratings, or product ratings.
- React, Next.js, or Vite migration.
- Live provider calls, MiniMax use, or DeepL use in automated tests.

## Open Questions

Fundamental semantics are settled. Only these implementation-evidence details may be resolved before their respective implementation task begins:

1. Whether documented provider economics or adapter constraints require a small change to Alibaba/Mercado Libre's initial 5/10/15 pool values. Any change MUST be centralized, bounded, provider-capped, and recorded in `design.md` before code changes.
2. Which reviewed, unambiguous forms from the proposed Caracas metropolitan allowlist the existing Facebook fixture corpus can support without unacceptable false positives.
3. Final compact Spanish diagnostic wording, provided it preserves every specified distinction and does not imply unavailable metrics are zero.
