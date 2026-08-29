# alibaba-zen-semantic-validation Specification

## ADDED Requirements

### Requirement: Alibaba SEARCH uses a pinned Zen Actor with a closed input contract

After the Z5 production cutover, generic **Búsquedas** Alibaba SEARCH SHALL acquire candidates only through Actor `zen-studio/alibaba-scraper` (alias `zen-studio~alibaba-scraper`). The Apify client SHALL pin an exact validated Actor build recorded in this change. `latest`, `default`, and any other floating build pointer SHALL be rejected. Until that exact build is recovered from the five existing benchmark runs named in this change, the build remains unpinned and Z1 MUST NOT invent one. Recovery SHALL collect `runId`, `buildId`, and `buildNumber` from all five runs. Those five runs SHALL share exactly the same `buildId` and `buildNumber`. That single shared build is the only allowed pin for the taxonomy snapshot, structural fixtures, Z4, and Z5. If any run differs, Z1 SHALL NOT choose a majority, last, or default build, SHALL NOT mix fixtures as validation of an arbitrary build, and SHALL block Z1, Z4, and Z5 until a new OpenSpec decision records authoritative benchmarks produced by one build.

When Alibaba is selected, configured, and startable, and the shared Alibaba provider query passes preflight, one logical Alibaba SEARCH operation SHALL produce exactly one Zen Actor execution. Missing token, pinned build, or other required configuration, or an invalid or oversized provider query, SHALL finalize Alibaba as preflight `ERROR` with zero Zen executions, zero validator calls, and a sanitized diagnostic. No Actor condemned to fail SHALL be started. Other selected providers MAY continue normally. The run input SHALL be:

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

#### Scenario: Conflicting benchmark builds block the pin
- **GIVEN** the five named benchmark runs expose `runId`, `buildId`, and `buildNumber`
- **AND** at least one run reports a different `buildId` or `buildNumber`
- **WHEN** Z1 would recover the validated build
- **THEN** no majority, last, or default build is selected
- **AND** fixtures from different builds are not mixed as validation of one pin
- **AND** Z1, Z4, and Z5 remain blocked
- **AND** a new OpenSpec decision plus single-build authoritative benchmarks are required

#### Scenario: Missing token or build is preflight ERROR with zero executions
- **GIVEN** Alibaba is selected
- **AND** the required token, pinned build, or other configuration is absent
- **WHEN** the logical operation starts
- **THEN** Alibaba status is preflight `ERROR`
- **AND** Zen executions are zero
- **AND** validator calls are zero
- **AND** no doomed Actor run is started
- **AND** the diagnostic is sanitized

### Requirement: Alibaba SEARCH uses one complete normalized query with a 256 code-point limit

The Alibaba provider query SHALL be one shared normalized string. That same complete string SHALL be used for:

- the one-element `keywords` array sent to Zen
- the category resolver `normalized_query`
- the semantic validator query field

The enforceable limit is `ZEN_SEMANTIC_MAX_QUERY_CHARS = 256` Unicode code points after the shared normalization below. The limit SHALL be validated before category resolution, Zen, and the validator. Implementations SHALL NOT truncate the query to satisfy the limit. Implementations SHALL NOT send Zen the complete query while sending the validator only its first 256 characters.

Shared normalization SHALL be exactly:

1. Unicode NFKC
2. replace every Unicode whitespace character, including whitespace controls such as TAB, LF, CR, VT, and FF, with one ASCII space
3. remove remaining Unicode general-category `Cc` and `Cf` characters
4. compact any whitespace sequence to one ASCII space and strip
5. apply Unicode casefold only when matching category-resolver aliases

`impact\ndriver` SHALL become `impact driver`, never `impactdriver`, in the resolver and the validator. Zen `keywords` and the validator query SHALL use the complete string after steps 1–4 and SHALL NOT be casefolded.

If the normalized query exceeds 256 code points:

- Alibaba SHALL terminate as preflight `ERROR`
- Zen executions SHALL be zero
- validator calls SHALL be zero
- the diagnostic SHALL be sanitized
- the query SHALL NOT be truncated
- other selected providers MAY continue normally
- `original_user_query` SHALL be retained as provenance

#### Scenario: Shared query is complete and identical
- **GIVEN** the normalized Alibaba provider query is `impact driver`
- **AND** it has at most 256 code points
- **WHEN** category resolution, Zen input, and the validator request are built
- **THEN** the resolver input, Zen `keywords[0]`, and the validator query are exactly that complete string
- **AND** no consumer receives a truncated prefix

#### Scenario: Oversized Alibaba query is preflight ERROR
- **GIVEN** the normalized Alibaba provider query exceeds 256 code points
- **AND** Facebook and Mercado Libre are also selected
- **WHEN** Alibaba preflight runs
- **THEN** Alibaba status is `ERROR`
- **AND** no Zen execution is started
- **AND** the validator is called zero times
- **AND** category resolution does not run
- **AND** the query is not truncated for Zen or the validator
- **AND** the diagnostic exposes no raw oversized payload
- **AND** Facebook and Mercado Libre may continue
- **AND** `original_user_query` remains on the snapshot

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

