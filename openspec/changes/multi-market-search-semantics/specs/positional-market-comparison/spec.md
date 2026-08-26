# positional-market-comparison Specification

## ADDED Requirements

### Requirement: Generic comparison aligns canonical candidates by position

Generic multi-market search SHALL build `SearchPositionComparisonRow` values by one-based position. A genuine single acquisition MUST preserve provider acquisition/result order after required integrity validation and deduplication only when truthful stable identity exists. Identity-less candidates remain distinct. Only multiple acquisitions lacking truthful global native order use documented deterministic BERA aggregate ordering. BERA controls MUST NOT reorder frozen generic results. Missing cells remain empty and candidates are never fabricated.

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

The system SHALL NOT use position, title, fuzzy title, relevance, image similarity, search rank, or native provider-listing ID equality to authorize landed/import cost, profitability ceiling, negotiation context, tracking identity, supplier refresh, price history, exact association, or product-specific persistence. Existing explicit association IDs/context product IDs SHALL be non-empty and exactly agree under the existing exact-product contract. Native marketplace IDs are independent namespaces and equality between them establishes nothing.

#### Scenario: Landed cost stays with exact product A
- **GIVEN** an exact Alibaba product A has landed-cost context
- **AND** Facebook and Mercado Libre candidates share A's positional row
- **WHEN** generic comparison renders or persists session state
- **THEN** landed-cost context is not attached to either positional candidate

#### Scenario: Association context IDs must explicitly agree
- **GIVEN** the exact-product workflow's association/context IDs are empty or do not agree
- **WHEN** exact context eligibility is evaluated
- **THEN** exact context is denied regardless of title, image, relevance, or rank similarity

#### Scenario: Equal native listing ID strings do not establish identity
- **GIVEN** listings from two marketplaces coincidentally have the same native ID string
- **WHEN** generic positional comparison is built
- **THEN** no exact-product association or context is created

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

Position N SHALL preserve provider acquisition/result order for a genuine single acquisition. Only multiple acquisitions without truthful native global order use documented deterministic BERA aggregate ordering. Alibaba opportunity, relevance, seller reputation, price sorting, and other BERA controls remain annotations or specialized projections and SHALL NOT reorder frozen generic results. No global cross-market rank/opportunity is synthesized; Alibaba opportunity MAY render only with its Alibaba candidate.

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

### Requirement: Positional cells render truthful provider-owned fields

Each candidate cell SHALL preserve and render when available its marketplace-owned image, title, published price/currency, listing URL, supplier/seller name, genuine product rating/review count, genuine seller/supplier reputation/service metadata, and existing useful provider-specific fields such as Alibaba MOQ or Mercado Libre condition. Unavailable optional fields SHALL render blank/`—`, SHALL NOT invalidate the candidate, and SHALL NOT be fabricated. Facebook seller or rating data SHALL never be invented.

#### Scenario: Available listing fields render in their own cell
- **GIVEN** a candidate provides title, price/currency, URL, seller, genuine rating/reviews, reputation metadata, image, and provider-specific fields
- **WHEN** its positional cell renders
- **THEN** those values are preserved truthfully in that marketplace cell

#### Scenario: Optional cell fields are absent
- **GIVEN** a valid candidate lacks image, rating, review count, seller/reputation metadata, or provider-specific optional fields
- **WHEN** its positional cell renders
- **THEN** unavailable fields are blank or `—`
- **AND** the candidate remains present
- **AND** no Facebook seller or rating value is fabricated
