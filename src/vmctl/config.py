"""Profile configuration: the YAML source-definition model and its loader.

Mirrors the Logstash file-input model in YAML (see docs/adr/0003): a config holds
named **profiles**; each profile has **hosts** and a list of **inputs** (file
sources) plus optional **filters**. Parsing only — filters are stored but not yet
acted on (extraction lands in later milestones).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CODEC_NAMES = ("plain", "json", "multiline")
START_POSITIONS = ("beginning", "end")
MODES = ("tail", "read")
MULTILINE_WHAT = ("previous", "next")


class ConfigError(Exception):
    """Raised when a profile config is malformed. Message names the offending spot."""


@dataclass
class Codec:
    """How a file's bytes are split into events (and whether parsed)."""

    name: str = "plain"
    delimiter: str = "\n"
    # multiline only:
    pattern: str | None = None
    negate: bool = False
    what: str = "previous"
    max_lines: int | None = None


@dataclass
class Input:
    """One Logstash-style file input: which files, how to read/frame, how to label."""

    type: str
    path: list[str]
    exclude: list[str] = field(default_factory=list)
    start_position: str = "end"
    mode: str = "tail"
    codec: Codec = field(default_factory=Codec)
    tags: list[str] = field(default_factory=list)


@dataclass
class Filter:
    """A Logstash-style filter. Parsed and stored; not applied yet (later milestones)."""

    condition: str | None = None
    grok: dict[str, Any] | None = None


@dataclass
class Host:
    """A host to collect from. An optional inline password takes highest priority;
    if omitted, the password is sourced at run time (env / prompt). A config file
    that sets passwords holds secrets and should be gitignored."""

    host: str
    user: str
    password: str | None = None


@dataclass
class Profile:
    name: str
    hosts: list[Host]
    inputs: list[Input]
    base_dir: str | None = None
    filters: list[Filter] = field(default_factory=list)


@dataclass
class Config:
    profiles: dict[str, Profile]


def default_config_path() -> Path:
    """Where vmctl looks for its config when ``--config`` is not given."""
    return Path("vmctl.yml")


def load_config(path: str | Path) -> Config:
    """Load and validate a profile config file. Raises ConfigError on any problem."""
    p = Path(path)
    try:
        raw = yaml.safe_load(p.read_text())
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {p}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {p}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"{p}: top level must be a mapping with a 'profiles:' key")
    profiles_raw = _require(raw, "profiles", dict, "top level")
    profiles = {
        name: _parse_profile(name, _as_mapping(spec, f"profile '{name}'"))
        for name, spec in profiles_raw.items()
    }
    if not profiles:
        raise ConfigError(f"{p}: no profiles defined")
    return Config(profiles=profiles)


def _parse_profile(name: str, spec: dict[str, Any]) -> Profile:
    where = f"profile '{name}'"
    hosts_raw = _require(spec, "hosts", list, where)
    inputs_raw = _require(spec, "inputs", list, where)
    hosts = [_parse_host(name, h) for h in hosts_raw]
    inputs = [_parse_input(name, i) for i in inputs_raw]
    filters = [_parse_filter(name, f) for f in spec.get("filters", [])]
    base_dir = spec.get("base_dir")
    if base_dir is not None and not isinstance(base_dir, str):
        raise ConfigError(f"{where}: base_dir must be a string")
    return Profile(name=name, hosts=hosts, inputs=inputs, base_dir=base_dir, filters=filters)


def _parse_host(profile: str, spec: Any) -> Host:
    m = _as_mapping(spec, f"profile '{profile}' host")
    host = _require(m, "host", str, f"profile '{profile}' host")
    user = _require(m, "user", str, f"host '{host}'")
    password = m.get("password")
    if password is not None and not isinstance(password, str):
        raise ConfigError(f"host '{host}': password must be a string")
    return Host(host=host, user=user, password=password)


