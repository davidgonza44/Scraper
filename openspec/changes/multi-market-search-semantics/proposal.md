# Change: Multi-market search semantics

## Why

BERA's generic marketplace search currently risks using one ambiguous result limit for both provider acquisition and user-visible output, conflating presentation-filtered rows with provider truth, and overloading exact-product comparison structures for unrelated search results. That ambiguity can hide valid later candidates, misreport empty searches as errors, produce misleading summary counts, and accidentally suggest that listings at the same search position share product identity.

This change defines one coherent, bounded, observable search-session contract for Alibaba, Facebook Marketplace Venezuela, and Mercado Libre Venezuela. The contract preserves provider provenance, monetary safety, exact-product safeguards, and the one-execution budget while allowing a single provider run to acquire enough candidates to fill the requested display maximum when valid candidates exist.

## What Changes

- Define UI choices `1`, `3`, and `5` as a maximum number of usable/displayed listings per selected marketplace, labelled **Máximo por plataforma**. They are ceilings, not guarantees or raw actor request counts.
- Separate `display_limit` from a centralized, deterministic, provider-capped `acquisition_limit`.
- Permit at most one execution per selected provider and zero automatic marketplace retries in both multi-market and single-market modes.
- Introduce truthful provider pipeline metrics, rejection reasons, `SUCCESS`/`EMPTY`/`ERROR` semantics, compact **Ver detalles** diagnostics, and aggregate schema-drift observability.
- Build generic comparison rows by provider result position using a dedicated `SearchPositionComparisonRow`; explicitly prohibit positional alignment from establishing exact-product identity or authorizing provenance-dependent workflows.
- Derive summary cards, total results, exports, and session labels from canonical current-session data rather than presentation filters.
- Route provider-specific queries while retaining the original query and query origin, reusing existing query-generation/translation infrastructure with an offline-safe fallback.
- Define an explicit deterministic Caracas metropolitan-area location policy without broadening Facebook scope to all Venezuela, while retaining strict Mercado Libre Venezuela provenance.
- Preserve fail-closed currency behavior and add truthful UX for visible Alibaba prices whose source currency is unknown.
- Preserve marketplace-specific ordering, images, ratings, CSV security, stale-response protection, and exact-product workflows.

## Capabilities

### New capabilities

- `bounded-provider-search`: display/acquisition limits, run budget, canonical provider results, metrics, status, and single-market parity.
- `positional-market-comparison`: position-based generic rows, canonical summaries and totals, disclosure, and strict separation from exact-product identity.
- `provider-search-diagnostics`: compact safe diagnostics, provider rejection counters, schema-drift signals, session status copy, and unknown-currency explanations.
- `marketplace-query-routing`: original/provider query provenance, shared Venezuela query generation, fallback behavior, and deterministic Caracas scope.
- `search-session-export-safety`: current-session CSV semantics, query/metric provenance, stale-response clearing, and preserved export security.

### Modified capabilities

- None represented by pre-existing OpenSpec files. The new specifications constrain and preserve existing application behavior described under Compatibility.

## Impact

- **Domain/application models:** add explicit search intent, provider execution result/metrics, provider query provenance, and positional comparison types.
- **Provider orchestration:** calculate bounded acquisition once, invoke each selected provider no more than once, instrument observable stages, and never retry automatically.
- **Provider adapters/mappers:** expose safe aggregate counts and truthful rejection reasons without exposing or retaining raw actor payloads.
- **Generic Reflex UI:** rename the limit control, render positional comparison rows and disclosure, use canonical counts/statuses, add compact diagnostics, and explain unknown Alibaba currency.
- **Export:** retain one row per real listing and current-session semantics, with truthful optional provenance/metric columns.
- **Tests:** add offline unit/integration fixtures and 1440x900 Playwright coverage; no live provider or translation calls.
- **Cost:** Alibaba and Mercado Libre normally request up to 5/10/15 candidates for display maxima 1/3/5. This may increase per-run records and processing relative to requesting exactly the display maximum, but remains deterministic and bounded. Facebook remains capped at 5, so display 5 has no rejection buffer. Alibaba's provider maximum of 500 is not a normal candidate pool.

## Compatibility

Implementation MUST remain compatible with current marketplace provider adapters, exact-product workflows, Alibaba tracking, landed cost, negotiation, profitability, the Facebook H0019 specialized flow, Facebook generic priced-only filtering, marketplace-owned images, genuine rating rules, CSV injection protection and UTF-8 BOM, monetary provenance, the search-generation guard, and the Reflex-native frontend.

## External-call budget

- Selected marketplace provider executions: at most one each.
- Automatic marketplace retries: zero.
- Provider executions during implementation and automated tests: zero.
- DeepL calls during automated tests and implementation: zero.
- MiniMax calls: zero.
- Live smoke calls are prohibited unless explicitly authorized after the implementation PR exists.

## Non-goals

- Provider retries, infinite/deep pagination, or Alibaba's maximum 500 as a routine pool.
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
