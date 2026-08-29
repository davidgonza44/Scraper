# alibaba-zen-semantic-validation Specification

## ADDED Requirements

### Requirement: Alibaba SEARCH uses a pinned Zen Actor with a closed input contract

After the Z4 production cutover, generic **Búsquedas** Alibaba SEARCH SHALL acquire candidates only through Actor `zen-studio/alibaba-scraper` (alias `zen-studio~alibaba-scraper`). The Apify client SHALL pin an exact validated Actor build recorded in this change. `latest`, `default`, and any other floating build pointer SHALL be rejected. Until that exact build is recovered from the five existing benchmark runs named in this change, the build remains unpinned and Z1 MUST NOT invent one.

One logical Alibaba SEARCH operation SHALL produce exactly one Zen Actor execution. The run input SHALL be:

- `resultType="products"`
- `keywords=[normalized query]` as a one-element array
- `category` only when the local category resolver produces an exact and sufficiently safe category; otherwise the field SHALL be omitted
- `sortBy="relevance"`; `sales_volume` SHALL never be the default
- `shipToCountry="US"`
- `marketplace="standard"`
- `verifiedSupplier`, `verifiedManufacturer`, `verifiedProSupplier`, `tradeAssurance`, `guaranteed`, `localStock`, and `paidSamples` all `false`
- `includeReviews=false`
- `includeSupplierReport=false`
- `maxResults=acquisition_budget`
- Apify client `max_items=acquisition_budget`

The input SHALL NOT include `proxyConfiguration`. Zen manages residential proxies internally. The input SHALL NOT use `resultType="suppliers"` or `resultType="category"`. Refresh of an already identified product SHALL continue to use `xtracto/alibaba-product-scraper` and SHALL NOT switch to Zen.

#### Scenario: Closed Zen SEARCH input
- **GIVEN** a generic Alibaba SEARCH after Z4 with normalized query `iphone 15`
- **AND** `acquisition_budget = 10`
- **AND** the category resolver did not produce an exact safe category
- **WHEN** the Zen run input is built
- **THEN** it contains `resultType="products"`
- **AND** `keywords=["iphone 15"]`
- **AND** `category` is omitted
- **AND** `sortBy="relevance"`
- **AND** `shipToCountry="US"`
- **AND** `marketplace="standard"`
- **AND** `maxResults=10`
- **AND** the Apify client uses `max_items=10`
- **AND** verified/tradeAssurance/guaranteed/localStock/paidSamples are false
- **AND** `includeReviews` and `includeSupplierReport` are false
- **AND** `proxyConfiguration` is absent
- **AND** no floating build pointer is used

#### Scenario: Exact safe category may be sent
- **GIVEN** the local category resolver produces one exact and sufficiently safe Zen category for the query
- **WHEN** the Zen run input is built
- **THEN** `category` equals that exact category
- **AND** `resultType` remains `"products"`
- **AND** the resolver does not browse a category without keywords

#### Scenario: Unsafe or inexact category is omitted
- **GIVEN** the resolver cannot produce an exact and sufficiently safe category
- **WHEN** the Zen run input is built
- **THEN** `category` is omitted
- **AND** search proceeds by keywords alone

#### Scenario: Sales volume is never the default sort
- **GIVEN** any generic Alibaba SEARCH
- **WHEN** the Zen run input is built
- **THEN** `sortBy` is `"relevance"`
- **AND** it is not `"sales_volume"`

#### Scenario: Refresh stays on xtracto
- **GIVEN** an already identified Alibaba product is refreshed
- **WHEN** the refresh Actor is selected
- **THEN** the Actor is `xtracto/alibaba-product-scraper`
- **AND** Zen is not used for that refresh

#### Scenario: Unpinned build blocks implementation, not invention
- **GIVEN** the five existing Zen benchmark run metadata are unavailable
- **WHEN** Z0 records the SEARCH Actor contract
- **THEN** the Actor name is `zen-studio/alibaba-scraper`
- **AND** the exact build remains unpinned
- **AND** no `latest` or `default` build is recorded as validated

### Requirement: One Zen execution and one semantic batch validation per logical operation

A logical Alibaba SEARCH operation SHALL perform exactly one Zen Actor execution and exactly one semantic-validation batch call. The orchestrator SHALL NOT start a second Zen execution to refill candidates discarded by mapping, integrity policy, or semantic validation. The validator SHALL NOT retry a failed, unavailable, or invalid batch.

