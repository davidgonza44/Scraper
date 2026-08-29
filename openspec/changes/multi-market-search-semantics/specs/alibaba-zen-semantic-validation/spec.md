# alibaba-zen-semantic-validation Specification

## ADDED Requirements

### Requirement: Alibaba SEARCH uses a pinned Zen Actor with a closed input contract

After the Z5 production cutover, generic **Búsquedas** Alibaba SEARCH SHALL acquire candidates only through Actor `zen-studio/alibaba-scraper` (alias `zen-studio~alibaba-scraper`). The Apify client SHALL pin an exact validated Actor build recorded in this change. `latest`, `default`, and any other floating build pointer SHALL be rejected. Until that exact build is recovered from the five existing benchmark runs named in this change, the build remains unpinned and Z1 MUST NOT invent one.

One logical Alibaba SEARCH operation SHALL produce exactly one Zen Actor execution. The run input SHALL be:

- `resultType="products"`
- `keywords=[normalized query]` as a one-element array
- `category` only when the deterministic local resolver defined below produces exactly one snapshot-safe category; otherwise the field SHALL be omitted
- `sortBy="relevance"`; `sales_volume` SHALL never be the default
- `shipToCountry="US"`
- `marketplace="standard"`
- `verifiedSupplier`, `verifiedManufacturer`, `verifiedProSupplier`, `tradeAssurance`, `guaranteed`, `localStock`, and `paidSamples` all `false`
- `includeReviews=false`
- `includeSupplierReport=false`
- `maxResults=acquisition_budget`

The Apify client call SHALL use:

- `build=<exact buildNumber>` of the pinned build
- `max_items=acquisition_budget`
- `restart_on_error=False`

The input SHALL NOT include `proxyConfiguration`. Zen manages residential proxies internally. The input SHALL NOT use `resultType="suppliers"` or `resultType="category"`. BERA SHALL NOT restart, retry, resurrect, or reboot that Actor run. Refresh of an already identified product SHALL continue to use `xtracto/alibaba-product-scraper` and SHALL NOT switch to Zen.

#### Scenario: Closed Zen SEARCH input
- **GIVEN** a generic Alibaba SEARCH after Z5 with normalized query `iphone 15`
- **AND** `acquisition_budget = 10`
- **AND** the category resolver did not produce a snapshot-safe category
- **WHEN** the Zen run input and Apify client call are built
- **THEN** the input contains `resultType="products"`
- **AND** `keywords=["iphone 15"]`
- **AND** `category` is omitted
- **AND** `sortBy="relevance"`
- **AND** `shipToCountry="US"`
- **AND** `marketplace="standard"`
- **AND** `maxResults=10`
- **AND** the Apify client uses `max_items=10`
- **AND** the Apify client uses `build` equal to the exact pinned `buildNumber`
- **AND** the Apify client uses `restart_on_error=False`
- **AND** BERA issues no restart, retry, resurrect, or reboot
- **AND** verified/tradeAssurance/guaranteed/localStock/paidSamples are false
- **AND** `includeReviews` and `includeSupplierReport` are false
- **AND** `proxyConfiguration` is absent
- **AND** no floating build pointer is used

#### Scenario: Exact safe category may be sent
- **GIVEN** the local category resolver produces exactly one snapshot-safe Zen category for the query
- **WHEN** the Zen run input is built
- **THEN** `category` equals that exact snapshot member
- **AND** `resultType` remains `"products"`
- **AND** `keywords` remain the independently routed query
- **AND** the resolver does not browse a category without keywords

#### Scenario: Unsafe or inexact category is omitted
- **GIVEN** the resolver cannot produce exactly one snapshot-safe category
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

### Requirement: Category resolution is a local deterministic snapshot lookup

"Exact and sufficiently safe" SHALL mean this operational contract, not an implementer judgment:

- a versioned snapshot of the Zen category enum that corresponds 1:1 to the pinned Actor build
- a local deterministic resolver
- audited exact-match alias rules for that snapshot
- no LLM, embeddings, fuzzy matching, substring scoring, or edit-distance matching in the first version

Resolver inputs SHALL be exactly:

1. `normalized_query` — the same one-element `keywords` value that will be sent to Zen
2. `taxonomy_snapshot` — the frozen allowed category strings for `taxonomy_version`
3. `alias_rules` — the audited exact-match table for that `taxonomy_version`

