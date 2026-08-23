"""Offline HTTP-contract tests for the MiniMax negotiation adapter."""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal

import httpx
import pytest

from bera_price_tracker.application.alibaba_negotiation import (
    AlibabaNegotiationInput,
    NegotiationStage,
    NegotiationTier,
    SanitizedNegotiationContext,
    calculate_alibaba_negotiation_plan,
    sanitized_negotiation_context,
)
from bera_price_tracker.application.ports import (
    AlibabaNegotiationDraftInvalidError,
    AlibabaNegotiationDraftUnavailableError,
)
from bera_price_tracker.infrastructure.ai.ollama_negotiation import (
    NEGOTIATION_ANALYZE_TOOL_NAME,
    NEGOTIATION_DRAFT_TOOL_NAME,
    OLLAMA_NEGOTIATION_SYSTEM_PROMPT,
    OllamaAlibabaNegotiationDrafter,
)

type Handler = Callable[[httpx.Request], httpx.Response]


def _plan_context() -> SanitizedNegotiationContext:
    plan = calculate_alibaba_negotiation_plan(
        AlibabaNegotiationInput(
            desired_quantity=40,
            title="Wireless Mouse",
            supplier_name="Example Electronics Co., Ltd.",
            tiers=(
                NegotiationTier(min_quantity=1, max_quantity=49, unit_price=Decimal("4.30")),
                NegotiationTier(min_quantity=50, max_quantity=199, unit_price=Decimal("4.00")),
            ),
        )
    )
    return sanitized_negotiation_context(plan, stage=NegotiationStage.OPENING)


def _tool_response(
    request: httpx.Request,
    *,
    name: str = NEGOTIATION_DRAFT_TOOL_NAME,
    arguments: object | None = None,
    status_code: int = 200,
) -> httpx.Response:
    if arguments is None:
        arguments = {"message": "Please consider $4.03 for 40 units."}
    return httpx.Response(
        status_code,
        json={
            "model": "minimax-m3:cloud",
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"type": "function", "function": {"name": name, "arguments": arguments}}
                ],
            },
            "done": True,
        },
        request=request,
    )


def test_opening_request_uses_local_chat_and_system_constraints() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _tool_response(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        drafter = OllamaAlibabaNegotiationDrafter(client=client)
        message = drafter.draft_opening(_plan_context())
    assert message.startswith("Please consider")
    assert len(requests) == 1
    assert str(requests[0].url).endswith("/api/chat")
    body = json.loads(requests[0].content)
    assert body["stream"] is False
    assert body["think"] is False
    system = body["messages"][0]["content"]
    assert system == OLLAMA_NEGOTIATION_SYSTEM_PROMPT
    assert "never invent prices" in system
    assert "never change opening_offer" in system
    user = json.loads(body["messages"][1]["content"])
    authorized = user["authorized_negotiation"]
    assert "token" not in json.dumps(user).lower()
    assert authorized["opening_offer"] == "4.03"
    assert authorized["target_price"] == "4.06"


def test_analyze_parses_tool_arguments() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _tool_response(
            request,
            name=NEGOTIATION_ANALYZE_TOOL_NAME,
            arguments={
                "response_summary": "Quoted four ten",
                "quoted_unit_price": "4.10",
                "quoted_quantity": "40",
                "quoted_moq": None,
                "shipping_mentioned": True,
                "notes": "FOB mentioned",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        analysis = OllamaAlibabaNegotiationDrafter(client=client).analyze_reply(
            _plan_context(),
            "We can do $4.10 FOB. Contact me at sales@example.com",
        )
    assert analysis.quoted_unit_price == "4.10"
    assert analysis.shipping_mentioned is True
    assert "example.com" not in analysis.response_summary or "[redacted]" in (
        json.dumps({"x": "sales@example.com"})
    )


def test_http_error_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _tool_response(request, status_code=503)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AlibabaNegotiationDraftUnavailableError):
            OllamaAlibabaNegotiationDrafter(client=client).draft_opening(_plan_context())


def test_missing_tool_is_invalid() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "minimax-m3:cloud",
                "message": {"role": "assistant", "content": "hi"},
                "done": True,
            },
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AlibabaNegotiationDraftInvalidError):
            OllamaAlibabaNegotiationDrafter(client=client).draft_opening(_plan_context())
