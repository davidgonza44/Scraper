# search-session-export-safety Specification

## ADDED Requirements

### Requirement: CSV exports one row per real canonical marketplace listing

CSV SHALL contain one row per real canonical current-session marketplace listing. It SHALL NOT merge positionally aligned candidates into a single identity record, and presentation filters SHALL NOT remove canonical listings from export. Marketplace identity SHALL remain explicit.

#### Scenario: Positional row has three candidates
- **GIVEN** one positional comparison row contains Alibaba, Facebook, and Mercado Libre listings
- **WHEN** CSV is exported
- **THEN** it contains three marketplace listing rows rather than one merged identity row

### Requirement: Exported provenance and metrics are truthful

CSV MAY include `original_search_query`, `provider_query`, `provider_query_origin`, `display_requested`, `acquisition_requested`, `provider_fetched`, `provider_mapped`, `provider_rejected`, `provider_usable`, and `provider_displayed`. It SHALL include a value only when genuinely known and SHALL NOT invent zero for unavailable stages.

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

### Requirement: New search clears transient canonical session state

**Nueva búsqueda** SHALL clear current results, diagnostics, provider-query provenance, and exportable session data while preserving persistent tracking. It SHALL advance or replace the search generation before new responses may commit.

#### Scenario: User starts a new search
- **GIVEN** the current session contains displayed results and export rows
- **WHEN** the user activates **Nueva búsqueda**
- **THEN** those results, diagnostics, query provenance, and export rows are cleared
- **AND** persistent tracking remains

### Requirement: Stale responses cannot repopulate a newer session

Every asynchronous provider response SHALL be associated with its initiating search generation. A response from a previous generation SHALL be ignored and SHALL NOT modify results, diagnostics, provenance, totals, or export data for the current generation.

#### Scenario: Previous-generation response arrives late
- **GIVEN** generation A started a provider call
- **AND** the user created generation B before A returned
- **WHEN** A's response arrives
- **THEN** generation B remains unchanged
