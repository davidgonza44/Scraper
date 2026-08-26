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

1. A new search generation creates `SearchIntent(original_user_query, display_limit, selected_providers, generation)`; `display_limit` is a supported positive value no greater than centralized finite `MAX_DISPLAY_LIMIT`, and the supported set explicitly includes 10.
2. Query routing produces one `ProviderQuery` per selected provider with `provider_query`, `provider_query_origin` (`USER_ORIGINAL`, `DETERMINISTIC_GENERATED`, `TRANSLATED`, or `FALLBACK`), and the provider-local market/geographic scope needed to reproduce the request. The default Venezuela scope is **Toda Venezuela**; supported narrower scopes may include Caracas.
3. A centralized acquisition policy computes `acquisition_limit(provider, display_limit, geographic_scope)` and caps/bounds the aggregate provider strategy.
4. The orchestrator starts one logical search operation for each selected provider. The provider strategy may perform multiple bounded internal acquisitions to cover scope, partitions, or pagination, but the orchestrator does not start a replacement logical operation when mapping or policy rejects candidates.
5. Each adapter returns or is wrapped into a `ProviderRunResult` containing the deterministically deduplicated and ordered usable pool, consolidated metrics, safe rejection counters, query/market/generation provenance, and an execution outcome.
6. The pipeline is explicitly: acquired candidates → mapped/policy-evaluated candidates → ordered usable pool → canonical session results (`ordered_usable_pool[:display_limit]`) → presentation projections. The acquisition buffer exists only to improve the chance of filling the display maximum; extra usable buffer candidates are not canonical session results.
7. Generic comparison constructs positional rows. Exact-product workflows continue to use their separate identity-checked context.
8. UI summaries, diagnostics, CSV export, and session status read the current generation's canonical session snapshot. Late results from older generations are discarded.

## Core models

### SearchIntent

- `original_user_query`: the exact normalized user intent retained for display/provenance.
- `display_limit`: supported positive maximum of usable listings displayed per selected provider, constrained by centralized finite `MAX_DISPLAY_LIMIT`; 10 is supported.
- `selected_providers`: explicit provider set.
- `generation`: stale-response guard identity.
- provider-local market/geographic scopes sufficient to reproduce each provider request, without introducing a generic geospatial subsystem.

The UI label is **Máximo por plataforma**. A display maximum is not a guarantee; the application returns fewer results when fewer usable candidates exist and never fabricates or duplicates candidates.

### AcquisitionLimitPolicy

The policy is a centralized deterministic function of provider, `display_limit`, geographic scope, and provider hard caps. A central policy module defines a finite `MAX_DISPLAY_LIMIT >= 10`, the finite maximum internal acquisitions per provider/logical search, and the finite aggregate acquisition budget per provider. All limits are testable and SHALL NOT be scattered across adapters/views. It SHALL request at least the display limit when supported and MAY add a bounded rejection buffer. Provider hard limits may mean fewer results are possible; Alibaba's maximum 500 is never a routine pool.

A provider strategy MAY split the aggregate acquisition budget across multiple bounded internal acquisitions—for example pagination or partitions needed for **Toda Venezuela**. It SHOULD terminate early once at least `display_limit` unique valid candidates exist, unless a documented provider ordering algorithm requires completing a bounded set to determine their canonical order. When the maximum acquisitions or aggregate budget is exhausted, it returns fewer results rather than continuing. Exact finite values remain an implementation-evidence decision recorded here before implementation.

### Canonical aggregate provider ordering

When a provider offers one genuine nationwide search, BERA SHOULD preserve that provider-native ordering after provider-integrity validation and identity deduplication. When nationwide coverage requires pages, partitions, or multiple internal acquisitions, BERA SHALL deduplicate candidates by stable provider identity and combine them using a documented deterministic provider-specific aggregation algorithm before constructing the ordered usable pool. A duplicate observed in multiple partitions appears once.

Partition concatenation order SHALL NOT be presented as a truthful global provider ranking unless the provider contract explicitly establishes that ordering. For partitioned searches, the resulting order is named the **deterministic BERA aggregate provider ordering**, not a single provider-native result order. Each provider implementation MUST document its identity key, deduplication precedence, aggregation/order keys, tie breakers, and interaction with early termination. Positional comparison freezes this resulting order when the run commits to the session snapshot.

### Generic-search candidate validity

Generic **Búsquedas** performs only deterministic provider-integrity and safety validation. Legitimate rejection includes malformed/unmappable records; missing required identity, title, or URL; invalid/missing price where the provider's generic contract requires price; explicit foreign evidence for Venezuela scope; duplicate provider identity; and other already-justified deterministic provider-policy violations.

Cross-market similarity, category/title similarity, price attractiveness, seller reputation, opportunity score, or a relevance threshold MUST NOT reject a candidate. Relevance or opportunity MAY affect a provider's documented canonical ordering where already supported, but never validity. Missing optional image, rating, seller reputation, or other non-required display metadata MUST NOT by itself reject an otherwise valid listing.

