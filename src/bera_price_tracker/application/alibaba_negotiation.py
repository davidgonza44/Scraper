"""Deterministic Alibaba negotiation copilot.

Python owns every price and limit. MiniMax may only draft or summarize text
against those authorized numbers. This module never talks to Alibaba or Apify.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Protocol

from bera_price_tracker.application.alibaba_statistics import (
    explicit_alibaba_currency,
    format_alibaba_currency,
)
from bera_price_tracker.domain.money import MONEY_QUANTUM, quantize_money

DEFAULT_NEGOTIATION_AGGRESSIVENESS = 50
MIN_NEGOTIATION_AGGRESSIVENESS = 0
MAX_NEGOTIATION_AGGRESSIVENESS = 100
NO_TIER_MAX_DISCOUNT = Decimal("0.05")
OPENING_BENCHMARK_RATIO = Decimal("0.90")
MAX_NEGOTIATION_TITLE_LENGTH = 300
MAX_NEGOTIATION_SUPPLIER_NAME_LENGTH = 120
MAX_NEGOTIATION_SUPPLIER_TEXT_LENGTH = 4_000
MAX_NEGOTIATION_LADDER_SUMMARY_LENGTH = 400
MAX_NEGOTIATION_NOTES_LENGTH = 400

MISSING_QUANTITY = "Indica una cantidad deseada mayor que cero."
MISSING_PUBLIC_PRICE = (
    "Este producto no tiene un precio comparable para esa cantidad. "
    "Usa un precio simple, un producto ya actualizado, o tramos de precio."
)
MISSING_LISTING_CURRENCY = "No se puede negociar un producto Alibaba sin una moneda explícita."
DRAFT_CURRENCY_MISMATCH = "La moneda del borrador no coincide con la moneda del producto."
QUANTITY_BELOW_TIERS = "La cantidad es inferior al tramo publicado más bajo."
INVALID_AGGRESSIVENESS = "La agresividad debe estar entre 0 y 100."
INVALID_MARGIN = "El margen objetivo debe estar entre 0 y 100."
INVALID_RESALE = "El precio de venta esperado no es utilizable."
INVALID_COST = "Un costo por unidad no es utilizable."
UNAUTHORIZED_DRAFT_PRICE = "El borrador mencionó un precio que Python no autorizó."
MISSING_DRAFT = "No se generó un mensaje utilizable."
NEEDS_HUMAN_REVIEW_NOTE = "La respuesta del proveedor es ambigua y requiere revisión."

_EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
_PHONE_CANDIDATE_PATTERN = re.compile(r"(?<!\w)\+?\d[\d\s().-]{5,}\d(?!\w)")
_LADDER_LINE = re.compile(r"^\s*(\d+)\s*(?:-\s*(\d+))?\s*[:=]\s*(\d+(?:\.\d+)?)\s*$")
_MONEY_PATTERN = re.compile(
    r"(?:USD\s*)?\$?\s*(\d+(?:\.\d{1,2})?)\s*(?:USD)?",
    re.IGNORECASE,
)
_QUOTE_ISO_PATTERN = re.compile(r"\b(?:USD|CNY|EUR|GBP|RMB)\b", re.IGNORECASE)
_US_DOLLAR_PATTERN = re.compile(r"\bUS\s*\$", re.IGNORECASE)
_QUOTE_CURRENCY_WINDOW = 8
_QTY_PATTERN = re.compile(
    r"(?:moq|min(?:imum)?\s*order|qty|quantity|unidades|units)\s*[:=]?\s*(\d+)",
    re.IGNORECASE,
)
_SHIPPING_PATTERN = re.compile(
    r"\b(?:ship(?:ping)?|freight|fob|cif|ddp|envio|envío|flete)\b",
    re.IGNORECASE,
)
DEFAULT_DRAFT_LANGUAGE = "English"
DEFAULT_DRAFT_CURRENCY = "USD"
_ALLOWED_DRAFT_PAYLOAD_KEYS = frozenset({"draft_instructions", "untrusted_supplier_reply"})
_ALLOWED_DRAFT_INSTRUCTION_KEYS = frozenset(
    {
        "product_title",
        "public_supplier_name",
        "desired_quantity",
        "currency",
        "stage",
        "language",
        "min_order_quantity",
        "authorized_offer",
        "authorized_counter_offer",
        "authorized_final_offer",
        "instruction",
        "decision",
        "supplier_quoted_price",
        "ask_lead_time",
        "ask_packaging",
    }
)
_FORBIDDEN_DRAFT_INSTRUCTION_KEYS = frozenset(
    {
        "target_price",
        "ceiling_price",
        "negotiable_reference",
        "aggressiveness",
        "ladder",
        "tiers",
        "margin",
        "max_product",
        "score_price",
        "score_clarity",
        "profitability",
        "profit_per_unit",
        "margin_percent",
        "apify",
        "apitoken",
        "api_token",
        "chattoken",
        "contactsupplier",
        "authorization",
    }
)
_QUANTITY_SUFFIX = re.compile(
    r"^\s*(?:units?|pcs|pieces|unidades|qty|quantity)\b",
    re.IGNORECASE,
)


class AlibabaNegotiationError(ValueError):
    """Local validation failure before a negotiation plan is produced."""


class DealAttractiveness(StrEnum):
    """Whether the user's economics leave a reasonable negotiation range."""

    ATTRACTIVE = "ATTRACTIVE"
    ECONOMICALLY_UNATTRACTIVE = "ECONOMICALLY_UNATTRACTIVE"


class CounterOfferDecision(StrEnum):
    """Deterministic comparison of a supplier unit price against Python bounds."""

    ACCEPTABLE = "ACCEPTABLE"
    NEGOTIABLE = "NEGOTIABLE"
    ABOVE_CEILING = "ABOVE_CEILING"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"


class NegotiationStage(StrEnum):
    """Which message the copilot is drafting."""

    OPENING = "opening"
    SUPPLIER_REPLY = "supplier_reply"
    COUNTEROFFER = "counteroffer"
    ACCEPTABLE = "acceptable"
    ABOVE_CEILING = "final_offer"


class NegotiationWarning(StrEnum):
    """Non-fatal flags attached to a plan or recommendation."""

    NO_LADDER = "NO_LADDER"
    OPENING_BELOW_BENCHMARK = "OPENING_BELOW_BENCHMARK"
    AMBIGUOUS_SUPPLIER_RESPONSE = "AMBIGUOUS_SUPPLIER_RESPONSE"


