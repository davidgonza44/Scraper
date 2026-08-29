# search-session-export-safety Specification

## ADDED Requirements

### Requirement: CSV exports one row per real canonical marketplace listing

CSV SHALL contain one row per real listing in each provider's frozen canonical session result prefix. Extra usable candidates remaining in the acquisition buffer SHALL NOT be exported. After Z5, Alibaba REVIEW and IRRELEVANT listings SHALL NOT be exported. CSV SHALL NOT merge positionally aligned candidates into a single identity record, and presentation projections SHALL neither remove nor add canonical session results. Marketplace identity SHALL remain explicit.

#### Scenario: Positional row has three candidates
- **GIVEN** one positional comparison row contains Alibaba, Facebook, and Mercado Libre listings
- **WHEN** CSV is exported
- **THEN** it contains three marketplace listing rows rather than one merged identity row

#### Scenario: Alibaba REVIEW listing is not exported
- **GIVEN** an Alibaba Zen run produced one RELEVANT listing and one REVIEW listing
- **WHEN** CSV is exported
- **THEN** only the RELEVANT canonical listing is exported
- **AND** the REVIEW listing is absent

#### Scenario: Acquisition buffer has more usable candidates than display maximum
- **GIVEN** `acquisition_requested = 10`
- **AND** the ordered usable pool has 8 candidates
- **AND** `display_limit = 3`
- **WHEN** CSV is exported
- **THEN** `provider_usable = 8`
- **AND** `provider_displayed = 3`
- **AND** exactly the 3 frozen canonical session results are exported for that provider

### Requirement: Exported provenance and metrics are truthful

Every CSV row SHALL contain columns `original_user_query`, `provider_query`, `provider_query_origin`, `requested_geographic_scope`, `effective_geographic_scope`, `coverage_status`, `generation`, `display_requested`, `acquisition_budget`, and `acquisition_requested`. The defined provider metric columns `provider_fetched`, `provider_mapped`, `provider_rejected`, `provider_usable`, and `provider_displayed` SHALL also remain present. After Z5, Alibaba SEARCH export SHALL also retain `semantic_relevant`, `semantic_irrelevant`, `semantic_review`, and `semantic_validation_status` when the contract applies; unknown values and `not_run` stay blank/unavailable. Unknown/unobservable values are blank/unavailable, never numeric zero. Geographic columns remain present for non-applicable providers and use the documented blank/not-applicable representation. Semantic-validation columns MUST NOT reuse `coverage_status`.

#### Scenario: Alibaba-only export retains required provenance columns
- **GIVEN** an Alibaba-only settled session where geographic coverage is not applicable
- **WHEN** CSV is exported
- **THEN** every required query, scope, generation, limit, budget, requested-work, and provider-metric column is present
- **AND** geographic values use the documented blank/not-applicable representation

#### Scenario: Provider query origin and generation cannot be omitted
- **WHEN** any canonical session result is exported
- **THEN** `provider_query_origin` and `generation` columns are present
- **AND** their known values are retained

#### Scenario: Export retains requested and effective scope
- **GIVEN** requested scope is Toda Venezuela
- **AND** effective scope is partial/broad Venezuela with coverage `PARTIAL`
- **WHEN** canonical session results are exported
- **THEN** requested scope, effective scope, and coverage status remain distinguishable

#### Scenario: Unestablished error coverage exports as unavailable
- **GIVEN** a provider is `ERROR` before any truthful coverage exists
- **WHEN** the settled session is exported
- **THEN** `effective_geographic_scope` and `coverage_status` are unavailable/blank according to the CSV contract
- **AND** neither is fabricated as `COMPLETE` or `PARTIAL`

#### Scenario: Some provider metrics are unknown
- **GIVEN** a current-session listing whose provider fetched count is unobservable
- **WHEN** it is exported
- **THEN** fetched is represented as unavailable/blank according to the CSV contract
- **AND** it is not written as numeric zero

### Requirement: Existing CSV safety remains intact

CSV output SHALL retain spreadsheet-formula injection protection and UTF-8 BOM behavior.

#### Scenario: Formula-like title is exported
- **GIVEN** a listing field begins with a spreadsheet formula trigger
- **WHEN** CSV is created
- **THEN** the existing injection mitigation is applied
- **AND** the file retains its UTF-8 BOM

### Requirement: Export waits for all selected providers to settle

Export SHALL remain disabled until every selected provider reaches terminal `SUCCESS`, `EMPTY`, or `ERROR`. Once settled, completed sessions with `PARTIAL` coverage or provider errors MAY export their canonical results.

#### Scenario: One selected provider is still running
- **GIVEN** one selected provider has committed results
- **AND** another selected provider is not terminal
- **WHEN** export availability is evaluated
- **THEN** export remains disabled

### Requirement: New search clears transient canonical session state

**Nueva búsqueda** SHALL clear current results, diagnostics, provider-query provenance, and exportable session data while preserving persistent tracking. It SHALL advance or replace the search generation before new responses may commit.

#### Scenario: User starts a new search
- **GIVEN** the current session contains displayed results and export rows
- **WHEN** the user activates **Nueva búsqueda**
- **THEN** those results, diagnostics, query provenance, and export rows are cleared
- **AND** persistent tracking remains

### Requirement: Stale responses cannot repopulate a newer session

Every asynchronous routing, translation, and provider continuation SHALL compare its initiating generation before committing provenance, starting downstream provider work, or modifying session/export state. A previous-generation continuation is ignored.

#### Scenario: Previous-generation response arrives late
- **GIVEN** generation A started a provider call
- **AND** the user created generation B before A returned
- **WHEN** A's response arrives
- **THEN** generation B remains unchanged
- **AND** generation B's query provenance and export membership remain unchanged

#### Scenario: Stale translation cannot launch provider work
- **GIVEN** generation A awaits translation
- **AND** generation B replaces it
- **WHEN** A's translation completes
- **THEN** it cannot commit provider-query provenance
- **AND** it cannot start a provider operation
