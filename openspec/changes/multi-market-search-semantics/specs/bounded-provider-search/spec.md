# bounded-provider-search Specification

## ADDED Requirements

### Requirement: Display limits represent per-provider visible maxima

The system SHALL interpret UI values 1, 3, and 5 as `display_limit`, the maximum usable listings displayed for each selected marketplace. The control SHALL be labelled **Máximo por plataforma** or equivalent copy that communicates a maximum. It SHALL NOT treat this value as a raw acquisition count or a guaranteed count, and SHALL NOT fabricate or duplicate listings when fewer usable listings exist.

#### Scenario: Fewer usable listings than requested
- **GIVEN** `display_limit = 3`
- **AND** a selected provider has exactly two usable canonical candidates
- **WHEN** the provider result is displayed
- **THEN** `displayed = 2`
- **AND** no listing is fabricated or duplicated

### Requirement: Canonical session results are the frozen displayed prefix

The provider pipeline SHALL be acquired candidates → mapped/policy-evaluated candidates → ordered usable pool → canonical session results (`ordered_usable_pool[:display_limit]`) → presentation projections. The acquisition buffer SHALL exist only to improve the chance of filling the display maximum. `usable` SHALL count the ordered usable pool; `displayed` SHALL count the canonical session result prefix. Comparison, summaries, totals, and export SHALL consume only that frozen prefix.

#### Scenario: Over-acquisition produces only three session results
- **GIVEN** `display_limit = 3`
- **AND** `acquisition_requested = 10`
- **AND** the ordered usable pool contains 8 candidates
- **WHEN** the provider result is committed
- **THEN** `usable = 8`
- **AND** `displayed = 3`
- **AND** canonical session results contain the first 3 candidates
- **AND** that provider contributes exactly 3 CSV rows

### Requirement: Acquisition limits are explicit, centralized, and bounded

The system SHALL represent `acquisition_limit` separately from `display_limit`. A centralized deterministic policy SHALL initially map Alibaba and Mercado Libre display limits 1/3/5 to acquisition limits 5/10/15, and Facebook display limits 1/3/5 to acquisition limit 5. Every value SHALL remain capped by the provider hard maximum. Alibaba's maximum 500 SHALL NOT be used as a normal acquisition pool. Any evidence-based adjustment SHALL be documented in the design before implementation and SHALL remain centralized and bounded.

#### Scenario: Invalid first candidate within one pool
- **GIVEN** `display_limit = 1`
- **AND** the bounded acquisition pool contains an invalid first candidate and a valid later candidate
- **WHEN** provider policy evaluates the original pool
- **THEN** the valid later candidate is displayed
- **AND** `displayed = 1`
- **AND** exactly one provider execution occurred

#### Scenario: Facebook has no buffer at display five
- **GIVEN** Facebook `display_limit = 5`
- **WHEN** the policy computes the acquisition request
- **THEN** `acquisition_requested = 5`
- **AND** diagnostics/design communicate that the current hard cap provides no additional rejection buffer

### Requirement: Generic search executes one acquisition per selected provider and generation

In generic **Búsquedas**, Alibaba, Facebook, and Mercado Libre SHALL each have at most one marketplace acquisition execution per selected provider per search generation. A marketplace acquisition execution means one logical externally initiated Actor run, API marketplace search request, or equivalent provider search operation that obtains that provider's bounded pool. In single-market generic search, the selected provider has the same limit. The system SHALL NOT launch a second acquisition execution to refill mapping/policy losses. This rule SHALL NOT redefine CLI collect, tracking, refresh, history, exact-product, specialized workflow, or internal provider-transport behavior outside generic **Búsquedas**.

#### Scenario: Only two usable candidates exist
- **GIVEN** `display_limit = 3`
- **AND** one provider execution exhausts its bounded pool with two usable candidates
- **WHEN** orchestration completes
- **THEN** `displayed = 2`
- **AND** the provider is not executed again

#### Scenario: Single-market bounded acquisition
- **GIVEN** only Mercado Libre is selected
- **AND** `display_limit = 3`
- **WHEN** search runs
- **THEN** one Mercado Libre execution requests its bounded candidate pool
- **AND** displays at most three usable listings
- **AND** performs no retry