@dataclass(frozen=True, slots=True, kw_only=True)
class NegotiationTier:
    """One published quantity-price tier used for negotiation math."""

    min_quantity: int
    max_quantity: int | None
    unit_price: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.min_quantity, int) or isinstance(self.min_quantity, bool):
            raise TypeError("min_quantity must be an int")
        if self.min_quantity <= 0:
            raise ValueError("min_quantity must be positive")
        if self.max_quantity is not None:
            if not isinstance(self.max_quantity, int) or isinstance(self.max_quantity, bool):
                raise TypeError("max_quantity must be an int or None")
            if self.max_quantity < self.min_quantity:
                raise ValueError("max_quantity must not be below min_quantity")
        object.__setattr__(self, "unit_price", _required_money(self.unit_price, "unit_price"))


@dataclass(frozen=True, slots=True, kw_only=True)
class AlibabaNegotiationInput:
    """User and product facts required to compute a negotiation plan."""

    desired_quantity: int
    title: str = ""
    supplier_name: str | None = None
    min_order_quantity: int | None = None
    tiers: tuple[NegotiationTier, ...] = ()
    public_unit_price: Decimal | None = None
    expected_resale_price: Decimal | None = None
    target_margin_percent: Decimal | None = None
    shipping_per_unit: Decimal | None = None
    duties_per_unit: Decimal | None = None
    other_costs_per_unit: Decimal | None = None
    negotiation_aggressiveness: int = DEFAULT_NEGOTIATION_AGGRESSIVENESS
    currency: str | None = None


@dataclass(frozen=True, slots=True)
class NegotiationPriceBounds:
    """Authorized unit prices. MiniMax must not change these."""

    public_unit_price: Decimal
    opening_offer: Decimal
    target_price: Decimal
    ceiling_price: Decimal
    negotiable_reference: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class AlibabaNegotiationPlan:
    """Deterministic strategy for one quantity of one product."""

    title: str
    supplier_name: str | None
    desired_quantity: int
    min_order_quantity: int | None
    public_unit_price: Decimal
    opening_offer: Decimal
    target_price: Decimal
    ceiling_price: Decimal
    negotiable_reference: Decimal
    selected_min_quantity: int | None
    selected_max_quantity: int | None
    next_tier_min_quantity: int | None
    next_tier_price: Decimal | None
    tier_proximity: Decimal | None
    max_product_unit_price: Decimal | None
    aggressiveness: int
    attractiveness: DealAttractiveness
    explanation: str
    ladder_summary: str
    warnings: tuple[NegotiationWarning, ...]
    bounds: NegotiationPriceBounds
    currency: str


@dataclass(frozen=True, slots=True, kw_only=True)
class SupplierCounterOffer:
    """Numbers extracted from a pasted supplier reply. None means unknown."""

    raw_text: str
    response_summary: str
    quoted_unit_price: Decimal | None
    quoted_quantity: int | None
    quoted_moq: int | None
    shipping_mentioned: bool
    needs_human_review: bool
    notes: str
    extracted_prices: tuple[Decimal, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class NegotiationRecommendation:
    """Python decision plus the only price MiniMax may propose next."""

    decision: CounterOfferDecision
    authorized_price: Decimal | None
    attractiveness: DealAttractiveness
    notes: str


@dataclass(frozen=True, slots=True, kw_only=True)
class NegotiationDraftContext:
    """Least-privilege payload for MiniMax. Internal plan prices never belong here."""

    product_title: str
    public_supplier_name: str | None
    desired_quantity: int
    currency: str
    stage: str
    language: str
    authorized_offer: str | None = None
    authorized_counter_offer: str | None = None
    authorized_final_offer: str | None = None
    min_order_quantity: int | None = None
    decision: str | None = None
    supplier_quoted_price: str | None = None
    supplier_response: str | None = None
    ask_lead_time: bool = False
    ask_packaging: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class NegotiationDraftAnalysis:
    """Untrusted MiniMax parse of a supplier reply. Python still validates."""

    response_summary: str
    quoted_unit_price: str | None = None
    quoted_quantity: str | None = None
    quoted_moq: str | None = None
    shipping_mentioned: bool = False
    notes: str = ""


class AlibabaNegotiationDrafter(Protocol):
    """MiniMax/Ollama port. Implementations must not invent or change prices."""

    def draft_opening(self, context: NegotiationDraftContext) -> str: ...

    def analyze_reply(
        self,
        context: NegotiationDraftContext,
        supplier_text: str,
    ) -> NegotiationDraftAnalysis: ...

    def draft_counter(self, context: NegotiationDraftContext) -> str: ...


def _required_money(value: object, name: str) -> Decimal:
    parsed = _parse_money(value)
    if parsed is None:
        raise TypeError(f"{name} must be a positive finite Decimal")
    return parsed


def _parse_money(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, int):
        parsed = Decimal(value)
    elif isinstance(value, str) and value.strip():
        compact = value.strip().replace(",", "").replace("$", "")
        try:
            parsed = Decimal(compact)
        except InvalidOperation:
            return None
    else:
        return None
    if not parsed.is_finite() or parsed <= Decimal("0"):
        return None
    return quantize_money(parsed)


def _parse_optional_cost(value: object, name: str) -> Decimal:
    if value is None:
        return Decimal("0.00")
    if isinstance(value, bool):
        raise AlibabaNegotiationError(INVALID_COST)
    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, int):
        parsed = Decimal(value)
    elif isinstance(value, str) and value.strip():
        try:
            parsed = Decimal(value.strip())
        except InvalidOperation:
            raise AlibabaNegotiationError(INVALID_COST) from None
    else:
        raise AlibabaNegotiationError(INVALID_COST)
    if not parsed.is_finite() or parsed < Decimal("0"):
        raise AlibabaNegotiationError(INVALID_COST)
    del name
    return quantize_money(parsed)


def _explicit_listing_currency(value: object) -> str:
    """Return an explicit ISO code or fail before monetary planning."""

    currency = explicit_alibaba_currency(value)
    if currency is None:
        raise AlibabaNegotiationError(MISSING_LISTING_CURRENCY)
    return currency


