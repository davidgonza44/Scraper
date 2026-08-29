"""Regressions for Cursor Cloud GitNexus install/start scripts.

These tests stay offline: they never invoke npm or a real GitNexus CLI.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTALL_SCRIPT = ROOT / ".cursor" / "install-gitnexus.sh"
START_SCRIPT = ROOT / ".cursor" / "start-gitnexus.sh"
ENVIRONMENT_JSON = ROOT / ".cursor" / "environment.json"


def _run(
    args: list[str],
    cwd: Path,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=dict(env) if env is not None else None,
        check=False,
        capture_output=True,
        text=True,
    )


def _git(repo: Path, *args: str, env: Mapping[str, str] | None = None) -> str:
    result = _run(["git", *args], cwd=repo, env=env)
    assert result.returncode == 0, f"git {' '.join(args)}\n{result.stderr}\n{result.stdout}"
    return result.stdout.strip()


def _init_git_repo(repo: Path) -> str:
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "cloud-scripts@test.local")
    _git(repo, "config", "user.name", "Cloud Scripts Test")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "README").write_text("cloud-scripts\n", encoding="utf-8")
    _git(repo, "add", "README")
    _git(repo, "commit", "-q", "-m", "init")
    return _git(repo, "rev-parse", "HEAD")


def _write_executable(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _fake_nvm_home(home: Path, node_bin: Path) -> Path:
    nvm_dir = home / ".nvm"
    nvm_dir.mkdir(parents=True)
    (nvm_dir / "nvm.sh").write_text(
        "\n".join(
            [
                "nvm() {",
                '    case "$1" in',
                "        use) return 0 ;;",
                f'        which) printf "%s\\n" "{node_bin}" ;;',
                "        *) return 0 ;;",
                "    esac",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return nvm_dir


def _start_env(home: Path, launcher: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["NVM_DIR"] = str(home / ".nvm")
    env["GITNEXUS_SYSTEM_LAUNCHER"] = str(launcher)
    return env


def _prepare_start_repo(tmp_path: Path) -> tuple[Path, str, dict[str, str]]:
    repo = tmp_path / "repo"
    cursor_dir = repo / ".cursor"
    cursor_dir.mkdir(parents=True)
    shutil.copy2(START_SCRIPT, cursor_dir / "start-gitnexus.sh")
    (repo / ".nvmrc").write_text("24\n", encoding="utf-8")
    head = _init_git_repo(repo)

    home = tmp_path / "home"
    home.mkdir()
    node_bin = _write_executable(home / "bin" / "node", "#!/bin/sh\necho v24.0.0\n")
    _fake_nvm_home(home, node_bin)
    launcher = _write_executable(
        home / "bin" / "gitnexus",
        "\n".join(
            [
                "#!/bin/sh",
                'if [ "$1" = "--version" ]; then',
                "    echo 1.6.10",
                "    exit 0",
                "fi",
                "exit 0",
                "",
            ]
        ),
    )
    return repo, head, _start_env(home, launcher)


def _write_meta(repo: Path, body: str) -> Path:
    meta_dir = repo / ".gitnexus"
    meta_dir.mkdir(parents=True)
    meta = meta_dir / "gitnexus.json"
    meta.write_text(body, encoding="utf-8")
    return meta_dir


def _run_start(repo: Path, env: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
    return _run(["bash", str(repo / ".cursor" / "start-gitnexus.sh")], cwd=repo, env=env)


def test_environment_json_keeps_cloud_install_and_start_hooks() -> None:
    text = ENVIRONMENT_JSON.read_text(encoding="utf-8")
    assert '"install": "bash .cursor/install.sh && bash .cursor/install-gitnexus.sh"' in text
    assert '"start": "bash .cursor/start-gitnexus.sh"' in text
    assert '".venv/bin/reflex run"' in text
    assert '"port": 3000' in text
    assert '"port": 8000' in text


def test_scripts_remain_pinned_to_gitnexus_1_6_10() -> None:
    install = INSTALL_SCRIPT.read_text(encoding="utf-8")
    start = START_SCRIPT.read_text(encoding="utf-8")
    assert 'GITNEXUS_VERSION="1.6.10"' in install
    assert 'GITNEXUS_VERSION="1.6.10"' in start
    assert "npx" not in install
    assert "npx" not in start


def test_install_keeps_nvm_path_and_launcher_overwrite_guards() -> None:
    text = INSTALL_SCRIPT.read_text(encoding="utf-8")
    assert 'export PATH="$(dirname "${NODE_BIN}"):${PATH}"' in text
    assert "hash -r" in text
    assert 'rm -f "${USER_LAUNCHER}"' in text
    assert "writing the launcher overwrote" in text
    assert "CLI entrypoint looks like a shell launcher" in text


def test_start_keeps_set_euo_pipefail() -> None:
    text = START_SCRIPT.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
    assert "set +euo pipefail" not in text
    assert "set +euo" not in text


def test_install_does_not_pass_unsupported_npm_option() -> None:
    text = INSTALL_SCRIPT.read_text(encoding="utf-8")
    assert "--dangerously-allow-all-scripts" not in text
    assert "ignore-scripts" not in text
    assert '"${NPM_BIN}" install -g --prefix "${NPM_GLOBAL}"' in text
    assert '"gitnexus@${GITNEXUS_VERSION}"' in text


def test_install_uses_git_plumbing_for_worktrees() -> None:
    text = INSTALL_SCRIPT.read_text(encoding="utf-8")
    assert "git rev-parse --is-inside-work-tree" in text
    assert "git rev-parse --git-path info/exclude" in text
    assert "[[ ! -d .git ]]" not in text
    assert "[[ -d .git ]]" not in text
    assert 'exclude_file=".git/info/exclude"' not in text
    assert 'EXCLUDE_FILE=".git/info/exclude"' not in text
    assert "GIT_DIR" not in text
    assert "GIT_COMMON_DIR" not in text


def test_malformed_metadata_discards_index_and_exits_0(tmp_path: Path) -> None:
    repo, _head, env = _prepare_start_repo(tmp_path)
    _write_meta(repo, '{"lastCommit": "abc"')
    result = _run_start(repo, env)
    assert result.returncode == 0, result.stderr + result.stdout
    assert not (repo / ".gitnexus").exists()
    assert "removing .gitnexus" in result.stdout


def test_truncated_json_metadata_discards_index_and_exits_0(tmp_path: Path) -> None:
    repo, _head, env = _prepare_start_repo(tmp_path)
    _write_meta(repo, "{")
    result = _run_start(repo, env)
    assert result.returncode == 0, result.stderr + result.stdout
    assert not (repo / ".gitnexus").exists()


def test_non_object_metadata_discards_index_and_exits_0(tmp_path: Path) -> None:
    repo, _head, env = _prepare_start_repo(tmp_path)
    _write_meta(repo, '["not-an-object"]\n')
    result = _run_start(repo, env)
    assert result.returncode == 0, result.stderr + result.stdout
    assert not (repo / ".gitnexus").exists()


def test_string_metadata_discards_index_and_exits_0(tmp_path: Path) -> None:
    repo, _head, env = _prepare_start_repo(tmp_path)
    _write_meta(repo, '"abc123"\n')
    result = _run_start(repo, env)
    assert result.returncode == 0, result.stderr + result.stdout
    assert not (repo / ".gitnexus").exists()


def test_missing_last_commit_discards_index_and_exits_0(tmp_path: Path) -> None:
    repo, _head, env = _prepare_start_repo(tmp_path)
    _write_meta(repo, '{"other": true}\n')
    result = _run_start(repo, env)
    assert result.returncode == 0, result.stderr + result.stdout
    assert not (repo / ".gitnexus").exists()


def test_null_last_commit_discards_index_and_exits_0(tmp_path: Path) -> None:
    repo, _head, env = _prepare_start_repo(tmp_path)
    _write_meta(repo, '{"lastCommit": null}\n')
    result = _run_start(repo, env)
    assert result.returncode == 0, result.stderr + result.stdout
    assert not (repo / ".gitnexus").exists()


def test_wrong_head_metadata_discards_index_and_exits_0(tmp_path: Path) -> None:
    repo, _head, env = _prepare_start_repo(tmp_path)
    _write_meta(repo, '{"lastCommit": "deadbeef"}\n')
    result = _run_start(repo, env)
    assert result.returncode == 0, result.stderr + result.stdout
    assert not (repo / ".gitnexus").exists()


def test_unreadable_metadata_discards_index_and_exits_0(tmp_path: Path) -> None:
    repo, _head, env = _prepare_start_repo(tmp_path)
    meta_dir = _write_meta(repo, '{"lastCommit": "abc"}\n')
    meta = meta_dir / "gitnexus.json"
    meta.chmod(0)
    try:
        result = _run_start(repo, env)
    finally:
        if meta.exists():
            meta.chmod(0o644)
    assert result.returncode == 0, result.stderr + result.stdout
    assert not (repo / ".gitnexus").exists()


def test_valid_metadata_matching_head_is_retained(tmp_path: Path) -> None:
    repo, head, env = _prepare_start_repo(tmp_path)
    _write_meta(repo, json.dumps({"lastCommit": head}) + "\n")
    result = _run_start(repo, env)
    assert result.returncode == 0, result.stderr + result.stdout
    assert (repo / ".gitnexus" / "gitnexus.json").is_file()
    assert "index lastCommit matches HEAD" in result.stdout
    assert "removing .gitnexus" not in result.stdout


def test_linked_worktree_is_accepted_and_excludes_gitnexus(tmp_path: Path) -> None:
    main = tmp_path / "main"
    cursor_dir = main / ".cursor"
    cursor_dir.mkdir(parents=True)
    shutil.copy2(INSTALL_SCRIPT, cursor_dir / "install-gitnexus.sh")
    (main / ".nvmrc").write_text("24\n", encoding="utf-8")
    _init_git_repo(main)
    _git(main, "add", ".cursor/install-gitnexus.sh", ".nvmrc")
    _git(main, "commit", "-q", "-m", "scripts")

    linked = tmp_path / "linked"
    _git(main, "worktree", "add", "--detach", str(linked))
    try:
        gitfile = linked / ".git"
        assert gitfile.is_file(), "linked worktree must use a gitfile, not a directory"
        assert not gitfile.is_dir()

        env = os.environ.copy()
        env["GITNEXUS_CLOUD_PHASE"] = "ensure-exclude"
        result = _run(
            ["bash", str(linked / ".cursor" / "install-gitnexus.sh")],
            cwd=linked,
            env=env,
        )
        assert result.returncode == 0, result.stderr + result.stdout

        exclude_raw = _git(linked, "rev-parse", "--git-path", "info/exclude")
        exclude = Path(exclude_raw)
        if not exclude.is_absolute():
            exclude = linked / exclude
        assert exclude.is_file()
        lines = [
            line
            for line in exclude.read_text(encoding="utf-8").splitlines()
            if line == ".gitnexus/"
        ]
        assert lines == [".gitnexus/"]

        second = _run(
            ["bash", str(linked / ".cursor" / "install-gitnexus.sh")],
            cwd=linked,
            env=env,
        )
        assert second.returncode == 0, second.stderr + second.stdout
        lines_again = [
            line
            for line in exclude.read_text(encoding="utf-8").splitlines()
            if line == ".gitnexus/"
        ]
        assert lines_again == [".gitnexus/"]
    finally:
        _git(main, "worktree", "remove", "--force", str(linked))


def test_main_worktree_exclude_uses_git_path(tmp_path: Path) -> None:
    repo = tmp_path / "main"
    cursor_dir = repo / ".cursor"
    cursor_dir.mkdir(parents=True)
    shutil.copy2(INSTALL_SCRIPT, cursor_dir / "install-gitnexus.sh")
    (repo / ".nvmrc").write_text("24\n", encoding="utf-8")
    _init_git_repo(repo)

    env = os.environ.copy()
    env["GITNEXUS_CLOUD_PHASE"] = "ensure-exclude"
    result = _run(["bash", str(repo / ".cursor" / "install-gitnexus.sh")], cwd=repo, env=env)
    assert result.returncode == 0, result.stderr + result.stdout
    exclude_raw = _git(repo, "rev-parse", "--git-path", "info/exclude")
    exclude = Path(exclude_raw)
    if not exclude.is_absolute():
        exclude = repo / exclude
    assert ".gitnexus/" in exclude.read_text(encoding="utf-8").splitlines()
