# provider-search-diagnostics Specification

## ADDED Requirements

### Requirement: Session completion copy reflects provider statuses

The session SHALL render `Búsqueda completada` when at least one provider succeeds and none errors; `Búsqueda completada · Sin resultados` when all selected providers are empty; `Búsqueda completada con incidencias` when at least one errors and another succeeds or is empty; and `Búsqueda con error` when all selected providers error.

#### Scenario: All providers empty
- **GIVEN** every selected provider status is `EMPTY`
- **WHEN** session copy renders
- **THEN** it is `Búsqueda completada · Sin resultados`

#### Scenario: Partial provider error
- **GIVEN** one selected provider is `ERROR`
- **AND** another is `SUCCESS` or `EMPTY`
- **WHEN** session copy renders
- **THEN** it is `Búsqueda completada con incidencias`

### Requirement: Compact provider details are available when useful

The production UI SHALL offer **Ver detalles** for useful `EMPTY`, `ERROR`, rejection/filtering, and schema/mapping-loss states. Expanded details SHALL compactly present **Máximo a mostrar**, **Pedidos al proveedor**, **Recibidos**, **Mapeados**, **Rechazados**, **Usables**, and **Mostrados**. Unknown values SHALL display **No disponible**. The change SHALL NOT add a large diagnostics dashboard.

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
- **AND** no sensitive configuration material is shown

### Requirement: Unknown Alibaba currency is explained without USD inference

An Alibaba listing with a published price and unconfirmed source currency MAY remain visible, but USD aggregates SHALL remain unavailable. The UI SHALL explain that the published price is available while source currency is unconfirmed and USD statistics are unavailable for that reason. No fallback SHALL label the unknown currency as USD.

#### Scenario: Unknown currency listing remains truthful
- **GIVEN** an Alibaba listing has price range 4.78–9.78
- **AND** source currency is unconfirmed
- **WHEN** results and summaries render
- **THEN** the listing remains eligible for display
- **AND** USD aggregate is unavailable
- **AND** no `$`-to-USD inference occurs
- **AND** explanatory copy is present