def _resolve_draft_currency(plan_currency: object, requested_currency: object = None) -> str:
    """Require the plan ISO and reject any draft-time currency substitution."""

    currency = _explicit_listing_currency(plan_currency)
    if requested_currency is None:
        return currency
    requested = _explicit_listing_currency(requested_currency)
    if requested != currency:
        raise AlibabaNegotiationError(DRAFT_CURRENCY_MISMATCH)
    return currency


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def sanitize_negotiation_text(value: object, limit: int) -> str:
    """Redact contacts and bound length. Listing text is never treated as code."""

    if not isinstance(value, str):
        return ""
    without_emails = _EMAIL_PATTERN.sub("[redacted]", value)
    without_urls = _URL_PATTERN.sub("[redacted]", without_emails)
    without_phones = _PHONE_CANDIDATE_PATTERN.sub(_redact_phone_candidate, without_urls)
    normalized = unicodedata.normalize("NFKC", without_phones)
    without_controls = "".join(
        " " if unicodedata.category(character).startswith("C") else character
        for character in normalized
    )
    return " ".join(without_controls.split())[:limit].rstrip()


def _redact_phone_candidate(match: re.Match[str]) -> str:
    value = match.group(0)
    if sum(character.isdigit() for character in value) >= 7:
        return "[redacted]"
    return value


def parse_ladder_text(value: object) -> tuple[NegotiationTier, ...]:
    """Parse optional ``min-max:price`` lines. Empty input yields no tiers."""

    if value is None:
        return ()
    if not isinstance(value, str):
        raise AlibabaNegotiationError("Los tramos de precio no son utilizables.")
    tiers: list[NegotiationTier] = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _LADDER_LINE.match(line)
        if match is None:
            raise AlibabaNegotiationError("Cada tramo debe verse como 1-49:4.30 o 1000:3.50.")
        minimum = int(match.group(1))
        maximum = None if match.group(2) is None else int(match.group(2))
        price = _parse_money(match.group(3))
        if price is None:
            raise AlibabaNegotiationError("Un tramo tiene un precio no utilizable.")
        tiers.append(NegotiationTier(min_quantity=minimum, max_quantity=maximum, unit_price=price))
    return tuple(tiers)


def _tier_covers(tier: NegotiationTier, quantity: int) -> bool:
    if quantity < tier.min_quantity:
        return False
    return not (tier.max_quantity is not None and quantity > tier.max_quantity)


def select_quantity_tier(
    tiers: Sequence[NegotiationTier],
    quantity: int,
) -> NegotiationTier | None:
    """Return the published tier that covers ``quantity``. Not a range midpoint."""

    covering = [tier for tier in tiers if _tier_covers(tier, quantity)]
    if not covering:
        return None
    covering.sort(
        key=lambda tier: (
            -tier.min_quantity,
            tier.max_quantity if tier.max_quantity is not None else 10**12,
        )
    )
    return covering[0]


def next_better_tier(
    tiers: Sequence[NegotiationTier],
    selected: NegotiationTier,
) -> NegotiationTier | None:
    """Closest later tier whose unit price is strictly better than ``selected``."""

    better = [
        tier
        for tier in tiers
        if tier.min_quantity > selected.min_quantity and tier.unit_price < selected.unit_price
    ]
    if not better:
        return None
    better.sort(key=lambda tier: (tier.min_quantity, tier.unit_price))
    return better[0]


def tier_proximity(desired_quantity: int, next_tier_min_quantity: int) -> Decimal:
    """``desired_quantity / next_tier_min_quantity`` clamped to ``[0, 1]``."""

    if next_tier_min_quantity <= 0:
        raise AlibabaNegotiationError("El siguiente tramo no tiene cantidad válida.")
    ratio = Decimal(desired_quantity) / Decimal(next_tier_min_quantity)
    if ratio < Decimal("0"):
        return Decimal("0")
    if ratio > Decimal("1"):
        return Decimal("1")
    return ratio


def negotiable_reference_price(
    public_unit_price: Decimal,
    next_tier_price: Decimal | None,
    proximity: Decimal | None,
) -> Decimal:
    """Linear interpolation from public toward the next-tier price.

    ``public - proximity * (public - next)``. Without a next tier the reference
    is the public price. This is a negotiation reference, not a promise.
    """

    public = _required_money(public_unit_price, "public_unit_price")
    if next_tier_price is None or proximity is None:
        return public
    nxt = _required_money(next_tier_price, "next_tier_price")
    if not isinstance(proximity, Decimal) or not proximity.is_finite():
        raise TypeError("proximity must be a finite Decimal")
    if proximity < Decimal("0") or proximity > Decimal("1"):
        raise ValueError("proximity must be between 0 and 1")
    return quantize_money(public - proximity * (public - nxt))


def margin_product_ceiling(
    expected_resale_price: Decimal,
    target_margin_percent: Decimal,
    shipping_per_unit: Decimal,
    duties_per_unit: Decimal,
    other_costs_per_unit: Decimal,
) -> Decimal:
    """Maximum product unit price that still hits the requested margin."""

    resale = _parse_money(expected_resale_price)
    if resale is None:
        raise AlibabaNegotiationError(INVALID_RESALE)
    if not isinstance(target_margin_percent, Decimal):
        raise AlibabaNegotiationError(INVALID_MARGIN)
    if (
        not target_margin_percent.is_finite()
        or target_margin_percent < Decimal("0")
        or target_margin_percent > Decimal("100")
    ):
        raise AlibabaNegotiationError(INVALID_MARGIN)
    shipping = _parse_optional_cost(shipping_per_unit, "shipping_per_unit")
    duties = _parse_optional_cost(duties_per_unit, "duties_per_unit")
    other = _parse_optional_cost(other_costs_per_unit, "other_costs_per_unit")
    factor = Decimal("1") - (target_margin_percent / Decimal("100"))
    max_total = quantize_money(resale * factor)
    return quantize_money(max_total - shipping - duties - other)


def _opening_floor(public: Decimal, next_tier_price: Decimal | None) -> Decimal:
    if next_tier_price is not None:
        return next_tier_price
    return quantize_money(public * (Decimal("1") - NO_TIER_MAX_DISCOUNT))


def _benchmark_floor(public: Decimal, next_tier_price: Decimal | None) -> Decimal:
    if next_tier_price is not None:
        return next_tier_price
    return quantize_money(public * OPENING_BENCHMARK_RATIO)


