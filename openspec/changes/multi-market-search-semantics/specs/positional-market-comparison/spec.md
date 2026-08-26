# positional-market-comparison Specification

## ADDED Requirements

### Requirement: Generic comparison aligns canonical candidates by position

Generic multi-market search SHALL build `SearchPositionComparisonRow` values by one-based position in each provider's canonical BERA ordering. The ordering and canonical session prefix SHALL freeze when `ProviderRunResult` is committed to the current-generation session snapshot. Row count SHALL equal the maximum displayed candidate count among selected providers. Missing cells SHALL remain empty; candidates SHALL NOT be duplicated to fill cells.

Generic comparison SHALL be purely positional. Cross-market similarity, relatedness, equivalence, compatibility, category, title, or image comparisons SHALL NOT filter, discard, promote, demote, reorder, or replace valid candidates in any provider list. Any future identical-product/high-confidence matching flow SHALL be separate from generic search and SHALL NOT mutate its provider lists.

#### Scenario: Uneven three-two-one results
- **GIVEN** Alibaba displays A1, A2, A3
- **AND** Facebook displays F1, F2
- **AND** Mercado Libre displays M1
- **WHEN** comparison rows are built
- **THEN** there are three rows
- **AND** row 1 contains A1, F1, M1
- **AND** row 2 contains A2, F2, and an empty Mercado Libre cell
- **AND** row 3 contains A3 and empty Facebook and Mercado Libre cells

#### Scenario: Ten valid results per provider remain positional
- **GIVEN** `display_limit = 10`
- **AND** each selected provider has at least ten valid ordered results
- **WHEN** generic comparison is built
- **THEN** each provider contributes exactly its first ten valid results
- **AND** the table has ten positional rows
- **AND** no candidate is discarded for lacking similarity to another marketplace candidate

#### Scenario: Presentation sort cannot change Resultado number one
- **GIVEN** candidate A is frozen as canonical `Resultado #1`
- **WHEN** a specialized view applies price sorting, relevance filtering, or a ranking preset that places another candidate first in its projection
- **THEN** A remains generic comparison `Resultado #1`
- **AND** session totals, export membership, provider status, and the canonical snapshot remain unchanged

#### Scenario: Unrelated-looking candidates remain in provider order
- **GIVEN** the first valid results from Alibaba, Facebook, and Mercado Libre do not appear similar to each other
- **WHEN** generic comparison is built
- **THEN** all three remain in `Resultado #1` in their respective columns
- **AND** none is discarded or reordered for cross-market relatedness
- **AND** the row implies neither identity, equivalence, nor compatibility

### Requirement: Positional comparison has a distinct non-identity model

Generic search SHALL use `SearchPositionComparisonRow` with rank, optional marketplace candidates, and invariant `identity_confirmed = false`. It SHALL NOT overload the exact-product association row/context. The UI SHALL disclose **Comparables de la misma búsqueda · identidad exacta no confirmada** or approved equivalent concise wording that cannot imply exact matching.

#### Scenario: First-position candidates are unrelated by default
- **GIVEN** Alibaba, Facebook, and Mercado Libre candidates share `Resultado #1`
- **WHEN** the comparison is constructed
- **THEN** `identity_confirmed` is false
- **AND** no exact-product association is created

### Requirement: Position never authorizes provenance-dependent workflows

The system SHALL NOT use position, title, fuzzy title, relevance, image similarity, or search rank to authorize landed/import cost, profitability ceiling, negotiation context, tracking identity, supplier refresh, price history, exact Alibaba association, or product-specific persistence. Exact-product context SHALL continue to require both product IDs to be non-empty and exactly equal.

#### Scenario: Landed cost stays with exact product A
- **GIVEN** an exact Alibaba product A has landed-cost context
- **AND** Facebook and Mercado Libre candidates share A's positional row
- **WHEN** generic comparison renders or persists session state
- **THEN** landed-cost context is not attached to either positional candidate

#### Scenario: Empty or unequal IDs cannot establish identity
- **GIVEN** two positional candidates have empty or unequal product IDs
- **WHEN** exact context eligibility is evaluated
- **THEN** exact context is denied regardless of title, image, relevance, or rank similarity

### Requirement: Summary counts use canonical current-session results

Generic summary cards SHALL derive counts from the frozen canonical session result prefixes, not the remainder of ordered usable acquisition pools, `alibaba_visible_rows`, `ml_visible_rows`, or any presentation projection. **Total de resultados** SHALL equal the sum of provider displayed/canonical session result counts and SHALL NOT equal positional row count unless coincidentally equal.

#### Scenario: Hidden Mercado Libre presentation row remains counted
- **GIVEN** Mercado Libre has one canonical usable/displayed current-session listing
- **AND** a presentation relevance filter hides it elsewhere
- **WHEN** the generic summary is rendered
- **THEN** Mercado Libre does not report `0 resultados`
- **AND** the canonical listing contributes to total results

#### Scenario: Total counts listings rather than rows
- **GIVEN** Alibaba displays 1, Facebook displays 1, and Mercado Libre displays 0
- **WHEN** total results is calculated
- **THEN** total is 2

### Requirement: Ordering and opportunity remain marketplace-specific

Position N SHALL mean position N in that provider's existing canonical ordering: Alibaba's existing ranking/opportunity/relevance behavior, Facebook's existing deterministic relevance/result behavior, and Mercado Libre's existing deterministic result/relevance behavior. The system SHALL NOT synthesize a global cross-market rank or opportunity score. Alibaba opportunity MAY render only with the Alibaba candidate that owns it.

#### Scenario: Row without Alibaba has no Alibaba opportunity
- **GIVEN** a positional row contains only Facebook and Mercado Libre candidates
- **WHEN** row metadata renders
- **THEN** no Alibaba opportunity score is shown

### Requirement: Marketplace images and ratings retain their own provenance

Alibaba SHALL use its own image and genuine `reviewScore` for product stars; Facebook SHALL use its own primary scraped photo and SHALL have no fabricated product rating; Mercado Libre SHALL use its own thumbnail and genuine `ratingAverage`. Positional alignment SHALL NOT copy images or ratings across markets. Relevance, opportunity, supplier service score, and seller reputation SHALL NOT be converted into stars.

#### Scenario: Positionally aligned candidates render independent media
- **GIVEN** three providers have candidates at the same rank
- **WHEN** the row renders
- **THEN** each cell uses only that listing's marketplace-owned image and genuine rating fields
