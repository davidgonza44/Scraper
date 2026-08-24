"""Offline HTTP-contract tests for the MiniMax negotiation adapter."""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal

import httpx
import pytest

from bera_price_tracker.application.alibaba_negotiation import (
    DEFAULT_DRAFT_CURRENCY,
    AlibabaNegotiationInput,
    NegotiationDraftContext,
    NegotiationStage,
    NegotiationTier,
    calculate_alibaba_negotiation_plan,
    draft_context_from_plan,
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


def _plan_context() -> NegotiationDraftContext:
    plan = calculate_alibaba_negotiation_plan(
        AlibabaNegotiationInput(
            desired_quantity=40,
            title="Wireless Mouse",
            supplier_name="Example Electronics Co., Ltd.",
            tiers=(
                NegotiationTier(min_quantity=1, max_quantity=49, unit_price=Decimal("4.30")),
                NegotiationTier(min_quantity=50, max_quantity=199, unit_price=Decimal("4.00")),
            ),
            currency=DEFAULT_DRAFT_CURRENCY,
        )
    )
    return draft_context_from_plan(plan, stage=NegotiationStage.OPENING)


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
    assert "never invent, change, or choose a unit price" in system
    assert "target_price" not in system
    assert "ceiling_price" not in system
    user = json.loads(body["messages"][1]["content"])
    authorized = user["draft_instructions"]
    user_blob = json.dumps(user).lower()
    assert "token" not in user_blob
    assert authorized["authorized_offer"] == "4.03"
    assert "target_price" not in user_blob
    assert "ceiling" not in user_blob
    assert "4.06" not in user_blob
    assert "4.30" not in user_blob
    assert "3.80" not in user_blob
    assert "3.50" not in user_blob
    assert "ladder" not in user_blob


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


def test_wrong_context_type_is_rejected() -> None:
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: _tool_response(request))
    ) as client:
        drafter = OllamaAlibabaNegotiationDrafter(client=client)
        with pytest.raises(TypeError, match="NegotiationDraftContext"):
            drafter.draft_opening("context")  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="NegotiationDraftContext"):
            drafter.draft_counter("context")  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="NegotiationDraftContext"):
            drafter.analyze_reply("context", "hello")  # type: ignore[arg-type]