def calculate_price_bounds(
    public_unit_price: Decimal,
    *,
    next_tier_price: Decimal | None,
    proximity: Decimal | None,
    aggressiveness: int,
    max_product_unit_price: Decimal | None,
) -> tuple[NegotiationPriceBounds, tuple[NegotiationWarning, ...]]:
    """Derive opening/target/ceiling. Target is the negotiable reference."""

    public = _required_money(public_unit_price, "public_unit_price")
    if (
        not isinstance(aggressiveness, int)
        or isinstance(aggressiveness, bool)
        or aggressiveness < MIN_NEGOTIATION_AGGRESSIVENESS
        or aggressiveness > MAX_NEGOTIATION_AGGRESSIVENESS
    ):
        raise AlibabaNegotiationError(INVALID_AGGRESSIVENESS)
    reference = negotiable_reference_price(public, next_tier_price, proximity)
    ceiling = public
    if max_product_unit_price is not None:
        if not isinstance(max_product_unit_price, Decimal):
            raise AlibabaNegotiationError(INVALID_COST)
        if max_product_unit_price.is_finite() and max_product_unit_price > Decimal("0"):
            ceiling = min(public, quantize_money(max_product_unit_price))
    target = min(reference, ceiling)
    floor = _opening_floor(public, next_tier_price)
    if floor > target:
        floor = target
    factor = Decimal(aggressiveness) / Decimal("100")
    opening = quantize_money(target - factor * (target - floor))
    if opening <= Decimal("0"):
        opening = MONEY_QUANTUM
    if opening > target:
        opening = target
    if opening > ceiling:
        opening = ceiling
    warnings: list[NegotiationWarning] = []
    if opening < _benchmark_floor(public, next_tier_price):
        warnings.append(NegotiationWarning.OPENING_BELOW_BENCHMARK)
    bounds = NegotiationPriceBounds(
        public_unit_price=public,
        opening_offer=opening,
        target_price=target,
        ceiling_price=ceiling,
        negotiable_reference=reference,
    )
    return bounds, tuple(warnings)


def _ladder_summary(tiers: Sequence[NegotiationTier], currency: str) -> str:
    if not tiers:
        return ""
    parts: list[str] = []
    for tier in sorted(tiers, key=lambda item: item.min_quantity):
        maximum = "" if tier.max_quantity is None else f"–{tier.max_quantity}"
        parts.append(
            f"{tier.min_quantity}{maximum}: {format_alibaba_currency(tier.unit_price, currency)}"
        )
    return "; ".join(parts)[:MAX_NEGOTIATION_LADDER_SUMMARY_LENGTH]


def build_negotiation_explanation(plan_like: AlibabaNegotiationPlan) -> str:
    """Short human explanation. Never claims the supplier will accept a price."""

    public = format_alibaba_currency(plan_like.public_unit_price, plan_like.currency)
    if plan_like.next_tier_min_quantity is None or plan_like.next_tier_price is None:
        text = (
            f"No hay un tramo posterior con mejor precio. El precio publicado "
            f"para {plan_like.desired_quantity} unidades es {public}. "
            f"La referencia de negociación coincide con ese precio."
        )
    else:
        percent = (plan_like.tier_proximity or Decimal("0")) * Decimal("100")
        shown = percent.quantize(Decimal("1"))
        next_tier = format_alibaba_currency(plan_like.next_tier_price, plan_like.currency)
        reference = format_alibaba_currency(plan_like.negotiable_reference, plan_like.currency)
        text = (
            f"Tu cantidad está al {shown}% del siguiente tramo de precio. "
            f"El siguiente tramo comienza en {plan_like.next_tier_min_quantity} "
            f"unidades a {next_tier}. "
            f"La referencia matemática de negociación es {reference}."
        )
    if plan_like.attractiveness is DealAttractiveness.ECONOMICALLY_UNATTRACTIVE:
        text += " Con el margen y los costos indicados, el trato no es económicamente atractivo."
    return text


def _resolve_public_from_input(
    payload: AlibabaNegotiationInput,
) -> tuple[Decimal, NegotiationTier | None, NegotiationTier | None, Decimal | None]:
    if payload.tiers:
        selected = select_quantity_tier(payload.tiers, payload.desired_quantity)
        if selected is None:
            raise AlibabaNegotiationError(QUANTITY_BELOW_TIERS)
        nxt = next_better_tier(payload.tiers, selected)
        proximity = (
            None if nxt is None else tier_proximity(payload.desired_quantity, nxt.min_quantity)
        )
        return selected.unit_price, selected, nxt, proximity
    public = _parse_money(payload.public_unit_price)
    if public is None:
        raise AlibabaNegotiationError(MISSING_PUBLIC_PRICE)
    return public, None, None, None