def _parse_input(profile: str, spec: Any) -> Input:
    m = _as_mapping(spec, f"profile '{profile}' input")
    itype = _require(m, "type", str, f"profile '{profile}' input")
    where = f"profile '{profile}' input '{itype}'"
    path = _string_list(_require(m, "path", (str, list), where), "path", where)
    if not path:
        raise ConfigError(f"{where}: 'path' must list at least one glob")
    exclude = _string_list(m.get("exclude", []), "exclude", where)
    start_position = _enum(m.get("start_position", "end"), START_POSITIONS, "start_position", where)
    mode = _enum(m.get("mode", "tail"), MODES, "mode", where)
    tags = _string_list(m.get("tags", []), "tags", where)
    codec = _parse_codec(m.get("codec", "plain"), where)
    return Input(
        type=itype,
        path=path,
        exclude=exclude,
        start_position=start_position,
        mode=mode,
        codec=codec,
        tags=tags,
    )


def _parse_codec(spec: Any, where: str) -> Codec:
    # String form: `codec: json`. Mapping form: `codec: {multiline: {pattern: ...}}`.
    if isinstance(spec, str):
        name = _enum(spec, CODEC_NAMES, "codec", where)
        return Codec(name=name)
    if isinstance(spec, dict):
        if len(spec) != 1:
            raise ConfigError(f"{where}: codec mapping must have exactly one key ({CODEC_NAMES})")
        name, opts = next(iter(spec.items()))
        name = _enum(name, CODEC_NAMES, "codec", where)
        opts = _as_mapping(opts if opts is not None else {}, f"{where} codec '{name}'")
        codec = Codec(name=name)
        if "delimiter" in opts:
            codec.delimiter = _require(opts, "delimiter", str, f"{where} codec")
        if name == "multiline":
            codec.pattern = _require(opts, "pattern", str, f"{where} multiline codec")
            codec.negate = bool(opts.get("negate", False))
            codec.what = _enum(opts.get("what", "previous"), MULTILINE_WHAT, "what", where)
            if "max_lines" in opts:
                codec.max_lines = _int(opts["max_lines"], "max_lines", where)
        return codec
    raise ConfigError(f"{where}: codec must be a string or a mapping, got {type(spec).__name__}")


def _parse_filter(profile: str, spec: Any) -> Filter:
    m = _as_mapping(spec, f"profile '{profile}' filter")
    condition = m.get("if")
    if condition is not None and not isinstance(condition, str):
        raise ConfigError(f"profile '{profile}' filter: 'if' must be a string")
    grok = m.get("grok")
    if grok is not None and not isinstance(grok, dict):
        raise ConfigError(f"profile '{profile}' filter: 'grok' must be a mapping")
    return Filter(condition=condition, grok=grok)


# --- small validation helpers -------------------------------------------------


def _require(m: dict[str, Any], key: str, typ: type | tuple[type, ...], where: str) -> Any:
    if key not in m:
        raise ConfigError(f"{where}: missing required key '{key}'")
    val = m[key]
    if not isinstance(val, typ):
        want = typ.__name__ if isinstance(typ, type) else " or ".join(t.__name__ for t in typ)
        raise ConfigError(f"{where}: '{key}' must be {want}, got {type(val).__name__}")
    return val


def _as_mapping(spec: Any, where: str) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise ConfigError(f"{where}: expected a mapping, got {type(spec).__name__}")
    return spec


def _string_list(val: Any, key: str, where: str) -> list[str]:
    if isinstance(val, str):
        return [val]
    if isinstance(val, list) and all(isinstance(x, str) for x in val):
        return list(val)
    raise ConfigError(f"{where}: '{key}' must be a string or list of strings")


def _enum(val: Any, allowed: tuple[str, ...], key: str, where: str) -> str:
    if val not in allowed:
        raise ConfigError(f"{where}: '{key}' must be one of {allowed}, got {val!r}")
    return val


def _int(val: Any, key: str, where: str) -> int:
    if not isinstance(val, int) or isinstance(val, bool):
        raise ConfigError(f"{where}: '{key}' must be an integer")
    return val
