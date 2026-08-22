"""Pure unit tests for conservative BERA brake-pad classification."""

from dataclasses import FrozenInstanceError

import pytest

from bera_price_tracker.domain import (
    BeraBikeModel,
    BrakePosition,
    BrandFamily,
    ClassificationDecision,
    ClassificationReason,
    CompatibilityFamily,
    ProductClassification,
    ProductType,
    classify_brake_pad_candidate,
)


@pytest.mark.parametrize(
    ("title", "expected_models", "expected_other_compatibility"),
    [
        ("Pastillas de freno H0019", (), ()),
        ("Pastillas Bera SBR 150", (BeraBikeModel.SBR,), ()),
        (
            "Pastillas Bera Socialista 150",
            (BeraBikeModel.SOCIALISTA_150,),
            (),
        ),
        ("Pastillas Honda CG125 ES4", (), ("CG125 ES4",)),
        ("Pastillas Kawasaki KLX125", (), ("KLX125",)),
        ("Pastillas Suzuki DR125", (), ("DR125",)),
        ("Pastillas Yamaha YFM350", (), ("YFM350",)),
        ("Pastillas AKT AK100S", (), ("AK100S",)),
    ],
)
def test_real_relevant_candidates_are_accepted(
    title: str,
    expected_models: tuple[BeraBikeModel, ...],
    expected_other_compatibility: tuple[str, ...],
) -> None:
    result = classify_brake_pad_candidate(title)

    assert result.relevant is True
    assert result.decision is ClassificationDecision.RELEVANT
    assert result.product_type is ProductType.BRAKE_PAD
    assert result.compatibility_family is CompatibilityFamily.H0019
    assert result.bike_models == expected_models
    assert result.other_compatibility == expected_other_compatibility
    assert result.position is BrakePosition.UNKNOWN
    assert ClassificationReason.BRAKE_PAD_TERM_FOUND in result.reasons


@pytest.mark.parametrize(
    ("title", "expected_product_type", "expected_reason"),
    [
        (
            "Faro Honda CG125 ES4",
            ProductType.OTHER,
            ClassificationReason.EXCLUDED_PRODUCT_HEADLIGHT,
        ),
        (
            "Camara Original Bera Sbr sola",
            ProductType.OTHER,
            ClassificationReason.EXCLUDED_PRODUCT_INNER_TUBE,
        ),
        (
            "Disco de freno Bera SBR 150",
            ProductType.BRAKE_DISC,
            ClassificationReason.EXCLUDED_PRODUCT_BRAKE_DISC,
        ),
        (
            "PASTILLAS DE FRENO DELANTERA CHEVROLET CAPTIVA 3.2",
            ProductType.BRAKE_PAD,
            ClassificationReason.MISSING_H0019_EVIDENCE,
        ),
        (
            "Pastillas de freno trasera de cerámica para Benelli",
            ProductType.BRAKE_PAD,
            ClassificationReason.MISSING_H0019_EVIDENCE,
        ),
        (
            "Pastillas de Freno Delanteras Ford Explorer",
            ProductType.BRAKE_PAD,
            ClassificationReason.MISSING_H0019_EVIDENCE,
        ),
    ],
)
def test_real_irrelevant_candidates_are_rejected(
    title: str,
    expected_product_type: ProductType,
    expected_reason: ClassificationReason,
) -> None:
    result = classify_brake_pad_candidate(title)

    assert result.relevant is False
    assert result.decision is ClassificationDecision.IRRELEVANT
    assert result.product_type is expected_product_type
    assert expected_reason in result.reasons


def test_title_and_description_are_combined_for_classification() -> None:
    result = classify_brake_pad_candidate(
        "Pastillas de freno",
        "Compatible con Bera SBR",
    )

    assert result.relevant is True
    assert result.brand_match is True
    assert result.bike_models == (BeraBikeModel.SBR,)
    assert ClassificationReason.BERA_BRAND_FOUND in result.reasons
    assert ClassificationReason.BERA_MODEL_SBR_FOUND in result.reasons


