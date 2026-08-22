"""Offline tests for the controlled Ollama classifier smoke tool."""

from __future__ import annotations

import json

import httpx
import pytest

from tools.ollama_classifier_smoke import (
    SMOKE_DESCRIPTION,
    SMOKE_TITLE,
    SmokeExitCode,
    main,
)


def _environment() -> dict[str, str]:
    return {
        "BERA_TRACKER_OLLAMA_BASE_URL": "http://localhost:11434",
        "BERA_TRACKER_OLLAMA_MODEL": "minimax-m3:cloud",
        "BERA_TRACKER_OLLAMA_TIMEOUT_SECONDS": "90",
    }


def _valid_response(request: httpx.Request) -> httpx.Response:
    arguments = {
        "decision": "relevant",
        "product_type": "brake_pad",
        "brand_family": "bera",
        "bike_models": ["SBR"],
        "other_compatibility": ["Matrix"],
        "position": "unknown",
        "rationale": "Brake pads explicitly compatible with BERA SBR and Matrix.",
    }
    return httpx.Response(
        200,
        json={
            "message": {
                "role": "assistant",
                "content": '":"truncated content ignored}',
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {
                            "name": "classify_bera_brake_pad_candidate",
                            "arguments": arguments,
                        },
                    }
                ],
            },
            "done": True,
        },
        request=request,
    )


def test_dry_run_is_default_and_makes_zero_requests(
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_count = 0

    def forbidden_handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        raise AssertionError(f"dry-run attempted HTTP: {request.url}")

    with httpx.Client(transport=httpx.MockTransport(forbidden_handler)) as client:
        exit_code = main([], environ=_environment(), client=client)

    captured = capsys.readouterr()
    assert exit_code == SmokeExitCode.SUCCESS
    assert request_count == 0
    assert "Base URL: http://localhost:11434" in captured.out
    assert "Model: minimax-m3:cloud" in captured.out
    assert "Mode: DRY RUN" in captured.out
    assert f"Candidate title: {SMOKE_TITLE}" in captured.out
    assert f"{len(SMOKE_DESCRIPTION)} sanitized characters" in captured.out
    assert SMOKE_DESCRIPTION not in captured.out
    assert "DRY RUN - no request sent" in captured.out


def test_execute_performs_exactly_one_inference_and_prints_sanitized_result(
    capsys: pytest.CaptureFixture[str],
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _valid_response(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        exit_code = main(["--execute"], environ=_environment(), client=client)

    captured = capsys.readouterr()
    assert exit_code == SmokeExitCode.SUCCESS
    assert len(requests) == 1
    assert requests[0].url.path == "/api/chat"
    body = json.loads(requests[0].content)
    user_message = body["messages"][1]["content"]
    assert json.loads(user_message) == {
        "untrusted_marketplace_candidate": {
            "title": SMOKE_TITLE,
            "description": SMOKE_DESCRIPTION,
        }
    }
    assert "Mode: EXECUTE" in captured.out
    assert "HTTP status: 200" in captured.out
    assert "Message thinking: absent" in captured.out
    assert "classify_bera_brake_pad_candidate" in captured.out
    assert "Decision: RELEVANT" in captured.out
    assert "Product type: brake_pad" in captured.out
    assert "Brand family: bera" in captured.out
    assert "Bike models: SBR" in captured.out
    assert "Other compatibility: Matrix" in captured.out
    assert "Position: unknown" in captured.out
    assert "Classification source: ai" in captured.out
    assert "Traceback" not in captured.out + captured.err


@pytest.mark.parametrize(
    ("response_kind", "expected_source"),
    [
        ("http", "ai_unavailable"),
        ("invalid_tool_call", "ai_invalid_response"),
    ],
)
def test_execute_failure_is_controlled_and_never_retried(
    response_kind: str,
    expected_source: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if response_kind == "http":
            return httpx.Response(500, content=b"PRIVATE_REMOTE_BODY", request=request)
        return httpx.Response(
            200,
            json={"message": {"content": "", "tool_calls": []}, "done": True},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        exit_code = main(["--execute"], environ=_environment(), client=client)

    captured = capsys.readouterr()
    assert exit_code == SmokeExitCode.INFERENCE_ERROR
    assert request_count == 1
    assert "HTTP status:" in captured.out
    assert "Decision: REVIEW" in captured.out
    assert f"Classification source: {expected_source}" in captured.out
    assert "Inference failed safely" in captured.err
    assert "PRIVATE_REMOTE_BODY" not in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err


def test_invalid_configuration_fails_before_http(
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_count = 0

    def forbidden_handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        raise AssertionError(f"invalid configuration attempted HTTP: {request.url}")

    environment = _environment()
    environment["BERA_TRACKER_OLLAMA_BASE_URL"] = "https://ollama.com"
    with httpx.Client(transport=httpx.MockTransport(forbidden_handler)) as client:
        exit_code = main(["--execute"], environ=environment, client=client)

    captured = capsys.readouterr()
    assert exit_code == SmokeExitCode.CONFIGURATION_ERROR
    assert request_count == 0
    assert "Configuration error" in captured.err
    assert "Traceback" not in captured.err