def test_cny_opening_keeps_iso_out_of_http_when_only_authorized_amount_is_sent() -> None:
    plan = calculate_alibaba_negotiation_plan(
        AlibabaNegotiationInput(
            desired_quantity=40,
            title="Wireless Mouse",
            supplier_name="Example Electronics Co., Ltd.",
            tiers=(
                NegotiationTier(min_quantity=1, max_quantity=49, unit_price=Decimal("4.30")),
                NegotiationTier(min_quantity=50, max_quantity=199, unit_price=Decimal("4.00")),
            ),
            currency="CNY",
        )
    )
    context = draft_context_from_plan(plan, stage=NegotiationStage.OPENING)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _tool_response(
            request, arguments={"message": "Please consider CNY 4.03 for 40 units."}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        message = OllamaAlibabaNegotiationDrafter(client=client).draft_opening(context)
    assert "CNY 4.03" in message
    user = json.loads(json.loads(requests[0].content)["messages"][1]["content"])
    blob = json.dumps(user).lower()
    assert context.currency == "CNY"
    assert user["draft_instructions"]["authorized_offer"] == "4.03"
    assert "4.30" not in blob
    assert "ladder" not in blob
    assert "margin" not in blob
    assert "target" not in blob
    assert "ceiling" not in blob


def test_analyze_rejects_non_boolean_shipping_flag() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _tool_response(
            request,
            name=NEGOTIATION_ANALYZE_TOOL_NAME,
            arguments={
                "response_summary": "Quoted",
                "quoted_unit_price": "4.10",
                "shipping_mentioned": "yes",
                "notes": "",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AlibabaNegotiationDraftInvalidError, match="shipping_mentioned"):
            OllamaAlibabaNegotiationDrafter(client=client).analyze_reply(_plan_context(), "hi")


def test_timeout_and_transport_errors_are_unavailable() -> None:
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        del request
        raise httpx.TimeoutException("timed out")

    with httpx.Client(transport=httpx.MockTransport(timeout_handler)) as client:
        with pytest.raises(AlibabaNegotiationDraftUnavailableError, match="timed out"):
            OllamaAlibabaNegotiationDrafter(client=client).draft_opening(_plan_context())

    def connect_handler(request: httpx.Request) -> httpx.Response:
        del request
        raise httpx.ConnectError("refused")

    with httpx.Client(transport=httpx.MockTransport(connect_handler)) as client:
        with pytest.raises(AlibabaNegotiationDraftUnavailableError, match="connection"):
            OllamaAlibabaNegotiationDrafter(client=client).draft_counter(_plan_context())


def test_http_404_is_unavailable_and_does_not_invent_prices() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model"}, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AlibabaNegotiationDraftUnavailableError):
            OllamaAlibabaNegotiationDrafter(client=client).draft_opening(_plan_context())


def test_malformed_and_incomplete_json_are_invalid() -> None:
    def invalid_json(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json", request=request)

    with httpx.Client(transport=httpx.MockTransport(invalid_json)) as client:
        with pytest.raises(AlibabaNegotiationDraftInvalidError, match="invalid JSON"):
            OllamaAlibabaNegotiationDrafter(client=client).draft_opening(_plan_context())

    def not_object(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["nope"], request=request)

    with httpx.Client(transport=httpx.MockTransport(not_object)) as client:
        with pytest.raises(AlibabaNegotiationDraftInvalidError, match="object"):
            OllamaAlibabaNegotiationDrafter(client=client).draft_opening(_plan_context())

    def not_done(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "tool_calls": []}, "done": False},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(not_done)) as client:
        with pytest.raises(AlibabaNegotiationDraftInvalidError, match="complete"):
            OllamaAlibabaNegotiationDrafter(client=client).draft_opening(_plan_context())


def test_tool_call_shape_errors_are_invalid() -> None:
    def missing_message(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"done": True, "message": "hi"}, request=request)

    with httpx.Client(transport=httpx.MockTransport(missing_message)) as client:
        with pytest.raises(AlibabaNegotiationDraftInvalidError, match="message"):
            OllamaAlibabaNegotiationDrafter(client=client).draft_opening(_plan_context())

    def two_calls(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "done": True,
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {"function": {"name": NEGOTIATION_DRAFT_TOOL_NAME, "arguments": {}}},
                        {"function": {"name": NEGOTIATION_DRAFT_TOOL_NAME, "arguments": {}}},
                    ],
                },
            },
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(two_calls)) as client:
        with pytest.raises(AlibabaNegotiationDraftInvalidError, match="exactly one"):
            OllamaAlibabaNegotiationDrafter(client=client).draft_opening(_plan_context())

    def not_object_call(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"done": True, "message": {"tool_calls": ["nope"]}},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(not_object_call)) as client:
        with pytest.raises(AlibabaNegotiationDraftInvalidError, match="tool call"):
            OllamaAlibabaNegotiationDrafter(client=client).draft_opening(_plan_context())

    def missing_function(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"done": True, "message": {"tool_calls": [{"function": "nope"}]}},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(missing_function)) as client:
        with pytest.raises(AlibabaNegotiationDraftInvalidError, match="function"):
            OllamaAlibabaNegotiationDrafter(client=client).draft_opening(_plan_context())

    def wrong_tool(request: httpx.Request) -> httpx.Response:
        return _tool_response(request, name="other_tool")

    with httpx.Client(transport=httpx.MockTransport(wrong_tool)) as client:
        with pytest.raises(AlibabaNegotiationDraftInvalidError, match="unexpected tool"):
            OllamaAlibabaNegotiationDrafter(client=client).draft_opening(_plan_context())


def test_arguments_json_string_and_invalid_arguments() -> None:
    def string_args(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "done": True,
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "function": {
                                "name": NEGOTIATION_DRAFT_TOOL_NAME,
                                "arguments": json.dumps(
                                    {"message": "Please consider $4.03 for 40 units."}
                                ),
                            }
                        }
                    ],
                },
            },
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(string_args)) as client:
        message = OllamaAlibabaNegotiationDrafter(client=client).draft_opening(_plan_context())
    assert message == "Please consider $4.03 for 40 units."

    def bad_string_args(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "done": True,
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": NEGOTIATION_DRAFT_TOOL_NAME,
                                "arguments": "{not-json",
                            }
                        }
                    ]
                },
            },
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(bad_string_args)) as client:
        with pytest.raises(AlibabaNegotiationDraftInvalidError, match="arguments"):
            OllamaAlibabaNegotiationDrafter(client=client).draft_opening(_plan_context())

    def list_args(request: httpx.Request) -> httpx.Response:
        return _tool_response(request, arguments=["Please consider $4.03"])

    with httpx.Client(transport=httpx.MockTransport(list_args)) as client:
        with pytest.raises(AlibabaNegotiationDraftInvalidError, match="arguments"):
            OllamaAlibabaNegotiationDrafter(client=client).draft_opening(_plan_context())