def test_description_without_h0019_evidence_does_not_make_candidate_relevant() -> None:
    result = classify_brake_pad_candidate(
        "Pastillas de freno",
        "Compatible con Chevrolet",
    )

    assert result.relevant is False
    assert result.product_type is ProductType.BRAKE_PAD
    assert result.brand_match is False
    assert ClassificationReason.MISSING_H0019_EVIDENCE in result.reasons


def test_description_can_supply_brake_pad_and_bera_evidence() -> None:
    result = classify_brake_pad_candidate(
        "Repuesto para motocicleta",
        "Pastillas de freno para Bera SBR",
    )

    assert result.relevant is True
    assert result.product_type is ProductType.BRAKE_PAD
    assert result.brand_match is True


@pytest.mark.parametrize(
    ("title", "expected_position"),
    [
        ("Pastillas de freno delanteras Bera SBR", BrakePosition.FRONT),
        ("Pastillas traseras Bera SBR", BrakePosition.REAR),
        ("Pastillas delanteras y traseras Bera SBR", BrakePosition.BOTH),
        ("Pastillas Bera SBR", BrakePosition.UNKNOWN),
    ],
)
def test_explicit_position_is_extracted(
    title: str,
    expected_position: BrakePosition,
) -> None:
    result = classify_brake_pad_candidate(title)

    assert result.position is expected_position


@pytest.mark.parametrize(
    ("title", "expected_position"),
    [
        ("Pastilla delantera Bera", BrakePosition.FRONT),
        ("Pastillas delanteros Bera", BrakePosition.FRONT),
        ("Pastilla trasero Bera", BrakePosition.REAR),
        ("Pastillas traseras y delanteras Bera", BrakePosition.BOTH),
    ],
)
def test_position_recognizes_requested_spanish_variants(
    title: str,
    expected_position: BrakePosition,
) -> None:
    assert classify_brake_pad_candidate(title).position is expected_position


def test_bera_model_and_external_compatibility_remain_separate() -> None:
    result = classify_brake_pad_candidate("Pastillas freno sbr tx dr200 matrix")

    assert result.bike_models == (BeraBikeModel.SBR,)
    assert result.other_compatibility == ("Matrix",)
    assert ClassificationReason.BERA_MODEL_SBR_FOUND in result.reasons


def test_explicit_bera_brand_does_not_invent_a_bike_model() -> None:
    result = classify_brake_pad_candidate("Pastillas BERA")

    assert result.brand_match is True
    assert result.decision is ClassificationDecision.REVIEW
    assert result.compatibility_family is None
    assert result.bike_models == ()
    assert ClassificationReason.BERA_BRAND_FOUND in result.reasons


@pytest.mark.parametrize(
    ("title", "expected_product_type"),
    [
        ("Pastillas Bera", ProductType.BRAKE_PAD),
        ("Disco de freno Bera", ProductType.BRAKE_DISC),
        ("Faro delantero Bera", ProductType.OTHER),
        ("Repuesto Bera", ProductType.UNKNOWN),
    ],
)
def test_product_types_are_distinguished(
    title: str,
    expected_product_type: ProductType,
) -> None:
    assert classify_brake_pad_candidate(title).product_type is expected_product_type


def test_freno_alone_is_not_brake_pad_evidence() -> None:
    result = classify_brake_pad_candidate("Freno Bera SBR")

    assert result.relevant is False
    assert result.decision is ClassificationDecision.REVIEW
    assert result.product_type is ProductType.UNKNOWN
    assert ClassificationReason.BRAKE_TERM_WITHOUT_PAD_FOUND in result.reasons
    assert ClassificationReason.NON_BRAKE_PAD_PRODUCT in result.reasons


def test_brake_disc_exclusion_wins_over_brake_pad_words_and_bera() -> None:
    result = classify_brake_pad_candidate("Pastillas y discos de freno Bera SBR")

    assert result.relevant is False
    assert result.product_type is ProductType.BRAKE_DISC
    assert ClassificationReason.BRAKE_DISC_TERM_FOUND in result.reasons
    assert ClassificationReason.EXCLUDED_PRODUCT_BRAKE_DISC in result.reasons