### Consolidated ProviderRunMetrics

The repository's existing `ProviderAcquisitionMetrics` and provider-specific Facebook metrics SHALL be evolved/consolidated into this run contract rather than retained as competing sources of truth. Provider-specific reason counters remain optional detail alongside it. Every field is an optional non-negative integer except where the application itself always knows it. An unknown value renders **No disponible**, never synthetic zero.

- `display_requested`: user-visible maximum requested for that provider; always known.
- `acquisition_requested`: aggregate bounded candidate budget requested across all internal acquisitions in the logical operation; known when the complete strategy budget is fixed/observable.
- `fetched`: aggregate raw provider records actually received across internal acquisitions, only if the adapter boundary can observe this truthfully; counting before or after cross-partition deduplication MUST be documented.
- `mapped`: provider records successfully converted into BERA's narrow safe model.
- `rejected`: acquired or mapped candidates rejected by provider-specific policy, only where the stage boundary makes the aggregate truthful. Provider-specific reason counters state their counting boundary.
- `usable`: size of the ordered usable pool after provider-integrity mapping/policy, stable-identity deduplication, and canonical aggregate provider ordering; always known for a completed execution.
- `displayed`: `min(usable, display_requested)`; always known for a completed execution.

Each adapter/instrumentation point SHALL document the measurement boundary for every emitted counter. `mapped` and `rejected` need not be disjoint: rejection can happen before or after narrow mapping, stages may overlap, and some records may be unobservable. Therefore neither `fetched = mapped + rejected` nor `mapped = usable + rejected` is required. Unobservable counters remain unknown. Safe reason counts may be included only with documented, deterministic definitions.

For example, `display_limit = 3`, `acquisition_requested = 10`, and an ordered usable pool of 8 yields `usable = 8`, `displayed = 3`, exactly 3 canonical session results, and exactly 3 provider rows in CSV.

### ProviderRunResult and status

- `SUCCESS`: logical provider operation completed and `usable >= 1`.
- `EMPTY`: logical provider operation completed normally and `usable == 0`.
- `ERROR`: the logical provider operation failed with an actual exception/failure outcome.

Presentation filters do not change provider status. A successfully completed logical operation whose internal acquisition(s) return no records, or records that cannot map, is `EMPTY`, not `ERROR`.

A selected provider that cannot start because required configuration or credentials are missing is `ERROR`, never `EMPTY`. Diagnostics may say that the provider is not configured, but never expose credential names/values, raw configuration, tokens, or stack traces.

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

Row count is the maximum displayed count among selected providers. Candidate N comes from position N in that provider's frozen canonical order: provider-native nationwide order when genuinely available, otherwise its documented deterministic BERA aggregate provider ordering. Missing cells remain empty and are rendered as `—`; no listing is repeated to fill a row. There is no global cross-market rank score.

Generic comparison is purely positional. No cross-market similarity, relatedness, equivalence, compatibility, title, image, or category test may filter, discard, promote, demote, or replace a valid candidate in any provider list. A future identical-product or high-confidence matching flow must be separate and cannot mutate generic-search provider results.

### ExactProductContext

Exact-product association remains a separate model and entry path. It requires both product IDs to be non-empty and exactly equal. Search position, title, fuzzy title, relevance, image similarity, or rank can never create or authorize it.

Positional alignment MUST NOT authorize landed/import cost, profitability ceiling, negotiation context, tracking identity, supplier refresh, price history, exact Alibaba association, or product-specific persistence. No positional candidate is attached to those workflows absent the existing exact-ID invariant.

## Canonical session and presentation

`SearchSessionSnapshot` owns provider run results, the frozen canonical session result prefix for each provider, provider query and geographic scope provenance, generation, and export rows. The provider's canonical ordering is frozen when its `ProviderRunResult` is committed to the current-generation snapshot. Generic provider cards use `usable` metrics and canonical session result/displayed counts, not `alibaba_visible_rows`, `ml_visible_rows`, relevance filters, or other presentation projections.

Subsequent presentation sorting, price filtering, relevance filtering, ranking-preset changes, or other UI projections MUST NOT change positional `Resultado #N`, totals, export membership, provider status, or the snapshot. Specialized marketplace views may independently sort/filter only their projections.

**Total de resultados** is the sum of displayed marketplace listings, not the number of positional rows. For displayed counts Alibaba 1, Facebook 1, Mercado Libre 0, total is 2.

Session labels are derived solely from selected-provider statuses:

| Condition | Copy |
|---|---|
| At least one `SUCCESS`, no `ERROR` | `Búsqueda completada` |
| All selected providers `EMPTY` | `Búsqueda completada · Sin resultados` |
| At least one `ERROR` and at least one other `SUCCESS` or `EMPTY` | `Búsqueda completada con incidencias` |
| All selected providers `ERROR` | `Búsqueda con error` |

The comparison table shows concise disclosure such as **Comparables de la misma búsqueda · identidad exacta no confirmada**. Implementation may refine wording but may not suggest exact matching.