Normalization for matching SHALL be NFKC, removal of Unicode `Cc`/`Cf` characters, whitespace compaction to one ASCII space with strip, then case-fold. A rule matches only by exact equality of that normalized form to the rule's documented match key.

Outcomes SHALL be:

- exactly one matching rule whose category is a snapshot member → send that category and record `category_origin=exact_rule`
- zero matching rules → omit `category` and record `category_origin=omitted_unknown`
- more than one matching rule, or matching rules that disagree on category → omit `category` and record `category_origin=omitted_ambiguous`
- exactly one matching rule whose category is not a snapshot member → omit `category` and record `category_origin=omitted_not_in_snapshot`

The sent `category` value SHALL belong exactly to the snapshot. The run SHALL record `category` when sent, plus `category_origin` and `taxonomy_version` in every case. The resolver SHALL NOT rewrite `keywords`. Category SHALL NOT become identity, cross-market association, or the final semantic-validation criterion.

#### Scenario: Unique exact rule sends the snapshot category
- **GIVEN** `taxonomy_version` identifies the snapshot for the pinned Zen build
- **AND** exactly one audited rule matches the normalized query
- **AND** that rule's category is a member of the snapshot
- **WHEN** the resolver runs
- **THEN** `category` equals that snapshot member
- **AND** `category_origin` is `exact_rule`
- **AND** `taxonomy_version` is recorded
- **AND** `keywords` are unchanged

#### Scenario: Unknown query omits category
- **GIVEN** no audited rule matches the normalized query
- **WHEN** the resolver runs
- **THEN** `category` is omitted
- **AND** `category_origin` is `omitted_unknown`
- **AND** `taxonomy_version` is recorded
- **AND** search proceeds by keywords alone

#### Scenario: Ambiguous rules omit category
- **GIVEN** two audited rules match the same normalized query
- **AND** they name different snapshot categories
- **WHEN** the resolver runs
- **THEN** `category` is omitted
- **AND** `category_origin` is `omitted_ambiguous`
- **AND** neither category is sent

#### Scenario: Category outside the snapshot is omitted
- **GIVEN** exactly one audited rule matches the normalized query
- **AND** that rule's category is absent from the versioned snapshot
- **WHEN** the resolver runs
- **THEN** `category` is omitted
- **AND** `category_origin` is `omitted_not_in_snapshot`
- **AND** the out-of-snapshot value is not sent to Zen

### Requirement: One Zen execution and at most one semantic batch per logical operation

A logical Alibaba SEARCH operation SHALL perform exactly one Zen Actor execution. Semantic-validation batch calls SHALL depend on the mapped pool:

- `mapped == 0`: zero real validator calls and a normal `EMPTY` outcome when Zen completed
- `mapped > 0`: exactly one semantic-validation batch call

The empty-pool case SHALL NOT be described or implemented as an external no-op call. The orchestrator SHALL NOT start a second Zen execution to refill candidates discarded by mapping, integrity policy, or semantic validation. The validator SHALL NOT retry a failed, unavailable, or invalid batch.

#### Scenario: Zen fetched zero makes zero validator calls
- **GIVEN** one Zen execution completes normally
- **AND** `fetched = 0`
- **AND** `mapped = 0`
- **WHEN** the logical operation finalizes
- **THEN** the validator is called zero times
- **AND** status is `EMPTY`
- **AND** no second Zen execution is started

#### Scenario: Fetched-positive mapped-zero makes zero validator calls
- **GIVEN** one Zen execution completes normally
- **AND** `fetched > 0`
- **AND** every record fails safe mapping
- **AND** `mapped = 0`
- **WHEN** the logical operation finalizes
- **THEN** the validator is called zero times
- **AND** status is `EMPTY` with mapping diagnostics
- **AND** no second Zen execution is started

#### Scenario: Mapped-positive issues exactly one batch
- **GIVEN** one Zen execution returns records
- **AND** `mapped > 0`
- **WHEN** semantic validation runs
- **THEN** the validator is called exactly once
- **AND** no retry is issued
- **AND** no second Zen execution is started

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

Alibaba Zen semantic validation SHALL be a distinct application port and infrastructure adapter. It SHALL NOT reuse `AIProductClassifier`, H0019 brake-pad classification, `classification.py` decisions, or the H0019 Ollama tool/prompt/domain. Deterministic title-token relevance in `alibaba_relevance.py` MAY remain a specialized annotation and SHALL NOT reject generic candidates.

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
- **GIVEN** a known-size mapped batch exists
- **AND** the semantic adapter is unavailable
- **WHEN** the batch is finalized
- **THEN** every candidate in that batch is REVIEW
- **AND** the reason is `VALIDATOR_UNAVAILABLE`
- **AND** none is IRRELEVANT solely because the validator failed

