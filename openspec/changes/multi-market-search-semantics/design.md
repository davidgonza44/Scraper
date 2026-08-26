# Design: Multi-market search semantics

## Context

Generic **Búsquedas** is a search comparison, not an exact-product association workflow. Each selected marketplace has different acquisition caps, mapping schemas, policy filters, ordering, monetary evidence, and geographic provenance. A single user-facing `limit` cannot truthfully describe both requested actor records and visible usable listings. Likewise, one table row cannot safely serve both search-position comparison and exact-product provenance.

The redesign introduces explicit boundaries between acquisition, canonical provider results, presentation, and exact-product context. It does not replace provider adapters or the Reflex frontend.

## Goals

- Return up to the user's per-marketplace display maximum from a bounded candidate pool acquired in one provider execution.
- Make provider outcomes and pipeline loss truthful and observable without retaining sensitive raw data.
- Compare generic results positionally without asserting identity.
- Keep summary, total, export, and status semantics tied to immutable current-session canonical results.
- Route marketplace-appropriate queries with explicit provenance and no new translation subsystem.
- Preserve all geographic, monetary, rating, image, exact-identity, and stale-session safeguards.

## Architecture and data flow

1. A new search generation creates `SearchIntent(original_user_query, display_limit, selected_providers)`; `display_limit` accepts only 1, 3, or 5.
2. Query routing produces one `ProviderQuery` per selected provider with `provider_query` and `query_origin` (`USER_ORIGINAL`, `DETERMINISTIC_GENERATED`, `TRANSLATED`, or `FALLBACK`).
3. A centralized acquisition policy computes `acquisition_limit(provider, display_limit)` and caps it at the provider hard maximum.
4. The orchestrator starts each selected provider once. It does not invoke a replacement run when mapping or policy rejects candidates.
5. Each adapter returns or is wrapped into a `ProviderRunResult` containing canonical ordered usable candidates, metrics, safe rejection counters, query provenance, and an execution outcome.
6. `displayed_candidates` is the ordered prefix of canonical usable candidates of length `display_limit`. Presentation filters may hide views elsewhere but do not mutate this session result.
7. Generic comparison constructs positional rows. Exact-product workflows continue to use their separate identity-checked context.
8. UI summaries, diagnostics, CSV export, and session status read the current generation's canonical session snapshot. Late results from older generations are discarded.

## Core models

### SearchIntent

- `original_user_query`: the exact normalized user intent retained for display/provenance.
- `display_limit`: maximum usable listings displayed per selected provider; one of 1, 3, or 5.
- `selected_providers`: explicit provider set.
- `generation`: stale-response guard identity.

The UI label is **Máximo por plataforma**. A display maximum is not a guarantee; the application returns fewer results when fewer usable candidates exist and never fabricates or duplicates candidates.

### AcquisitionLimitPolicy

Initial deterministic table:

| Provider | Display 1 | Display 3 | Display 5 | Notes |
|---|---:|---:|---:|---|
| Alibaba | 5 | 10 | 15 | Always capped by provider hard maximum; never routinely expand to 500 |
| Facebook | 5 | 5 | 5 | Existing hard maximum; display 5 has no rejection buffer |
| Mercado Libre | 5 | 10 | 15 | Always capped by provider hard maximum |

The table lives in one policy module/configuration and is covered by contract tests. It is not duplicated in adapters or views. Larger pools increase fetched-record/processing cost, but never provider execution count. Any evidence-based adjustment to 5/10/15 must first update this design with rationale, cost effect, and tests.

### ProviderRunMetrics

Every field is an optional non-negative integer except where the application itself always knows it. An unknown value renders **No disponible**, never synthetic zero.

