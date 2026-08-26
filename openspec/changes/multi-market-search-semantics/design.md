# Design: Multi-market search semantics

## Context

Generic **Búsquedas** is a search comparison, not an exact-product association workflow. Each selected marketplace has different acquisition caps, mapping schemas, policy filters, ordering, monetary evidence, and geographic provenance. A single user-facing `limit` cannot truthfully describe both requested actor records and visible usable listings. Likewise, one table row cannot safely serve both search-position comparison and exact-product provenance.

The redesign introduces explicit boundaries between acquisition, canonical provider results, presentation, and exact-product context. It does not replace provider adapters or the Reflex frontend.

## Goals

- Return the first up to `display_limit` valid results from every provider in that provider's own canonical order, without cross-market similarity filtering.
- Make provider outcomes and pipeline loss truthful and observable without retaining sensitive raw data.
- Compare generic results positionally without asserting identity.
- Keep summary, total, export, and status semantics tied to immutable current-session canonical results.
- Route marketplace-appropriate queries with explicit provenance and no new translation subsystem.
- Preserve all geographic, monetary, rating, image, exact-identity, and stale-session safeguards.

## Architecture and data flow

1. A new search generation creates `SearchIntent(original_user_query, display_limit, selected_providers, generation)`. `SearchIntent` only requires a positive integer `display_limit`; the effective `AcquisitionBudgetPolicy` is the sole runtime authority for supported membership (default `1 / 3 / 5 / 10`, `MAX_DISPLAY_LIMIT >= 10`) and rejects unsupported values before acquisition. Implementation PR A delivers this application core; `TrackerState` is not yet wired to it and still uses the existing GUI search path.
2. Query routing produces one `ProviderQuery` per selected provider with query provenance and `requested_geographic_scope`. `ProviderRunResult` separately records truthful optional `effective_geographic_scope` and `coverage_status` (`COMPLETE`, `PARTIAL`, or unavailable).
3. A centralized acquisition-budget policy computes and returns `acquisition_budget(provider, display_limit, requested_geographic_scope)`, the finite ceiling for the aggregate strategy. `acquisition_requested` is measured later from executed internal acquisitions.
4. The orchestrator starts one logical search operation for each selected provider. The provider strategy may perform multiple bounded internal acquisitions to cover scope, partitions, or pagination, but the orchestrator does not start a replacement logical operation when mapping or policy rejects candidates.
5. Each adapter returns or is wrapped into a `ProviderRunResult` containing the deterministically ordered usable pool, with deduplication only where truthful stable identity exists, plus consolidated metrics, coverage, provenance, and execution outcome.
6. The pipeline is explicitly: acquired candidates → mapped/policy-evaluated candidates → ordered usable pool → canonical session results (`ordered_usable_pool[:display_limit]`) → presentation projections. The acquisition buffer exists only to improve the chance of filling the display maximum; extra usable buffer candidates are not canonical session results.
7. Generic comparison constructs positional rows. Exact-product workflows continue to use their separate identity-checked context.
8. UI summaries, diagnostics, CSV export, and session status read the current generation's canonical session snapshot. Late results from older generations are discarded.

### Architecture diagrams

Explanatory PlantUML for Implementation PR A lives in the repository and must be updated when this architecture changes:

- `docs/architecture/multi-market-search-core.puml`
- `docs/architecture/multi-market-search-sequence.puml`

See `docs/architecture/README.md` for source-of-truth precedence. OpenSpec remains authoritative for staged implementation scope (PRs A–E). Diagrams must never justify behavior that contradicts this design or existing provider contracts. They must distinguish the PR A core that is implemented now, existing `TrackerState`/provider boundaries, and deferred integration edges that are not wired yet. Later-phase components (PRs B–E) and unwired GUI orchestration must not be shown as current architecture.

## Core models

### SearchIntent

- `original_user_query`: the exact normalized user intent retained for display/provenance.
- `display_limit`: positive maximum of usable listings displayed per selected provider. Runtime membership in the supported set is owned only by `AcquisitionBudgetPolicy` (default `1 / 3 / 5 / 10`, `MAX_DISPLAY_LIMIT >= 10`). `SearchIntent` does not independently enumerate supported values.
- `selected_providers`: explicit provider set.
- `generation`: stale-response guard identity.
- `requested_geographic_scope` per provider, sufficient to reproduce user intent without introducing a generic geospatial subsystem.

