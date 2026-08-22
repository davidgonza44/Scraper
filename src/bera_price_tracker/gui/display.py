"""Money display helpers. No FX. Decimal only."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_CENTS = Decimal("0.01")


def as_decimal(value: object) -> Decimal | None:
    """Parse a stored price without using float."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, int) and not isinstance(value, bool):
        amount = Decimal(value)
    elif isinstance(value, str):
        text = value.strip().replace(",", "").replace("$", "")
        if not text:
            return None
        try:
            amount = Decimal(text)
        except InvalidOperation:
            return None
    else:
        return None
    return amount


def format_price(value: object) -> str:
    """Format the backend-stored listing price as $X.XX. Never convert currency."""
    amount = as_decimal(value)
    if amount is None:
        return "—"
    quantized = amount.quantize(_CENTS, rounding=ROUND_HALF_UP)
    return f"${quantized}"


def is_valid_price(value: object) -> bool:
    amount = as_decimal(value)
    return amount is not None and amount > 0