#### Scenario: Mapping loss does not start a second Zen run
- **GIVEN** one Zen execution returns records
- **AND** some records fail safe mapping
- **WHEN** fewer than `display_limit` RELEVANT candidates remain
- **THEN** no second Zen execution is started

#### Scenario: Semantic IRRELEVANT does not start a refill run
- **GIVEN** one Zen execution and one semantic batch complete
- **AND** several mapped candidates are IRRELEVANT
- **WHEN** fewer than `display_limit` RELEVANT candidates remain
- **THEN** no second Zen execution is started
- **AND** the validator is not called again

#### Scenario: Invalid validator response is not retried
- **GIVEN** the semantic batch response is missing, duplicated, or contains extra `candidate_ref` values
- **WHEN** the adapter evaluates the response
- **THEN** the entire batch is treated as REVIEW
- **AND** no retry is issued

### Requirement: Initial Alibaba Zen acquisition budget is min(display_limit * 2, 20)

Until a later OpenSpec revision changes it, `AcquisitionBudgetPolicy` SHALL compute the Alibaba SEARCH `acquisition_budget` as `min(display_limit * 2, 20)`. `display_limit` remains the visible maximum and SHALL NOT be treated as acquisition work. Alibaba's documented 500-result ceiling SHALL NOT become a routine budget. `maximum_internal_acquisitions` for Alibaba SEARCH SHALL be 1.

#### Scenario: Display ten yields budget twenty
- **GIVEN** `display_limit = 10`
- **WHEN** Alibaba SEARCH budget is computed
- **THEN** `acquisition_budget = 20`
- **AND** exactly one Zen execution may request at most 20 items

#### Scenario: Display five yields budget ten
- **GIVEN** `display_limit = 5`
- **WHEN** Alibaba SEARCH budget is computed
- **THEN** `acquisition_budget = 10`

#### Scenario: Display one yields budget two
- **GIVEN** `display_limit = 1`
- **WHEN** Alibaba SEARCH budget is computed
- **THEN** `acquisition_budget = 2`

### Requirement: Semantic validation is a dedicated port independent of H0019

Alibaba Zen semantic validation SHALL be a distinct application port and infrastructure adapter. It SHALL NOT reuse `AIProductClassifier`, H0019 brake-pad classification, `classification.py` decisions, or the H0019 Ollama tool/prompt. Deterministic title-token relevance in `alibaba_relevance.py` MAY remain a specialized annotation and SHALL NOT reject generic candidates.

The only authorized generic-search rejection beyond existing provider-integrity/safety policy is **provider-internal compatibility validation between the user query and a listing acquired by Alibaba Zen**. That exception SHALL NOT authorize:

- cross-market identity inference
- association by title, image, brand, or model
- landed cost, negotiation, or tracking without explicit existing association IDs
- filtering Facebook or Mercado Libre candidates using Alibaba semantic decisions
- treating RELEVANT as proof of authenticity, genuineness, or exact product identity

#### Scenario: H0019 classifier is not invoked for generic Alibaba SEARCH
- **GIVEN** a generic Alibaba SEARCH batch of mapped Zen listings
- **WHEN** semantic validation runs
- **THEN** `AIProductClassifier.classify` is not called
- **AND** no H0019 decision, bike model, or brake-pad rationale is produced

#### Scenario: Title-token relevance cannot reject
- **GIVEN** a mapped Alibaba Zen listing with a low deterministic title-token relevance score
- **AND** the semantic validator has not decided IRRELEVANT
- **WHEN** generic-search validity is determined
- **THEN** the low score alone does not reject the listing

#### Scenario: Alibaba IRRELEVANT cannot remove a Facebook candidate
- **GIVEN** an Alibaba listing is IRRELEVANT for the user query
- **AND** a Facebook candidate occupies the same positional rank
- **WHEN** generic comparison is built
- **THEN** the Facebook candidate remains in its provider list
- **AND** no Alibaba reason code is applied to Facebook or Mercado Libre

#### Scenario: RELEVANT is not authenticity
- **GIVEN** a listing is RELEVANT with reason `MATCHES_INTENT`
- **WHEN** exact-product, landed-cost, negotiation, or tracking eligibility is evaluated
- **THEN** that decision does not create identity
- **AND** it does not authorize those workflows

### Requirement: Closed semantic decisions and reason codes

Each validated candidate SHALL receive exactly one of `RELEVANT`, `IRRELEVANT`, or `REVIEW`. IRRELEVANT SHALL be used only when the listing explicitly contradicts the user intent. REVIEW SHALL be used for ambiguity, insufficient evidence, or a controlled validator failure. RELEVANT means semantic match to the query, not authenticity.