The UI label is **Máximo por plataforma**. A display maximum is not a guarantee; the application returns fewer results when fewer usable candidates exist and never fabricates or duplicates candidates.

### AcquisitionBudgetPolicy

The policy's output is `acquisition_budget`, a centralized deterministic finite ceiling based on provider, `display_limit`, requested scope, and provider hard caps. It does not represent work already requested. The same policy module defines finite `MAX_DISPLAY_LIMIT` and maximum internal acquisitions. All are testable and not scattered across adapters/views. Alibaba's maximum 500 is never a routine budget.

The same policy is the only runtime authority for supported display limits: `validate_display_limit()` / `validate_intent()` reject unsupported values before acquisition begins. Module-level `SUPPORTED_DISPLAY_LIMITS` is the default set used by the policy, not a second validator on `SearchIntent`. A custom policy and a structurally valid `SearchIntent` may therefore disagree; execution follows the effective policy.

A `BoundedAcquisitionPlan` is executable only when derived from `AcquisitionBudgetPolicy.create_plan()` or proven by `validate_plan()`. Callers cannot supply an arbitrary `acquisition_budget` or `maximum_internal_acquisitions` to bypass this policy. `execute_bounded_provider_search()` re-validates the plan against the policy before any internal acquisition.

A provider strategy MAY split the aggregate acquisition budget across multiple bounded internal acquisitions. It SHOULD terminate early once at least `display_limit` unique valid candidates exist only if doing so preserves canonical ordering and the truth of the declared geographic scope. Explicit **Toda Venezuela** cannot terminate after only early city partitions: it requires either one genuine nationwide search or completion of the entire finite configured nationwide partition set. If a finite budget cannot truthfully cover that scope, results use accurate partial/broad Venezuela copy. Exact finite values remain an implementation-evidence decision recorded here before implementation.

### Canonical aggregate provider ordering

For any genuine single provider acquisition, generic **Búsquedas** MUST preserve provider acquisition/result order after required provider-integrity validation. When a truthful stable provider identity exists, BERA deduplicates on that documented key. It MUST NOT invent identity from title/image similarity, price, rank, or fuzzy matching. Valid Alibaba candidates lacking both usable product ID and another documented stable identity remain distinct and usable even when they look similar. Multiple acquisitions without truthful global order use the documented deterministic aggregation algorithm; only identity-bearing duplicates are removed.

Partition concatenation order SHALL NOT be presented as a truthful global provider ranking unless the provider contract explicitly establishes that ordering. For partitioned searches, the resulting order is the **deterministic BERA aggregate provider ordering**. Each provider implementation MUST document stable identity keys when available, no-dedup behavior when unavailable, deduplication precedence, order keys, tie breakers, and early termination. Positional comparison freezes that order.

### Generic-search candidate validity

Generic **Búsquedas** performs only deterministic provider-integrity and safety validation. A missing field rejects only when required by that provider's existing generic-search mapper/integrity contract. Alibaba may map a title-bearing product without `product_id`, `product_url`, image, rating, reputation, or other optional metadata. Mercado Libre retains required external ID/title and MLV/Venezuela provenance, but permalink is not universally mandatory when other valid MLV evidence exists. Facebook retains its existing priced-only and required-integrity fields. Other legitimate rejection includes malformed/unmappable records, explicit foreign evidence, stable provider-identity duplicates, and existing justified provider-policy violations.

Cross-market similarity, category/title similarity, price attractiveness, seller reputation, opportunity score, or a relevance threshold MUST NOT reject a candidate. These values may be annotations or specialized-view projections, but MUST NOT reorder a genuine single-acquisition generic result order after it freezes. A multi-acquisition aggregation algorithm may use only its documented deterministic merge keys, never a subsequent UI ranking control. Missing optional metadata MUST NOT reject an otherwise valid listing.

### Consolidated ProviderRunMetrics

The repository's existing `ProviderAcquisitionMetrics` and provider-specific Facebook metrics SHALL be evolved/consolidated into this run contract rather than retained as competing sources of truth. Provider-specific reason counters remain optional detail alongside it. Every field is an optional non-negative integer except where the application itself always knows it. An unknown value renders **No disponible**, never synthetic zero.