@pytest.mark.parametrize(
    ("title", "expected_reason"),
    [
        (
            "Pastillas y faro Bera SBR",
            ClassificationReason.EXCLUDED_PRODUCT_HEADLIGHT,
        ),
        (
            "Pastillas y cámara Bera SBR",
            ClassificationReason.EXCLUDED_PRODUCT_INNER_TUBE,
        ),
    ],
)
def test_other_strong_exclusions_win_over_brake_pad_words_and_bera(
    title: str,
    expected_reason: ClassificationReason,
) -> None:
    result = classify_brake_pad_candidate(title)

    assert result.relevant is False
    assert result.product_type is ProductType.OTHER
    assert expected_reason in result.reasons


def test_normalization_handles_case_accents_punctuation_and_repeated_whitespace() -> None:
    result = classify_brake_pad_candidate(
        "  PÁSTILLAS,\tDE   FRENO!!! bÉrA / SbR.  ",
    )

    assert result.relevant is True
    assert result.product_type is ProductType.BRAKE_PAD
    assert result.brand_match is True
    assert result.bike_models == (BeraBikeModel.SBR,)


def test_accented_camera_is_normalized_and_strongly_excluded() -> None:
    result = classify_brake_pad_candidate("CÁMARA, ORIGINAL; BERA-SBR")

    assert result.relevant is False
    assert result.product_type is ProductType.OTHER
    assert ClassificationReason.EXCLUDED_PRODUCT_INNER_TUBE in result.reasons


def test_bera_must_be_an_explicit_token_not_a_substring() -> None:
    result = classify_brake_pad_candidate("Pastillas liberadas para motocicleta")

    assert result.relevant is False
    assert result.decision is ClassificationDecision.REVIEW
    assert result.brand_match is False
    assert ClassificationReason.MISSING_H0019_EVIDENCE in result.reasons


def test_reasons_describe_acceptance_by_sbr_without_explicit_bera() -> None:
    result = classify_brake_pad_candidate("Pastillas de freno SBR Matrix")

    assert result.relevant is True
    assert result.reasons == (
        ClassificationReason.BRAKE_PAD_TERM_FOUND,
        ClassificationReason.BERA_MODEL_SBR_FOUND,
        ClassificationReason.H0019_APPLICATION_FOUND,
    )
    assert result.other_compatibility == ("Matrix",)


def test_reasons_describe_both_missing_requirements_deterministically() -> None:
    result = classify_brake_pad_candidate("Accesorio universal")

    assert result.relevant is False
    assert result.reasons == (
        ClassificationReason.PRODUCT_TYPE_UNKNOWN,
        ClassificationReason.NON_BRAKE_PAD_PRODUCT,
        ClassificationReason.MISSING_H0019_EVIDENCE,
    )


def test_classification_is_an_immutable_value_object() -> None:
    result = classify_brake_pad_candidate("Pastillas de freno Bera SBR")

    assert isinstance(result, ProductClassification)
    assert isinstance(result.bike_models, tuple)
    assert isinstance(result.reasons, tuple)
    with pytest.raises(FrozenInstanceError):
        result.relevant = False  # type: ignore[misc]


def test_classification_is_deterministic() -> None:
    arguments = (
        "Pastillas de freno delanteras SBR",
        "Compatible con Bera SBR",
    )

    first = classify_brake_pad_candidate(*arguments)
    second = classify_brake_pad_candidate(*arguments)

    assert first == second
    assert first is not second


def test_title_and_description_require_text_values() -> None:
    with pytest.raises(TypeError, match="title"):
        classify_brake_pad_candidate(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="description"):
        classify_brake_pad_candidate("Pastillas Bera", 7)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "title",
    [
        "Pastillas de freno Bera SBR",
        "Pastillas de freno Bera SBR150",
        "Pastillas de freno Bera SBR-150",
        "Pastillas de freno Bera Socialista 150",
        "Pastillas de freno Bera Socialista150",
    ],
)
def test_bera_h0019_aliases_are_exact_model_evidence(title: str) -> None:
    result = classify_brake_pad_candidate(title)

    assert result.decision is ClassificationDecision.RELEVANT
    assert result.brand_family is BrandFamily.BERA
    assert len(result.bike_models) == 1


