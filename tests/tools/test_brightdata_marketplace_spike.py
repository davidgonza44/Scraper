"""Offline coverage for the isolated Bright Data Marketplace spike."""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable
from decimal import Decimal
from typing import cast

import httpx
import pytest

from tools.brightdata_marketplace_spike import (
    BRIGHT_DATA_ENDPOINT,
    DEFAULT_DATASET_ID,
    DEFAULT_DISPLAY_LIMIT,
    MAX_DISPLAY_LIMIT,
    MIN_DISPLAY_LIMIT,
    MarketplaceRecord,
    SpikeConfiguration,
    SpikeExitCode,
    _display_limit,
    build_parser,
    main,
    parse_marketplace_response,
)

type Handler = Callable[[httpx.Request], httpx.Response]

KEYWORD = "pastillas de freno bera"
TOKEN = "SPIKE_TOKEN_PREFIX-never-print-SPIKE_TOKEN_SUFFIX"
DATASET_ENV = "BERA_TRACKER_BRIGHTDATA_DATASET_ID"
TOKEN_ENV = "BERA_TRACKER_BRIGHTDATA_API_TOKEN"
TIMEOUT_ENV = "BERA_TRACKER_BRIGHTDATA_TIMEOUT_SECONDS"


def _environment(
    *,
    token: str | None = TOKEN,
    dataset_id: str = DEFAULT_DATASET_ID,
    timeout_seconds: str = "37.5",
) -> dict[str, str]:
    environ = {
        DATASET_ENV: dataset_id,
        TIMEOUT_ENV: timeout_seconds,
    }
    if token is not None:
        environ[TOKEN_ENV] = token
    return environ


def _response(
    request: httpx.Request,
    *,
    status_code: int = 200,
    content: bytes = b"[]",
) -> httpx.Response:
    return httpx.Response(status_code, content=content, request=request)


def _records_content(count: int, *, country_code: str = "US") -> bytes:
    records: list[dict[str, object]] = []
    for index in range(count):
        records.append(
            {
                "product_id": f"PRODUCT-{index}",
                "title": f"Listing {index}",
                "country_code": country_code,
            }
        )
    return json.dumps(records).encode()


