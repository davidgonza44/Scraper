"""Offline regressions for the Alibaba reputation live/replay validator."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from bera_price_tracker.application.ports import MarketplaceSourceUnavailable
from bera_price_tracker.application.services import SearchAlibabaProducts
from bera_price_tracker.config import DEFAULT_APIFY_ALIBABA_ACTOR
from bera_price_tracker.gui.services import run_alibaba_search
from bera_price_tracker.infrastructure.providers.alibaba import (
    ApifyAlibabaClient,
    map_alibaba_item,
)
from bera_price_tracker.infrastructure.providers.alibaba import (
    _identity_text as production_identity_text,
)
from bera_price_tracker.infrastructure.providers.alibaba import (
    _scalar_text as production_scalar_text,
)
from tools.validate_alibaba_reputation_e2e import (
    HISTORICAL_SEARCH_ACTOR_KEYS,
    MEMO23_DOCUMENTED_ACTOR_KEYS,
    RecordingSearchService,
    ReplayActorClient,
    ReplayActorMismatch,
    ReplayProvenanceUnavailable,
    _configured_actor_aliases,
    _display_provenance,
    _print_run_record,
    alibaba_product_excludes_transport_fields,
    classify_observed_schema,
    classify_replay_provenance,
    emit_search_failure,
    extract_run_provenance,
    find_exception_in_chain,
    has_mapped_products,
    identity_text,
    indep_count,
    indep_rating,
    indep_years,
    replay_search_failure_kind,
    report_mapped_products,
    run_belongs_to_configured_search_actor,
    scalar_text,
)

MEMO23_SEARCH_ACTOR = "memo23/alibaba-scraper"
MEMO23_OPAQUE_ACTOR_ID = "7Rn373Iimdl3A6goA"
OTHER_OPAQUE_ACTOR_ID = "0OTHERACTORID0001"
VALIDATOR_PATH = (
    Path(__file__).resolve().parents[2] / "tools" / "validate_alibaba_reputation_e2e.py"
)
PRODUCTION_ALIBABA_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "bera_price_tracker"
    / "infrastructure"
    / "providers"
    / "alibaba.py"
)


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


def test_indep_years_rejects_exponent_and_signed_forms() -> None:
    assert indep_years("6 yrs") == Decimal("6")
    assert indep_years("1 yr") == Decimal("1")
    assert indep_years("5") == Decimal("5")
    for raw in (1e100, -5.0, "1e100", "1e+100", "-5", "-5.0"):
        assert indep_years(raw) is None


def test_indep_count_requires_non_negative_integral_value() -> None:
    assert indep_count(0) == Decimal("0")
    assert indep_count(1.0) == Decimal("1")
    assert indep_count("12.0") == Decimal("12.0")
    for raw in (0.5, 1.5, "0.5", -1, float("nan"), float("inf")):
        assert indep_count(raw) is None
    assert indep_rating(4.5) == Decimal("4.5")


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
    with pytest.raises(ReplayProvenanceUnavailable):
        client.call(run_input={})
    assert record["run_act_id"] is None
    assert record["actor_calls_created"] == 0


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


def _secret_run_record() -> dict[str, Any]:
    return {
        "actor_calls_created": 0,
        "configured_actor_id": {"token": "SECRET_CONFIG"},
        "run_id": {"password": "SECRET_RUN"},
        "run_act_id": {"token": "SECRET_ACT"},
        "run_build_id": {"token": "SECRET_BUILD"},
        "run_build_number": ["SECRET_NUMBER"],
        "run_status": {"authorization": "SECRET_STATUS"},
    }


def _assert_no_run_metadata_secrets(text: str) -> None:
    for secret in (
        "SECRET_CONFIG",
        "SECRET_RUN",
        "SECRET_ACT",
        "SECRET_BUILD",
        "SECRET_NUMBER",
        "SECRET_STATUS",
    ):
        assert secret not in text
    assert "token" not in text
    assert "password" not in text
    assert "authorization" not in text


def test_extract_run_provenance_drops_malformed_metadata_objects() -> None:
    provenance = extract_run_provenance(
        {
            "id": {"password": "SECRET_RUN"},
            "status": {"authorization": "SECRET_STATUS"},
            "actId": {"token": "SECRET_ACT"},
            "buildId": {"token": "SECRET_BUILD"},
            "buildNumber": ["SECRET_NUMBER"],
        }
    )
    assert provenance == {
        "run_id": None,
        "act_id": None,
        "build_id": None,
        "build_number": None,
        "status": None,
    }
    dumped = repr(provenance)
    _assert_no_run_metadata_secrets(dumped)


def test_display_provenance_does_not_stringify_objects() -> None:
    assert _display_provenance("  memo23/alibaba-scraper  ") == MEMO23_SEARCH_ACTOR
    assert _display_provenance(None) == "—"
    assert _display_provenance({"token": "SECRET_ACT"}) == "—"
    assert _display_provenance(["SECRET_NUMBER"]) == "—"
    assert _display_provenance({"authorization": "SECRET_STATUS"}) == "—"
    assert "SECRET_ACT" not in _display_provenance({"token": "SECRET_ACT"})


def test_malformed_run_metadata_is_redacted_on_failure_path(
    capsys: pytest.CaptureFixture[str],
) -> None:
    record = _secret_run_record()
    assert (
        emit_search_failure(MarketplaceSourceUnavailable("Alibaba source is unavailable"), record)
        == 1
    )
    out = capsys.readouterr().out
    _assert_no_run_metadata_secrets(out)
    assert "Actor configurado: —" in out
    assert "Actor real del run (actId): —" in out
    assert "buildId: —" in out
    assert "buildNumber: —" in out
    assert "status: —" in out


def test_malformed_run_metadata_is_redacted_on_success_report(
    capsys: pytest.CaptureFixture[str],
) -> None:
    record = _secret_run_record()
    _print_run_record(record)
    out = capsys.readouterr().out
    _assert_no_run_metadata_secrets(out)
    assert "run reutilizable: —" in out
    assert "status: —" in out


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


def _explicit_wrap(inner: BaseException, outer: BaseException) -> BaseException:
    try:
        raise outer from inner
    except type(outer) as wrapped:
        return wrapped


def _implicit_wrap(inner: BaseException, outer: BaseException) -> BaseException:
    outer.__context__ = inner
    return outer


def _mismatch() -> ReplayActorMismatch:
    return ReplayActorMismatch(
        "Replayed run does not belong to the configured Alibaba SEARCH Actor"
    )


class _ReplayCallFactory:
    def __init__(self, actor_client: object) -> None:
        self._actor_client = actor_client
        self.dataset_reads = 0

    def actor(self, actor_id: str) -> object:
        del actor_id
        return self._actor_client

    def dataset(self, dataset_id: str) -> object:
        del dataset_id
        self.dataset_reads += 1
        raise AssertionError("dataset mapping must not run for provenance failures")


def test_find_exception_in_chain_direct_mismatch() -> None:
    exc = _mismatch()
    assert find_exception_in_chain(exc, ReplayActorMismatch) is exc
    assert replay_search_failure_kind(exc) == "mismatch"


def test_find_exception_in_chain_wrapped_from_mismatch() -> None:
    inner = _mismatch()
    wrapped = _explicit_wrap(inner, MarketplaceSourceUnavailable("Alibaba source is unavailable"))
    assert isinstance(wrapped, MarketplaceSourceUnavailable)
    assert not isinstance(wrapped, ReplayActorMismatch)
    assert find_exception_in_chain(wrapped, ReplayActorMismatch) is inner
    assert replay_search_failure_kind(wrapped) == "mismatch"


def test_find_exception_in_chain_two_nested_wrappers() -> None:
    inner = _mismatch()
    mid = _explicit_wrap(inner, RuntimeError("mid wrapper"))
    outer = _explicit_wrap(mid, MarketplaceSourceUnavailable("Alibaba source is unavailable"))
    assert find_exception_in_chain(outer, ReplayActorMismatch) is inner
    assert replay_search_failure_kind(outer) == "mismatch"


def test_find_exception_in_chain_implicit_context() -> None:
    inner = _mismatch()
    wrapped = _implicit_wrap(inner, MarketplaceSourceUnavailable("Alibaba source is unavailable"))
    assert wrapped.__context__ is inner
    assert find_exception_in_chain(wrapped, ReplayActorMismatch) is inner
    assert replay_search_failure_kind(wrapped) == "mismatch"


def test_unrelated_source_unavailable_is_not_replay_mismatch() -> None:
    exc = MarketplaceSourceUnavailable("Alibaba source is unavailable")
    assert find_exception_in_chain(exc, ReplayActorMismatch) is None
    assert replay_search_failure_kind(exc) == "other"


def test_unrelated_valueerror_in_chain_is_not_replay_mismatch() -> None:
    inner = ValueError("unrelated validator input")
    wrapped = _explicit_wrap(inner, MarketplaceSourceUnavailable("Alibaba source is unavailable"))
    assert find_exception_in_chain(wrapped, ReplayActorMismatch) is None
    assert find_exception_in_chain(wrapped, ReplayProvenanceUnavailable) is None
    assert replay_search_failure_kind(wrapped) == "other"


def test_find_exception_in_chain_is_cycle_safe() -> None:
    first = RuntimeError("first")
    second = RuntimeError("second")
    first.__cause__ = second
    second.__cause__ = first
    first.__context__ = second
    second.__context__ = first
    assert find_exception_in_chain(first, ReplayActorMismatch) is None
    assert replay_search_failure_kind(first) == "other"


def test_production_client_wraps_replay_mismatch_and_validator_still_detects_it() -> None:
    production_source = PRODUCTION_ALIBABA_PATH.read_text(encoding="utf-8")
    assert "ReplayActorMismatch" not in production_source
    assert "ReplayProvenanceUnavailable" not in production_source

    record: dict[str, Any] = {
        "actor_calls_created": 0,
        "configured_actor_id": MEMO23_SEARCH_ACTOR,
        "configured_actor_aliases": [MEMO23_SEARCH_ACTOR],
    }
    replay = ReplayActorClient(
        _FakeRunClient(
            {
                "id": "run-legacy",
                "status": "SUCCEEDED",
                "actId": _legacy_search_actor(),
                "buildId": "build-legacy",
                "buildNumber": "1.0.0",
                "defaultDatasetId": "ds-legacy",
            }
        ),
        record,
    )
    factory = _ReplayCallFactory(replay)
    client = ApifyAlibabaClient(
        _api_token="token",
        client_factory=lambda _token: cast(Any, factory),
    )
    with pytest.raises(MarketplaceSourceUnavailable) as caught:
        client.search("wireless mouse", 1)
    assert type(caught.value) is MarketplaceSourceUnavailable
    assert not isinstance(caught.value, ReplayActorMismatch)
    assert isinstance(caught.value.__cause__, ReplayActorMismatch)
    assert find_exception_in_chain(caught.value, ReplayActorMismatch) is caught.value.__cause__
    assert replay_search_failure_kind(caught.value) == "mismatch"
    assert record["actor_calls_created"] == 0
    assert factory.dataset_reads == 0
    assert record["run_act_id"] == _legacy_search_actor()
    assert record["configured_actor_id"] == MEMO23_SEARCH_ACTOR
    assert record["run_build_id"] == "build-legacy"
    assert record["run_build_number"] == "1.0.0"


def test_wrapped_mismatch_report_stays_sanitized(capsys: pytest.CaptureFixture[str]) -> None:
    record = {
        "actor_calls_created": 0,
        "configured_actor_id": MEMO23_SEARCH_ACTOR,
        "run_act_id": _legacy_search_actor(),
        "run_build_id": "build-legacy",
        "run_build_number": "1.0.0",
        "run_status": "SUCCEEDED",
    }
    inner = ReplayActorMismatch("chatToken=secret-payload raw-json")
    wrapped = _explicit_wrap(inner, MarketplaceSourceUnavailable("Alibaba source is unavailable"))
    assert emit_search_failure(wrapped, record) == 1
    out = capsys.readouterr().out
    assert "el run reutilizado no pertenece al Actor SEARCH configurado" in out
    assert f"Actor configurado: {MEMO23_SEARCH_ACTOR}" in out
    assert f"Actor real del run (actId): {_legacy_search_actor()}" in out
    assert "buildId: build-legacy" in out
    assert "buildNumber: 1.0.0" in out
    assert "chatToken" not in out
    assert "secret-payload" not in out
    assert "raw-json" not in out
    assert "ReplayActorMismatch" not in out


def test_missing_run_act_id_is_unavailable_not_mismatch() -> None:
    assert (
        classify_replay_provenance(
            configured_actor_id=MEMO23_SEARCH_ACTOR,
            run_act_id=None,
        )
        == "unavailable"
    )
    assert (
        classify_replay_provenance(
            configured_actor_id=MEMO23_SEARCH_ACTOR,
            run_act_id="   ",
        )
        == "unavailable"
    )
    record: dict[str, Any] = {
        "actor_calls_created": 0,
        "configured_actor_id": MEMO23_SEARCH_ACTOR,
        "configured_actor_aliases": [MEMO23_SEARCH_ACTOR, "memo23~alibaba-scraper"],
    }
    client = ReplayActorClient(
        _FakeRunClient({"id": "run-missing-act", "status": "SUCCEEDED", "defaultDatasetId": "ds"}),
        record,
    )
    with pytest.raises(ReplayProvenanceUnavailable):
        client.call(run_input={})
    assert replay_search_failure_kind(ReplayProvenanceUnavailable()) == "unavailable"
    wrapped = _explicit_wrap(
        ReplayProvenanceUnavailable(),
        MarketplaceSourceUnavailable("Alibaba source is unavailable"),
    )
    assert replay_search_failure_kind(wrapped) == "unavailable"
    assert find_exception_in_chain(wrapped, ReplayActorMismatch) is None


def test_slash_tilde_and_opaque_actor_aliases() -> None:
    assert (
        classify_replay_provenance(
            configured_actor_id=MEMO23_SEARCH_ACTOR,
            run_act_id=MEMO23_SEARCH_ACTOR,
        )
        == "match"
    )
    assert (
        classify_replay_provenance(
            configured_actor_id=MEMO23_SEARCH_ACTOR,
            run_act_id="memo23~alibaba-scraper",
        )
        == "match"
    )
    assert (
        classify_replay_provenance(
            configured_actor_id=MEMO23_SEARCH_ACTOR,
            run_act_id=MEMO23_OPAQUE_ACTOR_ID,
            extra_ids=(MEMO23_OPAQUE_ACTOR_ID,),
        )
        == "match"
    )
    assert (
        classify_replay_provenance(
            configured_actor_id=MEMO23_SEARCH_ACTOR,
            run_act_id=OTHER_OPAQUE_ACTOR_ID,
            extra_ids=(MEMO23_OPAQUE_ACTOR_ID,),
        )
        == "mismatch"
    )


def test_opaque_actor_ids_are_compared_exactly_without_casefold() -> None:
    assert (
        classify_replay_provenance(
            configured_actor_id=MEMO23_SEARCH_ACTOR,
            run_act_id=MEMO23_OPAQUE_ACTOR_ID.casefold(),
            extra_ids=(MEMO23_OPAQUE_ACTOR_ID,),
        )
        == "mismatch"
    )
    assert MEMO23_OPAQUE_ACTOR_ID != MEMO23_OPAQUE_ACTOR_ID.casefold()


def test_alias_lookup_failure_with_opaque_run_id_is_unverifiable() -> None:
    class _LookupFails:
        def actor(self, actor_id: str) -> object:
            del actor_id

            class _Actor:
                def get(self) -> dict[str, object]:
                    raise RuntimeError("actor metadata unavailable")

            return _Actor()

    aliases = _configured_actor_aliases(MEMO23_SEARCH_ACTOR, _LookupFails())
    assert MEMO23_SEARCH_ACTOR in aliases
    assert "memo23~alibaba-scraper" in aliases
    assert MEMO23_OPAQUE_ACTOR_ID not in aliases
    assert (
        classify_replay_provenance(
            configured_actor_id=MEMO23_SEARCH_ACTOR,
            run_act_id=MEMO23_OPAQUE_ACTOR_ID,
            extra_ids=aliases,
        )
        == "unavailable"
    )
    record: dict[str, Any] = {
        "actor_calls_created": 0,
        "configured_actor_id": MEMO23_SEARCH_ACTOR,
        "configured_actor_aliases": aliases,
    }
    client = ReplayActorClient(
        _FakeRunClient(
            {
                "id": "run-opaque",
                "status": "SUCCEEDED",
                "actId": MEMO23_OPAQUE_ACTOR_ID,
                "buildId": "build-ok",
                "buildNumber": "0.1.4",
                "defaultDatasetId": "ds",
            }
        ),
        record,
    )
    with pytest.raises(ReplayProvenanceUnavailable):
        client.call(run_input={})
    assert record["actor_calls_created"] == 0
    assert record["run_act_id"] == MEMO23_OPAQUE_ACTOR_ID
    assert record["run_build_id"] == "build-ok"
    assert record["run_build_number"] == "0.1.4"


def test_matching_failed_run_is_source_failure_not_actor_mismatch() -> None:
    record: dict[str, Any] = {
        "actor_calls_created": 0,
        "configured_actor_id": MEMO23_SEARCH_ACTOR,
        "configured_actor_aliases": [MEMO23_SEARCH_ACTOR, "memo23~alibaba-scraper"],
    }
    failed_run: dict[str, object] = {
        "id": "run-failed",
        "status": "FAILED",
        "actId": MEMO23_SEARCH_ACTOR,
        "buildId": "build-failed",
        "buildNumber": "0.1.4",
        "defaultDatasetId": "ds-failed",
    }
    replay = ReplayActorClient(_FakeRunClient(failed_run), record)
    returned = replay.call(run_input={"searchTerms": ["wireless mouse"], "maxItems": 20})
    assert returned["status"] == "FAILED"
    assert record["actor_calls_created"] == 0

    factory = _ReplayCallFactory(replay)
    client = ApifyAlibabaClient(
        _api_token="token",
        client_factory=lambda _token: cast(Any, factory),
    )
    with pytest.raises(MarketplaceSourceUnavailable) as caught:
        client.search("wireless mouse", 1)
    assert replay_search_failure_kind(caught.value) == "other"
    assert find_exception_in_chain(caught.value, ReplayActorMismatch) is None
    assert find_exception_in_chain(caught.value, ReplayProvenanceUnavailable) is None


def test_unavailable_report_does_not_claim_another_actor(
    capsys: pytest.CaptureFixture[str],
) -> None:
    record = {
        "actor_calls_created": 0,
        "configured_actor_id": MEMO23_SEARCH_ACTOR,
        "run_act_id": None,
        "run_build_id": None,
        "run_build_number": None,
        "run_status": "SUCCEEDED",
    }
    wrapped = _explicit_wrap(
        ReplayProvenanceUnavailable(),
        MarketplaceSourceUnavailable("Alibaba source is unavailable"),
    )
    assert emit_search_failure(wrapped, record) == 1
    out = capsys.readouterr().out
    assert "no se pudo verificar el Actor del run reutilizado" in out
    assert "no pertenece al Actor SEARCH configurado" not in out
    assert "Actor configurado:" in out
    assert "Actor real del run (actId):" in out


def test_validator_search_handler_does_not_catch_baseexception() -> None:
    source = VALIDATOR_PATH.read_text(encoding="utf-8")
    assert "except BaseException as exc" not in source
    assert "except Exception as exc" in source


def test_validator_never_indexes_first_product_without_a_presence_check() -> None:
    source = VALIDATOR_PATH.read_text(encoding="utf-8")
    assert "products[0]" not in source


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Mouse", "Mouse"),
        ("  Mouse  ", "Mouse"),
        ("", None),
        ("  ", None),
        (4.5, None),
        (5, None),
        (True, None),
        (False, None),
        (None, None),
    ],
)
def test_validator_identity_text_matches_production_boundary(
    raw: object, expected: str | None
) -> None:
    assert identity_text(raw) == expected
    assert production_identity_text(raw) == expected
    assert identity_text(raw) == production_identity_text(raw)


class _FakeDataset:
    def __init__(self, owner: _LiveFakeApify) -> None:
        self.owner = owner

    def list_items(self, *, limit: int) -> Any:
        del limit
        if self.owner.dataset_error is not None:
            raise self.owner.dataset_error
        return SimpleNamespace(items=list(self.owner.items))


class _FakeActor:
    def __init__(self, owner: _LiveFakeApify) -> None:
        self.owner = owner

    def call(self, *, run_input: dict[str, object]) -> Any:
        self.owner.calls.append(run_input)
        return self.owner.run


class _LiveFakeApify:
    def __init__(self, items: list[object]) -> None:
        self.items = items
        self.calls: list[dict[str, object]] = []
        self.run: object = {"status": "SUCCEEDED", "defaultDatasetId": "ds1"}
        self.dataset_error: Exception | None = None
        self.actor_id = ""

    def actor(self, actor_id: str) -> _FakeActor:
        self.actor_id = actor_id
        return _FakeActor(self)

    def dataset(self, dataset_id: str) -> _FakeDataset:
        del dataset_id
        return _FakeDataset(self)


def _collecting_check(failures: list[str]) -> Any:
    def check(name: str, condition: bool, detail: str = "") -> None:
        del detail
        if not condition:
            failures.append(name)

    return check


def _search_live(items: Sequence[object]) -> tuple[_LiveFakeApify, list[Any], dict[str, Any]]:
    fake = _LiveFakeApify(list(items))
    client = ApifyAlibabaClient(
        _api_token="token",
        actor_id=DEFAULT_APIFY_ALIBABA_ACTOR,
        client_factory=lambda _token: fake,
    )
    service = RecordingSearchService(SearchAlibabaProducts(provider=client))
    payload = run_alibaba_search("wireless mouse", 20, search_service=service)
    return fake, service.products, payload


def test_succeeded_empty_dataset_fails_closed_without_indexing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake, products, payload = _search_live([])
    assert products == []
    assert payload["ui_status"] == "EMPTY"
    assert payload["results"] == []
    assert len(fake.calls) == 1
    assert has_mapped_products(products) is False
    assert alibaba_product_excludes_transport_fields(products) is False

    failures: list[str] = []
    record = {
        "actor_calls_created": len(fake.calls),
        "configured_actor_id": MEMO23_SEARCH_ACTOR,
        "run_act_id": MEMO23_SEARCH_ACTOR,
        "run_build_id": "build-empty",
        "run_build_number": "1.0.0",
        "run_status": "SUCCEEDED",
        "run_id": "run-empty",
    }
    _print_run_record(record)
    report_mapped_products(products, _collecting_check(failures))
    out = capsys.readouterr().out
    assert "Actor runs creados: 1" in out
    assert "status: SUCCEEDED" in out
    assert "run reutilizable: run-empty" in out
    assert failures == ["SUCCEEDED produjo al menos un producto mapeable"]
    raw_items: list[dict[str, object]] = []
    mapped_raw = [item for item in raw_items if identity_text(item.get("title")) is not None]
    assert list(zip(mapped_raw, products, strict=True)) == []


def test_succeeded_titleless_rows_fail_closed_without_indexing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw_items: list[dict[str, object]] = [
        {"productId": "1", "price": "US $1.00", "supplierName": "Ghost"},
        {"title": 4.5, "productId": "2", "price": "US $2.00"},
        {"title": 5, "productId": "3"},
        {"title": True, "productId": "4"},
        {"title": "  "},
    ]
    fake, products, payload = _search_live(raw_items)
    assert products == []
    assert all(map_alibaba_item(item) is None for item in raw_items)
    assert payload["ui_status"] == "EMPTY"
    assert len(fake.calls) == 1
    assert has_mapped_products(products) is False

    failures: list[str] = []
    record = {
        "actor_calls_created": 1,
        "configured_actor_id": MEMO23_SEARCH_ACTOR,
        "run_act_id": MEMO23_SEARCH_ACTOR,
        "run_status": "SUCCEEDED",
        "run_id": "run-titleless",
    }
    _print_run_record(record)
    report_mapped_products(products, _collecting_check(failures))
    out = capsys.readouterr().out
    assert "status: SUCCEEDED" in out
    assert failures == ["SUCCEEDED produjo al menos un producto mapeable"]
    mapped_raw = [item for item in raw_items if identity_text(item.get("title")) is not None]
    assert mapped_raw == []
    assert list(zip(mapped_raw, products, strict=True)) == []


def test_succeeded_nonempty_run_keeps_first_product_field_assertions() -> None:
    item = {
        "title": "Wireless mouse",
        "productId": "1601111111111",
        "productUrl": "https://www.alibaba.com/product-detail/mouse.html",
        "price": "US $1.00-$9.00",
        "supplierName": "Example Co.",
        "reviewScore": 4.8,
        "reviewCount": 12,
        "supplierServiceScore": 4.9,
    }
    fake, products, payload = _search_live([item])
    assert len(products) == 1
    assert products[0].title == "Wireless mouse"
    assert payload["ui_status"] == "SUCCESS"
    assert payload["results"][0]["title"] == "Wireless mouse"
    assert len(fake.calls) == 1
    assert has_mapped_products(products) is True
    assert alibaba_product_excludes_transport_fields(products) is True
    failures: list[str] = []
    report_mapped_products(products, _collecting_check(failures))
    assert failures == []
    mapped_raw = [item]
    assert list(zip(mapped_raw, products, strict=True))[0][1].title == "Wireless mouse"


def test_replay_empty_dataset_creates_zero_actor_runs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    record: dict[str, Any] = {
        "actor_calls_created": 0,
        "actor_id": MEMO23_SEARCH_ACTOR,
        "configured_actor_id": MEMO23_SEARCH_ACTOR,
        "configured_actor_aliases": [MEMO23_SEARCH_ACTOR],
    }
    client = ReplayActorClient(
        _FakeRunClient(
            {
                "id": "run-replay-empty",
                "status": "SUCCEEDED",
                "actId": MEMO23_SEARCH_ACTOR,
                "buildId": "build-replay",
                "buildNumber": "1.0.0",
                "defaultDatasetId": "ds-empty",
            }
        ),
        record,
    )
    run = client.call(run_input={"searchTerms": ["wireless mouse"], "maxItems": 20})
    assert record["actor_calls_created"] == 0
    assert record["run_status"] == "SUCCEEDED"
    assert record["run_id"] == "run-replay-empty"
    assert isinstance(run, dict)
    _print_run_record(record)
    failures: list[str] = []
    report_mapped_products([], _collecting_check(failures))
    out = capsys.readouterr().out
    assert "Actor runs creados: 0" in out
    assert "status: SUCCEEDED" in out
    assert failures == ["SUCCEEDED produjo al menos un producto mapeable"]


def test_float_title_does_not_join_mapped_raw_with_valid_siblings() -> None:
    raw_items: list[dict[str, object]] = [
        {"title": 4.5, "reviewScore": 4.8},
        {"title": "Wireless mouse", "reviewScore": 4.9},
    ]
    products = [item for item in (map_alibaba_item(raw) for raw in raw_items) if item is not None]
    mapped_raw = [item for item in raw_items if identity_text(item.get("title")) is not None]
    paired = list(zip(mapped_raw, products, strict=True))
    assert len(paired) == 1
    assert paired[0][0]["title"] == "Wireless mouse"
    assert paired[0][1].title == "Wireless mouse"
