"""Fast tests for CLI wiring (pre-network error paths only)."""

from __future__ import annotations

from pathlib import Path

import pytest

from vmctl.cli import main


def test_no_command_prints_help() -> None:
    assert main([]) == 0


def test_discover_requires_profile() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["discover"])  # missing required positional
    assert exc.value.code == 2


def test_discover_bad_config_path_returns_1(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["discover", "test_ig", "--config", "/no/such/file.yml"]) == 1
    assert "config error" in capsys.readouterr().err


def test_discover_unknown_profile_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = tmp_path / "c.yml"
    cfg.write_text(
        "profiles:\n  p:\n    hosts: [{host: h, user: u}]\n    inputs:\n      - {type: t, path: 'x'}\n"
    )
    assert main(["discover", "zzz", "--config", str(cfg)]) == 1
    assert "unknown profile" in capsys.readouterr().err
