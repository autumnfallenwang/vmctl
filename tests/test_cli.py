"""Fast tests for CLI wiring (pre-network error paths only)."""

from __future__ import annotations

from pathlib import Path

import pytest

from vmctl.cli import build_parser, main


def test_no_command_prints_help() -> None:
    assert main([]) == 0


def test_output_defaults_to_ndjson() -> None:
    """Piping is the common case, so the default must stay machine-readable."""
    parser = build_parser()
    assert parser.parse_args(["tail", "p"]).output == "ndjson"
    assert parser.parse_args(["search", "p", "-q", "a:1"]).output == "ndjson"
    assert parser.parse_args(["tail", "p", "--output", "human"]).output == "human"


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


def test_tail_requires_profile() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["tail"])
    assert exc.value.code == 2


def test_tail_bad_config_path_returns_1(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["tail", "test_ig", "--config", "/no/such/file.yml"]) == 1
    assert "config error" in capsys.readouterr().err


def _config(tmp_path: Path) -> str:
    cfg = tmp_path / "c.yml"
    cfg.write_text(
        "profiles:\n  p:\n    hosts: [{host: h, user: u, password: x}]\n"
        "    inputs:\n      - {type: t, path: 'x'}\n"
    )
    return str(cfg)


def test_search_requires_query() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["search", "test_ig"])  # -q is required
    assert exc.value.code == 2


def test_search_bad_config_path_returns_1(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["search", "test_ig", "-q", "a:1", "--config", "/no/such/file.yml"]) == 1
    assert "config error" in capsys.readouterr().err


def test_search_reports_bad_kql(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["search", "p", "-q", "a:", "--config", _config(tmp_path)]) == 1
    assert "query error" in capsys.readouterr().err


def test_search_reports_bad_time_bound(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["search", "p", "-q", "a:1", "--since", "yesterday", "--config", _config(tmp_path)]
    assert main(args) == 1
    assert "invalid time bound" in capsys.readouterr().err