- `display_requested`: user-visible maximum requested for that provider; always known.
- `acquisition_budget`: finite aggregate ceiling available to the strategy; centralized and known before execution.
- `acquisition_requested`: sum of candidate limits actually requested by internal acquisitions that actually executed. Unused budget is excluded; budget 30 with two executed requests of 5 yields 10.
- `fetched`: aggregate raw provider records actually received across internal acquisitions, only if the adapter boundary can observe this truthfully; counting before or after cross-partition deduplication MUST be documented.
- `mapped`: provider records successfully converted into BERA's narrow safe model.
- `rejected`: acquired or mapped candidates rejected by provider-specific policy, only where the stage boundary makes the aggregate truthful. Provider-specific reason counters state their counting boundary.
- `usable`: size of the ordered usable pool after provider-integrity policy, deduplication only where truthful stable identity exists, and canonical ordering; identity-less valid candidates remain included.
- `displayed`: exactly `min(usable, display_requested)`; always known for a completed execution. Weaker inequalities such as `displayed <= usable` are not sufficient; inconsistent values are rejected by the contract itself.

Each adapter/instrumentation point SHALL document the measurement boundary for every emitted counter. `mapped` and `rejected` need not be disjoint: rejection can happen before or after narrow mapping, stages may overlap, and some records may be unobservable. Therefore neither `fetched = mapped + rejected` nor `mapped = usable + rejected` is required. Unobservable counters remain unknown. Safe reason counts may be included only with documented, deterministic definitions.

If an executed internal acquisition does not provide a truthful observable value for an optional aggregate stage, the final aggregate for that stage remains unknown unless the low-level contract explicitly proves the missing contribution is zero. A thrown executed step is not a proven zero: mix a known `fetched=5`/`mapped=5`/`rejected=0` step with a later executed step that raises, and the aggregates are unknown. `acquisition_requested` still includes the failed attempted step because that request actually executed.

For example, `display_limit = 3`, `acquisition_requested = 10`, and an ordered usable pool of 8 yields `usable = 8`, `displayed = 3`, exactly 3 canonical session results, and exactly 3 provider rows in CSV.

### ProviderRunResult and status

`ProviderRunResult` owns the `generation` that produced it. `execute_bounded_provider_search()` copies `SearchIntent.generation` into the result. `SearchSessionSnapshot.commit(result)` accepts the result only when `result.generation == snapshot.intent.generation`. A stale result cannot be relabelled by supplying a separate generation argument.

The result contract also rejects internally inconsistent values: `metrics.usable` must equal `len(ordered_usable_pool)`, `metrics.displayed` must equal `len(canonical_session_results)`, and `canonical_session_results` must be the frozen prefix `ordered_usable_pool[:metrics.displayed]`. `status` must be a `ProviderStatus` member and `coverage_status` must be `None` or a `CoverageStatus` member. String lookalikes such as `"SUCCESS"`, `"ERROR"`, or `"PARTIAL"` are rejected at construction; Python type hints are not runtime enforcement.

- `SUCCESS`: logical provider operation completed and `usable >= 1`.
- `EMPTY`: logical provider operation completed normally and `usable == 0`.
- `ERROR`: the logical provider operation failed with an actual exception/failure outcome. ERROR exposes empty pools and `metrics.usable == metrics.displayed == 0`.

Presentation filters do not change provider status. A successfully completed logical operation whose internal acquisition(s) return no records, or records that cannot map, is `EMPTY`, not `ERROR`.

A selected provider that cannot start because required configuration or credentials are missing is `ERROR`, never `EMPTY`. Diagnostics may say that the provider is not configured, but never expose credential names/values, raw configuration, tokens, or stack traces.

### Requested scope, effective coverage, and incidence

`SearchIntent`/`ProviderQuery` retain `requested_geographic_scope`. `ProviderRunResult` and `SearchSessionSnapshot` retain optional `effective_geographic_scope` and optional `coverage_status`. In PR A there is one authoritative path: requested scope on the intent/plan, complete/partial effective-scope labels on `BoundedAcquisitionPlan`, and derived `effective_geographic_scope` plus `coverage_status` on `ProviderRunResult`. `AcquisitionBatch` does not carry effective geographic scope; concrete Facebook nationwide partitions, aliases, and city catalogs belong to PR D.

- `COMPLETE`: every acquisition required by the documented requested-scope strategy completed, or one genuine provider search truthfully covered the requested scope.
- `PARTIAL`: a proper subset completed and produced a truthful partial/broad effective scope, whether or not usable results were found.
- not applicable: geographic coverage does not apply to that provider/search (for example Alibaba generic search). Effective scope and coverage status may use the documented not-applicable/blank representation and are ignored by session coverage aggregation.
- unavailable/not established: geographic coverage applies but no truthful coverage exists, such as `ERROR` before any successful acquisition. Effective scope is unavailable and diagnostics render **No disponible**.