def test_dry_run_is_default_and_does_not_use_http(
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_count = 0

    def forbidden_handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        raise AssertionError(f"dry-run attempted HTTP: {request.method} {request.url}")

    with httpx.Client(transport=httpx.MockTransport(forbidden_handler)) as client:
        exit_code = main(
            [KEYWORD],
            environ=_environment(token=None),
            client=client,
        )

    captured = capsys.readouterr()
    assert exit_code == SpikeExitCode.SUCCESS
    assert request_count == 0
    assert "Mode: DRY RUN" in captured.out
    assert "no request sent" in captured.out
    assert f"Endpoint: {BRIGHT_DATA_ENDPOINT}" in captured.out
    assert f"Keyword: {KEYWORD}" in captured.out
    assert f"Dataset ID: {DEFAULT_DATASET_ID}" in captured.out
    assert "API token: NOT CONFIGURED" in captured.out
    assert f"Display limit: {DEFAULT_DISPLAY_LIMIT}" in captured.out
    assert "does not limit Bright Data records processed or billed" in captured.out
    assert captured.err == ""


def test_execute_sends_one_exact_documented_request_with_explicit_timeout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    requests: list[httpx.Request] = []
    custom_dataset_id = "custom-facebook-marketplace-dataset"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        exit_code = main(
            [KEYWORD, "--execute"],
            environ=_environment(
                dataset_id=custom_dataset_id,
                timeout_seconds="42.25",
            ),
            client=client,
        )

    captured = capsys.readouterr()
    assert exit_code == SpikeExitCode.SUCCESS
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert f"{request.url.scheme}://{request.url.host}{request.url.path}" == BRIGHT_DATA_ENDPOINT
    assert request.url.params.multi_items() == [("dataset_id", custom_dataset_id)]
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert request.headers["Content-Type"] == "application/json"
    request_body: object = json.loads(request.content)
    assert request_body == {"input": [{"keyword": KEYWORD}]}
    timeout = cast(dict[str, float], request.extensions["timeout"])
    assert timeout == {
        "connect": 42.25,
        "read": 42.25,
        "write": 42.25,
        "pool": 42.25,
    }
    assert "HTTP status: 200" in captured.out
    assert captured.err == ""


def test_execute_without_token_stops_before_http(
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_count = 0

    def forbidden_handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        raise AssertionError(f"missing-token execution attempted HTTP: {request.url}")

    with httpx.Client(transport=httpx.MockTransport(forbidden_handler)) as client:
        exit_code = main(
            [KEYWORD, "--execute"],
            environ=_environment(token=None),
            client=client,
        )

    captured = capsys.readouterr()
    assert exit_code == SpikeExitCode.CONFIGURATION_ERROR
    assert request_count == 0
    assert "API token: NOT CONFIGURED" in captured.out
    assert f"{TOKEN_ENV} is required with --execute" in captured.err
    assert "Traceback" not in captured.err


def test_token_never_appears_in_stdout_stderr_logs_or_configuration_repr(
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    response_body = f"remote-body-containing-{TOKEN}".encode()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        return _response(request, status_code=401, content=response_body)

    configuration = SpikeConfiguration.from_env(_environment())
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        exit_code = main(
            [KEYWORD, "--execute"],
            environ=_environment(),
            client=client,
        )

    captured = capsys.readouterr()
    combined_output = captured.out + captured.err + caplog.text + repr(configuration)
    assert exit_code == SpikeExitCode.REQUEST_ERROR
    assert "authentication/authorization error" in captured.err
    for secret_fragment in (
        TOKEN,
        "SPIKE_TOKEN_PREFIX",
        "SPIKE_TOKEN_SUFFIX",
        f"Bearer {TOKEN}",
        "Authorization",
    ):
        assert secret_fragment not in combined_output


def test_valid_list_maps_all_allowlisted_fields_with_exact_decimal_and_sanitizes_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exact_price = "1234567890.12345678901234567890"
    content = (
        "["
        "{"
        '"product_id":"FB-123",'
        '"title":"Pastillas de freno BERA",'
        f'"final_price":{exact_price},'
        '"currency":"VES",'
        '"condition":"new",'
        '"location":"Caracas",'
        '"country_code":"VE",'
        '"url":"https://example.test/marketplace/FB-123",'
        '"listing_date":"2026-08-21",'
        '"profile_id":"PROFILE_SECRET_SENTINEL",'
        '"description":"DESCRIPTION_SECRET_SENTINEL",'
        '"seller_description":"SELLER_DESCRIPTION_SECRET_SENTINEL",'
        '"initial_price":"INITIAL_PRICE_SENTINEL",'
        '"images":["IMAGE_SECRET_SENTINEL"],'
        '"videos":["VIDEO_SECRET_SENTINEL"]'
        "}"
        "]"
    ).encode()

    records = parse_marketplace_response(content)

    assert len(records) == 1
    record = records[0]
    assert record.product_id == "FB-123"
    assert record.title == "Pastillas de freno BERA"
    assert isinstance(record.final_price, Decimal)
    assert str(record.final_price) == exact_price
    assert record.currency == "VES"
    assert record.condition == "new"
    assert record.location == "Caracas"
    assert record.country_code == "VE"
    assert record.url == "https://example.test/marketplace/FB-123"
    assert record.listing_date == "2026-08-21"

    def handler(request: httpx.Request) -> httpx.Response:
        return _response(request, content=content)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        exit_code = main(
            [KEYWORD, "--execute"],
            environ=_environment(),
            client=client,
        )

    captured = capsys.readouterr()
    assert exit_code == SpikeExitCode.SUCCESS
    for expected_line in (
        "Product ID: FB-123",
        "Title: Pastillas de freno BERA",
        f"Final price: {exact_price}",
        "Currency: VES",
        "Condition: new",
        "Location: Caracas",
        "Country code: VE",
        "URL: https://example.test/marketplace/FB-123",
        "Listing date: 2026-08-21",
    ):
        assert expected_line in captured.out
    for forbidden in (
        "profile_id",
        "PROFILE_SECRET_SENTINEL",
        "description",
        "DESCRIPTION_SECRET_SENTINEL",
        "seller_description",
        "SELLER_DESCRIPTION_SECRET_SENTINEL",
        "initial_price",
        "INITIAL_PRICE_SENTINEL",
        "images",
        "IMAGE_SECRET_SENTINEL",
        "videos",
        "VIDEO_SECRET_SENTINEL",
    ):
        assert forbidden not in captured.out
    assert captured.err == ""


def test_absent_optional_fields_map_to_none() -> None:
    records = parse_marketplace_response(b'[{"description":"ignored by allowlist"}]')

    assert records == (
        MarketplaceRecord(
            product_id=None,
            title=None,
            final_price=None,
            currency=None,
            condition=None,
            location=None,
            country_code=None,
            url=None,
            listing_date=None,
        ),
    )


def test_empty_response_is_valid_and_reports_no_country_information(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _response(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        exit_code = main(
            [KEYWORD, "--execute"],
            environ=_environment(),
            client=client,
        )

    captured = capsys.readouterr()
    assert exit_code == SpikeExitCode.SUCCESS
    assert "Records returned: 0" in captured.out
    assert "Records displayed: 0" in captured.out
    assert "Country information unavailable" in captured.out
    assert "Venezuela records found: UNKNOWN" in captured.out
    assert captured.err == ""


@pytest.mark.parametrize("content", [b"not-json", b"\xff"])
def test_invalid_json_is_reported_without_a_traceback(
    content: bytes,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _response(request, content=content)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        exit_code = main(
            [KEYWORD, "--execute"],
            environ=_environment(),
            client=client,
        )

    captured = capsys.readouterr()
    assert exit_code == SpikeExitCode.RESPONSE_ERROR
    assert "Bright Data returned invalid JSON" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    "content",
    [
        b"{}",
        b"null",
        b'"unexpected"',
        b'[{"unexpected":"field"}]',
        b"[7]",
    ],
    ids=["object-wrapper", "null", "string", "unknown-record", "non-object-record"],
)
def test_unexpected_json_structure_is_rejected_after_one_request(
    content: bytes,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return _response(request, content=content)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        exit_code = main(
            [KEYWORD, "--execute"],
            environ=_environment(),
            client=client,
        )

    captured = capsys.readouterr()
    assert exit_code == SpikeExitCode.RESPONSE_ERROR
    assert request_count == 1
    assert "Response error:" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    ("status_code", "expected_message"),
    [
        (400, "Invalid Bright Data request"),
        (401, "authentication/authorization error"),
        (403, "authentication/authorization error"),
        (402, "billing/credits problem"),
        (429, "rate limit"),
        (500, "server failure"),
        (503, "server failure"),
    ],
)
def test_http_errors_are_sanitized_and_never_retried(
    status_code: int,
    expected_message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_count = 0
    private_body = b"PRIVATE_REMOTE_RESPONSE_BODY"

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return _response(request, status_code=status_code, content=private_body)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        exit_code = main(
            [KEYWORD, "--execute"],
            environ=_environment(),
            client=client,
        )

    captured = capsys.readouterr()
    assert exit_code == SpikeExitCode.REQUEST_ERROR
    assert request_count == 1
    assert expected_message in captured.err
    assert "PRIVATE_REMOTE_RESPONSE_BODY" not in captured.out + captured.err
    assert "Traceback" not in captured.err


def test_http_202_stops_without_polling_or_a_second_request(
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return _response(
            request,
            status_code=202,
            content=b'{"snapshot_id":"PRIVATE_SNAPSHOT_ID"}',
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        exit_code = main(
            [KEYWORD, "--execute"],
            environ=_environment(),
            client=client,
        )

    captured = capsys.readouterr()
    assert exit_code == SpikeExitCode.REQUEST_ERROR
    assert request_count == 1
    assert "still processing" in captured.err
    assert "no follow-up request was sent" in captured.err
    assert "PRIVATE_SNAPSHOT_ID" not in captured.out + captured.err


def test_timeout_is_sanitized_and_never_retried(
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        raise httpx.ReadTimeout("PRIVATE_TIMEOUT_DETAIL", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        exit_code = main(
            [KEYWORD, "--execute"],
            environ=_environment(),
            client=client,
        )

    captured = capsys.readouterr()
    assert exit_code == SpikeExitCode.REQUEST_ERROR
    assert request_count == 1
    assert "Timeout while waiting for Bright Data" in captured.err
    assert "PRIVATE_TIMEOUT_DETAIL" not in captured.out + captured.err
    assert "Traceback" not in captured.err


def test_connectivity_error_is_sanitized_and_never_retried(
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        raise httpx.ConnectError("PRIVATE_CONNECTION_DETAIL", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        exit_code = main(
            [KEYWORD, "--execute"],
            environ=_environment(),
            client=client,
        )

    captured = capsys.readouterr()
    assert exit_code == SpikeExitCode.REQUEST_ERROR
    assert request_count == 1
    assert "Connection failure while contacting Bright Data" in captured.err
    assert "PRIVATE_CONNECTION_DETAIL" not in captured.out + captured.err
    assert "Traceback" not in captured.err


def test_display_limit_only_slices_local_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    content = _records_content(8)

    def handler(request: httpx.Request) -> httpx.Response:
        return _response(request, content=content)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        exit_code = main(
            [KEYWORD, "--execute", "--display-limit", "5"],
            environ=_environment(),
            client=client,
        )

    captured = capsys.readouterr()
    assert exit_code == SpikeExitCode.SUCCESS
    assert "Records returned: 8" in captured.out
    assert "Records displayed: 5" in captured.out
    for index in range(5):
        assert f"Product ID: PRODUCT-{index}" in captured.out
    for index in range(5, 8):
        assert f"Product ID: PRODUCT-{index}" not in captured.out


def test_display_limit_does_not_add_any_request_or_billing_limit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(request, content=_records_content(6))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        exit_code = main(
            [KEYWORD, "--execute", "--display-limit", "5"],
            environ=_environment(),
            client=client,
        )

    captured = capsys.readouterr()
    assert exit_code == SpikeExitCode.SUCCESS
    assert len(requests) == 1
    request = requests[0]
    assert request.url.params.multi_items() == [("dataset_id", DEFAULT_DATASET_ID)]
    request_body: object = json.loads(request.content)
    assert request_body == {"input": [{"keyword": KEYWORD}]}
    serialized_request = str(request.url) + request.content.decode()
    for invented_parameter in ("limit", "max_results", "count"):
        assert invented_parameter not in serialized_request
    assert "Records returned: 6" in captured.out
    assert "Records displayed: 5" in captured.out
    assert "does not limit Bright Data records processed or billed" in captured.out


def test_country_counts_and_detects_exact_ve_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    content = json.dumps(
        [
            {"product_id": "VE-1", "country_code": "VE"},
            {"product_id": "US-1", "country_code": "US"},
            {"product_id": "VE-2", "country_code": "VE"},
            {"product_id": "UNKNOWN", "title": "No country"},
        ]
    ).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return _response(request, content=content)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        exit_code = main(
            [KEYWORD, "--execute"],
            environ=_environment(),
            client=client,
        )

    captured = capsys.readouterr()
    assert exit_code == SpikeExitCode.SUCCESS
    assert "Countries:" in captured.out
    assert "US: 1" in captured.out
    assert "VE: 2" in captured.out
    assert "Venezuela records found: YES" in captured.out


def test_location_text_does_not_infer_country_or_venezuela(
    capsys: pytest.CaptureFixture[str],
) -> None:
    content = b'[{"title":"Venezuela item","location":"Caracas, Venezuela"}]'

    def handler(request: httpx.Request) -> httpx.Response:
        return _response(request, content=content)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        exit_code = main(
            [KEYWORD, "--execute"],
            environ=_environment(),
            client=client,
        )

    captured = capsys.readouterr()
    assert exit_code == SpikeExitCode.SUCCESS
    assert "Location: Caracas, Venezuela" in captured.out
    assert "Country information unavailable" in captured.out
    assert "Venezuela records found: UNKNOWN" in captured.out


def test_lowercase_country_code_is_not_claimed_as_exact_ve(
    capsys: pytest.CaptureFixture[str],
) -> None:
    content = b'[{"product_id":"lowercase","country_code":"ve"}]'

    def handler(request: httpx.Request) -> httpx.Response:
        return _response(request, content=content)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        exit_code = main(
            [KEYWORD, "--execute"],
            environ=_environment(),
            client=client,
        )

    captured = capsys.readouterr()
    assert exit_code == SpikeExitCode.SUCCESS
    assert "ve: 1" in captured.out
    assert "Venezuela records found: NO" in captured.out


@pytest.mark.parametrize("raw_limit", ["0", "21", "not-an-integer"])
def test_display_limit_rejects_invalid_values(raw_limit: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="display limit"):
        _display_limit(raw_limit)


@pytest.mark.parametrize("raw_limit", [str(MIN_DISPLAY_LIMIT), str(MAX_DISPLAY_LIMIT)])
def test_display_limit_accepts_documented_bounds(raw_limit: str) -> None:
    assert _display_limit(raw_limit) == int(raw_limit)


def test_help_warns_that_display_limit_does_not_control_cost() -> None:
    help_text = build_parser().format_help()
    normalized_help = " ".join(help_text.split())

    assert "--execute" in help_text
    assert "--display-limit N" in help_text
    assert (
        "Display limit does not limit Bright Data records processed or billed." in normalized_help
    )


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "inf", "not-a-number"])
def test_invalid_timeout_is_rejected_before_http(
    timeout: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_count = 0

    def forbidden_handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        raise AssertionError(f"invalid timeout attempted HTTP: {request.url}")

    with httpx.Client(transport=httpx.MockTransport(forbidden_handler)) as client:
        exit_code = main(
            [KEYWORD, "--execute"],
            environ=_environment(timeout_seconds=timeout),
            client=client,
        )

    captured = capsys.readouterr()
    assert exit_code == SpikeExitCode.CONFIGURATION_ERROR
    assert request_count == 0
    assert TIMEOUT_ENV in captured.err
    assert "Traceback" not in captured.err
