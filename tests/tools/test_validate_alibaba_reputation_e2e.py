"""Offline regressions for the Alibaba reputation live/replay validator."""

from __future__ import annotations

from typing import Any

import pytest

from bera_price_tracker.infrastructure.providers.alibaba import (
    _scalar_text as production_scalar_text,
)
from tools.validate_alibaba_reputation_e2e import (
    HISTORICAL_SEARCH_ACTOR_KEYS,
    MEMO23_DOCUMENTED_ACTOR_KEYS,
    ReplayActorClient,
    ReplayActorMismatch,
    classify_observed_schema,
    extract_run_provenance,
    indep_rating,
    run_belongs_to_configured_search_actor,
    scalar_text,
)

MEMO23_SEARCH_ACTOR = "memo23/alibaba-scraper"


def _legacy_search_actor(*, tilde: bool = False) -> str:
    separator = "~" if tilde else "/"
    return separator.join(("scraper-engine", "alibaba-scraper"))


class _FakeRunClient:
    def __init__(self, run: dict[str, object]) -> None:
        self.run = run
        self.gets = 0

    def get(self) -> dict[str, object]:
        self.gets += 1
        return dict(self.run)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (4.8, "4.8"),
        (4, "4"),
        (0, "0"),
        (0.0, "0.0"),
        ("4.8", "4.8"),
        (8.5, "8.5"),
        ("  ", None),
        (True, None),
        (False, None),
        (float("nan"), None),
        (float("inf"), None),
        (float("-inf"), None),
    ],
)
def test_validator_scalar_text_matches_production_boundary(
    raw: object, expected: str | None
) -> None:
    assert scalar_text(raw) == expected
    assert production_scalar_text(raw) == expected
    assert scalar_text(raw) == production_scalar_text(raw)


def test_zero_ratings_are_not_normalized_to_missing() -> None:
    assert scalar_text(0) == "0"
    assert scalar_text(0.0) == "0.0"
    assert scalar_text("0") == "0"
    assert indep_rating(0) == indep_rating("0")


def test_out_of_range_finite_score_survives_scalar_but_not_rating_parser() -> None:
    assert scalar_text(8.5) == "8.5"
    assert indep_rating(8.5) is None


def test_replay_rejects_legacy_search_actor_run() -> None:
    record: dict[str, Any] = {
        "actor_calls_created": 0,
        "actor_id": MEMO23_SEARCH_ACTOR,
        "configured_actor_id": MEMO23_SEARCH_ACTOR,
    }
    client = ReplayActorClient(
        _FakeRunClient(
            {
                "id": "run-legacy",
                "status": "SUCCEEDED",
                "actId": _legacy_search_actor(tilde=True),
                "buildId": "build-legacy",
                "buildNumber": "1.0.0",
                "defaultDatasetId": "ds-legacy",
            }
        ),
        record,
    )
    with pytest.raises(ReplayActorMismatch, match="SEARCH Actor"):
        client.call(run_input={"searchTerms": ["wireless mouse"], "maxItems": 20})
    assert record["actor_calls_created"] == 0
    assert record["run_act_id"] == _legacy_search_actor(tilde=True)
    assert record["configured_actor_id"] == MEMO23_SEARCH_ACTOR
    assert record["run_act_id"] != record["configured_actor_id"]


def test_replay_accepts_memo23_name_and_tilde_form() -> None:
    record: dict[str, Any] = {
        "actor_calls_created": 0,
        "actor_id": MEMO23_SEARCH_ACTOR,
        "configured_actor_id": MEMO23_SEARCH_ACTOR,
    }
    client = ReplayActorClient(
        _FakeRunClient(
            {
                "id": "run-memo23",
                "status": "SUCCEEDED",
                "actId": "memo23~alibaba-scraper",
                "buildId": "build-memo23",
                "buildNumber": "0.1.4",
                "defaultDatasetId": "ds-memo23",
            }
        ),
        record,
    )
    run = client.call(run_input={"searchTerms": ["wireless mouse"], "maxItems": 20})
    assert run["id"] == "run-memo23"
    assert record["run_build_id"] == "build-memo23"
    assert record["run_build_number"] == "0.1.4"
    assert run_belongs_to_configured_search_actor(
        configured_actor_id=MEMO23_SEARCH_ACTOR,
        run_act_id=record["run_act_id"],
    )