Example: requested `Toda Venezuela`, effective `Cobertura amplia/parcial de Venezuela`, coverage `PARTIAL`. Useful canonical results are retained. Partial `SUCCESS` or `EMPTY` outcomes create an incidence. If configuration is missing or failure occurs before truthful coverage, status is `ERROR`, effective scope and coverage are unavailable, and normal error copy wins; unavailable coverage never creates or suppresses an incidence by itself.

### Logical search operation and internal acquisition budget

For generic **Búsquedas**, a logical provider search operation is the single user-visible/orchestrator invocation for one selected provider and generation. There is exactly one when the provider is selected, configured, and startable. Its provider-owned acquisition strategy MAY issue multiple bounded Actor runs/API requests internally to cover pagination, partitions, or geographic scope. Those planned internal acquisitions belong to the same logical operation and are not retries. Mapping, validation, ordering, and slicing are also not logical operations.

After that strategy completes, the orchestrator MUST NOT launch a second logical operation merely to replace rejected or mapping-lost candidates. Cross-market relatedness is never a rejection criterion. Internal acquisition SHALL be bounded, deterministic, observable in aggregate where truthful, and must not become infinite/deep pagination.

This budget is scoped to generic **Búsquedas**. It does not change existing CLI collect, tracking, supplier refresh, history, exact-product, or other specialized workflow semantics or provider-library transport handling.

### SearchPositionComparisonRow

Generic search uses a dedicated type with:

- `rank`: one-based canonical result position.
- optional `alibaba_candidate`.
- optional `facebook_candidate`.
- optional `mercadolibre_candidate`.
- `identity_confirmed = false`, invariant and not user-settable.

Row count is the maximum displayed count among selected providers. Candidate N comes from position N in that provider's frozen canonical order: acquisition/result order for any genuine single acquisition, otherwise its documented deterministic BERA aggregate provider ordering. Missing cells remain empty and are rendered as `—`; no listing is repeated to fill a row. There is no global cross-market rank score.

Generic comparison is purely positional. No cross-market similarity, relatedness, equivalence, compatibility, title, image, or category test may filter, discard, promote, demote, or replace a valid candidate in any provider list. A future identical-product or high-confidence matching flow must be separate and cannot mutate generic-search provider results.

### ExactProductContext

Exact-product association remains a separate model and entry path. The existing workflow's explicit association IDs/context product IDs must be non-empty and exactly agree according to its current contract. Native Alibaba, Facebook, and Mercado Libre listing IDs occupy independent provider namespaces; string equality between native IDs never establishes cross-market identity. Search position, native listing-ID equality, title, fuzzy title, relevance, image similarity, or rank can never create or authorize an association.

Positional alignment MUST NOT authorize landed/import cost, profitability ceiling, negotiation context, tracking identity, supplier refresh, price history, exact Alibaba association, or product-specific persistence. No positional candidate is attached to those workflows absent the existing explicit association/context-ID invariant.

## Canonical session and presentation

`SearchSessionSnapshot` owns provider results, frozen canonical prefixes, query provenance, requested/effective scopes, coverage status, generation, and export rows. Canonical ordering freezes when `ProviderRunResult` commits. Generic cards use canonical metrics/results, never presentation projections.

Subsequent presentation sorting, price filtering, relevance filtering, ranking-preset changes, or other UI projections MUST NOT change positional `Resultado #N`, totals, export membership, provider status, or the snapshot. Specialized marketplace views may independently sort/filter only their projections.

**Total de resultados** is the sum of displayed marketplace listings, not the number of positional rows. For displayed counts Alibaba 1, Facebook 1, Mercado Libre 0, total is 2.

Session labels derive from provider statuses and coverage outcomes:

| Condition | Copy |
|---|---|
| At least one `SUCCESS`, no `ERROR`, all applicable coverage `COMPLETE` | `Búsqueda completada` |
| All selected providers `EMPTY`, all applicable coverage `COMPLETE` | `Búsqueda completada · Sin resultados` |
| Any selected provider coverage `PARTIAL` | `Búsqueda completada con incidencias` |
| At least one `ERROR` and at least one other `SUCCESS` or `EMPTY` | `Búsqueda completada con incidencias` |
| All selected providers `ERROR` | `Búsqueda con error` |

