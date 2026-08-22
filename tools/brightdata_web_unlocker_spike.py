"""Isolated Bright Data Web Unlocker spike for one known Marketplace URL.

This tool is not part of the production Facebook provider. Its default mode is a
dry run. Only ``--execute`` may send the single ``scrape_url`` call represented here.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum

from brightdata import SyncBrightDataClient

TOKEN_ENV = "BERA_TRACKER_BRIGHTDATA_API_TOKEN"
TARGET_URL = "https://www.facebook.com/marketplace/item/1541741674024621"
DEFAULT_TIMEOUT_SECONDS = 70

_LOGIN_MARKERS = (
    "login",
    "log in",
    "iniciar sesión",
    "iniciar sesion",
)
_MARKETPLACE_MARKERS = ("marketplace",)
_BEARER_PATTERN = re.compile(r"bearer\s+\S+", re.IGNORECASE)
_EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


class SpikeExitCode(IntEnum):
    """Stable exit codes for this experimental command."""

    SUCCESS = 0
    CONFIGURATION_ERROR = 2
    REQUEST_ERROR = 3


class PageKind(StrEnum):
    """Conservative in-memory classification of one Unlocker payload."""

    MARKETPLACE_CONTENT = "marketplace_content"
    LOGIN_PAGE = "login_page"
    UNKNOWN = "unknown"


class SpikeOutcome(StrEnum):
    """Sanitized final verdict printed by the spike."""

    MARKETPLACE_CONTENT = "MARKETPLACE_CONTENT"
    LOGIN_PAGE = "LOGIN_PAGE"
    UNKNOWN = "UNKNOWN"
    REQUEST_ERROR = "REQUEST_ERROR"


class SpikeConfigurationError(ValueError):
    """The local spike configuration is invalid or incomplete."""


class UnlockerRequestError(RuntimeError):
    """The one permitted Web Unlocker request did not complete successfully."""


@dataclass(frozen=True, slots=True)
class SpikeConfiguration:
    """Validated spike configuration with a redacted credential representation."""

    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    _api_token: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> SpikeConfiguration:
        """Load the existing tracker token without writing it to another env var."""

        values = os.environ if environ is None else environ
        raw_token = values.get(TOKEN_ENV)
        api_token = None if raw_token is None else raw_token.strip() or None
        return cls(_api_token=api_token)

    @property
    def api_token_configured(self) -> bool:
        """Return token presence without revealing any credential material."""

        return self._api_token is not None

    def require_api_token(self) -> str:
        """Return the credential only to the SDK boundary, or fail safely."""

        if self._api_token is None:
            raise SpikeConfigurationError(f"{TOKEN_ENV} is required with --execute")
        return self._api_token


@dataclass(frozen=True, slots=True)
class SanitizedUnlockerSummary:
    """Display-only facts from one Web Unlocker response."""

    success: bool
    result_type: str
    status: str
    content_bytes: int
    content_type: str
    page_kind: PageKind
    error: str | None = None


type ScrapeOnce = Callable[[str, str, int], object]


def classify_page_content(text: str) -> PageKind:
    """Classify Unlocker text in memory without printing any of it."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    lowered = text.casefold()
    if any(marker in lowered for marker in _LOGIN_MARKERS):
        return PageKind.LOGIN_PAGE
    if any(marker in lowered for marker in _MARKETPLACE_MARKERS):
        return PageKind.MARKETPLACE_CONTENT
    return PageKind.UNKNOWN