Normalization for matching SHALL use the same shared order as the validator:

1. Unicode NFKC
2. replace every Unicode whitespace character, including whitespace controls such as TAB, LF, CR, VT, and FF, with one ASCII space
3. remove remaining Unicode general-category `Cc` and `Cf` characters
4. compact any whitespace sequence to one ASCII space and strip
5. apply Unicode casefold only for alias matching

A rule matches only by exact equality of that casefolded form to the rule's documented match key. `impact\ndriver` SHALL become `impact driver`, never `impactdriver`.

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

#### Scenario: Resolver preserves whitespace token boundaries
- **GIVEN** the Alibaba provider query is `impact\ndriver`
- **AND** an audited alias match key is `impact driver`
- **WHEN** the resolver normalizes the query for matching
- **THEN** the normalized match form is `impact driver`
- **AND** it is not `impactdriver`

### Requirement: One Zen execution and at most one semantic batch per logical operation

When configuration and preflight are valid, a logical Alibaba SEARCH operation SHALL perform exactly one Zen Actor execution. Missing token, pinned build, or other required configuration, or an invalid or oversized provider query, SHALL be preflight `ERROR` with zero Zen executions and zero validator calls. No Actor condemned to fail SHALL be started. Semantic-validation batch calls SHALL depend on successful local batch construction, not on `mapped > 0` alone:

- `mapped == 0`: zero real validator calls, `semantic_validation_status = not_run`, and a normal `EMPTY` outcome when Zen completed
- `mapped` in `1..20` and the canonical serialized envelope is within `ZEN_SEMANTIC_MAX_BATCH_BYTES`: exactly one semantic-validation batch call
- local batch construction fails (`mapped > 20` or serialized size exceeds the cap): zero real validator calls and `invalid_response` for that known mapped count

The empty-pool and construction-failure cases SHALL NOT be described or implemented as external no-op calls. The orchestrator SHALL NOT start a second Zen execution to refill candidates discarded by mapping, integrity policy, or semantic validation. The validator SHALL NOT retry a failed, unavailable, or invalid batch.

#### Scenario: Startable configured search issues exactly one Zen execution
- **GIVEN** Alibaba is selected, configured, and startable
- **AND** the shared provider query passes the 256 code-point preflight
- **WHEN** the logical operation runs
- **THEN** exactly one Zen execution is started
- **AND** no doomed Actor is launched

#### Scenario: Zen fetched zero makes zero validator calls
- **GIVEN** one Zen execution completes normally
- **AND** `fetched = 0`
- **AND** `mapped = 0`
- **WHEN** the logical operation finalizes
- **THEN** the validator is called zero times
- **AND** status is `EMPTY`
- **AND** `semantic_validation_status` is `not_run`
- **AND** no second Zen execution is started

#### Scenario: Fetched-positive mapped-zero makes zero validator calls
- **GIVEN** one Zen execution completes normally
- **AND** `fetched > 0`
- **AND** every record fails safe mapping
- **AND** `mapped = 0`
- **WHEN** the logical operation finalizes
- **THEN** the validator is called zero times
- **AND** status is `EMPTY` with mapping diagnostics
- **AND** `semantic_validation_status` is `not_run`
- **AND** no second Zen execution is started

#### Scenario: Constructed mapped batch issues exactly one call
- **GIVEN** one Zen execution returns records
- **AND** `mapped` is between 1 and 20 inclusive
- **AND** the canonical serialized envelope is within `ZEN_SEMANTIC_MAX_BATCH_BYTES`
- **WHEN** semantic validation runs
- **THEN** the validator is called exactly once
- **AND** no retry is issued
- **AND** no second Zen execution is started

#### Scenario: Oversized constructed batch is invalid without a call
- **GIVEN** mapping produced more than 20 candidates or a canonical serialized envelope over `ZEN_SEMANTIC_MAX_BATCH_BYTES`
- **WHEN** the validator request would be built
- **THEN** the validator is called zero times
- **AND** `semantic_validation_status` is `invalid_response`
- **AND** that known mapped count is REVIEW only
- **AND** provider status is `ERROR`
- **AND** no retry is issued

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

No numeric confidence SHALL be invented, stored, or rendered as a validation score. `MATCHES_INTENT` is the only RELEVANT reason. `WRONG_*`, `ACCESSORY_OR_COMPONENT`, and `CONFLICTING_EVIDENCE` may justify IRRELEVANT only with explicit contradiction. `INSUFFICIENT_EVIDENCE` is a model-emitted REVIEW reason. `VALIDATOR_UNAVAILABLE` and `INVALID_PROVIDER_RESPONSE` SHALL be adapter-synthesized REVIEW reasons only and SHALL never be accepted as model output. Those three codes SHALL produce REVIEW, never IRRELEVANT.

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
- **AND** the adapter synthesizes `VALIDATOR_UNAVAILABLE`
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