Not-applicable coverage is excluded from coverage conditions, so Alibaba-only `SUCCESS` and `EMPTY` sessions complete normally. Unavailable coverage on an `ERROR` provider does not alter error rules. Where geographic scope applies, `SUCCESS` and `EMPTY` require established `COMPLETE` or `PARTIAL` coverage.

The comparison table shows concise disclosure such as **Comparables de la misma búsqueda · identidad exacta no confirmada**. Implementation may refine wording but may not suggest exact matching.

Alibaba opportunity remains attached only to an Alibaba candidate. Rows containing only Facebook/Mercado Libre have no Alibaba opportunity. Provider ordering, images, and genuine ratings remain provider-owned; positional rows never copy these values across cells.

## Provider diagnostics and schema drift

**Ver detalles** is available for `EMPTY`, `ERROR`, rejection/filtering, mapping loss, or `PARTIAL` coverage. It shows requested/effective scope, coverage status, **Máximo a mostrar**, finite budget where useful, actual aggregate **Pedidos al proveedor**, **Recibidos**, **Mapeados**, **Rechazados**, **Usables**, and **Mostrados**. Partial diagnostics explain incomplete scope with sanitized copy and no sensitive provider details. Unknown remains **No disponible**.

- **Facebook:** aggregate truthful reasons for Free/Gratis, invalid price, missing ID, duplicate ID, rejected location, missing title, and malformed URL/other currently measurable policy rejection. Priced-only is mandatory; an image never bypasses price validation.
- **Mercado Libre:** where observable, aggregate missing ID, missing title, missing Venezuela evidence, explicit foreign marketplace evidence, and mapped successfully. `fetched > 0 && mapped == 0` displays a sanitized schema/mapping-loss explanation distinct from `fetched == 0`.
- **Alibaba:** successful run with `fetched == 0` is `EMPTY`; `fetched > 0 && mapped == 0` is `EMPTY` with mapping diagnostic; mapped/usable results produce `SUCCESS`. Only an actual provider failure is `ERROR`.

Schema-drift observability consists only of aggregate counters and sanitized copy. Raw payload persistence/UI, actor JSON, cookies, tokens, and sensitive query parameters are prohibited.

## Query routing

Alibaba receives either `original_user_query` or an independently derived safe international query from existing infrastructure. It never inherits the Venezuela-localized query merely because Facebook/ML use it. Facebook Venezuela and Mercado Libre Venezuela receive a safely available Spanish marketplace query when appropriate. For `baseball glove`, one valid result is Alibaba `baseball glove`, Facebook/ML `guante de béisbol`. Every actual provider query and origin is retained.

Routing reuses existing BERA query-generation/translation infrastructure and adds neither language-detection AI nor a second translator. The deterministic decision contract is:

| Outcome | Provider query and origin |
|---|---|
| No localization/derivation needed | original query, `USER_ORIGINAL` |
| Valid deterministic generated query differing from original | generated query, `DETERMINISTIC_GENERATED` |
| Translator unavailable, timeout, or failure | original query, `FALLBACK` |
| Translation empty/invalid | original query, `FALLBACK` |
| Translation fails technical-token preservation/validation | original query, `FALLBACK` |
| Generated/translated output normalizes identically to original | original query, `USER_ORIGINAL` |
| Valid translated Venezuela query | translated query, `TRANSLATED` |

At most one shared Venezuela-localized generation may be reused by Facebook and Mercado Libre. There is no translation loop. Alibaba derivation is independent and cannot silently consume that localized output. Tests use fakes and make zero DeepL calls.

The snapshot always retains `original_user_query`, each `provider_query`, `provider_query_origin`, requested scope, effective scope, coverage status, and `generation`; diagnostics/export may expose them safely. Every asynchronous routing, translation, and provider continuation MUST compare its initiating generation before committing provenance or starting downstream work.

## Configurable Venezuela geographic scope

Generic Venezuela search may expose **Toda Venezuela** only with truthful nationwide coverage. `ProviderQuery` retains the requested scope; `ProviderRunResult` retains the effective completed scope and coverage status. The UI may offer narrower scopes or accurately named partial/broad coverage. This is not a generic geospatial subsystem.

