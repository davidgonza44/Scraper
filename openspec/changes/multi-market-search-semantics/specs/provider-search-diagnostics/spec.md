# provider-search-diagnostics Specification

## ADDED Requirements

### Requirement: Session completion copy reflects provider statuses

The session SHALL render `Búsqueda completada` when at least one provider succeeds, none errors, and all **applicable** coverage is `COMPLETE`; `Búsqueda completada · Sin resultados` when all providers are empty and all applicable coverage is `COMPLETE`; incidence copy when applicable coverage is `PARTIAL` or errors coexist with another terminal outcome; and error copy when all providers error. Coverage that is not applicable to a provider/search is ignored and MUST NOT become `PARTIAL`.

#### Scenario: All providers empty
- **GIVEN** every selected provider status is `EMPTY`
- **AND** every applicable coverage status is `COMPLETE`
- **WHEN** session copy renders
- **THEN** it is `Búsqueda completada · Sin resultados`

#### Scenario: Alibaba-only success ignores non-applicable coverage
- **GIVEN** Alibaba is the only selected provider
- **AND** Alibaba status is `SUCCESS`
- **AND** geographic coverage is not applicable
- **WHEN** session copy renders
- **THEN** it is `Búsqueda completada`

#### Scenario: Alibaba-only empty ignores non-applicable coverage
- **GIVEN** Alibaba is the only selected provider
- **AND** Alibaba status is `EMPTY`
- **AND** geographic coverage is not applicable
- **WHEN** session copy renders
- **THEN** it is `Búsqueda completada · Sin resultados`

#### Scenario: Partial provider error
- **GIVEN** one selected provider is `ERROR`
- **AND** another is `SUCCESS` or `EMPTY`
- **WHEN** session copy renders
- **THEN** it is `Búsqueda completada con incidencias`

#### Scenario: Partial coverage with usable results is an incidence
- **GIVEN** Facebook status is `SUCCESS`
- **AND** Facebook coverage is `PARTIAL`
- **WHEN** session copy renders
- **THEN** it is `Búsqueda completada con incidencias`

#### Scenario: Partial coverage with zero results is not nationwide empty
- **GIVEN** requested scope is Toda Venezuela
- **AND** provider status is `EMPTY`
- **AND** coverage is `PARTIAL`
- **WHEN** session copy and diagnostics render
- **THEN** the session does not claim complete nationwide `Sin resultados`
- **AND** sanitized incomplete-scope diagnostics are available

### Requirement: Compact provider details are available when useful

The production UI SHALL offer **Ver detalles** for useful `EMPTY`, `ERROR`, `PARTIAL`, rejection/filtering, and schema/mapping-loss states. Details SHALL show requested/effective scope, coverage status, **Máximo a mostrar**, actual **Pedidos al proveedor**, **Recibidos**, **Mapeados**, **Rechazados**, **Usables**, and **Mostrados**. Unestablished effective scope/coverage renders **No disponible** and does not override `ERROR`. Partial copy is sanitized; unknown metrics remain **No disponible**.

#### Scenario: Empty Mercado Libre details
- **GIVEN** Mercado Libre completes `EMPTY` with diagnostic metrics
- **WHEN** the user expands `Ver detalles`
- **THEN** compact pipeline metrics and applicable sanitized explanations are visible

### Requirement: Facebook diagnostics retain truthful rejection reasons

Where measurable, Facebook SHALL aggregate Free/Gratis, invalid price, missing ID, duplicate ID, rejected geographic scope, missing title, and malformed URL/other policy rejection reasons. Geographic rejection SHALL follow the documented scope-evidence contract: trustworthy acquisition/partition provenance may suffice when listing location is absent, while explicit foreign evidence rejects. Counters SHALL reflect actual policy decisions and SHALL NOT expose raw provider payloads.

#### Scenario: Image does not bypass invalid price
- **GIVEN** a Facebook record has an image and an invalid price
- **WHEN** it is evaluated
- **THEN** it is rejected as invalid price
- **AND** the truthful aggregate counter increments

### Requirement: Mercado Libre diagnostics distinguish no data from mapping loss