Before serialization, every string field SHALL be normalized in this order:

1. Unicode NFKC
2. replace every Unicode whitespace character, including whitespace controls such as TAB, LF, CR, VT, and FF, with one ASCII space
3. remove remaining Unicode general-category `Cc` and `Cf` characters
4. compact any whitespace sequence to one ASCII space and strip
5. deterministic truncation to the field cap by Unicode code points for title, category-path items, specification keys, and specification values. The shared query SHALL NOT be truncated here; it already passed the 256 code-point preflight.

Empty `categoryPath` items and specification pairs with an empty key or value SHALL be dropped after normalization. Token boundaries SHALL be preserved: `impact\ndriver` becomes `impact driver`, never `impactdriver`.

`categoryPath` SHALL keep the provider-reported Zen order after empty items are dropped. If more than `ZEN_SEMANTIC_MAX_CATEGORY_PATH_ITEMS` items remain, the implementation SHALL retain exactly the last 8 items. Implementations SHALL NOT sort, pick an arbitrary subset, or keep the first 8. Retaining that trailing suffix preserves the most specific path, including the leaf category.

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
| `ZEN_SEMANTIC_MAX_BATCH_BYTES` | 32768 |

A batch SHALL contain at most `ZEN_SEMANTIC_MAX_BATCH_CANDIDATES` candidates. Because `acquisition_budget` and `max_items` are at most 20, a truthful mapped pool cannot exceed 20. A larger mapped count is a contract violation: the validator SHALL NOT be called and the known mapped count SHALL be finalized as `invalid_response`.

Specification pairs SHALL keep provider-reported order after empty pairs are dropped. The first `ZEN_SEMANTIC_MAX_SPEC_PAIRS` remaining pairs SHALL be retained. Implementations SHALL NOT sort by key, hash iteration, or another arbitrary order. If a normalized candidate object still exceeds `ZEN_SEMANTIC_MAX_CANDIDATE_CHARS`, trailing retained pairs SHALL be dropped from the end until it fits; if it still exceeds the cap, `title` SHALL be truncated further to fit.

The semantic data envelope SHALL be exactly the object with keys `query` and `candidates`, where `query` is the complete shared provider query and `candidates` is the candidate array in existing order. Batch-size measurement SHALL use exclusively the canonical UTF-8 serialization of that complete envelope:

- `ensure_ascii=False`
- `sort_keys=True`
- `separators=(",", ":")`
- `allow_nan=False`
- `encode("utf-8")`
- compare `len(bytes)` with `ZEN_SEMANTIC_MAX_BATCH_BYTES`

The measurement SHALL include the complete query+candidates envelope. It SHALL NOT count HTTP headers, the system prompt, or static tool-schema bytes. Arrays SHALL keep their existing order; `sort_keys=True` orders object keys only.

If that byte length exceeds `ZEN_SEMANTIC_MAX_BATCH_BYTES`:

- model calls SHALL be zero
- the known batch SHALL be `invalid_response`
- every candidate SHALL be REVIEW
- provider status SHALL be `ERROR`
- no retry SHALL occur

#### Scenario: Raw Zen payload is stripped
- **GIVEN** a mapped Zen listing whose raw payload contains `descriptionHtml`, `chatToken`, `trackInfo`, `contactSupplier`, and URLs
- **WHEN** the validator request is built
- **THEN** those fields are absent
- **AND** the request contains sanitized query, title, optional resolved category, `categoryPath`, bounded specs, and `candidate_ref`

#### Scenario: Newline between tokens becomes a space
- **GIVEN** a mapped title `impact\ndriver`
- **WHEN** the validator request is built
- **THEN** the emitted title is `impact driver`
- **AND** it is not `impactdriver`

#### Scenario: Oversized title is truncated to the title cap
- **GIVEN** a mapped title longer than 300 code points after NFKC, whitespace-control replacement, remaining-control removal, and whitespace compaction
- **WHEN** the validator request is built
- **THEN** the emitted title has exactly 300 code points
- **AND** no raw HTML remains

#### Scenario: Specification set is capped
- **GIVEN** a listing has 12 specification pairs after normalization
- **AND** those pairs remain in provider-reported order
- **WHEN** the validator request is built
- **THEN** the first 8 pairs are emitted
- **AND** pairs 9 through 12 are dropped
- **AND** the retained pairs are not reordered by key
- **AND** each key has at most 64 code points
- **AND** each value has at most 128 code points

#### Scenario: Long root-to-leaf category path keeps the last eight
- **GIVEN** Zen reports a root-to-leaf `categoryPath` of 10 non-empty items after normalization
- **WHEN** the validator request is built
- **THEN** items 3 through 10 are emitted in that same provider-reported order
- **AND** the first two ancestor items are dropped
- **AND** the leaf category remains the last emitted item
- **AND** the path is not sorted or arbitrarily subsampled