#### Scenario: Mapping and rejection loss does not trigger refill execution
- **GIVEN** a provider's one bounded acquisition returns candidates that are lost during mapping or policy rejection
- **WHEN** fewer than `display_limit` usable candidates remain
- **THEN** no second Actor/API marketplace search acquisition is launched for that provider and generation

### Requirement: Provider metrics are precise and unknown-safe

The implementation SHALL evolve/consolidate existing `ProviderAcquisitionMetrics` and provider-specific metrics into one run contract exposing `display_requested`, `acquisition_requested`, optional `fetched`, optional `mapped`, optional `rejected`, `usable`, and `displayed` according to `design.md`, rather than maintain competing sources of truth. Every emitted counter SHALL document its measurement boundary. No arithmetic identity between fetched, mapped, rejected, and usable is required. An unobservable metric SHALL be unknown and render **No disponible**, never zero solely because it cannot be observed. Provider-specific rejection counters SHALL remain optional truthful detail.

#### Scenario: Unobservable fetched count
- **GIVEN** an adapter cannot observe raw records received
- **WHEN** metrics are constructed
- **THEN** `fetched` is unknown
- **AND** diagnostics show `No disponible`
- **AND** `fetched` is not reported as zero

### Requirement: Provider status derives from execution and canonical usability

The system SHALL classify a completed provider execution with at least one usable listing as `SUCCESS`, a normally completed execution with zero usable listings as `EMPTY`, and a failed execution as `ERROR`. Presentation filters SHALL NOT alter this status.

#### Scenario: Successful Alibaba execution with no fetched records
- **GIVEN** the Alibaba actor execution completes normally
- **AND** `fetched = 0`
- **WHEN** status is derived
- **THEN** status is `EMPTY`
- **AND** it is not `ERROR`

#### Scenario: Presentation filter hides a usable result
- **GIVEN** Mercado Libre completed with `usable = 1`
- **AND** a relevance presentation filter hides that listing in another view
- **WHEN** provider status is read
- **THEN** it remains `SUCCESS`

#### Scenario: Selected provider is not configured
- **GIVEN** a selected provider lacks required configuration or credentials and cannot execute
- **WHEN** its outcome is derived
- **THEN** status is `ERROR`
- **AND** status is not `EMPTY`
- **AND** diagnostics expose no credentials, raw configuration, tokens, sensitive values, or stack trace

### Requirement: Provider-specific validation remains fail-closed

Facebook generic search SHALL remain priced-only; Free/Gratis, zero/missing/invalid price, or an image without a valid price SHALL NOT become usable. Mercado Libre SHALL retain Venezuela evidence requirements and reject explicit foreign evidence. Monetary aggregation SHALL preserve `$` alone is not USD, no implicit FX, explicit compatible ISO USD for Alibaba, existing authorized Facebook normalization, and genuine compatible currency statistics for Mercado Libre.

#### Scenario: Facebook mixed acquisition pool
- **GIVEN** the Facebook pool contains a Free/Gratis listing, an invalid-price listing, and a valid priced listing
- **WHEN** policy validation runs
- **THEN** the first two are rejected for truthful reasons
- **AND** the valid listing may fill the display position
- **AND** only one provider execution occurs

#### Scenario: Later valid Mercado Libre Venezuela record
- **GIVEN** the first acquired record lacks MLV/Venezuela evidence
- **AND** a later record contains valid MLV evidence
- **WHEN** policy validation runs
- **THEN** the first record is rejected
- **AND** the later record may be displayed
- **AND** only one provider execution occurs

### Requirement: External-call budgets are enforced by implementation and tests

Implementation and automated tests SHALL make zero live marketplace provider calls, zero DeepL calls, and zero MiniMax calls. Tests SHALL use offline fixtures/fakes. Live smoke calls SHALL NOT occur unless explicitly authorized after the implementation pull request exists.

#### Scenario: Automated suite runs offline
- **WHEN** the automated suite exercises multi-market and translated-query paths
- **THEN** marketplace, DeepL, and MiniMax network call counts are all zero
