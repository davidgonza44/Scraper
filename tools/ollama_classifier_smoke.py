"""Controlled dry-run-first smoke tool for the local Ollama AI adapter."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from enum import IntEnum
from typing import cast

import httpx

from bera_price_tracker.application import (
    AIClassifierInvalidResponseError,
    AIClassifierUnavailableError,
    ClassificationSource,
    ProductCandidate,
    sanitize_candidate_for_ai,
)
from bera_price_tracker.config import Settings
from bera_price_tracker.infrastructure.ai import OllamaAIProductClassifier

SMOKE_TITLE = "Pastillas freno SBR Matrix"
SMOKE_DESCRIPTION = "Pastillas de freno compatibles con Bera SBR y Matrix."


class SmokeExitCode(IntEnum):
    """Stable outcomes for the isolated smoke tool."""

    SUCCESS = 0
    CONFIGURATION_ERROR = 2
    INFERENCE_ERROR = 3


def _print_response_diagnostics(response: httpx.Response | None) -> None:
    if response is None:
        print("HTTP status: unavailable")
        print("Message content: unavailable")
        print("Message thinking: absent")
        print("Message tool_calls: absent")
        return

    print(f"HTTP status: {response.status_code}")
    try:
        payload = response.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        print("Message content: unavailable")
        print("Message thinking: absent")
        print("Message tool_calls: absent")
        return
    if not isinstance(payload, dict):
        print("Message content: unavailable")
        print("Message thinking: absent")
        print("Message tool_calls: absent")
        return

    message = payload.get("message")
    if not isinstance(message, dict):
        print("Message content: absent")
        print("Message thinking: absent")
        print("Message tool_calls: absent")
        return

    content = message.get("content")
    print(
        "Message content: "
        + (json.dumps(content, ensure_ascii=False) if isinstance(content, str) else "absent")
    )
    print(f"Message thinking: {'present' if 'thinking' in message else 'absent'}")
    tool_calls = message.get("tool_calls")
    print(
        "Message tool_calls: "
        + (
            json.dumps(tool_calls, ensure_ascii=False, separators=(",", ":"))
            if isinstance(tool_calls, list)
            else "absent"
        )
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the isolated smoke-tool argument parser."""

    parser = argparse.ArgumentParser(
        description="Dry-run-first smoke test for Ollama BERA product classification."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Send exactly one real inference through the local Ollama API.",
    )
    return parser


def _print_plan(settings: Settings, *, execute: bool) -> None:
    candidate = sanitize_candidate_for_ai(
        ProductCandidate(title=SMOKE_TITLE, description=SMOKE_DESCRIPTION)
    )
    print("Ollama BERA classifier smoke")
    print()
    print(f"Base URL: {settings.ollama_base_url}")
    print(f"Model: {settings.ollama_model}")
    print(f"Mode: {'EXECUTE' if execute else 'DRY RUN'}")
    print(f"Candidate title: {candidate.title}")
    print(f"Candidate description: {len(candidate.description or '')} sanitized characters")
    print("Maximum inferences: 1")


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    client: httpx.Client | None = None,
) -> int:
    """Show a dry-run plan or perform at most one explicitly authorized inference."""

    namespace = build_parser().parse_args(argv)
    execute = cast(bool, namespace.execute)
    try:
        settings = Settings.from_env(environ)
    except (TypeError, ValueError) as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return SmokeExitCode.CONFIGURATION_ERROR

    _print_plan(settings, execute=execute)
    if not execute:
        print()
        print("DRY RUN - no request sent")
        return SmokeExitCode.SUCCESS

    candidate = sanitize_candidate_for_ai(
        ProductCandidate(title=SMOKE_TITLE, description=SMOKE_DESCRIPTION)
    )
    captured_responses: list[httpx.Response] = []

    def capture_response(response: httpx.Response) -> None:
        response.read()
        captured_responses.append(response)

    owned_client: httpx.Client | None = None
    adapter_client = client
    if adapter_client is None:
        owned_client = httpx.Client(
            transport=httpx.HTTPTransport(retries=0),
            timeout=httpx.Timeout(settings.ollama_timeout_seconds),
            trust_env=False,
            event_hooks={"response": [capture_response]},
        )
        adapter_client = owned_client
    else:
        adapter_client.event_hooks.setdefault("response", []).append(capture_response)

    adapter = OllamaAIProductClassifier(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        timeout_seconds=settings.ollama_timeout_seconds,
        client=adapter_client,
    )
    try:
        try:
            result = adapter.classify(candidate)
        except (AIClassifierInvalidResponseError, AIClassifierUnavailableError) as error:
            source = (
                ClassificationSource.AI_INVALID_RESPONSE
                if isinstance(error, AIClassifierInvalidResponseError)
                else ClassificationSource.AI_UNAVAILABLE
            )
            print()
            _print_response_diagnostics(captured_responses[-1] if captured_responses else None)
            print("Decision: REVIEW")
            print(f"Classification source: {source.value}")
            print(f"Adapter error: {error}", file=sys.stderr)
            print("Inference failed safely; candidate remains REVIEW.", file=sys.stderr)
            return SmokeExitCode.INFERENCE_ERROR

        print()
        _print_response_diagnostics(captured_responses[-1] if captured_responses else None)
        print(f"Decision: {result.decision.value.upper()}")
        print(f"Product type: {result.product_type.value}")
        print(f"Brand family: {result.brand_family.value}")
        print(f"Bike models: {', '.join(model.value for model in result.bike_models) or 'none'}")
        print(f"Other compatibility: {', '.join(result.other_compatibility) or 'none'}")
        print(f"Position: {result.position.value}")
        print(f"Classification source: {ClassificationSource.AI.value}")
        if result.rationale:
            print(f"Rationale: {result.rationale}")
        return SmokeExitCode.SUCCESS
    finally:
        if owned_client is not None:
            owned_client.close()


if __name__ == "__main__":
    raise SystemExit(int(main()))