def calculate_alibaba_negotiation_plan(
    payload: AlibabaNegotiationInput,
) -> AlibabaNegotiationPlan:
    """Compute the authorized strategy. No network and no MiniMax."""

    if not isinstance(payload, AlibabaNegotiationInput):
        raise TypeError("payload must be an AlibabaNegotiationInput")
    if (
        not isinstance(payload.desired_quantity, int)
        or isinstance(payload.desired_quantity, bool)
        or payload.desired_quantity <= 0
    ):
        raise AlibabaNegotiationError(MISSING_QUANTITY)
    currency = _explicit_listing_currency(payload.currency)
    public, selected, nxt, proximity = _resolve_public_from_input(payload)
    max_product: Decimal | None = None
    if payload.expected_resale_price is not None or payload.target_margin_percent is not None:
        if payload.expected_resale_price is None or payload.target_margin_percent is None:
            raise AlibabaNegotiationError(
                "El margen objetivo y el precio de venta esperado se usan juntos."
            )
        max_product = margin_product_ceiling(
            payload.expected_resale_price,
            payload.target_margin_percent,
            payload.shipping_per_unit if payload.shipping_per_unit is not None else Decimal("0"),
            payload.duties_per_unit if payload.duties_per_unit is not None else Decimal("0"),
            payload.other_costs_per_unit
            if payload.other_costs_per_unit is not None
            else Decimal("0"),
        )
    bounds, extra_warnings = calculate_price_bounds(
        public,
        next_tier_price=None if nxt is None else nxt.unit_price,
        proximity=proximity,
        aggressiveness=payload.negotiation_aggressiveness,
        max_product_unit_price=max_product,
    )
    if not (bounds.opening_offer <= bounds.target_price <= bounds.ceiling_price):
        raise AlibabaNegotiationError("Los límites de negociación quedaron incoherentes.")
    if bounds.ceiling_price > bounds.public_unit_price:
        raise AlibabaNegotiationError("El techo no puede superar el precio publicado.")
    best_known = nxt.unit_price if nxt is not None else public
    attractiveness = DealAttractiveness.ATTRACTIVE
    if max_product is not None and max_product < best_known:
        attractiveness = DealAttractiveness.ECONOMICALLY_UNATTRACTIVE
    warnings = list(extra_warnings)
    if not payload.tiers:
        warnings.append(NegotiationWarning.NO_LADDER)
    plan = AlibabaNegotiationPlan(
        title=payload.title.strip() if isinstance(payload.title, str) else "",
        supplier_name=_optional_text(payload.supplier_name),
        desired_quantity=payload.desired_quantity,
        min_order_quantity=payload.min_order_quantity,
        public_unit_price=bounds.public_unit_price,
        opening_offer=bounds.opening_offer,
        target_price=bounds.target_price,
        ceiling_price=bounds.ceiling_price,
        negotiable_reference=bounds.negotiable_reference,
        selected_min_quantity=None if selected is None else selected.min_quantity,
        selected_max_quantity=None if selected is None else selected.max_quantity,
        next_tier_min_quantity=None if nxt is None else nxt.min_quantity,
        next_tier_price=None if nxt is None else nxt.unit_price,
        tier_proximity=proximity,
        max_product_unit_price=max_product,
        aggressiveness=payload.negotiation_aggressiveness,
        attractiveness=attractiveness,
        explanation="",
        ladder_summary=_ladder_summary(payload.tiers, currency),
        warnings=tuple(warnings),
        bounds=bounds,
        currency=currency,
    )
    return AlibabaNegotiationPlan(
        title=plan.title,
        supplier_name=plan.supplier_name,
        desired_quantity=plan.desired_quantity,
        min_order_quantity=plan.min_order_quantity,
        public_unit_price=plan.public_unit_price,
        opening_offer=plan.opening_offer,
        target_price=plan.target_price,
        ceiling_price=plan.ceiling_price,
        negotiable_reference=plan.negotiable_reference,
        selected_min_quantity=plan.selected_min_quantity,
        selected_max_quantity=plan.selected_max_quantity,
        next_tier_min_quantity=plan.next_tier_min_quantity,
        next_tier_price=plan.next_tier_price,
        tier_proximity=plan.tier_proximity,
        max_product_unit_price=plan.max_product_unit_price,
        aggressiveness=plan.aggressiveness,
        attractiveness=plan.attractiveness,
        explanation=build_negotiation_explanation(plan),
        ladder_summary=plan.ladder_summary,
        warnings=plan.warnings,
        bounds=plan.bounds,
        currency=plan.currency,
    )


def classify_supplier_price(
    supplier_price: Decimal | None,
    bounds: NegotiationPriceBounds,
    *,
    ambiguous: bool = False,
) -> NegotiationRecommendation:
    """Compare a supplier unit price with opening/target/ceiling. Python only."""

    if not isinstance(bounds, NegotiationPriceBounds):
        raise TypeError("bounds must be a NegotiationPriceBounds")
    if ambiguous or supplier_price is None:
        return NegotiationRecommendation(
            decision=CounterOfferDecision.NEEDS_HUMAN_REVIEW,
            authorized_price=None,
            attractiveness=DealAttractiveness.ATTRACTIVE,
            notes=NEEDS_HUMAN_REVIEW_NOTE,
        )
    price = _required_money(supplier_price, "supplier_price")
    if price <= bounds.target_price:
        decision = CounterOfferDecision.ACCEPTABLE
        authorized: Decimal | None = None
        notes = "El precio del proveedor está en o por debajo del objetivo."
    elif price <= bounds.ceiling_price:
        decision = CounterOfferDecision.NEGOTIABLE
        authorized = bounds.target_price
        notes = "El precio del proveedor está entre el objetivo y el máximo aceptable."
    else:
        decision = CounterOfferDecision.ABOVE_CEILING
        authorized = bounds.ceiling_price
        notes = "El precio del proveedor supera el máximo aceptable."
    return NegotiationRecommendation(
        decision=decision,
        authorized_price=authorized,
        attractiveness=DealAttractiveness.ATTRACTIVE,
        notes=notes,
    )


def _looks_like_quantity(match: re.Match[str], text: str) -> bool:
    """Treat quantity words and bare integers as units, not USD amounts."""

    if _QUANTITY_SUFFIX.match(text[match.end() :]):
        return True
    token = match.group(0)
    has_money_marker = "$" in token or "usd" in token.lower()
    has_decimal = "." in match.group(1)
    return not has_money_marker and not has_decimal


def extract_supplier_money(text: str) -> tuple[Decimal, ...]:
    """Unique unit-price candidates found in pasted supplier text."""

    found: list[Decimal] = []
    seen: set[Decimal] = set()
    for match in _MONEY_PATTERN.finditer(text):
        parsed = _parse_money(match.group(1))
        if parsed is None or parsed in seen:
            continue
        if _looks_like_quantity(match, text):
            continue
        seen.add(parsed)
        found.append(parsed)
    return tuple(found)


def _normalize_quote_currency_token(token: str) -> str:
    currency = token.strip().upper()
    return "CNY" if currency == "RMB" else currency


def _quote_currency_markers(text: str, match: re.Match[str]) -> set[str]:
    """ISO or ``$`` markers adjacent to one extracted amount. ``$`` means USD here."""

    start, end = match.span()
    window = text[
        max(0, start - _QUOTE_CURRENCY_WINDOW) : min(len(text), end + _QUOTE_CURRENCY_WINDOW)
    ]
    markers = {
        _normalize_quote_currency_token(item.group(0))
        for item in _QUOTE_ISO_PATTERN.finditer(window)
    }
    if _US_DOLLAR_PATTERN.search(window) is not None or "$" in window:
        markers.add("USD")
    return markers


def _extracted_quote_currencies(text: str) -> set[str]:
    markers: set[str] = set()
    for match in _MONEY_PATTERN.finditer(text):
        parsed = _parse_money(match.group(1))
        if parsed is None or _looks_like_quantity(match, text):
            continue
        markers.update(_quote_currency_markers(text, match))
    return markers


def extract_supplier_quantity(text: str) -> int | None:
    match = _QTY_PATTERN.search(text)
    if match is None:
        return None
    value = int(match.group(1))
    return value if value > 0 else None


