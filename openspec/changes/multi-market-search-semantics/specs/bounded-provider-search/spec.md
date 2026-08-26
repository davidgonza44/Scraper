# bounded-provider-search Specification

## ADDED Requirements

### Requirement: Display limits represent per-provider visible maxima

The system SHALL interpret each supported positive UI value, including 10, as `display_limit`, the maximum usable listings displayed for each selected marketplace. The control SHALL be labelled **Máximo por plataforma** or equivalent copy that communicates a maximum. It SHALL NOT treat this value as a raw acquisition count or a guaranteed count, and SHALL NOT fabricate or duplicate listings when fewer usable listings exist.

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

The system SHALL represent aggregate `acquisition_limit` separately from `display_limit`. A centralized deterministic provider strategy SHALL scale the bounded acquisition budget from provider, requested display maximum, selected geographic scope, and provider hard caps; it SHALL support display values including 10 and request at least that many candidates when the provider supports it. The strategy MAY divide the budget into multiple bounded internal acquisitions. Alibaba's maximum 500 SHALL NOT be used as a normal pool. Exact functions/caps SHALL be documented in the design from implementation evidence before code implementation and remain centralized and deterministic.

#### Scenario: Invalid first candidate within one pool
- **GIVEN** `display_limit = 1`
- **AND** the bounded acquisition pool contains an invalid first candidate and a valid later candidate
- **WHEN** provider policy evaluates the original pool
- **THEN** the valid later candidate is displayed
- **AND** `displayed = 1`
- **AND** exactly one logical provider search operation occurred

#### Scenario: Display ten is supported
- **GIVEN** `display_limit = 10`
- **WHEN** a provider that supports at least ten candidates computes its bounded strategy
- **THEN** aggregate `acquisition_requested >= 10`
- **AND** at most the first ten ordered usable candidates become canonical session results

### Requirement: Generic search executes one logical operation per selected provider and generation

In generic **Búsquedas**, the orchestrator SHALL start exactly one logical provider search operation for each selected, configured, startable provider per generation. A provider-owned deterministic strategy MAY perform multiple bounded Actor/API acquisitions internally for scope coverage, partitioning, or pagination; these are parts of the same logical operation, not retries. After strategy completion, the orchestrator SHALL NOT start a second logical operation to refill mapping/policy losses. This rule SHALL NOT redefine CLI collect, tracking, refresh, history, exact-product, specialized workflow, or provider-transport behavior outside generic **Búsquedas**.

#### Scenario: Only two usable candidates exist
- **GIVEN** `display_limit = 3`
- **AND** one logical provider search operation exhausts its bounded strategy with two usable candidates
- **WHEN** orchestration completes
- **THEN** `displayed = 2`
- **AND** a second logical provider search operation is not started

#### Scenario: Single-market bounded acquisition
- **GIVEN** only Mercado Libre is selected
- **AND** `display_limit = 3`
- **WHEN** search runs
- **THEN** one logical Mercado Libre search operation runs its bounded acquisition strategy
- **AND** displays at most three usable listings
- **AND** starts no second logical provider search operation

#### Scenario: Mapping and rejection loss does not trigger a second logical operation
- **GIVEN** a provider's one bounded acquisition returns candidates that are lost during mapping or policy rejection
- **WHEN** fewer than `display_limit` usable candidates remain
- **THEN** the orchestrator launches no second logical provider search operation for that provider and generation

#### Scenario: Broad scope uses multiple internal acquisitions
- **GIVEN** Toda Venezuela requires multiple bounded geographic partitions or pages for a provider
- **WHEN** its deterministic strategy executes those internal Actor/API acquisitions
- **THEN** they count as one logical provider search operation
- **AND** they are not classified as retries
- **AND** the strategy terminates at its documented bound

### Requirement: Provider metrics are precise and unknown-safe

The implementation SHALL evolve/consolidate existing `ProviderAcquisitionMetrics` and provider-specific metrics into one run contract exposing `display_requested`, aggregate `acquisition_requested` across internal acquisitions, optional aggregate `fetched`, optional `mapped`, optional `rejected`, `usable`, and `displayed` according to `design.md`, rather than maintain competing sources of truth. Every emitted counter SHALL document its measurement boundary, including deduplication across partitions/pages. No arithmetic identity between fetched, mapped, rejected, and usable is required. An unobservable metric SHALL be unknown and render **No disponible**, never zero solely because it cannot be observed. Provider-specific rejection counters SHALL remain optional truthful detail.

#### Scenario: Unobservable fetched count
- **GIVEN** an adapter cannot observe raw records received
- **WHEN** metrics are constructed
- **THEN** `fetched` is unknown
- **AND** diagnostics show `No disponible`
- **AND** `fetched` is not reported as zero

### Requirement: Provider status derives from execution and canonical usability

The system SHALL classify a completed logical provider operation with at least one usable listing as `SUCCESS`, a normally completed logical operation with zero usable listings as `EMPTY`, and a failed logical operation as `ERROR`. Presentation filters SHALL NOT alter this status.

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
- **AND** only one logical provider search operation occurs

#### Scenario: Later valid Mercado Libre Venezuela record
- **GIVEN** the first acquired record lacks MLV/Venezuela evidence
- **AND** a later record contains valid MLV evidence
- **WHEN** policy validation runs
- **THEN** the first record is rejected
- **AND** the later record may be displayed
- **AND** only one logical provider search operation occurs

### Requirement: External-call budgets are enforced by implementation and tests

Implementation and automated tests SHALL make zero live marketplace provider calls, zero DeepL calls, and zero MiniMax calls. Tests SHALL use offline fixtures/fakes. Live smoke calls SHALL NOT occur unless explicitly authorized after the implementation pull request exists.

#### Scenario: Automated suite runs offline
- **WHEN** the automated suite exercises multi-market and translated-query paths
- **THEN** marketplace, DeepL, and MiniMax network call counts are all zero