@pytest.mark.parametrize(
    "title",
    [
        "Pastillas Honda CG125 para moto",
        "Pastillas SBR1500 para moto",
        "Pastillas H00190 para moto",
        "Pastillas Honda CG125 ES40",
    ],
)
def test_bera_and_sbr_model_matching_never_uses_raw_substrings(title: str) -> None:
    result = classify_brake_pad_candidate(title)

    assert result.decision is ClassificationDecision.REVIEW
    assert result.brand_match is False
    assert result.brand_family is BrandFamily.UNKNOWN
    assert result.bike_models == ()


@pytest.mark.parametrize(
    ("title", "expected_family", "expected_reason"),
    [
        (
            "Pastillas de freno para moto",
            None,
            ClassificationReason.REVIEW_BRAKE_PAD_WITHOUT_H0019,
        ),
        (
            "Repuestos Honda CG125 ES4",
            CompatibilityFamily.H0019,
            ClassificationReason.REVIEW_H0019_WITH_UNKNOWN_PRODUCT,
        ),
    ],
)
def test_ambiguous_h0019_cases_remain_in_review(
    title: str,
    expected_family: CompatibilityFamily | None,
    expected_reason: ClassificationReason,
) -> None:
    result = classify_brake_pad_candidate(title)

    assert result.decision is ClassificationDecision.REVIEW
    assert result.compatibility_family is expected_family
    assert result.brand_family is BrandFamily.UNKNOWN
    assert expected_reason in result.reasons


def test_review_case_b_is_bera_with_genuinely_unknown_product() -> None:
    result = classify_brake_pad_candidate("Repuestos Bera SBR disponibles")

    assert result.decision is ClassificationDecision.REVIEW
    assert result.product_type is ProductType.UNKNOWN
    assert result.brand_family is BrandFamily.BERA
    assert ClassificationReason.REVIEW_H0019_WITH_UNKNOWN_PRODUCT in result.reasons


@pytest.mark.parametrize("brand", ["Chevrolet", "Ford", "Benelli"])
def test_known_competing_brand_is_deterministically_irrelevant(brand: str) -> None:
    result = classify_brake_pad_candidate(f"Pastillas de freno {brand}")

    assert result.decision is ClassificationDecision.IRRELEVANT
    assert result.brand_family is BrandFamily.OTHER
    assert ClassificationReason.KNOWN_COMPETITOR_BRAND_FOUND in result.reasons


def test_known_competitor_does_not_override_explicit_bera_compatibility() -> None:
    result = classify_brake_pad_candidate("Pastillas Bera SBR compatibles con Ford")

    assert result.decision is ClassificationDecision.RELEVANT
    assert result.brand_family is BrandFamily.BERA


@pytest.mark.parametrize(
    "title",
    [
        "Faro Bera SBR",
        "Camara Bera SBR",
        "Disco de freno Bera SBR",
    ],
)
def test_strong_exclusions_never_become_review(title: str) -> None:
    assert classify_brake_pad_candidate(title).decision is ClassificationDecision.IRRELEVANT


def test_unknown_product_without_bera_evidence_is_not_a_review_trigger() -> None:
    result = classify_brake_pad_candidate("Repuestos universales disponibles")

    assert result.decision is ClassificationDecision.IRRELEVANT
    assert result.brand_family is BrandFamily.UNKNOWN


def test_unknown_product_with_only_a_competing_brand_is_irrelevant() -> None:
    result = classify_brake_pad_candidate("Repuestos Chevrolet disponibles")

    assert result.decision is ClassificationDecision.IRRELEVANT
    assert result.product_type is ProductType.UNKNOWN
    assert result.brand_family is BrandFamily.OTHER


def test_compatibility_boolean_is_derived_from_the_decision() -> None:
    relevant = classify_brake_pad_candidate("Pastillas H0019")
    review = classify_brake_pad_candidate("Pastillas para moto")
    irrelevant = classify_brake_pad_candidate("Pastillas Ford")

    assert relevant.relevant is True
    assert review.relevant is False
    assert irrelevant.relevant is False