def parse_supplier_response(
    text: object,
    *,
    summary: str = "",
    notes: str = "",
    quoted_unit_price: object = None,
    quoted_quantity: object = None,
    quoted_moq: object = None,
    shipping_mentioned: bool = False,
    expected_currency: object = None,
) -> SupplierCounterOffer:
    """Extract numbers from pasted text. Ambiguous prices need human review."""

    raw = text if isinstance(text, str) else ""
    sanitized = sanitize_negotiation_text(raw, MAX_NEGOTIATION_SUPPLIER_TEXT_LENGTH)
    prices = extract_supplier_money(sanitized)
    extracted_qty = extract_supplier_quantity(sanitized)
    shipping = shipping_mentioned or bool(_SHIPPING_PATTERN.search(sanitized))
    suggested = _parse_money(quoted_unit_price)
    expected = explicit_alibaba_currency(expected_currency)
    quote_currencies = _extracted_quote_currencies(sanitized)
    currency_mismatch = expected is not None and any(
        marker != expected for marker in quote_currencies
    )
    if suggested is not None and suggested not in prices:
        return SupplierCounterOffer(
            raw_text=sanitized,
            response_summary=sanitize_negotiation_text(summary, MAX_NEGOTIATION_NOTES_LENGTH),
            quoted_unit_price=None,
            quoted_quantity=extracted_qty,
            quoted_moq=_parse_optional_int(quoted_moq) or extracted_qty,
            shipping_mentioned=shipping,
            needs_human_review=True,
            notes=NEEDS_HUMAN_REVIEW_NOTE,
            extracted_prices=prices,
        )
    if len(prices) != 1 or currency_mismatch:
        return SupplierCounterOffer(
            raw_text=sanitized,
            response_summary=sanitize_negotiation_text(summary, MAX_NEGOTIATION_NOTES_LENGTH),
            quoted_unit_price=None,
            quoted_quantity=extracted_qty,
            quoted_moq=_parse_optional_int(quoted_moq),
            shipping_mentioned=shipping,
            needs_human_review=True,
            notes=NEEDS_HUMAN_REVIEW_NOTE,
            extracted_prices=prices,
        )
    quantity = _parse_optional_int(quoted_quantity) or extracted_qty
    moq = _parse_optional_int(quoted_moq)
    return SupplierCounterOffer(
        raw_text=sanitized,
        response_summary=sanitize_negotiation_text(summary, MAX_NEGOTIATION_NOTES_LENGTH)
        or sanitize_negotiation_text(notes, MAX_NEGOTIATION_NOTES_LENGTH),
        quoted_unit_price=prices[0],
        quoted_quantity=quantity,
        quoted_moq=moq,
        shipping_mentioned=shipping,
        needs_human_review=False,
        notes=sanitize_negotiation_text(notes, MAX_NEGOTIATION_NOTES_LENGTH),
        extracted_prices=prices,
    )


def _parse_optional_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def _money_text(value: Decimal) -> str:
    return f"{quantize_money(value):f}"


def draft_context_from_plan(
    plan: AlibabaNegotiationPlan,
    *,
    stage: NegotiationStage,
    recommendation: NegotiationRecommendation | None = None,
    supplier: SupplierCounterOffer | None = None,
    language: str = DEFAULT_DRAFT_LANGUAGE,
    currency: str | None = None,
) -> NegotiationDraftContext:
    """Build the only payload MiniMax may see. The full plan stays in Python."""

    title = sanitize_negotiation_text(plan.title, MAX_NEGOTIATION_TITLE_LENGTH)
    supplier_name = (
        None
        if plan.supplier_name is None
        else sanitize_negotiation_text(plan.supplier_name, MAX_NEGOTIATION_SUPPLIER_NAME_LENGTH)
        or None
    )
    authorized_offer: str | None = None
    authorized_counter: str | None = None
    authorized_final: str | None = None
    decision: str | None = None
    quoted: str | None = None
    supplier_response: str | None = None
    ask_lead_time = False
    resolved_stage = stage.value
    if stage is NegotiationStage.OPENING:
        authorized_offer = _money_text(plan.opening_offer)
        ask_lead_time = True
    elif stage is NegotiationStage.SUPPLIER_REPLY:
        resolved_stage = NegotiationStage.SUPPLIER_REPLY.value
    elif recommendation is not None:
        decision = recommendation.decision.value
        if recommendation.decision is CounterOfferDecision.ACCEPTABLE:
            resolved_stage = NegotiationStage.ACCEPTABLE.value
            if supplier is not None and supplier.quoted_unit_price is not None:
                quoted = _money_text(supplier.quoted_unit_price)
        elif recommendation.decision is CounterOfferDecision.NEGOTIABLE:
            resolved_stage = NegotiationStage.COUNTEROFFER.value
            if recommendation.authorized_price is not None:
                authorized_counter = _money_text(recommendation.authorized_price)
        elif recommendation.decision is CounterOfferDecision.ABOVE_CEILING:
            resolved_stage = NegotiationStage.ABOVE_CEILING.value
            decision = None
            if recommendation.authorized_price is not None:
                authorized_final = _money_text(recommendation.authorized_price)
        if supplier is not None and supplier.raw_text:
            supplier_response = sanitize_negotiation_text(
                supplier.raw_text, MAX_NEGOTIATION_SUPPLIER_TEXT_LENGTH
            )
    context = NegotiationDraftContext(
        product_title=title,
        public_supplier_name=supplier_name,
        desired_quantity=plan.desired_quantity,
        currency=_resolve_draft_currency(plan.currency, currency),
        stage=resolved_stage,
        language=language,
        authorized_offer=authorized_offer,
        authorized_counter_offer=authorized_counter,
        authorized_final_offer=authorized_final,
        min_order_quantity=plan.min_order_quantity,
        decision=decision,
        supplier_quoted_price=quoted,
        supplier_response=supplier_response,
        ask_lead_time=ask_lead_time,
    )
    assert_context_has_no_secrets(context)
    return context


def sanitized_negotiation_context(
    plan: AlibabaNegotiationPlan,
    *,
    stage: NegotiationStage,
    recommendation: NegotiationRecommendation | None = None,
    supplier: SupplierCounterOffer | None = None,
) -> NegotiationDraftContext:
    """Compatibility alias for :func:`draft_context_from_plan`."""

    return draft_context_from_plan(
        plan,
        stage=stage,
        recommendation=recommendation,
        supplier=supplier,
    )