For Facebook, prefer one genuine nationwide provider search when supported. Otherwise **Toda Venezuela** requires the complete finite configured nationwide partition set, followed by stable deduplication and deterministic aggregate ordering. Collecting only enough early partitions to fill `display_limit` MUST NOT be labelled **Toda Venezuela**; bounded subsets use accurate partial/broad Venezuela copy. Trustworthy acquisition provenance may establish candidate scope without listing-level location unless the existing contract requires it; explicit foreign evidence always rejects. Mercado Libre's MLV/Venezuela evidence contract is unchanged.

## Geographic and monetary provenance

Mercado Libre continues requiring truthful Venezuela evidence such as `siteId == MLV`, a Venezuela domain/permalink, Venezuela country evidence, or MLV product-ID evidence according to current policy; explicit foreign evidence is rejected. Result volume never justifies weakening provenance.

Money remains fail-closed: `$` alone is not USD and no implicit FX is introduced. Alibaba USD aggregates use only explicit compatible ISO USD; Facebook uses only its existing authorized Venezuela normalization; Mercado Libre combines only genuine compatible currency values.

An Alibaba listing with an unconfirmed source currency may remain visible, but USD aggregate fields stay unavailable. UI copy explains **Precio publicado disponible; moneda no confirmada.** and **Estadísticas USD no disponibles: moneda fuente no confirmada.** Any display fallback that labels unknown Alibaba currency as USD must be removed.

## Export, ratings, images, and session lifecycle

CSV emits one row per real canonical session result in the frozen displayed prefix. Its schema always contains the required query/session/scope columns and defined provider metric columns, even when a value is blank, unavailable, or not applicable. Export remains disabled until every selected provider is terminal; partial/error sessions may then export. Existing formula-injection protection and UTF-8 BOM remain mandatory.

Alibaba uses its own image and genuine `reviewScore`; Facebook uses its own primary scraped photo and no fabricated rating; Mercado Libre uses its own thumbnail and genuine `ratingAverage`. Relevance, opportunity, `supplierServiceScore`, and seller reputation tiers never become product stars.

Each positional cell preserves and renders truthfully when available: marketplace-owned image, title, published price/currency, listing URL, supplier/seller name, genuine product rating/review count, genuine seller/supplier reputation or service metadata, and existing provider-specific useful fields such as Alibaba MOQ or Mercado Libre condition. Unavailable fields render blank/`—`. Facebook seller/rating data is never fabricated, and absence of optional cell fields does not invalidate the candidate.

**Nueva búsqueda** increments/changes generation and clears results, diagnostics, provider-query provenance, and exportable session data while retaining persistent tracking. A result tagged with an older generation cannot repopulate the new snapshot.

Single-market generic **Búsquedas** follows the identical pipeline, configurable limit, geographic provenance, and one-logical-operation rule for its selected provider.

## Responsibility boundaries

New deterministic acquisition policy, coverage/metric derivation, routing, frozen-session selection, and positional rows SHOULD live in small pure modules. The generic strategy SHOULD compose existing bounded single-acquisition operations—especially Facebook's existing one-execute/one-Actor-run use case—rather than silently changing their low-level contracts. `TrackerState` coordinates calls, generation checks, and serialization; it is not a new service layer. Implementation PR A keeps those rules in `search_session.py` and does not move provider strategy into `TrackerState`. Wiring `TrackerState` to `SearchIntent`, `AcquisitionBudgetPolicy`, `execute_bounded_provider_search()`, and `SearchSessionSnapshot` is a deferred integration edge, not current runtime behavior. See `docs/architecture/multi-market-search-core.puml` and `docs/architecture/multi-market-search-sequence.puml`.

## Risks and trade-offs

- Bounded over-acquisition costs more records per run but avoids retries and improves the chance of filling visible positions after valid rejections.
- Provider caps or bounded scope strategies may return fewer usable results than requested; the UI maximum remains a ceiling rather than a guarantee.
- Optional metrics improve truthfulness but require UI/export consumers to handle unknown values explicitly.
- Positional comparison improves generic search readability but requires strong type and copy boundaries to prevent accidental exact-association reuse.
- Requested **Toda Venezuela** can require more internal acquisitions and cost than a city scope; finite complete-partition strategies and truthful scope copy control that risk.

## Open Questions

Only implementation-evidence details remain: centralized limits/budgets; the complete finite Facebook nationwide partition set plus supported partial/narrower scopes and aliases; and final compact Spanish diagnostic/coverage copy. All core semantics and safety invariants above are final.