def scrape_once(token: str, url: str, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> object:
    """Issue exactly one Web Unlocker ``scrape_url`` call."""

    if not isinstance(token, str) or not token.strip():
        raise SpikeConfigurationError("token must not be blank")
    if not isinstance(url, str) or not url.strip():
        raise SpikeConfigurationError("url must not be blank")
    try:
        with SyncBrightDataClient(
            token=token,
            timeout=timeout_seconds,
            auto_create_zones=False,
            validate_token=False,
        ) as client:
            return client.scrape_url(url)
    except SpikeConfigurationError:
        raise
    except Exception as error:
        raise UnlockerRequestError(type(error).__name__) from error


def _content_text(data: object) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    if isinstance(data, (bytes, bytearray)):
        return bytes(data).decode("utf-8", errors="replace")
    try:
        return json.dumps(data, ensure_ascii=False)
    except TypeError:
        return ""


def _content_type(data: object) -> str:
    if isinstance(data, str):
        stripped = data.lstrip().casefold()
        if stripped.startswith("<!doctype") or stripped.startswith("<html"):
            return "text/html"
        return "text"
    if isinstance(data, (bytes, bytearray)):
        return "bytes"
    if isinstance(data, (dict, list)):
        return "application/json"
    return "unavailable"


def _sanitized_error(message: str | None) -> str | None:
    if message is None:
        return None
    if not isinstance(message, str):
        return type(message).__name__
    redacted = _BEARER_PATTERN.sub("[redacted]", message)
    redacted = _EMAIL_PATTERN.sub("[redacted]", redacted)
    compact = " ".join(redacted.split())
    if not compact:
        return None
    return compact[:120]


def summarize_result(result: object) -> SanitizedUnlockerSummary:
    """Extract a secret-free summary from one SDK result object."""

    success = bool(getattr(result, "success", False))
    status = getattr(result, "status", None)
    data = getattr(result, "data", None)
    html_char_size = getattr(result, "html_char_size", None)
    text = _content_text(data)
    content_bytes = html_char_size if isinstance(html_char_size, int) else len(text.encode("utf-8"))
    page_kind = classify_page_content(text)
    error = _sanitized_error(getattr(result, "error", None))
    return SanitizedUnlockerSummary(
        success=success,
        result_type=type(result).__name__,
        status="unavailable" if status is None else str(status),
        content_bytes=content_bytes,
        content_type=_content_type(data),
        page_kind=page_kind,
        error=error,
    )


def _outcome_for_summary(summary: SanitizedUnlockerSummary) -> SpikeOutcome:
    if not summary.success and summary.content_bytes == 0:
        return SpikeOutcome.REQUEST_ERROR
    if summary.page_kind is PageKind.MARKETPLACE_CONTENT:
        return SpikeOutcome.MARKETPLACE_CONTENT
    if summary.page_kind is PageKind.LOGIN_PAGE:
        return SpikeOutcome.LOGIN_PAGE
    return SpikeOutcome.UNKNOWN


def build_parser() -> argparse.ArgumentParser:
    """Build the isolated Web Unlocker spike argument parser."""

    parser = argparse.ArgumentParser(
        prog="brightdata_web_unlocker_spike.py",
        description="Experimentally open one already-discovered Facebook Marketplace URL.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Send one real Web Unlocker request, which may consume Bright Data credits.",
    )
    return parser


def _print_dry_run(configuration: SpikeConfiguration) -> None:
    token_status = "CONFIGURED" if configuration.api_token_configured else "MISSING"
    print("Mode: DRY RUN")
    print(f"URL: {TARGET_URL}")
    print(f"Token: {token_status}")
    print("Request sent: NO")


def _print_execute_summary(
    configuration: SpikeConfiguration,
    *,
    request_sent: bool,
    summary: SanitizedUnlockerSummary | None,
    outcome: SpikeOutcome,
    error: str | None,
) -> None:
    token_status = "CONFIGURED" if configuration.api_token_configured else "MISSING"
    print("Mode: EXECUTE")
    print(f"URL: {TARGET_URL}")
    print(f"Token: {token_status}")
    print(f"Request sent: {'YES' if request_sent else 'NO'}")
    if summary is not None:
        print(f"success: {str(summary.success).lower()}")
        print(f"result_type: {summary.result_type}")
        print(f"status: {summary.status}")
        print(f"content_bytes: {summary.content_bytes}")
        print(f"content_type: {summary.content_type}")
        print(f"page_kind: {summary.page_kind.value}")
        if summary.error is not None:
            print(f"error: {summary.error}")
    if error is not None:
        print(f"error: {error}")
    print(f"RESULT = {outcome.value}")


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    scrape: ScrapeOnce = scrape_once,
) -> int:
    """Run the isolated Web Unlocker spike."""

    parser = build_parser()
    namespace = parser.parse_args(argv)
    configuration = SpikeConfiguration.from_env(environ)

    if not namespace.execute:
        _print_dry_run(configuration)
        return SpikeExitCode.SUCCESS

    if not configuration.api_token_configured:
        _print_execute_summary(
            configuration,
            request_sent=False,
            summary=None,
            outcome=SpikeOutcome.REQUEST_ERROR,
            error=f"{TOKEN_ENV} is required with --execute",
        )
        return SpikeExitCode.CONFIGURATION_ERROR

    try:
        result = scrape(
            configuration.require_api_token(), TARGET_URL, configuration.timeout_seconds
        )
        summary = summarize_result(result)
        outcome = _outcome_for_summary(summary)
        _print_execute_summary(
            configuration,
            request_sent=True,
            summary=summary,
            outcome=outcome,
            error=None,
        )
        if outcome is SpikeOutcome.REQUEST_ERROR:
            return SpikeExitCode.REQUEST_ERROR
        return SpikeExitCode.SUCCESS
    except UnlockerRequestError as error:
        _print_execute_summary(
            configuration,
            request_sent=True,
            summary=None,
            outcome=SpikeOutcome.REQUEST_ERROR,
            error=_sanitized_error(str(error)),
        )
        return SpikeExitCode.REQUEST_ERROR


if __name__ == "__main__":
    sys.exit(main())
