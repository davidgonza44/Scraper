# mypy: disable-error-code="no-untyped-def"
"""Static contracts for Windows fnm/Node 24 developer scripts."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8-sig")


def _invokes_taskkill(text: str) -> bool:
    for line in text.splitlines():
        code = line.split("#", 1)[0].strip()
        if not code or code.lower().startswith("write-host"):
            continue
        if "taskkill" in code.lower():
            return True
    return False


def test_node_pin_files_remain_24() -> None:
    assert (ROOT / ".node-version").read_text(encoding="utf-8").strip() == "24"
    assert (ROOT / ".nvmrc").read_text(encoding="utf-8").strip() == "24"


def test_node_pin_files_are_tracked() -> None:
    listed = subprocess.run(
        ["git", "ls-files", ".node-version", ".nvmrc"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    files = set(listed.stdout.split())
    assert files == {".node-version", ".nvmrc"}
    for pin in (".node-version", ".nvmrc"):
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", pin],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert ignored.returncode == 1, pin


def test_web_and_node_modules_are_gitignored() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    lines = {line.strip() for line in gitignore.splitlines()}
    assert ".web" in lines
    assert "node_modules/" in lines
    web_ignored = subprocess.run(
        ["git", "check-ignore", "-q", ".web"],
        cwd=ROOT,
        check=False,
    )
    assert web_ignored.returncode == 0
    modules_ignored = subprocess.run(
        ["git", "check-ignore", "-q", "node_modules/pkg"],
        cwd=ROOT,
        check=False,
    )
    assert modules_ignored.returncode == 0


def test_no_generated_node_modules_are_committed() -> None:
    listed = subprocess.run(
        ["git", "ls-files", "--", "node_modules", "*/node_modules/*", ".web"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert listed.stdout.strip() == ""


def test_dev_ps1_daily_start_contract() -> None:
    text = _read("dev.ps1")
    lower = text.lower()
    assert "$PSScriptRoot" in text
    assert "Get-Command fnm" in text
    assert "winget install Schniz.fnm" in text
    assert "fnm env --shell powershell" in text
    assert ".node-version" in text
    assert ".nvmrc" in text
    assert "fnm install" in text
    assert "fnm use" in text
    assert "node -v" in text
    assert "$env:PYTHONPATH =" in text
    assert "REFLEX_USE_NPM" in text
    assert r".venv\Scripts\python.exe" in text
    assert "-m reflex run" in text
    assert not _invokes_taskkill(text)
    assert "git pull" not in lower
    assert "remove-item" not in lower
    assert "reset-frontend.ps1" in text
    assert "no se instala fnm automaticamente" in lower


def test_dev_ps1_does_not_delete_web_on_normal_start() -> None:
    text = _read("dev.ps1")
    assert "Remove-Item" not in text
    assert "reset-frontend.ps1" in text


def test_reset_frontend_ps1_is_exceptional_and_targeted() -> None:
    text = _read("reset-frontend.ps1")
    lower = text.lower()
    assert "$PSScriptRoot" in text
    assert r".web" in text
    assert "Remove-Item" in text
    assert not _invokes_taskkill(text)
    assert "dev.ps1" in text
    assert "Get-CimInstance" in text or "Win32_Process" in text
    assert "reconstru" in lower


def test_dev_ps1_does_not_invoke_reset_frontend() -> None:
    text = _read("dev.ps1")
    mentions = [line.strip() for line in text.splitlines() if "reset-frontend.ps1" in line]
    assert mentions
    for line in mentions:
        assert line.startswith("Write-Host") or line.startswith("#")
        assert not line.startswith("&")


def test_powershell_scripts_have_balanced_braces() -> None:
    for name in ("dev.ps1", "reset-frontend.ps1"):
        text = _read(name)
        assert text.count("{") == text.count("}"), name


def test_readme_documents_windows_fnm_workflow() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    collapsed = " ".join(readme.split())
    assert "## Development on Windows" in readme
    assert "winget install Schniz.fnm" in readme
    assert "fnm install 24" in readme
    assert r".\dev.ps1" in readme
    assert r".\reset-frontend.ps1" in readme
    assert "--use-on-cd" in readme
    assert "$PROFILE" in readme
    assert "REFLEX_USE_NPM" in readme
    assert "no requiere reemplazar" in collapsed.lower()
    assert "Remove-Item -LiteralPath .web" not in readme
