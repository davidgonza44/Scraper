# bounded-provider-search Specification

## ADDED Requirements

### Requirement: Display limits represent per-provider visible maxima

The system SHALL interpret each supported positive UI value, including 10, as `display_limit`, the maximum usable listings displayed for each selected marketplace. A centralized finite `MAX_DISPLAY_LIMIT >= 10` SHALL reject unsupported, non-positive, or excessive values so the UI/API cannot request unbounded output. The control SHALL be labelled **Máximo por plataforma** or equivalent copy that communicates a maximum. It SHALL NOT treat this value as a raw acquisition count or a guaranteed count, and SHALL NOT fabricate or duplicate listings when fewer usable listings exist.

#### Scenario: Fewer usable listings than requested
- **GIVEN** `display_limit = 3`
- **AND** a selected provider has exactly two usable canonical candidates
- **WHEN** the provider result is displayed
- **THEN** `displayed = 2`
- **AND** no listing is fabricated or duplicated

#### Scenario: Display limit is centrally bounded
- **GIVEN** a requested value exceeds `MAX_DISPLAY_LIMIT`
- **WHEN** search intent is validated
- **THEN** validation rejects the unsupported value before acquisition begins
- **AND** no provider strategy receives an unbounded display request

### Requirement: Canonical session results are the frozen displayed prefix

The provider pipeline SHALL be acquired candidates → mapped/policy-evaluated candidates → ordered usable pool → canonical session results (`ordered_usable_pool[:display_limit]`) → presentation projections. After Z4, Alibaba SEARCH SHALL insert one provider-internal semantic-validation batch after safe mapping and before the usable pool freezes; only RELEVANT Alibaba Zen listings enter that pool. The acquisition buffer SHALL exist only to improve the chance of filling the display maximum. `usable` SHALL count the ordered usable pool; `displayed` SHALL count the canonical session result prefix. Comparison, summaries, totals, and export SHALL consume only that frozen prefix.

#### Scenario: Over-acquisition produces only three session results
- **GIVEN** `display_limit = 3`
- **AND** `acquisition_requested = 10`
- **AND** the ordered usable pool contains 8 candidates
- **WHEN** the provider result is committed
- **THEN** `usable = 8`
- **AND** `displayed = 3`
- **AND** canonical session results contain the first 3 candidates
- **AND** that provider contributes exactly 3 CSV rows

### Requirement: Acquisition budgets and actual requested work are distinct

The system SHALL use only `display_limit`, `acquisition_budget`, and `acquisition_requested` for these semantics. `acquisition_budget` is the centralized finite strategy ceiling returned by `AcquisitionBudgetPolicy`; `acquisition_requested` sums candidate limits of internal acquisitions actually executed and excludes unused budget. No third acquisition-volume value SHALL exist. Strategies stop early only when ordering and coverage remain truthful; on exhaustion they return fewer results.

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

#### Scenario: Acquisition stops early when filled
- **GIVEN** a provider strategy has collected enough unique valid candidates to fill `display_limit`
- **AND** no additional bounded acquisition is required to determine canonical aggregate order
- **AND** early termination does not overstate the declared geographic scope
- **WHEN** the strategy evaluates its termination condition
- **THEN** it performs no further internal acquisition

#### Scenario: Bounded budget is exhausted before display limit
- **GIVEN** the finite internal-acquisition or aggregate candidate budget is exhausted
- **AND** fewer than `display_limit` unique valid candidates exist
- **WHEN** the logical operation completes
- **THEN** it returns the available candidates
- **AND** it does not continue indefinitely or fabricate results

#### Scenario: Actual requested work excludes unused budget
- **GIVEN** `acquisition_budget = 30`
- **AND** two internal acquisitions each request 5 candidates
- **AND** the strategy safely terminates before using the remaining budget
- **WHEN** metrics are finalized
- **THEN** `acquisition_requested = 10`
- **AND** Pedidos al proveedor reports 10, not 30

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

#### Scenario: Nationwide partitions are deduplicated and ordered deterministically
- **GIVEN** a nationwide provider search uses multiple geographic partitions
- **WHEN** the provider constructs its usable pool
- **THEN** candidates are deduplicated by documented stable provider identity
- **AND** they are combined using the documented deterministic BERA aggregate provider ordering
- **AND** partition concatenation is not represented as provider-native global rank

#### Scenario: Duplicate across partitions appears once
- **GIVEN** the same stable provider listing identity appears in two geographic partitions
- **WHEN** aggregate ordering is constructed
- **THEN** the listing appears exactly once
- **AND** documented deterministic precedence selects the retained representation

#### Scenario: Similar identity-less Alibaba candidates remain distinct
- **GIVEN** two valid Alibaba candidates lack a usable product ID and any other documented stable identity
- **AND** their titles, images, or prices appear similar
- **WHEN** the aggregate pool is constructed
- **THEN** both candidates remain distinct and usable
- **AND** no title, image, price, rank, or fuzzy identity is invented

### Requirement: Provider metrics are precise and unknown-safe

The implementation SHALL evolve existing metrics into one contract exposing `display_requested`, finite `acquisition_budget`, actual `acquisition_requested`, optional aggregate `fetched`/`mapped`/`rejected`, `usable`, and `displayed`. Every boundary, including identity-aware deduplication, SHALL be documented. No arithmetic identity is required; unknown remains unknown. Provider-specific reasons remain optional truthful detail.