#### Scenario: Oversized canonical envelope is invalid without a model call
- **GIVEN** a constructed 1..20 candidate batch
- **AND** the canonical UTF-8 serialization of `{"query":"...","candidates":[...]}` exceeds 32768 bytes
- **WHEN** the validator request would be sent
- **THEN** the model is called zero times
- **AND** `semantic_validation_status` is `invalid_response`
- **AND** every candidate is REVIEW
- **AND** provider status is `ERROR`
- **AND** no retry is issued

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

A valid model response SHALL contain exactly one tool call named `classify_alibaba_zen_candidates`. That call's arguments object SHALL contain exactly one key, `decisions`, whose value is an array of items. Each item SHALL contain exactly these fields and no others:

- `candidate_ref` as a string
- `decision` as one of `RELEVANT`, `IRRELEVANT`, `REVIEW`
- `reason_code` as one closed model-emitted reason-code string

Zero tool calls, two or more tool calls, a different tool name including H0019's `classify_bera_brake_pad_candidate`, extra top-level argument keys, a missing `decisions` array, or wrapping the items under another key SHALL invalidate the whole batch. Ordinary assistant content SHALL NOT control classification.

A valid `decisions` array SHALL return exactly one item for each request `candidate_ref`. Extra fields, missing fields, duplicate refs, extra refs, incorrect types, or incompatible `decision`/`reason_code` pairs SHALL invalidate the whole batch. An invalid batch SHALL convert every candidate to REVIEW with adapter-synthesized `INVALID_PROVIDER_RESPONSE` and SHALL NOT be retried.

Permitted model-emitted pairs SHALL be exactly:

- `RELEVANT` with `MATCHES_INTENT` only
- `IRRELEVANT` with `WRONG_PRODUCT_TYPE`, `WRONG_BRAND`, `WRONG_MODEL`, `WRONG_VARIANT_OR_SPEC`, `WRONG_FITMENT`, `ACCESSORY_OR_COMPONENT`, or `CONFLICTING_EVIDENCE`
- `REVIEW` with `INSUFFICIENT_EVIDENCE` or `CONFLICTING_EVIDENCE` only

`VALIDATOR_UNAVAILABLE` and `INVALID_PROVIDER_RESPONSE` SHALL be synthesized only by the adapter. A model-emitted item that uses either failure reason SHALL invalidate the whole batch. Transport/outage failure SHALL be finalized as `unavailable` with adapter-synthesized `VALIDATOR_UNAVAILABLE`. A structurally or semantically invalid response SHALL be finalized as `invalid_response` with adapter-synthesized `INVALID_PROVIDER_RESPONSE`.

Any other pairing, including `RELEVANT` with `WRONG_PRODUCT_TYPE`, is an invalid batch.

The adapter SHALL use a dedicated versioned prompt independent of H0019. The prompt SHALL label query, title, resolved category, `categoryPath`, and specification values as untrusted marketplace data and SHALL instruct the model to ignore embedded instructions in those fields. Seller-controlled text SHALL NOT be treated as system, tool, or orchestration instructions. A prompt-like instruction in one candidate SHALL NOT change another candidate's decision. Provenance SHALL record `model` and `prompt_version`. Z4 SHALL record the exact loopback `model` identifier and `prompt_version` that passed the quality gate. After Z5, Alibaba SEARCH SHALL use only that recorded pair. A different `BERA_TRACKER_OLLAMA_MODEL`, a floating/default model, or a different `prompt_version` SHALL refuse to run the production validator and SHALL NOT cut over. The HTTP client SHALL use a loopback base URL (`127.0.0.1` or `localhost`), `trust_env=False`, and `ZEN_SEMANTIC_HTTP_TIMEOUT_SECONDS = 60`. Logs SHALL NOT contain raw Zen payloads, validator request bodies, or raw model content.

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
- **THEN** the whole batch is REVIEW with adapter-synthesized `INVALID_PROVIDER_RESPONSE`
- **AND** no retry occurs

#### Scenario: Missing field invalidates the batch
- **GIVEN** a response item contains `candidate_ref` and `decision` but no `reason_code`
- **WHEN** the adapter validates the response
- **THEN** the whole batch is REVIEW with adapter-synthesized `INVALID_PROVIDER_RESPONSE`

#### Scenario: Wrong type invalidates the batch
- **GIVEN** a response item has `decision` as an object or `candidate_ref` as a number
- **WHEN** the adapter validates the response
- **THEN** the whole batch is REVIEW with adapter-synthesized `INVALID_PROVIDER_RESPONSE`

#### Scenario: Duplicate reference invalidates the batch
- **GIVEN** the request contains refs `c1` and `c2`
- **AND** the response contains two decisions for `c1` and none for `c2`
- **WHEN** the adapter validates the response
- **THEN** the whole batch is REVIEW with adapter-synthesized `INVALID_PROVIDER_RESPONSE`