### Requirement: Validator input uses deterministic sanitization and concrete limits

The validator SHALL receive only:

- sanitized query
- title
- resolved category, when one was sent to Zen
- `categoryPath`
- specification pairs
- an ephemeral `candidate_ref`

It SHALL NOT receive HTML, full descriptions, URLs, tokens, tracking fields, contact information, chat tokens, or the raw Zen payload. `candidate_ref` SHALL be ephemeral, unique within the batch, and SHALL NOT be a marketplace identity, URL, or tracking token.

Before serialization, every string field SHALL be normalized in this order: Unicode NFKC; removal of Unicode general-category `Cc` and `Cf` characters; compaction of any whitespace sequence to one ASCII space and strip; deterministic truncation to the field cap by Unicode code points. Empty `categoryPath` items and specification pairs with an empty key or value SHALL be dropped after normalization.

The following constants SHALL be the enforceable limits:

| Constant | Value |
|---|---|
| `ZEN_SEMANTIC_MAX_QUERY_CHARS` | 256 |
| `ZEN_SEMANTIC_MAX_TITLE_CHARS` | 300 |
| `ZEN_SEMANTIC_MAX_CATEGORY_PATH_ITEMS` | 8 |
| `ZEN_SEMANTIC_MAX_CATEGORY_ITEM_CHARS` | 80 |
| `ZEN_SEMANTIC_MAX_SPEC_PAIRS` | 8 |
| `ZEN_SEMANTIC_MAX_SPEC_KEY_CHARS` | 64 |
| `ZEN_SEMANTIC_MAX_SPEC_VALUE_CHARS` | 128 |
| `ZEN_SEMANTIC_MAX_CANDIDATE_CHARS` | 1536 |
| `ZEN_SEMANTIC_MAX_BATCH_CANDIDATES` | 20 |
| `ZEN_SEMANTIC_MAX_BATCH_CHARS` | 32768 |

A batch SHALL contain at most `ZEN_SEMANTIC_MAX_BATCH_CANDIDATES` candidates. Because `acquisition_budget` and `max_items` are at most 20, a truthful mapped pool cannot exceed 20. A larger mapped count is a contract violation: the validator SHALL NOT be called and the known mapped count SHALL be finalized as `invalid_response`. If a normalized candidate object still exceeds `ZEN_SEMANTIC_MAX_CANDIDATE_CHARS`, trailing specification pairs SHALL be dropped until it fits; if it still exceeds the cap, `title` SHALL be truncated further to fit. If the serialized batch would exceed `ZEN_SEMANTIC_MAX_BATCH_CHARS`, the request SHALL NOT be sent and the known-size batch SHALL be treated as `invalid_response`.

#### Scenario: Raw Zen payload is stripped
- **GIVEN** a mapped Zen listing whose raw payload contains `descriptionHtml`, `chatToken`, `trackInfo`, `contactSupplier`, and URLs
- **WHEN** the validator request is built
- **THEN** those fields are absent
- **AND** the request contains sanitized query, title, optional resolved category, `categoryPath`, bounded specs, and `candidate_ref`

#### Scenario: Oversized title is truncated to the title cap
- **GIVEN** a mapped title longer than 300 code points after NFKC, control removal, and whitespace compaction
- **WHEN** the validator request is built
- **THEN** the emitted title has exactly 300 code points
- **AND** no raw HTML remains

#### Scenario: Specification set is capped
- **GIVEN** a listing has 12 specification pairs after normalization
- **WHEN** the validator request is built
- **THEN** at most 8 pairs are emitted
- **AND** each key has at most 64 code points
- **AND** each value has at most 128 code points

#### Scenario: Batch larger than twenty is rejected before the call
- **GIVEN** mapping produced more than 20 candidates
- **WHEN** the validator request would be built
- **THEN** no validator call is issued for an oversized batch
- **AND** the known mapped count is treated as `invalid_response`

#### Scenario: candidate_ref is not a product id
- **GIVEN** a listing with a native Alibaba product id
- **WHEN** `candidate_ref` is assigned
- **THEN** it is an ephemeral batch-local reference
- **AND** it is not the product id, URL, or tracking token