#### Scenario: Unobservable fetched count
- **GIVEN** an adapter cannot observe raw records received
- **WHEN** metrics are constructed
- **THEN** `fetched` is unknown
- **AND** diagnostics show `No disponible`
- **AND** `fetched` is not reported as zero

#### Scenario: Failed executed acquisition keeps optional aggregates unknown
- **GIVEN** one executed internal acquisition reports `candidate_limit = 5`, `fetched = 5`, `mapped = 5`, and `rejected = 0`
- **AND** a later executed internal acquisition with `candidate_limit = 5` raises before supplying those counts
- **WHEN** aggregate metrics are finalized
- **THEN** `acquisition_requested = 10`
- **AND** aggregate `fetched`, `mapped`, and `rejected` are unknown
- **AND** those aggregates are not reported as the successful-step counts or as zero

### Requirement: Provider status derives from execution and canonical usability

The system SHALL classify a completed logical provider operation with at least one usable listing as `SUCCESS`, a normally completed logical operation with zero usable listings as `EMPTY`, and a failed logical operation as `ERROR`. Presentation filters SHALL NOT alter this status.

#### Scenario: Successful Alibaba execution with no fetched records
- **GIVEN** the Alibaba actor execution completes normally
- **AND** `fetched = 0`
- **WHEN** status is derived
- **THEN** status is `EMPTY`
- **AND** it is not `ERROR`

#### Scenario: Completed Alibaba Zen validator with zero RELEVANT is EMPTY
- **GIVEN** Alibaba Zen mapping completed
- **AND** the semantic validator completed a valid batch
- **AND** `semantic_relevant = 0`
- **WHEN** status is derived
- **THEN** status is `EMPTY`
- **AND** coverage is not set to `PARTIAL`

#### Scenario: Alibaba Zen validator outage is ERROR
- **GIVEN** mapped Alibaba Zen candidates exist
- **AND** the semantic validator is unavailable or returns a wholly invalid batch
- **AND** no candidate is validated as RELEVANT
- **WHEN** status is derived
- **THEN** status is `ERROR`
- **AND** it is not a silent `SUCCESS`

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

Generic search SHALL reject candidates only for documented deterministic provider-integrity/safety policy. A missing field rejects only when required by that provider's existing generic mapper/integrity contract. Alibaba may accept a title-bearing product without ID, URL, image, rating, or reputation; Mercado Libre retains required external ID/title and MLV evidence without making permalink universal; Facebook retains priced-only and its required integrity fields. Malformed/unmappable records, explicit foreign evidence, stable-identity duplicates, and existing justified violations remain rejectable. Cross-market similarity, category/title similarity, price attractiveness, reputation, opportunity, or relevance thresholds SHALL NOT reject. Optional metadata absence SHALL NOT reject. The sole exception is provider-internal compatibility validation between the user query and a listing acquired by Alibaba Zen, as specified in `alibaba-zen-semantic-validation`. That exception SHALL NOT reject Facebook or Mercado Libre candidates, SHALL NOT infer cross-market identity, and SHALL NOT treat RELEVANT as authenticity.

#### Scenario: Alibaba optional identity and URL are absent
- **GIVEN** an Alibaba product has the title required by its existing mapper
- **AND** `product_id`, `product_url`, image, rating, and reputation are absent
- **WHEN** provider-integrity validity is evaluated
- **THEN** those optional absences alone do not reject the product

#### Scenario: Mercado Libre has valid provenance without permalink
- **GIVEN** a Mercado Libre candidate has its required external ID and title
- **AND** valid MLV/Venezuela evidence exists through the current contract
- **AND** permalink is absent
- **WHEN** provider-integrity validity is evaluated
- **THEN** permalink absence alone does not reject the candidate

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

#### Scenario: Optional image and rating are missing
- **GIVEN** a candidate passes all required provider-integrity and safety policy
- **AND** its optional image and rating are missing
- **WHEN** validity is determined
- **THEN** the candidate remains usable

#### Scenario: Cross-market relevance cannot reject a provider result
- **GIVEN** a valid provider candidate has low similarity or relevance to candidates from another marketplace
- **WHEN** generic-search validity is determined
- **THEN** it remains usable in its provider's canonical order

#### Scenario: Alibaba Zen explicit contradiction may be excluded
- **GIVEN** a mapped Alibaba Zen listing explicitly contradicts the user query
- **AND** the dedicated semantic validator returns IRRELEVANT with a closed reason code
- **WHEN** the usable pool is frozen
- **THEN** that listing is excluded from canonical results
- **AND** Facebook and Mercado Libre candidates are unchanged

#### Scenario: Alibaba title-token score still cannot reject
- **GIVEN** a mapped Alibaba Zen listing has a low deterministic title-token relevance score
- **AND** the semantic validator did not return IRRELEVANT
- **WHEN** generic-search validity is determined
- **THEN** the low score alone does not reject the listing

### Requirement: External-call budgets are enforced by implementation and tests

Implementation and automated tests SHALL make zero live marketplace provider calls, zero DeepL calls, and zero MiniMax calls. Tests SHALL use offline fixtures/fakes. Live smoke calls SHALL NOT occur unless explicitly authorized after the implementation pull request exists.

#### Scenario: Automated suite runs offline
- **WHEN** the automated suite exercises multi-market and translated-query paths
- **THEN** marketplace, DeepL, and MiniMax network call counts are all zero