#### Scenario: Incompatible decision and reason invalidates the batch
- **GIVEN** a response item is `RELEVANT` with `WRONG_PRODUCT_TYPE`
- **WHEN** the adapter validates the response
- **THEN** the whole batch is REVIEW with adapter-synthesized `INVALID_PROVIDER_RESPONSE`
- **AND** no candidate is published as canonical RELEVANT

#### Scenario: Model-emitted failure reason invalidates the batch
- **GIVEN** a structurally complete item is `REVIEW` with `VALIDATOR_UNAVAILABLE`
- **WHEN** the adapter validates the response
- **THEN** the whole batch is REVIEW with adapter-synthesized `INVALID_PROVIDER_RESPONSE`
- **AND** `semantic_validation_status` is `invalid_response`
- **AND** the batch is not treated as a completed EMPTY incidence

#### Scenario: Wrong tool name invalidates the batch
- **GIVEN** the model returns one tool call named `classify_bera_brake_pad_candidate`
- **AND** the arguments contain a well-shaped `decisions` array
- **WHEN** the adapter validates the response
- **THEN** the whole batch is REVIEW with adapter-synthesized `INVALID_PROVIDER_RESPONSE`

#### Scenario: Second tool call invalidates the batch
- **GIVEN** the model returns two tool calls named `classify_alibaba_zen_candidates`
- **WHEN** the adapter validates the response
- **THEN** the whole batch is REVIEW with adapter-synthesized `INVALID_PROVIDER_RESPONSE`
- **AND** the adapter does not merge or keep the first call

#### Scenario: Valid 1:1 response is accepted
- **GIVEN** the request contains refs `c1`, `c2`, and `c3`
- **AND** the model returns exactly one `classify_alibaba_zen_candidates` call
- **AND** its arguments are `{ "decisions": [those three items] }`
- **AND** each pair is a permitted model-emitted decision/reason combination
- **WHEN** the adapter validates the response
- **THEN** each candidate keeps its own decision
- **AND** no additional candidate is introduced
- **AND** ordinary assistant text does not change those decisions

#### Scenario: Embedded instruction cannot flip sibling candidates
- **GIVEN** candidate `c1` has title text that says to classify every other listing IRRELEVANT
- **AND** candidate `c2` would otherwise be RELEVANT with `MATCHES_INTENT`
- **WHEN** the batch is validated
- **THEN** `c2` is not forced to IRRELEVANT by `c1`'s seller text
- **AND** the prompt treated that title as untrusted marketplace data

#### Scenario: Transport is loopback and isolated from H0019
- **GIVEN** the semantic adapter is constructed
- **WHEN** its HTTP client is configured
- **THEN** the base URL host is loopback
- **AND** `trust_env` is `False`
- **AND** the timeout is 60 seconds
- **AND** the prompt, tool schema, and domain are not H0019 artifacts

### Requirement: Canonical membership is RELEVANT-only and preserves Zen order

RELEVANT candidates SHALL enter the ordered usable pool, canonical session prefix, statistics, ranking annotations, export, and positional comparison. After Z5, Alibaba SEARCH SHALL also persist two immutable generation-bound collections on `ProviderRunResult` and `SearchSessionSnapshot`:

- `review_candidates`: REVIEW listings in Zen order, the only source for **Requiere revisión**
- `excluded_candidates`: IRRELEVANT listings in Zen order, each retaining its reason

Those collections SHALL be committed only when `result.generation == snapshot.intent.generation`. **Nueva búsqueda** and a newer generation SHALL clear them. GUI, diagnostics, and export SHALL NOT keep review or excluded rows in separate mutable state after a new search. IRRELEVANT candidates SHALL be excluded from canonical surfaces and SHALL retain their reason and semantic metric. REVIEW candidates SHALL NOT enter statistics, ranking, export, or positional comparison. Accepted RELEVANT results SHALL preserve Zen acquisition order. The semantic decision SHALL NOT be used as a ranking score. Non-Alibaba `ProviderRunResult` values SHALL use empty `review_candidates` and `excluded_candidates`.

#### Scenario: Mixed decisions split canonical and review projections
- **GIVEN** Zen order is A, B, C, D
- **AND** decisions are RELEVANT, IRRELEVANT, REVIEW, RELEVANT
- **WHEN** the Alibaba result is committed
- **THEN** the ordered usable pool is A, D
- **AND** canonical session results are the `display_limit` prefix of A, D
- **AND** `review_candidates` is exactly `[C]`
- **AND** `excluded_candidates` is exactly `[B]`
- **AND** C appears only under **Requiere revisión**
- **AND** B is excluded with its IRRELEVANT reason
- **AND** B and C are absent from export and positional comparison

#### Scenario: Nueva búsqueda clears review and excluded collections
- **GIVEN** the current snapshot holds Alibaba `review_candidates` from generation `N`
- **WHEN** **Nueva búsqueda** starts generation `N+1`
- **THEN** those review and excluded rows are cleared
- **AND** a late generation-`N` result cannot repopulate them

