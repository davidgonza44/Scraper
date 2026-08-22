"""Pure USD price normalization. No HTTP and no hardcoded rates."""

from __future__ import annotations

import re
from decimal import Decimal

from bera_price_tracker.domain.money import (
    DOLLAR_SYMBOL_EVIDENCE,
    UNSUPPORTED_CURRENCY_EVIDENCE,
    ExchangeRate,
    NormalizationStatus,
    NormalizedPrice,
    quantize_money,
)

_ISO_CURRENCY = re.compile(r"^[A-Z]{3}$")
_VEF_TOKEN = re.compile(r"^VEF\d*$")
_DOLLAR_FORMAT = re.compile(r"^\$")


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("text fields must be strings")
    stripped = value.strip()
    return stripped or None


def _currency_token(value: str | None) -> str:
    text = _text(value)
    if text is None:
        return "UNKNOWN"
    return text.upper()


def _is_vef_token(currency: str, formatted: str | None) -> bool:
    if _VEF_TOKEN.fullmatch(currency) is not None:
        return True
    if formatted is None:
        return False
    compact = formatted.upper().replace(" ", "")
    return _VEF_TOKEN.fullmatch(compact) is not None or compact.startswith("VEF")


def _has_dollar_symbol(currency: str, formatted: str | None) -> bool:
    if currency == "$":
        return True
    if formatted is None:
        return False
    return _DOLLAR_FORMAT.match(formatted.strip()) is not None


def _invalid(amount: Decimal, currency: str, formatted: str | None) -> NormalizedPrice:
    return NormalizedPrice(
        original_amount=amount,
        original_currency=currency,
        original_formatted=formatted,
        usd_amount=None,
        normalization_status=NormalizationStatus.INVALID,
        evidence=("invalid",),
    )


class PriceNormalizer:
    """Map source money to optional USD without mutating the original."""

    def normalize(
        self,
        amount: Decimal | None,
        currency: str | None,
        formatted_amount: str | None = None,
        exchange_rate: ExchangeRate | None = None,
    ) -> NormalizedPrice:
        formatted = _text(formatted_amount)
        currency_token = _currency_token(currency)

        if amount is None or not isinstance(amount, Decimal) or not amount.is_finite():
            fallback = Decimal("0") if amount is None or not isinstance(amount, Decimal) else amount
            return _invalid(fallback, currency_token, formatted)
        if amount <= Decimal("0"):
            return _invalid(amount, currency_token, formatted)

        original_amount = amount
        if currency_token == "USD":
            return NormalizedPrice(
                original_amount=original_amount,
                original_currency="USD",
                original_formatted=formatted,
                usd_amount=quantize_money(original_amount),
                normalization_status=NormalizationStatus.ALREADY_USD,
                evidence=("explicit_iso_usd",),
            )

        if _is_vef_token(currency_token, formatted):
            original_currency = "VEF" if currency_token.startswith("VEF") else currency_token
            if _ISO_CURRENCY.fullmatch(currency_token):
                original_currency = currency_token
            return NormalizedPrice(
                original_amount=original_amount,
                original_currency=original_currency,
                original_formatted=formatted,
                usd_amount=None,
                normalization_status=NormalizationStatus.UNSUPPORTED_CURRENCY,
                evidence=(UNSUPPORTED_CURRENCY_EVIDENCE,),
            )

        if currency_token == "VES":
            if exchange_rate is None:
                return NormalizedPrice(
                    original_amount=original_amount,
                    original_currency="VES",
                    original_formatted=formatted,
                    usd_amount=None,
                    normalization_status=NormalizationStatus.MISSING_RATE,
                    evidence=("missing_rate",),
                )
            usd_amount = quantize_money(original_amount / exchange_rate.rate)
            return NormalizedPrice(
                original_amount=original_amount,
                original_currency="VES",
                original_formatted=formatted,
                usd_amount=usd_amount,
                normalization_status=NormalizationStatus.NORMALIZED,
                evidence=("ves_per_usd_rate",),
                usd_exchange_rate=exchange_rate.rate,
                usd_exchange_rate_source=exchange_rate.source,
                usd_exchange_rate_at=exchange_rate.observed_at,
            )

        if _has_dollar_symbol(currency_token, formatted):
            original_currency = currency_token if currency_token != "USD" else "UNKNOWN"
            return NormalizedPrice(
                original_amount=original_amount,
                original_currency=original_currency,
                original_formatted=formatted,
                usd_amount=quantize_money(original_amount),
                normalization_status=NormalizationStatus.DOLLAR_SYMBOL,
                evidence=(DOLLAR_SYMBOL_EVIDENCE,),
            )

        if currency_token == "UNKNOWN":
            return NormalizedPrice(
                original_amount=original_amount,
                original_currency="UNKNOWN",
                original_formatted=formatted,
                usd_amount=None,
                normalization_status=NormalizationStatus.UNSUPPORTED_CURRENCY,
                evidence=("unknown_currency",),
            )

        if _ISO_CURRENCY.fullmatch(currency_token) is None:
            return NormalizedPrice(
                original_amount=original_amount,
                original_currency=currency_token,
                original_formatted=formatted,
                usd_amount=None,
                normalization_status=NormalizationStatus.UNSUPPORTED_CURRENCY,
                evidence=(UNSUPPORTED_CURRENCY_EVIDENCE,),
            )

        return NormalizedPrice(
            original_amount=original_amount,
            original_currency=currency_token,
            original_formatted=formatted,
            usd_amount=None,
            normalization_status=NormalizationStatus.UNSUPPORTED_CURRENCY,
            evidence=(UNSUPPORTED_CURRENCY_EVIDENCE,),
        )
