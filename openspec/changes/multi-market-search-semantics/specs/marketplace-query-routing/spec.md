# marketplace-query-routing Specification

## ADDED Requirements

### Requirement: Original and provider-specific queries retain provenance

Each search session SHALL retain `original_user_query` and `generation`. Each selected provider SHALL retain `provider_query`, `provider_query_origin`, and the provider-local market/geographic scope required to reproduce that search; allowed origins are `USER_ORIGINAL`, `DETERMINISTIC_GENERATED`, `TRANSLATED`, and `FALLBACK`. Venezuela providers SHALL default to **Toda Venezuela** and MAY support narrower city/market scopes. This provenance SHALL answer what the user searched, what each provider received, what scope it used, and which generation produced the result without creating a generic geospatial subsystem. Diagnostics and exports MAY expose these fields safely; the primary UI SHALL emphasize the user's entered query.

#### Scenario: Provider queries preserve original intent
- **GIVEN** the user searches `baseball glove`
- **WHEN** provider routing completes
- **THEN** the session retains `baseball glove` as the original query
- **AND** every selected provider records its actual query and origin

#### Scenario: Default provider-local scope is reproducible
- **GIVEN** Facebook Venezuela runs with its default Toda Venezuela scope
- **WHEN** its result is committed
- **THEN** the snapshot retains the original query, Facebook provider query and origin, Toda Venezuela scope, and generation

### Requirement: Query routing is marketplace-specific

Alibaba SHALL receive either the original query or an independently derived safe international query using existing query-generation infrastructure. Facebook Venezuela and Mercado Libre Venezuela SHALL receive a safely available Spanish marketplace query when appropriate. A Venezuela-localized query SHALL NOT leak into or silently translate Alibaba solely because Venezuela providers use it. Alibaba's actual query and origin SHALL be retained.

#### Scenario: Shared Spanish Venezuela query
- **GIVEN** original query `baseball glove`
- **AND** safe generated/translated query `guante de béisbol`
- **WHEN** all providers are selected
- **THEN** Alibaba receives `baseball glove`
- **AND** Facebook and Mercado Libre may both receive `guante de béisbol`

### Requirement: Existing translation infrastructure is reused once with fallback

The system SHALL reuse existing BERA translation/query-generation infrastructure and SHALL NOT add language-detection AI or a parallel translation architecture. Deterministic/original routing SHALL be attempted first. If translation is necessary and configured, at most one shared Venezuela marketplace query generation SHALL occur per search and MAY be reused by Facebook and Mercado Libre. Translation SHALL NOT loop. Routing SHALL follow the decision table in `design.md`: no derivation needed or output identical to original uses original/`USER_ORIGINAL`; a differing valid deterministic result uses `DETERMINISTIC_GENERATED`; a valid translation uses `TRANSLATED`; translator unavailable/timeout/failure, empty/invalid output, or failed technical-token preservation/validation uses original/`FALLBACK`.

#### Scenario: Translator unavailable
- **GIVEN** a Venezuela query would benefit from translation
- **AND** the translator is unavailable or fails
- **WHEN** routing completes
- **THEN** Facebook and Mercado Libre receive the original query as fallback
- **AND** origin is `FALLBACK`
- **AND** provider search can proceed without a translation retry loop

#### Scenario: Translator times out or fails
- **GIVEN** Venezuela localization is requested
- **AND** the configured translator times out or returns failure
- **WHEN** routing completes
- **THEN** the original query is used with `FALLBACK`
- **AND** no translation loop occurs

#### Scenario: Translation changes a protected technical token
- **GIVEN** the original query contains a technical token such as `21V` or `G102`
- **AND** translated output removes or alters that token
- **WHEN** existing technical-token validation rejects the output
- **THEN** the original query is used with `FALLBACK`

#### Scenario: Generated output equals original
- **GIVEN** valid generated output normalizes identically to the original query
- **WHEN** routing records provenance
- **THEN** the original query is used with `USER_ORIGINAL`

#### Scenario: Valid Venezuela translation succeeds
- **GIVEN** translated output is non-empty, valid, and preserves required technical tokens
- **WHEN** routing completes
- **THEN** Facebook and Mercado Libre may reuse it with `TRANSLATED`
- **AND** at most one shared Venezuela-localized generation occurred

### Requirement: Venezuela geographic scope is configurable and deterministic

Venezuela generic search SHALL default to **Toda Venezuela** and MAY offer supported narrower city/market scopes such as Caracas. Toda Venezuela SHALL still require truthful Venezuela evidence and reject explicit foreign evidence. Narrower scopes SHALL use normalized explicit reviewed identifiers/aliases and SHALL NOT use arbitrary fuzzy matches or ambiguous standalone terms. Missing/insufficient geographic evidence SHALL fail closed under provider policy.

#### Scenario: Toda Venezuela is the default
- **GIVEN** the user does not choose a narrower supported geographic scope
- **WHEN** a Venezuela provider query is created
- **THEN** its scope is Toda Venezuela

#### Scenario: Truthful Venezuela evidence passes country scope
- **GIVEN** Toda Venezuela is selected
- **AND** a candidate has truthful Venezuela evidence without explicit foreign evidence
- **WHEN** location policy evaluates it
- **THEN** it is not rejected merely for being outside Caracas

#### Scenario: Ambiguous standalone place is not fuzzy-matched
- **GIVEN** a narrower scope is selected
- **AND** a location contains an ambiguous token without required geographic context
- **WHEN** location policy evaluates it
- **THEN** arbitrary similarity does not cause acceptance

#### Scenario: Supported city scope uses reviewed aliases
- **GIVEN** the user selects a supported city scope such as Caracas
- **AND** a candidate has a reviewed unambiguous normalized location identifier for that scope
- **WHEN** location policy evaluates it
- **THEN** it passes the narrower scope check

### Requirement: Mercado Libre Venezuela provenance is not weakened

Mercado Libre candidates SHALL continue to require truthful Venezuela evidence under existing policy, such as MLV site ID, Venezuela domain/permalink, Venezuela country evidence, or MLV product-ID evidence. Explicit foreign marketplace evidence SHALL be rejected; acquisition targets SHALL NOT weaken this requirement.

#### Scenario: Foreign marketplace evidence overrides volume goals
- **GIVEN** a Mercado Libre candidate has explicit foreign marketplace evidence
- **WHEN** provider policy evaluates it
- **THEN** it is rejected even if the display maximum would otherwise remain unfilled