#### Scenario: Semantic decision does not reorder RELEVANT results
- **GIVEN** two RELEVANT listings where the later Zen result looks like a closer match
- **WHEN** canonical order is frozen
- **THEN** the earlier Zen RELEVANT listing remains first
- **AND** no semantic score reorders them

### Requirement: Alibaba SEARCH status uses semantic outcomes without reusing coverage

After a completed validator batch, `usable` SHALL equal the RELEVANT pool size. A completed validator with zero RELEVANT SHALL be `EMPTY`. A validator outage or wholly invalid response against a known-size mapped batch SHALL be `ERROR`, never a silent `SUCCESS`. RELEVANT together with REVIEW SHALL be `SUCCESS` with a semantic-validation incidence. Geographic `coverage_status` SHALL NOT represent semantic validation. Alibaba SEARCH geographic coverage remains not applicable.

Required Alibaba SEARCH metrics SHALL include `fetched`, `mapped`, `semantic_relevant`, `semantic_irrelevant`, `semantic_review`, `usable`, and `semantic_validation_status`. Unknown remains unknown only when the failure occurs before a known-size mapped pool exists.

When a known-size mapped batch is `unavailable` or `invalid_response`:

- `semantic_relevant = 0`
- `semantic_irrelevant = 0`
- `semantic_review =` that known batch size
- `semantic_validation_status = unavailable` or `invalid_response`
- the canonical pool is empty
- provider status is `ERROR`
- the mapped candidates appear only under **Requiere revisión**

`semantic_validation_status` SHALL be one of `completed`, `unavailable`, `invalid_response`, or `not_run` when Alibaba Zen validation applies. It SHALL NOT be a `CoverageStatus` value. `not_run` is the required value when Zen completed and `mapped == 0`. Diagnostics and export SHALL render `not_run` as not applicable / blank, never as completed work and never as an error.

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

#### Scenario: Mapped-zero uses not_run rather than completed or error
- **GIVEN** Zen completed normally
- **AND** `mapped = 0`
- **WHEN** metrics are finalized
- **THEN** `semantic_validation_status` is `not_run`
- **AND** it is not `completed`, `unavailable`, or `invalid_response`
- **AND** diagnostics and export render that status as not applicable / blank

#### Scenario: Semantic metrics remain unknown only before a known mapped pool exists
- **GIVEN** mapping has not yet produced a known mapped count
- **AND** the provider fails before that count is known
- **WHEN** metrics are finalized
- **THEN** `semantic_relevant`, `semantic_irrelevant`, and `semantic_review` remain unknown
- **AND** those counts are not fabricated as zero completed totals

### Requirement: Alibaba SEARCH currency uses Zen structured USD evidence

The memo23 SEARCH raw `price` marker `US $` / `US$` SHALL NOT be reused for Zen SEARCH. Zen SEARCH SHALL expose distinct fields:

- `localized_currency`
- `source_currency`
- `price_provenance`
- `ship_to_country`

Localized USD mapping SHALL be deterministic:

1. Parse each `detail.price.productLadderPrices[*].dollarPrice` as a `Decimal`. Reject booleans, non-finite values, and values `<= 0`.
2. If at least one valid ladder value exists, `min_price` is the minimum of those values and `max_price` is the maximum. A single valid value fills both fields. Do not select the first tier, last tier, or an MOQ tier.
3. Independently parse `detail.price.productRangePrices.dollarPriceRangeLow` and `dollarPriceRangeHigh` with the same Decimal rules. If only one of the two range fields is valid, range evidence is insufficient. If both are valid and `range_low > range_high`, the range is inverted and SHALL be treated as conflicting evidence: `localized_currency` stays unknown and the price SHALL NOT enter USD statistics.
4. If both ladder extrema and a complete range exist, they are compatible only when `quantize_money(ladder_min) == quantize_money(range_low)` and `quantize_money(ladder_max) == quantize_money(range_high)`. Any disagreement is conflicting evidence: `localized_currency` stays unknown and the price SHALL NOT enter USD statistics.
5. If no valid ladder values exist and a complete compatible range exists, use that range as `min_price` / `max_price`.
6. `product.price` is display/fallback only and SHALL NOT enter USD statistics.
7. `detail.currency` is source currency, never automatic localized currency.
8. If structured evidence is insufficient or conflicting, `localized_currency` is `None` and the price SHALL NOT enter USD statistics.

Z1 SHALL confirm those structured paths against sanitized fixtures. If a named path is absent, the mapper SHALL NOT invent `dollarPrice` from a bare `$` display string, from `detail.currency`, or from locale. `ship_to_country` for this SEARCH contract is `US`.