Alibaba opportunity remains attached only to an Alibaba candidate. Rows containing only Facebook/Mercado Libre have no Alibaba opportunity. Provider ordering, images, and genuine ratings remain provider-owned; positional rows never copy these values across cells.

## Provider diagnostics and schema drift

**Ver detalles** is a compact expandable production control when useful for `EMPTY`, `ERROR`, rejection/filtering, or mapping loss. It shows **Máximo a mostrar**, aggregate **Pedidos al proveedor**, aggregate **Recibidos**, **Mapeados**, **Rechazados**, **Usables**, and **Mostrados**, rendering unknown metrics as **No disponible**. It is not a new diagnostics dashboard. If an internal acquisition count is shown, it is explicitly labelled as internal calls/partitions and never as multiple user searches or retries.

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

The snapshot always retains `original_user_query`, each `provider_query`, `provider_query_origin`, provider-local market/geographic scope, and `generation`; diagnostics/export may expose them safely. The main UI continues to emphasize what the user entered.

## Configurable Venezuela geographic scope

Generic Venezuela search defaults to **Toda Venezuela**. `ProviderQuery` retains the selected provider-local geographic scope, and the UI may offer supported narrower scopes such as a city/market (including Caracas). This is a small provider-scope contract, not a generic geospatial subsystem.

For Facebook **Toda Venezuela**, trustworthy acquisition provenance from a provider search/partition may establish scope even when a listing-level location string is absent, unless the existing provider contract genuinely requires that field. Explicit foreign evidence always rejects the candidate. For narrower scopes, trustworthy partition provenance or explicit normalized reviewed identifiers/aliases may establish scope according to the documented provider contract; arbitrary fuzzy matching and ambiguous standalone tokens remain prohibited. Mercado Libre's existing MLV/Venezuela evidence contract is unchanged.

## Geographic and monetary provenance

Mercado Libre continues requiring truthful Venezuela evidence such as `siteId == MLV`, a Venezuela domain/permalink, Venezuela country evidence, or MLV product-ID evidence according to current policy; explicit foreign evidence is rejected. Result volume never justifies weakening provenance.

Money remains fail-closed: `$` alone is not USD and no implicit FX is introduced. Alibaba USD aggregates use only explicit compatible ISO USD; Facebook uses only its existing authorized Venezuela normalization; Mercado Libre combines only genuine compatible currency values.

An Alibaba listing with an unconfirmed source currency may remain visible, but USD aggregate fields stay unavailable. UI copy explains **Precio publicado disponible; moneda no confirmada.** and **Estadísticas USD no disponibles: moneda fuente no confirmada.** Any display fallback that labels unknown Alibaba currency as USD must be removed.

## Export, ratings, images, and session lifecycle

CSV emits one row per real canonical session result in the frozen displayed prefix, never one row for an extra usable acquisition-buffer candidate and never one merged identity row per positional comparison. Presentation filters do not remove or add canonical session results. Truthfully known fields may include original/provider query, market scope, generation, and the seven provider metrics; unavailable fields remain unavailable rather than zero. Existing spreadsheet-formula injection protection and UTF-8 BOM remain mandatory.

Alibaba uses its own image and genuine `reviewScore`; Facebook uses its own primary scraped photo and no fabricated rating; Mercado Libre uses its own thumbnail and genuine `ratingAverage`. Relevance, opportunity, `supplierServiceScore`, and seller reputation tiers never become product stars.

**Nueva búsqueda** increments/changes generation and clears results, diagnostics, provider-query provenance, and exportable session data while retaining persistent tracking. A result tagged with an older generation cannot repopulate the new snapshot.

Single-market generic **Búsquedas** follows the identical pipeline, configurable limit, geographic provenance, and one-logical-operation rule for its selected provider.

## Responsibility boundaries

New deterministic acquisition policy, metric derivation, query provenance/routing decisions, frozen-session selection, and positional-row construction SHOULD be implemented in small pure application/GUI modules where practical. `TrackerState` coordinates calls, generation checks, and serialization; it SHOULD NOT absorb all policy/domain logic or become a new service layer. This boundary requires no new framework, microservice, or generic geospatial architecture.

## Risks and trade-offs

- Bounded over-acquisition costs more records per run but avoids retries and improves the chance of filling visible positions after valid rejections.
- Provider caps or bounded scope strategies may return fewer usable results than requested; the UI maximum remains a ceiling rather than a guarantee.
- Optional metrics improve truthfulness but require UI/export consumers to handle unknown values explicitly.
- Positional comparison improves generic search readability but requires strong type and copy boundaries to prevent accidental exact-association reuse.
- Default **Toda Venezuela** can require more internal acquisitions and cost than a city scope; bounded strategies and truthful country evidence control that risk.

## Open Questions

Only implementation-evidence details remain: the centralized scaling/cap/internal-acquisition budgets for configurable limits; supported narrower Venezuela scopes and reviewed aliases; and final compact Spanish diagnostic copy. All core semantics and safety invariants above are final.