Reason codes SHALL be exactly this closed set:

- `MATCHES_INTENT`
- `WRONG_PRODUCT_TYPE`
- `WRONG_BRAND`
- `WRONG_MODEL`
- `WRONG_VARIANT_OR_SPEC`
- `WRONG_FITMENT`
- `ACCESSORY_OR_COMPONENT`
- `CONFLICTING_EVIDENCE`
- `INSUFFICIENT_EVIDENCE`
- `VALIDATOR_UNAVAILABLE`
- `INVALID_PROVIDER_RESPONSE`

No numeric confidence SHALL be invented, stored, or rendered as a validation score. `MATCHES_INTENT` is the only RELEVANT reason. `WRONG_*`, `ACCESSORY_OR_COMPONENT`, and `CONFLICTING_EVIDENCE` may justify IRRELEVANT only with explicit contradiction. `INSUFFICIENT_EVIDENCE`, `VALIDATOR_UNAVAILABLE`, and `INVALID_PROVIDER_RESPONSE` SHALL produce REVIEW, never IRRELEVANT.

#### Scenario: Explicit wrong product type is IRRELEVANT
- **GIVEN** the user query names a complete impact driver
- **AND** the listing title and allowed specs explicitly describe only a battery pack for that tool
- **WHEN** the validator decides
- **THEN** the decision is IRRELEVANT
- **AND** the reason is `ACCESSORY_OR_COMPONENT` or `WRONG_PRODUCT_TYPE`
- **AND** no confidence number is emitted

#### Scenario: Ambiguous listing is REVIEW
- **GIVEN** the listing title is compatible with several product types
- **AND** allowed specs do not resolve the contradiction
- **WHEN** the validator decides
- **THEN** the decision is REVIEW
- **AND** the reason is `INSUFFICIENT_EVIDENCE` or `CONFLICTING_EVIDENCE`

#### Scenario: Validator outage is REVIEW, not IRRELEVANT
- **GIVEN** the semantic adapter is unavailable
- **WHEN** the batch is finalized
- **THEN** every candidate in that batch is REVIEW
- **AND** the reason is `VALIDATOR_UNAVAILABLE`
- **AND** none is IRRELEVANT solely because the validator failed

### Requirement: Validator input is a narrow sanitized subset

The validator SHALL receive only:

- sanitized query
- title
- resolved category, when one was sent to Zen
- `categoryPath`
- a bounded set of specification pairs
- an ephemeral `candidate_ref`

It SHALL NOT receive HTML, full descriptions, URLs, tokens, tracking fields, contact information, chat tokens, or the raw Zen payload. `candidate_ref` SHALL be ephemeral, unique within the batch, and SHALL NOT be a marketplace identity, URL, or tracking token.

#### Scenario: Raw Zen payload is stripped
- **GIVEN** a mapped Zen listing whose raw payload contains `descriptionHtml`, `chatToken`, `trackInfo`, `contactSupplier`, and URLs
- **WHEN** the validator request is built
- **THEN** those fields are absent
- **AND** the request contains sanitized query, title, optional resolved category, `categoryPath`, bounded specs, and `candidate_ref`

#### Scenario: candidate_ref is not a product id
- **GIVEN** a listing with a native Alibaba product id
- **WHEN** `candidate_ref` is assigned
- **THEN** it is an ephemeral batch-local reference
- **AND** it is not the product id, URL, or tracking token

### Requirement: Batch response must be a complete 1:1 candidate_ref set

A valid batch response SHALL return exactly one decision for each request `candidate_ref`. Missing, duplicated, or extra references SHALL invalidate the whole batch. An invalid batch SHALL convert every candidate to REVIEW with `INVALID_PROVIDER_RESPONSE` and SHALL NOT be retried.

#### Scenario: Extra reference invalidates the batch
- **GIVEN** the request contains refs `c1` and `c2`
- **AND** the response also contains `c3`
- **WHEN** the adapter validates the response
- **THEN** `c1` and `c2` become REVIEW
- **AND** `c3` is discarded
- **AND** no retry occurs

#### Scenario: Duplicate reference invalidates the batch
- **GIVEN** the request contains refs `c1` and `c2`
- **AND** the response contains two decisions for `c1` and none for `c2`
- **WHEN** the adapter validates the response
- **THEN** the whole batch is REVIEW with `INVALID_PROVIDER_RESPONSE`

