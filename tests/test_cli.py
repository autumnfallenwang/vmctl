"""Fast tests for CLI wiring (pre-network error paths only)."""

from __future__ import annotations

from pathlib import Path

import pytest

from vmctl.cli import build_parser, main


def test_no_command_prints_help() -> None:
    assert main([]) == 0


def test_no_output_flag_anywhere() -> None:
    """ADR 0007: NDJSON is the only output, so there is nothing to choose between."""
    parser = build_parser()
    for argv in (["tail", "p"], ["search", "p", "--filter", "{}"], ["discover", "p"]):
        assert not hasattr(parser.parse_args(argv), "output")
    with pytest.raises(SystemExit):
        parser.parse_args(["tail", "p", "--output", "human"])


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


FILTER = '{"term": {"a": "1"}}'


def test_search_bad_config_path_returns_1(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["search", "test_ig", "--filter", FILTER, "--config", "/no/such/file.yml"]) == 1
    assert "config error" in capsys.readouterr().err


def test_search_reports_bad_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["search", "p", "--filter", "{not json", "--config", _config(tmp_path)]) == 1
    assert "query error" in capsys.readouterr().err


def test_search_reports_unsupported_construct(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unsupported clause must fail loudly, never match everything silently."""
    args = [
        "search", "p",
        "--filter", '{"match": {"message": "boom"}}',
        "--config", _config(tmp_path),
    ]
    assert main(args) == 1
    err = capsys.readouterr().err
    assert "query error" in err and "analyzer" in err


def test_search_filter_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "f.json"
    bad.write_text('{"size": 10, "query": {"match_all": {}}}')
    args = ["search", "p", "--filter-file", str(bad), "--config", _config(tmp_path)]
    assert main(args) == 1
    assert "size" in capsys.readouterr().err


def test_search_rejects_both_filter_sources(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = [
        "search", "p",
        "--filter", FILTER,
        "--filter-file", "/tmp/x.json",
        "--config", _config(tmp_path),
    ]
    assert main(args) == 1
    assert "not both" in capsys.readouterr().err