Where technically observable, Mercado Libre SHALL aggregate missing ID, missing title, missing Venezuela evidence, explicit foreign evidence, and successful mapping. `fetched > 0 && mapped = 0` SHALL remain `EMPTY` and SHALL show sanitized copy equivalent to `Se recibieron registros, pero ninguno pudo mapearse con el esquema esperado.` It SHALL be distinguishable from `fetched = 0`.

#### Scenario: Records fail narrow mapper
- **GIVEN** Mercado Libre `fetched > 0`
- **AND** `mapped = 0`
- **WHEN** diagnostics render
- **THEN** status is `EMPTY`
- **AND** mapping/schema loss is explained
- **AND** raw actor JSON is absent

### Requirement: Alibaba diagnostics distinguish empty, mapping loss, and failure

A normally completed Alibaba run with `fetched = 0` SHALL be `EMPTY` with received count zero. A normally completed run with `fetched > 0 && mapped = 0` SHALL be `EMPTY` with schema/mapping diagnostics. A run with usable records SHALL be `SUCCESS`. Only an actual provider execution failure SHALL be `ERROR`.

#### Scenario: Alibaba mapping loss
- **GIVEN** Alibaba execution completes normally with records received
- **AND** no records map to the safe model
- **WHEN** outcome is derived
- **THEN** it is `EMPTY`, not `ERROR`
- **AND** the schema/mapping diagnostic is available

### Requirement: Schema-drift observability is aggregate and safe

Diagnostics and observability SHALL contain only safe aggregate counters and sanitized copy. They SHALL NOT persist or display raw payloads, actor JSON, cookies, tokens, or sensitive query parameters.

#### Scenario: Diagnostic export is inspected
- **WHEN** a mapping-loss diagnostic is rendered or exported
- **THEN** it contains aggregate counts and sanitized text only

### Requirement: Configuration errors are sanitized

A selected provider unable to execute because required configuration or credentials are missing SHALL expose an `ERROR` diagnostic such as provider not configured. The diagnostic SHALL NOT expose credentials, tokens, raw configuration, sensitive values, or stack traces.

#### Scenario: Provider configuration is missing
- **GIVEN** a selected provider cannot start for missing required configuration
- **WHEN** the user expands `Ver detalles`
- **THEN** sanitized configuration-error copy is shown
- **AND** effective geographic scope and coverage status show `No disponible`
- **AND** provider status remains `ERROR`
- **AND** no sensitive configuration material is shown

### Requirement: Unknown Alibaba currency is explained without USD inference

An Alibaba listing with a published price and unconfirmed source currency MAY remain visible, but USD aggregates SHALL remain unavailable. The UI SHALL explain that the published price is available while source currency is unconfirmed and USD statistics are unavailable for that reason. No fallback SHALL label the unknown currency as USD. An authorized `memo23/alibaba-scraper` SEARCH raw `price` marker `US $` / `US$` is confirmed USD evidence after this contract and SHALL NOT be classified as unknown.

#### Scenario: Unknown currency listing remains truthful
- **GIVEN** an Alibaba listing has price range 4.78–9.78
- **AND** source currency is unconfirmed
- **WHEN** results and summaries render
- **THEN** the listing remains eligible for display
- **AND** USD aggregate is unavailable
- **AND** no `$`-to-USD inference occurs
- **AND** explanatory copy is present

#### Scenario: memo23 authorized US-dollar marker enters USD statistics
- **GIVEN** the configured Alibaba SEARCH Actor is `memo23/alibaba-scraper`
- **AND** the raw `price` field contains `US $3.20-$3.60`
- **AND** no contradictory provider evidence invalidates the price
- **WHEN** the listing is mapped
- **THEN** the raw/display price remains truthful
- **AND** min_price is 3.20
- **AND** max_price is 3.60
- **AND** normalized currency is USD
- **AND** the listing may participate in existing USD aggregates

#### Scenario: ambiguous dollar marker remains unconfirmed
- **GIVEN** the raw `price` field is `$3.20-$3.60`
- **WHEN** the listing is mapped
- **THEN** numeric amounts may remain available
- **AND** currency remains unknown
- **AND** the listing does not enter USD aggregates

#### Scenario: bare US prefix remains unconfirmed
- **GIVEN** the raw `price` field is `US 3.20`
- **WHEN** the listing is mapped
- **THEN** numeric amounts may remain available
- **AND** currency remains unknown
- **AND** the listing does not enter USD aggregates