#### Scenario: Valid 1:1 response is accepted
- **GIVEN** the request contains refs `c1`, `c2`, and `c3`
- **AND** the response contains exactly those three refs with closed decisions and reason codes
- **WHEN** the adapter validates the response
- **THEN** each candidate keeps its own decision
- **AND** no additional candidate is introduced

### Requirement: Canonical membership is RELEVANT-only and preserves Zen order

RELEVANT candidates SHALL enter the ordered usable pool, canonical session prefix, statistics, ranking annotations, export, and positional comparison. IRRELEVANT candidates SHALL be excluded from those surfaces and SHALL retain their reason and semantic metric. REVIEW candidates SHALL be retained only in a separate **Requiere revisión** projection. REVIEW SHALL NOT enter statistics, ranking, export, or positional comparison. Accepted RELEVANT results SHALL preserve Zen acquisition order. The semantic decision SHALL NOT be used as a ranking score.

#### Scenario: Mixed decisions split canonical and review projections
- **GIVEN** Zen order is A, B, C, D
- **AND** decisions are RELEVANT, IRRELEVANT, REVIEW, RELEVANT
- **WHEN** the Alibaba result is committed
- **THEN** the ordered usable pool is A, D
- **AND** canonical session results are the `display_limit` prefix of A, D
- **AND** C appears only under **Requiere revisión**
- **AND** B is excluded with its IRRELEVANT reason
- **AND** B and C are absent from export and positional comparison

#### Scenario: Semantic decision does not reorder RELEVANT results
- **GIVEN** two RELEVANT listings where the later Zen result looks like a closer match
- **WHEN** canonical order is frozen
- **THEN** the earlier Zen RELEVANT listing remains first
- **AND** no semantic score reorders them

### Requirement: Alibaba SEARCH status uses semantic outcomes without reusing coverage

After a completed validator batch, `usable` SHALL equal the RELEVANT pool size. A completed validator with zero RELEVANT SHALL be `EMPTY`. A validator outage or wholly invalid response with zero validated RELEVANT candidates SHALL be `ERROR`, never a silent `SUCCESS`. RELEVANT together with REVIEW SHALL be `SUCCESS` with a semantic-validation incidence. Geographic `coverage_status` SHALL NOT represent semantic validation. Alibaba SEARCH geographic coverage remains not applicable.

Required Alibaba SEARCH metrics SHALL include `fetched`, `mapped`, `semantic_relevant`, `semantic_irrelevant`, `semantic_review`, `usable`, and `semantic_validation_status`. Unknown remains unknown. Semantic counts SHALL NOT be fabricated as zero when the validator did not complete a valid batch.

`semantic_validation_status` SHALL be one of `completed`, `unavailable`, or `invalid_response` when Alibaba Zen validation applies. It SHALL NOT be a `CoverageStatus` value.

#### Scenario: All IRRELEVANT is EMPTY
- **GIVEN** the validator completes a valid batch
- **AND** every mapped candidate is IRRELEVANT
- **WHEN** status is derived
- **THEN** status is `EMPTY`
- **AND** `semantic_relevant = 0`
- **AND** `semantic_validation_status = completed`
- **AND** coverage remains not applicable

#### Scenario: Validator outage with no RELEVANT is ERROR
- **GIVEN** mapped candidates exist
- **AND** the validator is unavailable
- **WHEN** status is derived
- **THEN** status is `ERROR`
- **AND** it is not `SUCCESS`
- **AND** `semantic_validation_status = unavailable`
- **AND** canonical usable and displayed counts are 0
- **AND** the mapped candidates may appear only in the REVIEW projection

#### Scenario: Invalid batch with no RELEVANT is ERROR
- **GIVEN** mapped candidates exist
- **AND** the validator response is wholly invalid
- **WHEN** status is derived
- **THEN** status is `ERROR`
- **AND** `semantic_validation_status = invalid_response`
- **AND** every mapped candidate is REVIEW
- **AND** none is silently published as canonical SUCCESS

#### Scenario: RELEVANT plus REVIEW is SUCCESS with semantic incidence
- **GIVEN** at least one RELEVANT candidate
- **AND** at least one REVIEW candidate
- **AND** the validator completed a valid batch
- **WHEN** status and session copy are derived
- **THEN** provider status is `SUCCESS`
- **AND** a semantic-validation incidence is recorded
- **AND** coverage is not set to `PARTIAL`

#### Scenario: Semantic metrics remain unknown when the validator does not complete
- **GIVEN** mapping completed with `mapped = 4`
- **AND** the validator then becomes unavailable
- **WHEN** metrics are finalized
- **THEN** `semantic_validation_status = unavailable`
- **AND** `semantic_relevant` is not reported as a successful-batch count
- **AND** those semantic counts are not fabricated as proven completed totals