#### Scenario: Structured dollarPrice may enter USD statistics
- **GIVEN** sanitized fixture evidence contains `detail.price.productLadderPrices` with `dollarPrice` values `1.20` and `3.40`
- **AND** no contradictory range evidence exists
- **WHEN** the listing is mapped
- **THEN** `localized_currency` is USD
- **AND** `min_price` is `1.20`
- **AND** `max_price` is `3.40`
- **AND** `price_provenance` records the ladder dollarPrice path
- **AND** the listing may participate in USD aggregates
- **AND** neither the first nor last tier is selected by position

#### Scenario: Conflicting ladder and range stay unknown
- **GIVEN** valid ladder dollarPrice extrema `1.20` and `3.40`
- **AND** `dollarPriceRangeLow` / `dollarPriceRangeHigh` are `2.00` and `4.00`
- **WHEN** the listing is mapped
- **THEN** `localized_currency` remains unknown
- **AND** the listing does not enter USD aggregates

#### Scenario: Inverted structured range stays unknown
- **GIVEN** no valid ladder dollarPrice values exist
- **AND** `dollarPriceRangeLow` is `4.00`
- **AND** `dollarPriceRangeHigh` is `2.00`
- **WHEN** the listing is mapped
- **THEN** `localized_currency` remains unknown
- **AND** those inverted values are not assigned to `min_price` / `max_price`
- **AND** the listing does not enter USD aggregates

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

Those files are not in this repository at Z0. Their contents SHALL NOT be fabricated. Z1 SHALL incorporate sanitized structural fixtures after tokens, HTML, contacts, and tracking are removed, without semantic labels. Z4 SHALL add independent human-reviewed golden labels and SHALL measure the same loopback validator adapter and pinned prompt against those five datasets.

The Z4 labeled corpus SHALL exercise `RELEVANT`, `IRRELEVANT`, and `REVIEW` with at least one real human label of each class. Labels SHALL NOT be fabricated to satisfy coverage. If any class is missing, Z4 is incomplete and Z5 remains blocked. Golden labels SHALL NOT be generated by the same model being evaluated.

Call-budget classes SHALL stay distinct:

- Automated unit, integration, and Playwright suites: zero Apify, zero marketplaces, zero DeepL, zero Ollama/model inference, fakes only.
- Controlled Z4 semantic benchmark: zero Apify, zero marketplaces, and zero DeepL. It MAY perform exactly the inferences required against the evaluated `model` identifier and `prompt_version`, only through the loopback Ollama endpoint. It SHALL record `model`, `prompt_version`, and call count. It SHALL NOT call any other model. If the evaluated model has a cloud backend, including `minimax-m3:cloud`, the benchmark SHALL NOT be described as completely offline and SHALL NOT claim "MiniMax calls = 0".

The Z4 benchmark SHALL NOT substitute fakes or prerecorded decisions for the labeled measurement. Z4 SHALL record the exact `model` identifier and `prompt_version` that passed. Z5 MAY start only after every Z4 acceptance criterion passed and SHALL refuse cutover if the configured model or `prompt_version` differs from that pin. The production SEARCH Actor SHALL remain `memo23/alibaba-scraper` until that cutover.

After Z5 integrates the Actor, GUI, diagnostics, currency, and export, Z5 SHALL rerun format check, lint, mypy, unit, integration, applicable Playwright, the E.7-equivalent compatibility gate, and the tracking, refresh, landed-cost, negotiation, H0019, positional-comparison, generation-guard, CSV, and currency-provenance suites. Those automated tests remain fake/offline and SHALL NOT execute Apify or real models. Z5 SHALL NOT complete or merge if that gate fails.

Z4 minimum acceptance criteria SHALL be:

- identity-less listings remain distinct
- unknowns stay null / **No disponible**
- `display_limit` remains separate from `acquisition_budget`
- no cross-market identity was introduced
- `mapped == 0` produces zero validator calls and `semantic_validation_status = not_run`
- a successfully constructed batch of 1..20 produces exactly one call
- no validator retry and no second Zen run
- ALL-REVIEW uses `Búsqueda completada con incidencias`
- every human-labeled fixture is compared to the loopback validator decision and a complete confusion matrix is recorded
- Z4 fails if any human-RELEVANT fixture is classified IRRELEVANT
- Z4 fails if any of the five datasets has at least one human RELEVANT label and the validator produces zero RELEVANT on that dataset
- Z4 fails if any human-IRRELEVANT fixture is classified RELEVANT
- Z4 fails if any of the five datasets has at least one human IRRELEVANT label and the validator produces zero IRRELEVANT on that dataset
- any human-REVIEW fixture SHALL produce validator REVIEW
- Z4 fails if any human-REVIEW fixture is classified RELEVANT
- Z4 fails if any human-REVIEW fixture is classified IRRELEVANT
- an all-REVIEW degenerate result cannot pass datasets that contain human RELEVANT or human IRRELEVANT labels
- an all-RELEVANT degenerate result cannot pass
- no numeric precision/recall SLA is invented
- production Actor remains memo23 throughout Z4
- the passing `model` and `prompt_version` are recorded as the only authorized Z5 pair

