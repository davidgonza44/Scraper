"""Offline coverage for the isolated Bright Data Web Unlocker spike."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from tools.brightdata_web_unlocker_spike import (
    TARGET_URL,
    TOKEN_ENV,
    PageKind,
    SpikeExitCode,
    SpikeOutcome,
    classify_page_content,
    main,
)

TOKEN = "SPIKE_UNLOCKER_PREFIX-never-print-SPIKE_UNLOCKER_SUFFIX"


@dataclass(slots=True)
class FakeUnlockerResult:
    success: bool = True
    status: str = "ready"
    data: object = "<html><body>Facebook Marketplace listing</body></html>"
    error: str | None = None
    html_char_size: int | None = None


def test_dry_run_is_default_and_makes_zero_requests(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[str, str, int]] = []

    def forbidden_scrape(token: str, url: str, timeout_seconds: int) -> object:
        calls.append((token, url, timeout_seconds))
        raise AssertionError("dry-run must not call Web Unlocker")

    exit_code = main([], environ={}, scrape=forbidden_scrape)

    captured = capsys.readouterr()
    assert exit_code == SpikeExitCode.SUCCESS
    assert calls == []
    assert captured.out.splitlines() == [
        "Mode: DRY RUN",
        f"URL: {TARGET_URL}",
        "Token: MISSING",
        "Request sent: NO",
    ]
    assert captured.err == ""


def test_execute_without_token_does_not_send_a_request(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[str, str, int]] = []

    def forbidden_scrape(token: str, url: str, timeout_seconds: int) -> object:
        calls.append((token, url, timeout_seconds))
        raise AssertionError("missing token must not call Web Unlocker")

    exit_code = main(["--execute"], environ={}, scrape=forbidden_scrape)

    captured = capsys.readouterr()
    assert exit_code == SpikeExitCode.CONFIGURATION_ERROR
    assert calls == []
    assert "Token: MISSING" in captured.out
    assert "Request sent: NO" in captured.out
    assert f"RESULT = {SpikeOutcome.REQUEST_ERROR.value}" in captured.out


def test_classify_page_content_marketplace_content() -> None:
    assert (
        classify_page_content("Facebook Marketplace item available in Valencia")
        is PageKind.MARKETPLACE_CONTENT
    )


def test_classify_page_content_login_page() -> None:
    assert classify_page_content("Please log in to continue") is PageKind.LOGIN_PAGE
    assert classify_page_content("Iniciar sesión para continuar") is PageKind.LOGIN_PAGE


def test_classify_page_content_unknown() -> None:
    assert classify_page_content("access denied by upstream") is PageKind.UNKNOWN


def test_execute_summary_does_not_print_token_or_payload(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[str, str, int]] = []

    def fake_scrape(token: str, url: str, timeout_seconds: int) -> object:
        calls.append((token, url, timeout_seconds))
        return FakeUnlockerResult(
            data=(
                "<html><body>Facebook Marketplace listing contact sales@example.test</body></html>"
            )
        )

    exit_code = main(
        ["--execute"],
        environ={TOKEN_ENV: TOKEN},
        scrape=fake_scrape,
    )

    captured = capsys.readouterr()
    assert exit_code == SpikeExitCode.SUCCESS
    assert len(calls) == 1
    assert calls[0][0] == TOKEN
    assert calls[0][1] == TARGET_URL
    assert "Token: CONFIGURED" in captured.out
    assert "Request sent: YES" in captured.out
    assert f"RESULT = {SpikeOutcome.MARKETPLACE_CONTENT.value}" in captured.out
    assert TOKEN not in captured.out
    assert TOKEN not in captured.err
    assert "sales@example.test" not in captured.out
    assert "<html>" not in captured.out
    assert "contact" not in captured.out
