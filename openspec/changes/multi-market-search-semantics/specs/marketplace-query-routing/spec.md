# marketplace-query-routing Specification

## ADDED Requirements

### Requirement: Original and provider-specific queries retain provenance

Each session SHALL retain `requested_geographic_scope`; provider results separately retain optional `effective_geographic_scope` and optional `coverage_status`. Established coverage is `COMPLETE` or `PARTIAL`. When an `ERROR` occurs before truthful coverage exists, effective scope and coverage are unavailable and render **No disponible**; they MUST NOT be forced to either enum value or override error semantics.

#### Scenario: Configuration error has no established coverage
- **GIVEN** requested scope is Toda Venezuela
- **AND** provider configuration is missing so no acquisition starts
- **WHEN** the provider result is recorded
- **THEN** status is `ERROR`
- **AND** effective scope is unavailable
- **AND** coverage status is unavailable
- **AND** diagnostics render `No disponible` without exposing configuration

#### Scenario: Failure before first successful acquisition has no partial coverage
- **GIVEN** a provider operation fails before any successful acquisition establishes scope
- **WHEN** its result is recorded
- **THEN** status is `ERROR`
- **AND** coverage is unavailable, not `PARTIAL`

#### Scenario: Provider queries preserve original intent
- **GIVEN** the user searches `baseball glove`
- **WHEN** provider routing completes
- **THEN** the session retains `baseball glove` as the original query
- **AND** every selected provider records its actual query and origin

#### Scenario: Provider-local scope is reproducible
- **GIVEN** Facebook completes truthful nationwide coverage for a requested Toda Venezuela scope
- **WHEN** its result is committed
- **THEN** the snapshot retains the original query, Facebook provider query/origin, requested Toda Venezuela, effective Toda Venezuela, coverage `COMPLETE`, and generation

#### Scenario: Requested and effective scope are distinct
- **GIVEN** requested scope is Toda Venezuela
- **AND** some required partitions fail while a proper subset completes with useful results
- **WHEN** the provider result commits
- **THEN** requested scope remains Toda Venezuela
- **AND** effective scope records partial/broad Venezuela coverage
- **AND** coverage status is `PARTIAL`
- **AND** provider status is `SUCCESS`

### Requirement: Query routing is marketplace-specific

Alibaba SHALL receive either the original query or an independently derived safe international query using existing query-generation infrastructure. After Z4, that Alibaba query is the single normalized `keywords` value sent to Zen; local category resolution may add `category` only when exact and sufficiently safe, and SHALL NOT replace or silently rewrite the query. Facebook Venezuela and Mercado Libre Venezuela SHALL receive a safely available Spanish marketplace query when appropriate. A Venezuela-localized query SHALL NOT leak into or silently translate Alibaba solely because Venezuela providers use it. Alibaba's actual query and origin SHALL be retained.

#### Scenario: Shared Spanish Venezuela query
- **GIVEN** original query `baseball glove`
- **AND** safe generated/translated query `guante de béisbol`
- **WHEN** all providers are selected
- **THEN** Alibaba receives `baseball glove`
- **AND** Facebook and Mercado Libre may both receive `guante de béisbol`

#### Scenario: Alibaba Zen keywords stay independent of Venezuela localization
- **GIVEN** original query `baseball glove`
- **AND** Facebook/ML receive `guante de béisbol`
- **AND** the Alibaba category resolver does not produce an exact safe category
- **WHEN** the Zen SEARCH input is built after Z4
- **THEN** `keywords` is the independently routed Alibaba query
- **AND** `category` is omitted
- **AND** the Venezuela-localized query is not sent to Zen

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

Venezuela generic search MAY offer **Toda Venezuela**, supported narrower city/market scopes such as Caracas, and accurately named bounded broad/partial coverage. For Facebook, **Toda Venezuela** requires one genuine nationwide provider search when supported or completion of the entire finite configured nationwide partition set. Trustworthy acquisition provenance MAY establish scope without a listing-level location unless the existing contract requires it. Explicit foreign evidence always rejects. Narrower scopes use trustworthy partition provenance or reviewed identifiers/aliases without fuzzy/ambiguous matching. Mercado Libre's existing MLV/Venezuela contract is unchanged.

#### Scenario: Toda Venezuela is requested
- **GIVEN** the UI requests Toda Venezuela rather than a narrower supported scope
- **WHEN** a Venezuela provider query is created
- **THEN** the strategy uses genuine nationwide acquisition or the complete finite configured nationwide partition set
- **AND** final scope copy depends on the coverage actually completed

#### Scenario: Genuine nationwide acquisition supports Toda Venezuela
- **GIVEN** the provider supports one genuine nationwide search
- **WHEN** that search completes within its finite budget
- **THEN** the declared scope may be Toda Venezuela
- **AND** effective scope is Toda Venezuela and coverage status is `COMPLETE`
- **AND** provider acquisition/result order is preserved after integrity validation and deduplication

#### Scenario: Complete partition set supports Toda Venezuela
- **GIVEN** Facebook nationwide coverage requires a finite configured city/market partition set
- **WHEN** every required partition completes
- **THEN** the declared scope may be Toda Venezuela
- **AND** effective scope is Toda Venezuela and coverage status is `COMPLETE`
- **AND** results are deduplicated and placed in deterministic BERA aggregate order

#### Scenario: Partial partition coverage is not Toda Venezuela
- **GIVEN** only a bounded subset of Venezuela partitions is searched
- **WHEN** enough results are obtained or the finite budget ends
- **THEN** the scope is labelled as accurate broad/partial Venezuela coverage
- **AND** coverage status is `PARTIAL`
- **AND** it is not labelled Toda Venezuela

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

#### Scenario: Facebook missing location uses trustworthy acquisition provenance
- **GIVEN** a Facebook listing has no listing-level location string
- **AND** trustworthy acquisition provenance establishes that it came from the selected Venezuela search/partition
- **WHEN** the documented Facebook provider contract evaluates scope
- **THEN** missing optional location alone does not reject it unless that contract genuinely requires listing-level location

#### Scenario: Explicit foreign evidence still rejects Facebook candidate
- **GIVEN** Facebook acquisition provenance indicates Venezuela
- **AND** the candidate contains explicit foreign-market evidence
- **WHEN** provider-integrity policy evaluates it
- **THEN** the candidate is rejected

### Requirement: Mercado Libre Venezuela provenance is not weakened

Mercado Libre candidates SHALL continue to require truthful Venezuela evidence under existing policy, such as MLV site ID, Venezuela domain/permalink, Venezuela country evidence, or MLV product-ID evidence. Explicit foreign marketplace evidence SHALL be rejected; acquisition targets SHALL NOT weaken this requirement.

#### Scenario: Foreign marketplace evidence overrides volume goals
- **GIVEN** a Mercado Libre candidate has explicit foreign marketplace evidence
- **WHEN** provider policy evaluates it
- **THEN** it is rejected even if the display maximum would otherwise remain unfilled