#### Scenario: Missing benchmarks block fixture authorship, not cutover authorship
- **GIVEN** the five named benchmark files are unavailable
- **WHEN** Z0 is recorded
- **THEN** no synthetic Zen dataset is added to the repository
- **AND** Z1 remains blocked on sanitized structural fixtures
- **AND** Z4 remains blocked on independent human labels and a passing labeled quality gate
- **AND** Z5 remains blocked on a fully passing Z4

#### Scenario: Automated tests stay fake and offline
- **WHEN** future Z1–Z5 automated unit, integration, and Playwright suites run
- **THEN** Apify, marketplace, DeepL, and Ollama/model-inference call counts are all zero
- **AND** those suites use fakes rather than the Z4 quality-gate model

#### Scenario: Z4 quality gate exercises the evaluated loopback model
- **GIVEN** the five labeled datasets exist
- **AND** the evaluated model identifier is `minimax-m3:cloud`
- **WHEN** Z4 runs the semantic quality gate
- **THEN** the same loopback validator adapter and pinned prompt are called
- **AND** decisions are not replaced by fakes or prerecorded labels
- **AND** Apify, marketplace, and DeepL calls remain zero
- **AND** only that evaluated model and `prompt_version` are inferred, through loopback Ollama
- **AND** the recorded call count is greater than zero
- **AND** the benchmark is not described as completely offline
- **AND** the record does not claim MiniMax calls were zero

#### Scenario: Quality gate precedes production cutover
- **GIVEN** Z4 has not passed every acceptance criterion
- **WHEN** a later task attempts the production Actor switch
- **THEN** that switch is forbidden
- **AND** production SEARCH remains `memo23/alibaba-scraper`

#### Scenario: All-REVIEW validator cannot pass the labeled gate
- **GIVEN** a named benchmark dataset has at least one human RELEVANT label
- **AND** the loopback validator marks every fixture REVIEW
- **WHEN** Z4 evaluates acceptance
- **THEN** Z4 fails
- **AND** Z5 MUST NOT start

#### Scenario: All-RELEVANT validator cannot pass the labeled gate
- **GIVEN** a named benchmark dataset has at least one human IRRELEVANT label
- **AND** the loopback validator marks every fixture RELEVANT
- **WHEN** Z4 evaluates acceptance
- **THEN** Z4 fails
- **AND** Z5 MUST NOT start

#### Scenario: False exclusion of a human-RELEVANT fixture fails the gate
- **GIVEN** a human-reviewed fixture is labeled RELEVANT
- **AND** the loopback validator decides IRRELEVANT
- **WHEN** Z4 evaluates acceptance
- **THEN** Z4 fails
- **AND** Z5 MUST NOT start

#### Scenario: False inclusion of a human-IRRELEVANT fixture fails the gate
- **GIVEN** a human-reviewed fixture is labeled IRRELEVANT
- **AND** the loopback validator decides RELEVANT
- **WHEN** Z4 evaluates acceptance
- **THEN** Z4 fails
- **AND** Z5 MUST NOT start

#### Scenario: Human-REVIEW must remain REVIEW
- **GIVEN** a human-reviewed fixture is labeled REVIEW
- **WHEN** Z4 evaluates acceptance
- **THEN** the validator decision for that fixture is REVIEW
- **AND** human-REVIEW classified RELEVANT fails the gate
- **AND** human-REVIEW classified IRRELEVANT fails the gate

#### Scenario: Missing human class leaves Z4 incomplete
- **GIVEN** the labeled corpus has human RELEVANT and human IRRELEVANT fixtures
- **AND** it has no real human REVIEW label
- **WHEN** Z4 coverage is checked
- **THEN** Z4 is incomplete
- **AND** no fabricated REVIEW label is added
- **AND** Z5 remains blocked

#### Scenario: Z5 post-cutover quality gate is required
- **GIVEN** Z5 has switched the Actor and wired GUI, diagnostics, currency, and export
- **WHEN** the post-cutover gate runs
- **THEN** format check, lint, mypy, unit, integration, applicable Playwright, and the E.7-equivalent compatibility gate all run
- **AND** tracking, refresh, landed cost, negotiation, H0019, positional comparison, generation guards, CSV, and currency provenance are retested
- **AND** those automated suites remain fake/offline and start no Apify or real-model calls
- **AND** Z5 cannot complete or merge if that gate fails

#### Scenario: Z5 rejects a model or prompt that did not pass Z4
- **GIVEN** Z4 recorded `model = llama-gate:tag` and `prompt_version = zen-semantic-v1`
- **AND** production `BERA_TRACKER_OLLAMA_MODEL` is a different identifier
- **WHEN** Z5 would switch the SEARCH Actor or start production validation
- **THEN** that switch and validation are refused
- **AND** production SEARCH remains `memo23/alibaba-scraper`