- `display_requested`: user-visible maximum requested for that provider; always known.
- `acquisition_requested`: bounded candidate count sent to/requested from the provider; known when invocation occurs.
- `fetched`: raw provider records actually received, only if the adapter boundary can observe this truthfully.
- `mapped`: provider records successfully converted into BERA's narrow safe model.
- `rejected`: acquired or mapped candidates rejected by provider-specific policy, only where the stage boundary makes the aggregate truthful. Provider-specific reason counters state their counting boundary.
- `usable`: canonical valid listings after provider-specific mapping and policy; always known for a completed execution.
- `displayed`: `min(usable, display_requested)`; always known for a completed execution.

Counters must not be forced to an arithmetic identity when provider stages overlap or are unobservable. Safe reason counts may be included only with documented, deterministic definitions.

### ProviderRunResult and status

- `SUCCESS`: execution completed and `usable >= 1`.
- `EMPTY`: execution completed normally and `usable == 0`.
- `ERROR`: the provider execution failed with an actual exception/failure outcome.

Presentation filters do not change provider status. A successful actor run returning no records, or records that cannot map, is `EMPTY`, not `ERROR`.

### SearchPositionComparisonRow

Generic search uses a dedicated type with:

- `rank`: one-based canonical result position.
- optional `alibaba_candidate`.
- optional `facebook_candidate`.
- optional `mercadolibre_candidate`.
- `identity_confirmed = false`, invariant and not user-settable.

Row count is the maximum displayed count among selected providers. Candidate N comes from position N in that provider's existing canonical BERA ordering. Missing cells remain empty and are rendered as `—`; no listing is repeated to fill a row. There is no global cross-market rank score.

### ExactProductContext

Exact-product association remains a separate model and entry path. It requires both product IDs to be non-empty and exactly equal. Search position, title, fuzzy title, relevance, image similarity, or rank can never create or authorize it.

Positional alignment MUST NOT authorize landed/import cost, profitability ceiling, negotiation context, tracking identity, supplier refresh, price history, exact Alibaba association, or product-specific persistence. No positional candidate is attached to those workflows absent the existing exact-ID invariant.

## Canonical session and presentation

`SearchSessionSnapshot` owns provider run results, their displayed prefixes, query provenance, generation, and export rows. Generic provider cards use canonical `usable`/`displayed` data, not `alibaba_visible_rows`, `ml_visible_rows`, relevance filters, or other presentation projections.

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

**Ver detalles** is a compact expandable production control when useful for `EMPTY`, `ERROR`, rejection/filtering, or mapping loss. It shows **Máximo a mostrar**, **Pedidos al proveedor**, **Recibidos**, **Mapeados**, **Rechazados**, **Usables**, and **Mostrados**, rendering unknown metrics as **No disponible**. It is not a new diagnostics dashboard.

- **Facebook:** aggregate truthful reasons for Free/Gratis, invalid price, missing ID, duplicate ID, rejected location, missing title, and malformed URL/other currently measurable policy rejection. Priced-only is mandatory; an image never bypasses price validation.
- **Mercado Libre:** where observable, aggregate missing ID, missing title, missing Venezuela evidence, explicit foreign marketplace evidence, and mapped successfully. `fetched > 0 && mapped == 0` displays a sanitized schema/mapping-loss explanation distinct from `fetched == 0`.
- **Alibaba:** successful run with `fetched == 0` is `EMPTY`; `fetched > 0 && mapped == 0` is `EMPTY` with mapping diagnostic; mapped/usable results produce `SUCCESS`. Only an actual provider failure is `ERROR`.

Schema-drift observability consists only of aggregate counters and sanitized copy. Raw payload persistence/UI, actor JSON, cookies, tokens, and sensitive query parameters are prohibited.

## Query routing

Alibaba receives the original/international query. Facebook Venezuela and Mercado Libre Venezuela receive a safely available Spanish marketplace query when appropriate. For `baseball glove`, a valid result is Alibaba `baseball glove`, Facebook/ML `guante de béisbol`.