### Requirement: Tool response accepts only candidate_ref, decision, and reason_code

A valid tool-response item SHALL contain exactly these fields and no others:

- `candidate_ref` as a string
- `decision` as one of `RELEVANT`, `IRRELEVANT`, `REVIEW`
- `reason_code` as one closed reason-code string

A valid batch response SHALL return exactly one such item for each request `candidate_ref`. Extra fields, missing fields, duplicate refs, extra refs, or incorrect types SHALL invalidate the whole batch. An invalid batch SHALL convert every candidate to REVIEW with `INVALID_PROVIDER_RESPONSE` and SHALL NOT be retried. Ordinary assistant content SHALL NOT control classification.

The adapter SHALL use a dedicated versioned prompt independent of H0019. Provenance SHALL record `model` and `prompt_version`. The HTTP client SHALL use a loopback base URL (`127.0.0.1` or `localhost`), `trust_env=False`, and `ZEN_SEMANTIC_HTTP_TIMEOUT_SECONDS = 60`. Logs SHALL NOT contain raw Zen payloads, validator request bodies, or raw model content.

#### Scenario: Extra reference invalidates the batch
- **GIVEN** the request contains refs `c1` and `c2`
- **AND** the response also contains `c3`
- **WHEN** the adapter validates the response
- **THEN** `c1` and `c2` become REVIEW
- **AND** `c3` is discarded
- **AND** no retry occurs

#### Scenario: Extra field invalidates the batch
- **GIVEN** a response item contains `candidate_ref`, `decision`, `reason_code`, and `confidence`
- **WHEN** the adapter validates the response
- **THEN** the whole batch is REVIEW with `INVALID_PROVIDER_RESPONSE`
- **AND** no retry occurs

#### Scenario: Missing field invalidates the batch
- **GIVEN** a response item contains `candidate_ref` and `decision` but no `reason_code`
- **WHEN** the adapter validates the response
- **THEN** the whole batch is REVIEW with `INVALID_PROVIDER_RESPONSE`

#### Scenario: Wrong type invalidates the batch
- **GIVEN** a response item has `decision` as an object or `candidate_ref` as a number
- **WHEN** the adapter validates the response
- **THEN** the whole batch is REVIEW with `INVALID_PROVIDER_RESPONSE`

#### Scenario: Duplicate reference invalidates the batch
- **GIVEN** the request contains refs `c1` and `c2`
- **AND** the response contains two decisions for `c1` and none for `c2`
- **WHEN** the adapter validates the response
- **THEN** the whole batch is REVIEW with `INVALID_PROVIDER_RESPONSE`

#### Scenario: Valid 1:1 response is accepted
- **GIVEN** the request contains refs `c1`, `c2`, and `c3`
- **AND** the tool response contains exactly those three refs with only `candidate_ref`, `decision`, and `reason_code`
- **WHEN** the adapter validates the response
- **THEN** each candidate keeps its own decision
- **AND** no additional candidate is introduced
- **AND** ordinary assistant text does not change those decisions

#### Scenario: Transport is loopback and isolated from H0019
- **GIVEN** the semantic adapter is constructed
- **WHEN** its HTTP client is configured
- **THEN** the base URL host is loopback
- **AND** `trust_env` is `False`
- **AND** the timeout is 60 seconds
- **AND** the prompt, tool schema, and domain are not H0019 artifacts

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

After a completed validator batch, `usable` SHALL equal the RELEVANT pool size. A completed validator with zero RELEVANT SHALL be `EMPTY`. A validator outage or wholly invalid response against a known-size mapped batch SHALL be `ERROR`, never a silent `SUCCESS`. RELEVANT together with REVIEW SHALL be `SUCCESS` with a semantic-validation incidence. Geographic `coverage_status` SHALL NOT represent semantic validation. Alibaba SEARCH geographic coverage remains not applicable.

Required Alibaba SEARCH metrics SHALL include `fetched`, `mapped`, `semantic_relevant`, `semantic_irrelevant`, `semantic_review`, `usable`, and `semantic_validation_status`. Unknown remains unknown only when the failure occurs before a known-size batch is constructed.

When a known-size mapped batch is `unavailable` or `invalid_response`:

- `semantic_relevant = 0`
- `semantic_irrelevant = 0`
- `semantic_review =` that known batch size
- `semantic_validation_status = unavailable` or `invalid_response`
- the canonical pool is empty
- provider status is `ERROR`
- the mapped candidates appear only under **Requiere revisión**

