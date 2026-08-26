# marketplace-query-routing Specification

## ADDED Requirements

### Requirement: Original and provider-specific queries retain provenance

Each search session SHALL retain `original_user_query`. Each selected provider SHALL retain `provider_query` and `query_origin`, whose allowed values are `USER_ORIGINAL`, `DETERMINISTIC_GENERATED`, `TRANSLATED`, and `FALLBACK`. Diagnostics and exports MAY expose these fields; the primary UI SHALL continue to emphasize the user's entered query.

#### Scenario: Provider queries preserve original intent
- **GIVEN** the user searches `baseball glove`
- **WHEN** provider routing completes
- **THEN** the session retains `baseball glove` as the original query
- **AND** every selected provider records its actual query and origin

### Requirement: Query routing is marketplace-specific

Alibaba SHALL receive the original/international query. Facebook Venezuela and Mercado Libre Venezuela SHALL receive a safely available Spanish marketplace query when appropriate. A Venezuela-specific query SHALL NOT leak into Alibaba solely because Venezuela providers use it.

#### Scenario: Shared Spanish Venezuela query
- **GIVEN** original query `baseball glove`
- **AND** safe generated/translated query `guante de béisbol`
- **WHEN** all providers are selected
- **THEN** Alibaba receives `baseball glove`
- **AND** Facebook and Mercado Libre may both receive `guante de béisbol`

### Requirement: Existing translation infrastructure is reused once with fallback

The system SHALL reuse existing BERA translation/query-generation infrastructure and SHALL NOT create a parallel translation architecture. Deterministic/original routing SHALL be attempted first. If translation is necessary and configured, at most one shared Venezuela marketplace query generation SHALL occur per search and MAY be reused by Facebook and Mercado Libre. Translation SHALL NOT loop. Unavailable or failed translation SHALL fall back to the original query with truthful origin.

#### Scenario: Translator unavailable
- **GIVEN** a Venezuela query would benefit from translation
- **AND** the translator is unavailable or fails
- **WHEN** routing completes
- **THEN** Facebook and Mercado Libre receive the original query as fallback
- **AND** origin is `FALLBACK`
- **AND** provider search can proceed without a translation retry loop

### Requirement: Facebook Caracas scope uses an explicit deterministic policy

Facebook generic search SHALL use a normalized, explicit reviewed allowlist for Caracas metropolitan locations. It SHALL NOT accept all Venezuela, arbitrary fuzzy matches, or ambiguous standalone terms that may refer to other regions. Missing-location behavior SHALL remain compatible with current behavior unless evidence and rationale are first documented in the design.

#### Scenario: Explicit Caracas-area form is accepted
- **GIVEN** a listing location normalizes to a reviewed unambiguous allowlist entry such as `Caracas, Distrito Capital` or a context-qualified municipality
- **WHEN** location policy evaluates it
- **THEN** the location passes the Caracas-area check

#### Scenario: Broad Venezuela location is not enough
- **GIVEN** a listing says only that it is in Venezuela outside a reviewed Caracas-area form
- **WHEN** location policy evaluates it
- **THEN** it is rejected

#### Scenario: Ambiguous standalone place is not fuzzy-matched
- **GIVEN** a location contains an ambiguous token without required geographic context
- **WHEN** location policy evaluates it
- **THEN** arbitrary similarity does not cause acceptance

### Requirement: Mercado Libre Venezuela provenance is not weakened

Mercado Libre candidates SHALL continue to require truthful Venezuela evidence under existing policy, such as MLV site ID, Venezuela domain/permalink, Venezuela country evidence, or MLV product-ID evidence. Explicit foreign marketplace evidence SHALL be rejected; acquisition targets SHALL NOT weaken this requirement.

#### Scenario: Foreign marketplace evidence overrides volume goals
- **GIVEN** a Mercado Libre candidate has explicit foreign marketplace evidence
- **WHEN** provider policy evaluates it
- **THEN** it is rejected even if the display maximum would otherwise remain unfilled