def test_replay_accepts_resolved_unique_actor_id() -> None:
    record: dict[str, Any] = {
        "actor_calls_created": 0,
        "actor_id": MEMO23_SEARCH_ACTOR,
        "configured_actor_id": MEMO23_SEARCH_ACTOR,
        "configured_actor_aliases": ["7Rn373Iimdl3A6goA"],
    }
    client = ReplayActorClient(
        _FakeRunClient(
            {
                "id": "run-id-form",
                "status": "SUCCEEDED",
                "actId": "7Rn373Iimdl3A6goA",
                "buildId": "1BDUcxT7uIjwsJMN1",
                "buildNumber": "0.1.4",
            }
        ),
        record,
    )
    run = client.call(run_input={})
    assert run["actId"] == "7Rn373Iimdl3A6goA"


def test_replay_rejects_run_without_actor_provenance() -> None:
    record: dict[str, Any] = {
        "actor_calls_created": 0,
        "configured_actor_id": MEMO23_SEARCH_ACTOR,
    }
    client = ReplayActorClient(
        _FakeRunClient({"id": "run-opaque", "status": "SUCCEEDED", "defaultDatasetId": "ds"}),
        record,
    )
    with pytest.raises(ReplayActorMismatch, match="SEARCH Actor"):
        client.call(run_input={})


def test_extract_run_provenance_reports_build_fields() -> None:
    provenance = extract_run_provenance(
        {
            "id": "run-1",
            "status": "SUCCEEDED",
            "actId": "memo23~alibaba-scraper",
            "buildId": "build-123",
            "buildNumber": "0.1.4",
        }
    )
    assert provenance["run_id"] == "run-1"
    assert provenance["act_id"] == "memo23~alibaba-scraper"
    assert provenance["build_id"] == "build-123"
    assert provenance["build_number"] == "0.1.4"
    assert provenance["status"] == "SUCCEEDED"


def test_healthy_memo23_keys_are_not_unknown_schema() -> None:
    observed = {
        "productId",
        "title",
        "productUrl",
        "price",
        "priceMin",
        "minOrder",
        "unit",
        "quantityPrices",
        "supplierName",
        "supplierCountry",
        "supplierCountryCode",
        "supplierYears",
        "reviewScore",
        "supplierServiceScore",
        "reviewCount",
        "goldSupplier",
        "verifiedSupplierPro",
        "tradeAssurance",
        "category",
        "categoryId",
        "isAd",
        "mainImage",
        "searchTerm",
        "page",
        "certifications",
    }
    unknown, absent_optional = classify_observed_schema(observed)
    assert unknown == []
    assert "productReviewScore" in absent_optional
    assert "shippingTimeScore" in absent_optional
    assert "companyName" not in absent_optional
    assert "chatToken" not in absent_optional


def test_legacy_only_keys_are_unknown_not_required_optional() -> None:
    unknown, absent_optional = classify_observed_schema({"title", "companyName", "chatToken"})
    assert "companyName" in unknown
    assert "chatToken" in unknown
    assert "supplierName" in absent_optional
    assert "title" not in unknown
    assert "companyName" in HISTORICAL_SEARCH_ACTOR_KEYS
    assert "chatToken" in HISTORICAL_SEARCH_ACTOR_KEYS
    assert "companyName" not in MEMO23_DOCUMENTED_ACTOR_KEYS
    assert "supplierName" in MEMO23_DOCUMENTED_ACTOR_KEYS


def test_custom_actor_does_not_match_memo23() -> None:
    assert not run_belongs_to_configured_search_actor(
        configured_actor_id=MEMO23_SEARCH_ACTOR,
        run_act_id="custom/incompatible-alibaba-actor",
    )
    assert run_belongs_to_configured_search_actor(
        configured_actor_id=MEMO23_SEARCH_ACTOR,
        run_act_id="memo23~alibaba-scraper",
    )