`semantic_validation_status` SHALL be one of `completed`, `unavailable`, or `invalid_response` when Alibaba Zen validation applies. It SHALL NOT be a `CoverageStatus` value.

#### Scenario: All IRRELEVANT is EMPTY
- **GIVEN** the validator completes a valid batch
- **AND** every mapped candidate is IRRELEVANT
- **WHEN** status is derived
- **THEN** status is `EMPTY`
- **AND** `semantic_relevant = 0`
- **AND** `semantic_validation_status = completed`
- **AND** coverage remains not applicable

#### Scenario: Known-batch validator outage is ERROR with review counts
- **GIVEN** mapping produced a batch of 4 candidates
- **AND** the validator is unavailable
- **WHEN** status and metrics are derived
- **THEN** status is `ERROR`
- **AND** it is not `SUCCESS`
- **AND** `semantic_validation_status = unavailable`
- **AND** `semantic_relevant = 0`
- **AND** `semantic_irrelevant = 0`
- **AND** `semantic_review = 4`
- **AND** canonical usable and displayed counts are 0
- **AND** the four candidates appear only in the REVIEW projection

#### Scenario: Known-batch invalid response is ERROR with review counts
- **GIVEN** mapping produced a batch of 3 candidates
- **AND** the validator response is wholly invalid
- **WHEN** status and metrics are derived
- **THEN** status is `ERROR`
- **AND** `semantic_validation_status = invalid_response`
- **AND** `semantic_relevant = 0`
- **AND** `semantic_irrelevant = 0`
- **AND** `semantic_review = 3`
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

#### Scenario: Semantic metrics remain unknown only before a known batch exists
- **GIVEN** mapping has not yet produced a known-size batch
- **AND** the provider fails before that batch is constructed
- **WHEN** metrics are finalized
- **THEN** `semantic_relevant`, `semantic_irrelevant`, and `semantic_review` remain unknown
- **AND** those counts are not fabricated as zero completed totals

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

### Requirement: Structural fixtures belong to Z1 and the quality gate belongs to Z4

Future offline fixtures SHALL start from these existing benchmark names when they become available:

- `zen-benchmark-01-iphone15-relevance.json.json`
- `zen-benchmark-02-brake-pads.json.json`
- `zen-benchmark-03-solar-panels.json.json`
- `zen-benchmark-04-lifepo4-battery.json.json`
- `zen-benchmark-05-impact-driver.json.json`

Those files are not in this repository at Z0. Their contents SHALL NOT be fabricated. Z1 SHALL incorporate sanitized structural fixtures after tokens, HTML, contacts, and tracking are removed, without semantic labels. Z4 SHALL add independent human-reviewed golden labels and SHALL run the complete offline quality gate against those five datasets with zero live Apify, Ollama, DeepL, MiniMax, or marketplace calls. Golden labels SHALL NOT be generated by the same model being evaluated. Z5 MAY start only after every Z4 acceptance criterion passed. The production SEARCH Actor SHALL remain `memo23/alibaba-scraper` until that cutover.

Z4 minimum acceptance criteria SHALL be:

- identity-less listings remain distinct
- unknowns stay null / **No disponible**
- `display_limit` remains separate from `acquisition_budget`
- no cross-market identity was introduced
- `mapped == 0` produces zero validator calls
- `mapped > 0` produces exactly one batch
- no validator retry and no second Zen run
- ALL-REVIEW uses `Búsqueda completada con incidencias`
- production Actor remains memo23 throughout Z4

#### Scenario: Missing benchmarks block fixture authorship, not cutover authorship
- **GIVEN** the five named benchmark files are unavailable
- **WHEN** Z0 is recorded
- **THEN** no synthetic Zen dataset is added to the repository
- **AND** Z1 remains blocked on sanitized structural fixtures
- **AND** Z4 remains blocked on independent human labels and a passing offline gate
- **AND** Z5 remains blocked on a fully passing Z4

#### Scenario: Automated tests stay offline
- **WHEN** future Z1–Z5 automated suites run
- **THEN** Apify, Ollama, DeepL, MiniMax, and marketplace network call counts are all zero

#### Scenario: Quality gate precedes production cutover
- **GIVEN** Z4 has not passed every acceptance criterion
- **WHEN** a later task attempts the production Actor switch
- **THEN** that switch is forbidden
- **AND** production SEARCH remains `memo23/alibaba-scraper`
