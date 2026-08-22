"""Facebook Marketplace Venezuela display-price policy.

VEF5 / $4 on Facebook VE are treated as a USD *display* of the same numeric
amount. This is not an FX conversion and must not be applied globally.
"""

from __future__ import annotations

from decimal import Decimal

from bera_price_tracker.application.price_normalization import PriceNormalizer
from bera_price_tracker.domain.money import (
    DOLLAR_SYMBOL_EVIDENCE,
    FACEBOOK_VENEZUELA_EVIDENCE,
    NormalizationStatus,
    NormalizedPrice,
    quantize_money,
)

_normalizer = PriceNormalizer()


def normalize_facebook_venezuela_price(
    amount: Decimal | None,
    currency: str | None,
    formatted_amount: str | None = None,
) -> NormalizedPrice:
    """Normalize one Facebook VE price for USD display.

    The numeric amount is never changed. ``VEF5`` and ``$4`` become ``$5.00`` /
    ``$4.00`` with explicit Facebook-Venezuela evidence. Explicit ISO USD stays
    ``already_usd``. Source currency is preserved (``VEF``, ``UNKNOWN``, ...).
    """

    generic = _normalizer.normalize(amount, currency, formatted_amount)
    if generic.normalization_status is NormalizationStatus.INVALID:
        return generic
    if generic.normalization_status is NormalizationStatus.ALREADY_USD:
        return generic

    if generic.normalization_status is NormalizationStatus.DOLLAR_SYMBOL:
        return NormalizedPrice(
            original_amount=generic.original_amount,
            original_currency=generic.original_currency,
            original_formatted=generic.original_formatted,
            usd_amount=quantize_money(generic.original_amount),
            normalization_status=NormalizationStatus.DOLLAR_SYMBOL,
            evidence=(DOLLAR_SYMBOL_EVIDENCE, FACEBOOK_VENEZUELA_EVIDENCE),
        )

    if generic.normalization_status is NormalizationStatus.UNSUPPORTED_CURRENCY:
        token = generic.original_currency
        formatted = generic.original_formatted
        is_vef = token.startswith("VEF") or (
            formatted is not None and formatted.upper().replace(" ", "").startswith("VEF")
        )
        if is_vef:
            return NormalizedPrice(
                original_amount=generic.original_amount,
                original_currency=generic.original_currency,
                original_formatted=generic.original_formatted,
                usd_amount=quantize_money(generic.original_amount),
                normalization_status=NormalizationStatus.NORMALIZED,
                evidence=(FACEBOOK_VENEZUELA_EVIDENCE,),
            )

    return generic