def test_blank_message_and_blank_summary_are_invalid() -> None:
    def blank_message(request: httpx.Request) -> httpx.Response:
        return _tool_response(request, arguments={"message": "  "})

    with httpx.Client(transport=httpx.MockTransport(blank_message)) as client:
        with pytest.raises(AlibabaNegotiationDraftInvalidError, match="message"):
            OllamaAlibabaNegotiationDrafter(client=client).draft_opening(_plan_context())

    def blank_summary(request: httpx.Request) -> httpx.Response:
        return _tool_response(
            request,
            name=NEGOTIATION_ANALYZE_TOOL_NAME,
            arguments={
                "response_summary": " ",
                "quoted_unit_price": "4.10",
                "quoted_quantity": "40",
                "quoted_moq": None,
                "shipping_mentioned": False,
                "notes": "",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(blank_summary)) as client:
        with pytest.raises(AlibabaNegotiationDraftInvalidError, match="response_summary"):
            OllamaAlibabaNegotiationDrafter(client=client).analyze_reply(_plan_context(), "hi")


def test_analyze_optional_fields_and_non_string_notes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _tool_response(
            request,
            name=NEGOTIATION_ANALYZE_TOOL_NAME,
            arguments={
                "response_summary": "Quoted",
                "quoted_unit_price": 4.10,
                "quoted_quantity": None,
                "quoted_moq": "50",
                "shipping_mentioned": False,
                "notes": "",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AlibabaNegotiationDraftInvalidError, match="quoted_unit_price"):
            OllamaAlibabaNegotiationDrafter(client=client).analyze_reply(_plan_context(), "hi")

    def notes_handler(request: httpx.Request) -> httpx.Response:
        return _tool_response(
            request,
            name=NEGOTIATION_ANALYZE_TOOL_NAME,
            arguments={
                "response_summary": "Quoted",
                "quoted_unit_price": None,
                "quoted_quantity": None,
                "quoted_moq": None,
                "shipping_mentioned": False,
                "notes": 12,
            },
        )

    with httpx.Client(transport=httpx.MockTransport(notes_handler)) as client:
        with pytest.raises(AlibabaNegotiationDraftInvalidError, match="notes"):
            OllamaAlibabaNegotiationDrafter(client=client).analyze_reply(_plan_context(), "hi")


def test_analyze_missing_optional_quoted_fields_stay_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _tool_response(
            request,
            name=NEGOTIATION_ANALYZE_TOOL_NAME,
            arguments={
                "response_summary": "No number",
                "shipping_mentioned": False,
                "notes": "",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        analysis = OllamaAlibabaNegotiationDrafter(client=client).analyze_reply(
            _plan_context(), "thanks"
        )
    assert analysis.quoted_unit_price is None
    assert analysis.quoted_quantity is None
    assert analysis.quoted_moq is None
    assert analysis.response_summary == "No number"


def test_explicit_usd_draft_and_public_words_in_title_are_allowed() -> None:
    plan = calculate_alibaba_negotiation_plan(
        AlibabaNegotiationInput(
            desired_quantity=40,
            title="Target ceiling ladder margin wireless mouse",
            supplier_name="Example Electronics Co., Ltd.",
            tiers=(
                NegotiationTier(min_quantity=1, max_quantity=49, unit_price=Decimal("4.30")),
                NegotiationTier(min_quantity=50, max_quantity=199, unit_price=Decimal("4.00")),
            ),
            currency="USD",
        )
    )
    context = draft_context_from_plan(plan, stage=NegotiationStage.OPENING)
    assert "ladder" in context.product_title
    assert "margin" in context.product_title
    assert "Target" in context.product_title
    assert "ceiling" in context.product_title

    def handler(request: httpx.Request) -> httpx.Response:
        return _tool_response(
            request, arguments={"message": "Please consider USD 4.03 for 40 units."}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        message = OllamaAlibabaNegotiationDrafter(client=client).draft_opening(context)
    assert "USD 4.03" in message
    assert "4.30" not in message