Routing reuses existing BERA query-generation/translation infrastructure. It first chooses deterministic/original output. When translation is necessary and a configured translator exists, it performs at most one shared Venezuela-query generation that Facebook and Mercado Libre may reuse. Alibaba never inherits that translation merely because Venezuela providers need it. There is no translation loop. Failure/unavailability falls back to the original query with origin `FALLBACK`. Tests use fakes and make zero DeepL calls.

Diagnostics/export may expose `original_search_query`, `provider_query`, and `provider_query_origin`; the main UI continues to emphasize what the user entered.

## Facebook Caracas-area policy

The implementation will replace brittle single-string equality with an explicit, normalized, deterministic allowlist of reviewed Caracas metropolitan forms. Candidate forms for fixture evaluation are Caracas; Caracas, Distrito Capital; Distrito Capital; Municipio Libertador; context-qualified Libertador; Chacao; Baruta; El Hatillo; Petare; and context-qualified Municipio Sucre/Sucre, Miranda.

The policy MUST NOT accept all Venezuela, use arbitrary fuzzy matching, or accept ambiguous standalone place names that can refer elsewhere. Missing-location behavior remains unchanged unless evidence is documented in this design before implementation. False negatives remain possible for legitimate unlisted spellings; false positives are controlled through context-qualified entries and exact normalized membership. The final allowlist and normalization rules require fixture-based review under the open question, not a change to these constraints.

## Geographic and monetary provenance

Mercado Libre continues requiring truthful Venezuela evidence such as `siteId == MLV`, a Venezuela domain/permalink, Venezuela country evidence, or MLV product-ID evidence according to current policy; explicit foreign evidence is rejected. Result volume never justifies weakening provenance.

Money remains fail-closed: `$` alone is not USD and no implicit FX is introduced. Alibaba USD aggregates use only explicit compatible ISO USD; Facebook uses only its existing authorized Venezuela normalization; Mercado Libre combines only genuine compatible currency values.

An Alibaba listing with an unconfirmed source currency may remain visible, but USD aggregate fields stay unavailable. UI copy explains **Precio publicado disponible; moneda no confirmada.** and **Estadísticas USD no disponibles: moneda fuente no confirmada.** Any display fallback that labels unknown Alibaba currency as USD must be removed.

## Export, ratings, images, and session lifecycle

CSV emits one row per real canonical current-session marketplace listing, never one merged identity row per positional comparison. Presentation filters do not remove canonical session listings. Truthfully known fields may include original/provider query provenance and the seven provider metrics; unavailable fields remain unavailable rather than zero. Existing spreadsheet-formula injection protection and UTF-8 BOM remain mandatory.

Alibaba uses its own image and genuine `reviewScore`; Facebook uses its own primary scraped photo and no fabricated rating; Mercado Libre uses its own thumbnail and genuine `ratingAverage`. Relevance, opportunity, `supplierServiceScore`, and seller reputation tiers never become product stars.

**Nueva búsqueda** increments/changes generation and clears results, diagnostics, provider-query provenance, and exportable session data while retaining persistent tracking. A result tagged with an older generation cannot repopulate the new snapshot.

Single-market mode follows the identical pipeline, limits, metrics, query provenance, and no-retry rule for its one selected provider.

## Risks and trade-offs

- Bounded over-acquisition costs more records per run but avoids retries and improves the chance of filling visible positions after valid rejections.
- Facebook's hard cap of 5 offers no buffer at display 5, so fewer than five displayed results is expected when any candidate is rejected.
- Optional metrics improve truthfulness but require UI/export consumers to handle unknown values explicitly.
- Positional comparison improves generic search readability but requires strong type and copy boundaries to prevent accidental exact-association reuse.
- An explicit Caracas allowlist is auditable but needs maintenance as legitimate provider location forms appear.

## Open Questions

Only implementation-evidence details remain: justified adjustments to centralized Alibaba/ML 5/10/15 pools; the final unambiguous Caracas allowlist; and final compact Spanish diagnostic copy. All core semantics and safety invariants above are final.