### Requirement: Alibaba SEARCH currency uses Zen structured USD evidence

The memo23 SEARCH raw `price` marker `US $` / `US$` SHALL NOT be reused for Zen SEARCH. Zen SEARCH SHALL expose distinct fields:

- `localized_currency`
- `source_currency`
- `price_provenance`
- `ship_to_country`

Proposed precedence for localized USD:

1. `detail.price.productLadderPrices[*].dollarPrice` as localized USD
2. `detail.price.productRangePrices.dollarPriceRangeLow` / `dollarPriceRangeHigh` as localized USD
3. `product.price` only as display/fallback
4. `detail.currency` as source currency, never as automatic localized currency
5. if structured evidence is insufficient, localized currency is `None` and the price SHALL NOT enter USD statistics

Z1 SHALL confirm those structured paths against sanitized fixtures. If a named path is absent, the mapper SHALL NOT invent `dollarPrice` from a bare `$` display string, from `detail.currency`, or from locale. `ship_to_country` for this SEARCH contract is `US`.

#### Scenario: Structured dollarPrice may enter USD statistics
- **GIVEN** sanitized fixture evidence contains `detail.price.productLadderPrices` with `dollarPrice` values
- **AND** those values are finite and compatible
- **WHEN** the listing is mapped
- **THEN** `localized_currency` is USD
- **AND** `price_provenance` records the ladder dollarPrice path
- **AND** the listing may participate in USD aggregates

#### Scenario: Display price alone does not prove USD
- **GIVEN** `product.price` is `$0.53-0.63`
- **AND** no structured `dollarPrice` evidence exists
- **WHEN** the listing is mapped
- **THEN** the display price may remain visible
- **AND** `localized_currency` is unknown
- **AND** the listing does not enter USD aggregates
- **AND** no memo23 `US $` rule is applied

#### Scenario: detail.currency is source, not localized USD
- **GIVEN** `detail.currency` is `US $`
- **AND** no structured `dollarPrice` evidence exists
- **WHEN** the listing is mapped
- **THEN** `source_currency` may record that provider marker as source evidence
- **AND** `localized_currency` remains unknown
- **AND** USD statistics remain unavailable

### Requirement: soldOrder and ratings remain distinct unknown-safe fields

`soldOrder=null` SHALL remain unknown and SHALL NOT become zero. Product rating fields and supplier `serviceScore` are different concepts. Relevance, opportunity, and supplier service SHALL NOT become product stars.

#### Scenario: Null soldOrder stays unknown
- **GIVEN** a Zen listing with `soldOrder=null`
- **WHEN** it is mapped
- **THEN** sold quantity is unknown
- **AND** it is not stored or rendered as 0

#### Scenario: Product review and supplier service stay distinct
- **GIVEN** product review score `4.5` and supplier `serviceScore` `4.4`
- **WHEN** the listing is mapped and rendered
- **THEN** the product-star field uses only the genuine product rating
- **AND** `serviceScore` remains supplier service metadata

### Requirement: Benchmark fixtures must be sanitized and human-labeled

Future offline fixtures SHALL start from these existing benchmark names when they become available:

- `zen-benchmark-01-iphone15-relevance.json.json`
- `zen-benchmark-02-brake-pads.json.json`
- `zen-benchmark-03-solar-panels.json.json`
- `zen-benchmark-04-lifepo4-battery.json.json`
- `zen-benchmark-05-impact-driver.json.json`

Those files are not in this repository at Z0. Their contents SHALL NOT be fabricated. Before repository inclusion they SHALL be sanitized of tokens, HTML, contacts, and tracking while retaining fields required for mapping and validation. Golden semantic labels SHALL be reviewed by a person and SHALL NOT be generated by the same model being evaluated. Automated tests SHALL use only sanitized offline fixtures and SHALL make zero live Apify, Ollama, DeepL, MiniMax, or marketplace calls.

#### Scenario: Missing benchmarks block fixture authorship
- **GIVEN** the five named benchmark files are unavailable
- **WHEN** Z0 is recorded
- **THEN** no synthetic Zen dataset is added to the repository
- **AND** Z5 remains blocked on sanitized, human-labeled fixtures

#### Scenario: Automated tests stay offline
- **WHEN** future Z1–Z5 automated suites run
- **THEN** Apify, Ollama, DeepL, MiniMax, and marketplace network call counts are all zero
