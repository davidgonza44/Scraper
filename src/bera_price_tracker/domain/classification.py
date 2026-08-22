"""Pure, marketplace-independent classification of BERA brake-pad candidates."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum

from bera_price_tracker.domain.h0019 import (
    H0019_COMPATIBILITY_FAMILY,
    H0019_OTHER_APPLICATIONS,
    NON_H0019_OTHER_COMPATIBILITY,
    h0019_bera_model_value,
    has_explicit_h0019_code,
    matching_h0019_bera_applications,
    matching_h0019_other_applications,
    matching_non_h0019_other_compatibility,
)


class ProductType(StrEnum):
    """Conservative product type extracted from candidate text."""

    BRAKE_PAD = "brake_pad"
    BRAKE_DISC = "brake_disc"
    OTHER = "other"
    UNKNOWN = "unknown"


class ClassificationDecision(StrEnum):
    """Explicit outcome of a product classification."""

    RELEVANT = "relevant"
    IRRELEVANT = "irrelevant"
    REVIEW = "review"


class BrandFamily(StrEnum):
    """Brand-family evidence established by a classifier."""

    BERA = "bera"
    OTHER = "other"
    UNKNOWN = "unknown"


class CompatibilityFamily(StrEnum):
    """Provider-confirmed brake-pad fitment family."""

    H0019 = H0019_COMPATIBILITY_FAMILY


class BrakePosition(StrEnum):
    """Explicitly stated brake position, without inferred compatibility."""

    FRONT = "front"
    REAR = "rear"
    BOTH = "both"
    UNKNOWN = "unknown"


class BeraBikeModel(StrEnum):
    """Small, explicit set of BERA motorcycle models known to this classifier."""

    SBR = "SBR"
    SOCIALISTA_150 = "Socialista 150"


class ClassificationReason(StrEnum):
    """Stable facts explaining a classification decision."""

    BRAKE_PAD_TERM_FOUND = "brake_pad_term_found"
    BRAKE_DISC_TERM_FOUND = "brake_disc_term_found"
    BRAKE_TERM_WITHOUT_PAD_FOUND = "brake_term_without_pad_found"
    PRODUCT_TYPE_UNKNOWN = "product_type_unknown"
    EXCLUDED_PRODUCT_BRAKE_DISC = "excluded_product_brake_disc"
    EXCLUDED_PRODUCT_HEADLIGHT = "excluded_product_headlight"
    EXCLUDED_PRODUCT_INNER_TUBE = "excluded_product_inner_tube"
    BERA_BRAND_FOUND = "bera_brand_found"
    BERA_MODEL_SBR_FOUND = "bera_model_sbr_found"
    BERA_MODEL_SOCIALISTA_150_FOUND = "bera_model_socialista_150_found"
    H0019_CODE_FOUND = "h0019_code_found"
    H0019_APPLICATION_FOUND = "h0019_application_found"
    KNOWN_COMPETITOR_BRAND_FOUND = "known_competitor_brand_found"
    NON_BRAKE_PAD_PRODUCT = "non_brake_pad_product"
    MISSING_BERA_EVIDENCE = "missing_bera_evidence"
    MISSING_H0019_EVIDENCE = "missing_h0019_evidence"
    REVIEW_BRAKE_PAD_WITH_UNKNOWN_BRAND = "review_brake_pad_with_unknown_brand"
    REVIEW_BRAKE_PAD_WITHOUT_H0019 = "review_brake_pad_without_h0019"
    REVIEW_BERA_WITH_UNKNOWN_PRODUCT = "review_bera_with_unknown_product"
    REVIEW_H0019_WITH_UNKNOWN_PRODUCT = "review_h0019_with_unknown_product"


def _expected_deterministic_decision(
    product_type: ProductType,
    brand_family: BrandFamily,
    compatibility_family: CompatibilityFamily | None,
) -> ClassificationDecision:
    if product_type is ProductType.BRAKE_PAD and compatibility_family is CompatibilityFamily.H0019:
        return ClassificationDecision.RELEVANT
    if product_type is ProductType.BRAKE_PAD and brand_family is not BrandFamily.OTHER:
        return ClassificationDecision.REVIEW
    if product_type is ProductType.UNKNOWN and (
        brand_family is BrandFamily.BERA or compatibility_family is CompatibilityFamily.H0019
    ):
        return ClassificationDecision.REVIEW
    return ClassificationDecision.IRRELEVANT


@dataclass(frozen=True, slots=True)
class ProductClassification:
    """Immutable extracted facts and deterministic relevance decision."""

    decision: ClassificationDecision
    product_type: ProductType
    brand_family: BrandFamily
    compatibility_family: CompatibilityFamily | None
    bike_models: tuple[BeraBikeModel, ...]
    other_compatibility: tuple[str, ...]
    position: BrakePosition
    reasons: tuple[ClassificationReason, ...]
    relevant: bool = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.decision, ClassificationDecision):
            raise TypeError("decision must be a ClassificationDecision")
        if not isinstance(self.product_type, ProductType):
            raise TypeError("product_type must be a ProductType")
        if not isinstance(self.brand_family, BrandFamily):
            raise TypeError("brand_family must be a BrandFamily")
        if self.compatibility_family is not None and not isinstance(
            self.compatibility_family, CompatibilityFamily
        ):
            raise TypeError("compatibility_family must be a CompatibilityFamily or None")
        if not isinstance(self.position, BrakePosition):
            raise TypeError("position must be a BrakePosition")
        if not isinstance(self.bike_models, tuple) or any(
            not isinstance(model, BeraBikeModel) for model in self.bike_models
        ):
            raise TypeError("bike_models must be a tuple of BeraBikeModel values")
        if not isinstance(self.reasons, tuple) or any(
            not isinstance(reason, ClassificationReason) for reason in self.reasons
        ):
            raise TypeError("reasons must be a tuple of ClassificationReason values")
        if self.bike_models and self.brand_family is not BrandFamily.BERA:
            raise ValueError("BERA bike models require the BERA brand family")
        if self.bike_models and self.compatibility_family is not CompatibilityFamily.H0019:
            raise ValueError("BERA bike models require H0019 compatibility")
        if not isinstance(self.other_compatibility, tuple) or any(
            not isinstance(value, str) for value in self.other_compatibility
        ):
            raise TypeError("other_compatibility must be a tuple of strings")
        allowed_other_compatibility = H0019_OTHER_APPLICATIONS + NON_H0019_OTHER_COMPATIBILITY
        if any(value not in allowed_other_compatibility for value in self.other_compatibility):
            raise ValueError("other_compatibility must contain only controlled applications")
        if (
            self.other_compatibility
            and (self.compatibility_family is not CompatibilityFamily.H0019)
            and any(value in H0019_OTHER_APPLICATIONS for value in self.other_compatibility)
        ):
            raise ValueError("known H0019 applications require H0019 compatibility")
        expected_decision = _expected_deterministic_decision(
            self.product_type,
            self.brand_family,
            self.compatibility_family,
        )
        if self.decision is not expected_decision:
            raise ValueError("decision does not match deterministic classification facts")
        object.__setattr__(
            self,
            "relevant",
            self.decision is ClassificationDecision.RELEVANT,
        )

    @property
    def brand_match(self) -> bool:
        """Return whether explicit BERA-family evidence was found."""

        return self.brand_family is BrandFamily.BERA


_BRAKE_PAD_TERMS = frozenset({"pastilla", "pastillas"})
_BRAKE_DISC_TERMS = frozenset({"disco", "discos"})
_BRAKE_TERMS = frozenset({"freno", "frenos"})
_FRONT_TERMS = frozenset({"delantera", "delanteras", "delantero", "delanteros"})
_REAR_TERMS = frozenset({"trasera", "traseras", "trasero", "traseros"})
_OTHER_EXCLUSIONS: tuple[tuple[ClassificationReason, frozenset[str]], ...] = (
    (
        ClassificationReason.EXCLUDED_PRODUCT_HEADLIGHT,
        frozenset({"faro", "faros"}),
    ),
    (
        ClassificationReason.EXCLUDED_PRODUCT_INNER_TUBE,
        frozenset({"camara", "camaras"}),
    ),
)
_KNOWN_COMPETITOR_BRANDS = frozenset({"benelli", "chevrolet", "ford"})


def _normalized_text(value: str | None, field_name: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string or None")

    decomposed = unicodedata.normalize("NFKD", value.casefold().strip())
    without_accents = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    neutralized = "".join(
        character if character.isalnum() else " " for character in without_accents
    )
    return " ".join(neutralized.split())


def _candidate_tokens(title: str, description: str | None) -> frozenset[str]:
    if not isinstance(title, str):
        raise TypeError("title must be a string")
    title_text = _normalized_text(title, "title")
    description_text = _normalized_text(description, "description")
    return frozenset(f"{title_text} {description_text}".split())


def _position(tokens: frozenset[str]) -> BrakePosition:
    front_found = not _FRONT_TERMS.isdisjoint(tokens)
    rear_found = not _REAR_TERMS.isdisjoint(tokens)
    if front_found and rear_found:
        return BrakePosition.BOTH
    if front_found:
        return BrakePosition.FRONT
    if rear_found:
        return BrakePosition.REAR
    return BrakePosition.UNKNOWN


def classify_brake_pad_candidate(
    title: str,
    description: str | None = None,
) -> ProductClassification:
    """Classify one candidate using explicit product and H0019 fitment evidence.

    A result is relevant only when a brake-pad term and either the H0019 reference or a
    controlled H0019 application match are present. The function performs no I/O and
    retains none of the input text.
    """

    tokens = _candidate_tokens(title, description)
    brake_disc_found = not _BRAKE_DISC_TERMS.isdisjoint(tokens)
    brake_pad_found = not _BRAKE_PAD_TERMS.isdisjoint(tokens)
    brake_term_found = not _BRAKE_TERMS.isdisjoint(tokens)
    other_exclusions = tuple(
        reason for reason, terms in _OTHER_EXCLUSIONS if not terms.isdisjoint(tokens)
    )

    reasons: list[ClassificationReason] = []
    if brake_disc_found:
        product_type = ProductType.BRAKE_DISC
        reasons.extend(
            (
                ClassificationReason.BRAKE_DISC_TERM_FOUND,
                ClassificationReason.EXCLUDED_PRODUCT_BRAKE_DISC,
            )
        )
    elif other_exclusions:
        product_type = ProductType.OTHER
        reasons.extend(other_exclusions)
    elif brake_pad_found:
        product_type = ProductType.BRAKE_PAD
        reasons.append(ClassificationReason.BRAKE_PAD_TERM_FOUND)
    else:
        product_type = ProductType.UNKNOWN
        reasons.append(
            ClassificationReason.BRAKE_TERM_WITHOUT_PAD_FOUND
            if brake_term_found
            else ClassificationReason.PRODUCT_TYPE_UNKNOWN
        )

    bera_applications = matching_h0019_bera_applications(title, description)
    h0019_other_applications = matching_h0019_other_applications(title, description)
    other_compatibility = h0019_other_applications + matching_non_h0019_other_compatibility(
        title, description
    )
    h0019_code_found = has_explicit_h0019_code(title, description)
    bera_brand_found = "bera" in tokens
    model_values = tuple(h0019_bera_model_value(application) for application in bera_applications)
    if any(value is None for value in model_values):
        raise AssertionError("H0019 BERA application is missing its model mapping")
    bike_models = tuple(BeraBikeModel(value) for value in model_values if value is not None)
    known_competitor_found = not _KNOWN_COMPETITOR_BRANDS.isdisjoint(tokens)
    if bera_brand_found:
        reasons.append(ClassificationReason.BERA_BRAND_FOUND)
    if BeraBikeModel.SBR in bike_models:
        reasons.append(ClassificationReason.BERA_MODEL_SBR_FOUND)
    if BeraBikeModel.SOCIALISTA_150 in bike_models:
        reasons.append(ClassificationReason.BERA_MODEL_SOCIALISTA_150_FOUND)
    if h0019_code_found:
        reasons.append(ClassificationReason.H0019_CODE_FOUND)
    if bera_applications or h0019_other_applications:
        reasons.append(ClassificationReason.H0019_APPLICATION_FOUND)
    if known_competitor_found:
        reasons.append(ClassificationReason.KNOWN_COMPETITOR_BRAND_FOUND)

    brand_match = bera_brand_found or bool(bike_models)
    if brand_match:
        brand_family = BrandFamily.BERA
    elif known_competitor_found:
        brand_family = BrandFamily.OTHER
    else:
        brand_family = BrandFamily.UNKNOWN

    compatibility_family = (
        CompatibilityFamily.H0019
        if h0019_code_found or bera_applications or h0019_other_applications
        else None
    )
    decision = _expected_deterministic_decision(
        product_type,
        brand_family,
        compatibility_family,
    )
    if decision is ClassificationDecision.REVIEW and product_type is ProductType.BRAKE_PAD:
        reasons.append(ClassificationReason.REVIEW_BRAKE_PAD_WITHOUT_H0019)
    elif decision is ClassificationDecision.REVIEW:
        reasons.append(
            ClassificationReason.REVIEW_H0019_WITH_UNKNOWN_PRODUCT
            if compatibility_family is CompatibilityFamily.H0019
            else ClassificationReason.REVIEW_BERA_WITH_UNKNOWN_PRODUCT
        )

    if product_type is not ProductType.BRAKE_PAD:
        reasons.append(ClassificationReason.NON_BRAKE_PAD_PRODUCT)
    if compatibility_family is None:
        reasons.append(ClassificationReason.MISSING_H0019_EVIDENCE)

    return ProductClassification(
        decision=decision,
        product_type=product_type,
        brand_family=brand_family,
        compatibility_family=compatibility_family,
        bike_models=bike_models,
        other_compatibility=other_compatibility,
        position=_position(tokens),
        reasons=tuple(reasons),
    )