def draft_context_payload(
    context: NegotiationDraftContext,
    *,
    supplier_text: str | None = None,
) -> dict[str, object]:
    """JSON object actually sent to the MiniMax adapter. Omits unused fields."""

    if not isinstance(context, NegotiationDraftContext):
        raise TypeError("context must be a NegotiationDraftContext")
    instructions: dict[str, object] = {
        "product_title": context.product_title,
        "public_supplier_name": context.public_supplier_name,
        "desired_quantity": context.desired_quantity,
        "currency": context.currency,
        "stage": context.stage,
        "language": context.language,
    }
    if context.min_order_quantity is not None:
        instructions["min_order_quantity"] = context.min_order_quantity
    if context.authorized_offer is not None:
        instructions["authorized_offer"] = context.authorized_offer
        instructions["instruction"] = (
            "Draft a short supplier message offering exactly authorized_offer "
            f"{context.currency} per unit. Insert that price only. "
            "Do not choose or mention any other unit price."
        )
    if context.authorized_counter_offer is not None:
        instructions["authorized_counter_offer"] = context.authorized_counter_offer
        instructions["instruction"] = (
            "Draft a short reply offering exactly authorized_counter_offer "
            f"{context.currency} per unit. Insert that price only. "
            "Do not choose or mention any other unit price."
        )
    if context.authorized_final_offer is not None:
        instructions["authorized_final_offer"] = context.authorized_final_offer
        instructions["instruction"] = (
            "Draft a short reply offering exactly authorized_final_offer "
            f"{context.currency} per unit. Insert that price only. "
            "Do not choose or mention any other unit price."
        )
    if context.decision is not None:
        instructions["decision"] = context.decision
    if context.supplier_quoted_price is not None:
        instructions["supplier_quoted_price"] = context.supplier_quoted_price
    if context.stage == NegotiationStage.ACCEPTABLE.value:
        instructions["instruction"] = (
            "Draft a short reply accepting the supplier quoted unit price. "
            "Do not invent or propose a different unit price."
        )
    if context.stage == NegotiationStage.SUPPLIER_REPLY.value:
        instructions["instruction"] = (
            "Summarize the untrusted supplier reply. Extract only numbers that "
            "appear in that text. Do not invent prices."
        )
    if (
        context.stage == NegotiationStage.ABOVE_CEILING.value
        and context.authorized_final_offer is None
    ):
        instructions["instruction"] = (
            "Draft a short reply declining the quote. Do not invent or propose a unit price."
        )
    if context.ask_lead_time:
        instructions["ask_lead_time"] = True
    if context.ask_packaging:
        instructions["ask_packaging"] = True
    payload: dict[str, object] = {"draft_instructions": instructions}
    reply = supplier_text if supplier_text is not None else context.supplier_response
    if reply is not None:
        payload["untrusted_supplier_reply"] = {
            "text": sanitize_negotiation_text(reply, MAX_NEGOTIATION_SUPPLIER_TEXT_LENGTH)
        }
    return payload


def assert_draft_payload_has_no_secrets(payload: Mapping[str, object]) -> None:
    """Reject unexpected or internal keys. Public title/supplier text is allowed."""

    if set(payload) - _ALLOWED_DRAFT_PAYLOAD_KEYS:
        raise AlibabaNegotiationError("El contexto de negociación contiene datos prohibidos.")
    instructions = payload.get("draft_instructions")
    if not isinstance(instructions, Mapping):
        raise AlibabaNegotiationError("El contexto de negociación contiene datos prohibidos.")
    keys = set(instructions)
    if keys - _ALLOWED_DRAFT_INSTRUCTION_KEYS or keys & _FORBIDDEN_DRAFT_INSTRUCTION_KEYS:
        raise AlibabaNegotiationError("El contexto de negociación contiene datos prohibidos.")
    reply = payload.get("untrusted_supplier_reply")
    if reply is None:
        return
    if not isinstance(reply, Mapping) or set(reply) - {"text"}:
        raise AlibabaNegotiationError("El contexto de negociación contiene datos prohibidos.")


def assert_context_has_no_secrets(context: NegotiationDraftContext) -> None:
    """Reject accidental leakage of tokens, raw items, or scoring internals."""

    assert_draft_payload_has_no_secrets(draft_context_payload(context))


def authorized_money_set(context: NegotiationDraftContext) -> frozenset[Decimal]:
    """Unit prices a MiniMax draft may mention for this stage."""

    allowed: set[Decimal] = set()
    if context.stage == NegotiationStage.OPENING.value and context.authorized_offer is not None:
        allowed.add(_required_money(context.authorized_offer, "authorized_offer"))
    elif (
        context.stage == NegotiationStage.COUNTEROFFER.value
        and context.authorized_counter_offer is not None
    ):
        allowed.add(_required_money(context.authorized_counter_offer, "authorized_counter_offer"))
    elif (
        context.stage == NegotiationStage.ABOVE_CEILING.value
        and context.authorized_final_offer is not None
    ):
        allowed.add(_required_money(context.authorized_final_offer, "authorized_final_offer"))
    elif (
        context.stage == NegotiationStage.ACCEPTABLE.value
        and context.supplier_quoted_price is not None
    ):
        allowed.add(_required_money(context.supplier_quoted_price, "supplier_quoted_price"))
    return frozenset(allowed)


def unauthorized_prices_in_text(text: str, allowed: frozenset[Decimal]) -> tuple[Decimal, ...]:
    """Money amounts in ``text`` that Python did not authorize."""

    extras: list[Decimal] = []
    for price in extract_supplier_money(text):
        if price not in allowed:
            extras.append(price)
    return tuple(extras)


def _reject_unauthorized_draft(message: str, context: NegotiationDraftContext) -> str:
    cleaned = sanitize_negotiation_text(message, MAX_NEGOTIATION_SUPPLIER_TEXT_LENGTH)
    if not cleaned:
        raise AlibabaNegotiationError(MISSING_DRAFT)
    extras = unauthorized_prices_in_text(cleaned, authorized_money_set(context))
    if extras:
        raise AlibabaNegotiationError(UNAUTHORIZED_DRAFT_PRICE)
    return cleaned


class CalculateAlibabaNegotiationPlan:
    """Pure calculation use case."""

    def execute(self, payload: AlibabaNegotiationInput) -> AlibabaNegotiationPlan:
        return calculate_alibaba_negotiation_plan(payload)


