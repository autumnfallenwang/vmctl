"""Unit tests for the profile config loader (M02-A). No network."""

from __future__ import annotations

from pathlib import Path

import pytest

from vmctl.config import ConfigError, load_config

EXAMPLE = Path(__file__).resolve().parents[1] / "testenv" / "infra" / "vmctl.example.yml"


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "cfg.yml"
    p.write_text(text)
    return p


def test_load_example_profile() -> None:
    cfg = load_config(EXAMPLE)
    prof = cfg.profiles["test_ig"]
    assert prof.base_dir == "/opt/ig-instance/logs"
    assert [h.host for h in prof.hosts] == ["192.168.77.11", "192.168.77.12"]
    assert all(h.user == "vmctl" for h in prof.hosts)
    types = [i.type for i in prof.inputs]
    assert types == ["ig-system", "ig-route", "ig-audit"]
    # audit uses the json codec; route uses multiline with the timestamp anchor.
    audit = next(i for i in prof.inputs if i.type == "ig-audit")
    assert audit.codec.name == "json"
    route = next(i for i in prof.inputs if i.type == "ig-route")
    assert route.codec.name == "multiline"
    assert route.codec.pattern == r"^\d{4}-\d{2}-\d{2}T"
    assert route.codec.negate is True
    assert route.exclude == ["route-system*"]


def test_codec_string_and_mapping_forms(tmp_path: Path) -> None:
    cfg = load_config(
        _write(
            tmp_path,
            """
            profiles:
              p:
                hosts: [{host: h1, user: u}]
                inputs:
                  - {type: a, path: "a.log", codec: json}
                  - {type: b, path: ["b.log"]}   # default codec = plain
                  - type: c
                    path: "c.log"
                    codec: {multiline: {pattern: '^X', negate: true, what: next}}
            """,
        )
    )
    inputs = {i.type: i for i in cfg.profiles["p"].inputs}
    assert inputs["a"].codec.name == "json"
    assert inputs["b"].codec.name == "plain" and inputs["b"].codec.delimiter == "\n"
    assert inputs["b"].path == ["b.log"]  # string coerced to a one-item list
    assert inputs["c"].codec.name == "multiline"
    assert inputs["c"].codec.what == "next"
    assert inputs["c"].codec.pattern == "^X"


def test_timestamp_spec_forms(tmp_path: Path) -> None:
    cfg = load_config(
        _write(
            tmp_path,
            """
            profiles:
              p:
                hosts: [{host: h1, user: u}]
                inputs:
                  - {type: a, path: "a.json", codec: json, timestamp: {field: eventTime}}
                  - type: b
                    path: "b.log"
                    timestamp: {pattern: '\\[([^\\]]+)\\]', format: '%d/%b/%Y:%H:%M:%S %z'}
                  - {type: c, path: "c.log"}   # no timestamp block -> default
            """,
        )
    )
    inputs = {i.type: i for i in cfg.profiles["p"].inputs}
    assert inputs["a"].timestamp.field == "eventTime"
    assert inputs["b"].timestamp.pattern and inputs["b"].timestamp.format == "%d/%b/%Y:%H:%M:%S %z"
    assert inputs["c"].timestamp.field is None and inputs["c"].timestamp.pattern is None


def test_timestamp_spec_conflicting_forms_raise(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        profiles:
          p:
            hosts: [{host: h1, user: u}]
            inputs:
              - {type: a, path: "a.log", timestamp: {field: t, pattern: 'x', format: 'y'}}
        """,
    )
    with pytest.raises(ConfigError, match="not both"):
        load_config(p)


def test_timestamp_spec_pattern_without_format_raises(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        profiles:
          p:
            hosts: [{host: h1, user: u}]
            inputs:
              - {type: a, path: "a.log", timestamp: {pattern: 'x'}}
        """,
    )
    with pytest.raises(ConfigError, match="together"):
        load_config(p)


def test_missing_path_raises(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        profiles:
          p:
            hosts: [{host: h1, user: u}]
            inputs:
              - {type: noPath}
        """,
    )
    with pytest.raises(ConfigError, match="path"):
        load_config(p)


def test_unknown_codec_raises(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        profiles:
          p:
            hosts: [{host: h1, user: u}]
            inputs:
              - {type: a, path: "a.log", codec: bogus}
        """,
    )
    with pytest.raises(ConfigError, match="codec"):
        load_config(p)


def test_bad_enum_raises(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        profiles:
          p:
            hosts: [{host: h1, user: u}]
            inputs:
              - {type: a, path: "a.log", mode: sideways}
        """,
    )
    with pytest.raises(ConfigError, match="mode"):
        load_config(p)


def test_host_password_optional(tmp_path: Path) -> None:
    cfg = load_config(
        _write(
            tmp_path,
            """
            profiles:
              p:
                hosts:
                  - {host: h1, user: u, password: s3cret}
                  - {host: h2, user: u}
                inputs:
                  - {type: t, path: "x"}
            """,
        )
    )
    hosts = cfg.profiles["p"].hosts
    assert hosts[0].password == "s3cret"
    assert hosts[1].password is None


def test_no_profiles_raises(tmp_path: Path) -> None:
    p = _write(tmp_path, "profiles: {}\n")
    with pytest.raises(ConfigError, match="no profiles"):
        load_config(p)
