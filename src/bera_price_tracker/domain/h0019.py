"""Authoritative fitment data and conservative matching for brake-pad family H0019."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

H0019_COMPATIBILITY_FAMILY = "H0019"

H0019_BERA_FITMENTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("SBR 150", "SBR", ("SBR", "SBR150", "SBR 150")),
    ("Socialista 150", "Socialista 150", ("Socialista 150", "Socialista150")),
)
H0019_BERA_APPLICATION_ALIASES = tuple(
    (application, aliases) for application, _model, aliases in H0019_BERA_FITMENTS
)

H0019_APPLICATIONS_BY_BRAND: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Honda", ("CRF150R", "CG125 ES4", "CG150", "CBX125", "MRX50", "ATC250 RB")),
    ("Kawasaki", ("KLX125", "KVF360", "KX65", "BN125")),
    ("Suzuki", ("RM65", "DR125", "LT-A400", "SX200", "DF200", "TS125")),
    ("Yamaha", ("YFM250", "YFM350", "YFM450")),
    ("Keeway", ("Dragon 250 Quad",)),
    ("Hyosung", ("TE450 Quad Rapier",)),
    ("Jialing", ("JH125 B Roadstar",)),
    ("Superbyke", ("RMR125",)),
    ("AKT", ("AK100S", "AK200 SM/XM")),
)

H0019_UNBRANDED_APPLICATIONS: tuple[str, ...] = (
    "GL145",
    "VF125",
    "GY6-150(F)",
    "GL PRO",
    "GL MAX",
)

# Mentioned compatibility that must remain separate from the provider-confirmed family.
NON_H0019_OTHER_COMPATIBILITY: tuple[str, ...] = ("Matrix",)

H0019_BERA_APPLICATIONS = tuple(
    application for application, _model, _aliases in H0019_BERA_FITMENTS
)
H0019_BERA_TOOL_VALUES = tuple(
    alias for _application, _model, aliases in H0019_BERA_FITMENTS for alias in aliases
)
H0019_OTHER_APPLICATIONS = (
    tuple(
        application
        for _brand, applications in H0019_APPLICATIONS_BY_BRAND
        for application in applications
    )
    + H0019_UNBRANDED_APPLICATIONS
)
H0019_ALL_APPLICATIONS = H0019_BERA_APPLICATIONS + H0019_OTHER_APPLICATIONS


def _fold_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def _exact_syntax_pattern(value: str) -> re.Pattern[str]:
    segments = re.findall(r"[a-z0-9]+", _fold_text(value))
    expression = r"[^a-z0-9]*".join(re.escape(segment) for segment in segments)
    return re.compile(rf"(?<![a-z0-9]){expression}(?![a-z0-9])")


_H0019_CODE_PATTERN = _exact_syntax_pattern(H0019_COMPATIBILITY_FAMILY)
_H0019_BERA_PATTERNS = tuple(
    (canonical, tuple(_exact_syntax_pattern(alias) for alias in aliases))
    for canonical, aliases in H0019_BERA_APPLICATION_ALIASES
)
_H0019_OTHER_PATTERNS = tuple(
    (application, _exact_syntax_pattern(application)) for application in H0019_OTHER_APPLICATIONS
)
_NON_H0019_OTHER_PATTERNS = tuple(
    (application, _exact_syntax_pattern(application))
    for application in NON_H0019_OTHER_COMPATIBILITY
)


def _validated_texts(values: Iterable[str | None]) -> tuple[str, ...]:
    texts: list[str] = []
    for value in values:
        if value is None:
            continue
        if not isinstance(value, str):
            raise TypeError("H0019 matching values must be strings or None")
        texts.append(_fold_text(value))
    return tuple(texts)


def has_explicit_h0019_code(*values: str | None) -> bool:
    """Return whether H0019 appears as a bounded, explicit reference."""

    return any(_H0019_CODE_PATTERN.search(text) is not None for text in _validated_texts(values))


def matching_h0019_bera_applications(*values: str | None) -> tuple[str, ...]:
    """Return canonical BERA applications explicitly present in the supplied fields."""

    texts = _validated_texts(values)
    return tuple(
        canonical
        for canonical, patterns in _H0019_BERA_PATTERNS
        if any(pattern.search(text) is not None for pattern in patterns for text in texts)
    )


def matching_h0019_other_applications(*values: str | None) -> tuple[str, ...]:
    """Return canonical non-BERA or unbranded H0019 applications explicitly present."""

    texts = _validated_texts(values)
    return tuple(
        application
        for application, pattern in _H0019_OTHER_PATTERNS
        if any(pattern.search(text) is not None for text in texts)
    )


def matching_non_h0019_other_compatibility(*values: str | None) -> tuple[str, ...]:
    """Return controlled external compatibility without treating it as H0019 evidence."""

    texts = _validated_texts(values)
    return tuple(
        application
        for application, pattern in _NON_H0019_OTHER_PATTERNS
        if any(pattern.search(text) is not None for text in texts)
    )


def canonical_h0019_bera_tool_value(value: str) -> str | None:
    """Map one exact permitted tool value to its canonical classifier model value."""

    if not isinstance(value, str):
        raise TypeError("BERA tool value must be a string")
    for _application, model, aliases in H0019_BERA_FITMENTS:
        if value in aliases:
            return model
    return None


def h0019_bera_model_value(application: str) -> str | None:
    """Map a provider-canonical BERA application to the public model value."""

    for known_application, model, _aliases in H0019_BERA_FITMENTS:
        if application == known_application:
            return model
    return None


def is_h0019_compatible_application(value: str) -> bool:
    """Return whether provider text names a known H0019 application exactly."""

    return is_h0019_bera_application(value) or is_h0019_other_application(value)


def is_h0019_bera_application(value: str) -> bool:
    """Return whether text contains a controlled BERA application."""

    return bool(matching_h0019_bera_applications(value))


def is_h0019_other_application(value: str) -> bool:
    """Return whether text contains a controlled non-BERA H0019 application."""

    return bool(matching_h0019_other_applications(value))