class GenerateNegotiationOpeningMessage:
    """Ask MiniMax to draft the first message using Python-owned bounds."""

    def __init__(self, drafter: AlibabaNegotiationDrafter) -> None:
        self._drafter = drafter

    def execute(self, plan: AlibabaNegotiationPlan) -> str:
        if not isinstance(plan, AlibabaNegotiationPlan):
            raise TypeError("plan must be an AlibabaNegotiationPlan")
        context = draft_context_from_plan(plan, stage=NegotiationStage.OPENING)
        return _reject_unauthorized_draft(self._drafter.draft_opening(context), context)


class AnalyzeSupplierResponse:
    """Parse a pasted reply. MiniMax may summarize; Python owns the numbers."""

    def __init__(self, drafter: AlibabaNegotiationDrafter | None = None) -> None:
        self._drafter = drafter

    def execute(
        self,
        plan: AlibabaNegotiationPlan,
        supplier_text: str,
    ) -> tuple[SupplierCounterOffer, NegotiationRecommendation]:
        if not isinstance(plan, AlibabaNegotiationPlan):
            raise TypeError("plan must be an AlibabaNegotiationPlan")
        draft = NegotiationDraftAnalysis(response_summary="")
        if self._drafter is not None:
            context = draft_context_from_plan(plan, stage=NegotiationStage.SUPPLIER_REPLY)
            draft = self._drafter.analyze_reply(context, supplier_text)
        parsed = parse_supplier_response(
            supplier_text,
            summary=draft.response_summary,
            notes=draft.notes,
            quoted_unit_price=draft.quoted_unit_price,
            quoted_quantity=draft.quoted_quantity,
            quoted_moq=draft.quoted_moq,
            shipping_mentioned=draft.shipping_mentioned,
            expected_currency=plan.currency,
        )
        recommendation = classify_supplier_price(
            parsed.quoted_unit_price,
            plan.bounds,
            ambiguous=parsed.needs_human_review,
        )
        recommendation = NegotiationRecommendation(
            decision=recommendation.decision,
            authorized_price=recommendation.authorized_price,
            attractiveness=plan.attractiveness,
            notes=recommendation.notes,
        )
        return parsed, recommendation


class GenerateNegotiationReply:
    """Draft the next message using the authorized counter price only."""

    def __init__(self, drafter: AlibabaNegotiationDrafter) -> None:
        self._drafter = drafter

    def execute(
        self,
        plan: AlibabaNegotiationPlan,
        supplier: SupplierCounterOffer,
        recommendation: NegotiationRecommendation,
    ) -> str:
        if recommendation.decision is CounterOfferDecision.NEEDS_HUMAN_REVIEW:
            raise AlibabaNegotiationError(NEEDS_HUMAN_REVIEW_NOTE)
        if plan.attractiveness is DealAttractiveness.ECONOMICALLY_UNATTRACTIVE:
            if recommendation.decision is CounterOfferDecision.ABOVE_CEILING:
                raise AlibabaNegotiationError(
                    "El trato no es económicamente atractivo; no se prometen volúmenes."
                )
        context = draft_context_from_plan(
            plan,
            stage=NegotiationStage.COUNTEROFFER,
            recommendation=recommendation,
            supplier=supplier,
        )
        return _reject_unauthorized_draft(self._drafter.draft_counter(context), context)


def public_price_from_catalog_row(row: Mapping[str, object]) -> Decimal | None:
    """Use a simple or canonical price. Never a discovery range midpoint.

    Numeric bounds without an explicit ISO currency are not usable. ``$``
    alone is not USD.
    """

    if explicit_alibaba_currency(row.get("currency")) is None:
        return None
    last_price = _parse_money(row.get("last_price") or row.get("public_price"))
    minimum = _parse_money(row.get("price_min"))
    maximum = _parse_money(row.get("price_max"))
    source = row.get("source")
    if source == "tracked" and last_price is not None:
        return last_price
    if minimum is not None and maximum is not None and minimum == maximum:
        return minimum
    if last_price is not None and (minimum is None or maximum is None or minimum == maximum):
        return last_price
    simple = _parse_money(row.get("representative"))
    if simple is not None and minimum is not None and maximum is not None and minimum == maximum:
        return simple
    if simple is not None and minimum is None and maximum is None:
        return simple
    return None


__all__ = [
    "DEFAULT_DRAFT_CURRENCY",
    "DEFAULT_DRAFT_LANGUAGE",
    "DEFAULT_NEGOTIATION_AGGRESSIVENESS",
    "INVALID_AGGRESSIVENESS",
    "MAX_NEGOTIATION_AGGRESSIVENESS",
    "MIN_NEGOTIATION_AGGRESSIVENESS",
    "MISSING_LISTING_CURRENCY",
    "MISSING_PUBLIC_PRICE",
    "MISSING_QUANTITY",
    "NO_TIER_MAX_DISCOUNT",
    "OPENING_BENCHMARK_RATIO",
    "UNAUTHORIZED_DRAFT_PRICE",
    "assert_context_has_no_secrets",
    "assert_draft_payload_has_no_secrets",
    "AlibabaNegotiationDrafter",
    "AlibabaNegotiationError",
    "AlibabaNegotiationInput",
    "AlibabaNegotiationPlan",
    "AnalyzeSupplierResponse",
    "CalculateAlibabaNegotiationPlan",
    "CounterOfferDecision",
    "DealAttractiveness",
    "GenerateNegotiationOpeningMessage",
    "GenerateNegotiationReply",
    "NegotiationDraftAnalysis",
    "NegotiationDraftContext",
    "NegotiationPriceBounds",
    "NegotiationRecommendation",
    "NegotiationStage",
    "NegotiationTier",
    "NegotiationWarning",
    "SupplierCounterOffer",
    "assert_context_has_no_secrets",
    "authorized_money_set",
    "build_negotiation_explanation",
    "calculate_alibaba_negotiation_plan",
    "calculate_price_bounds",
    "classify_supplier_price",
    "draft_context_from_plan",
    "draft_context_payload",
    "extract_supplier_money",
    "margin_product_ceiling",
    "negotiable_reference_price",
    "next_better_tier",
    "parse_ladder_text",
    "parse_supplier_response",
    "public_price_from_catalog_row",
    "sanitize_negotiation_text",
    "sanitized_negotiation_context",
    "select_quantity_tier",
    "tier_proximity",
    "unauthorized_prices_in_text",
]
