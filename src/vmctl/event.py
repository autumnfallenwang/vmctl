"""Build the ECS event around a framed log record (docs/adr/0004, docs/adr/0010).

``build_event`` adds the **put** fields — the collection metadata vmctl generates (host,
agent, file, timestamps, dataset, profile), unchanged and ECS-compatible — plus the raw
line. ``enrich`` is the **parse** step. ``assemble`` runs both.

Minimal-by-default parsing (ADR 0010): the **whole raw line is always in ``message``**
(parsed or not), and the **only** field parsed from the content by default is
``@timestamp`` (per-input configurable via ``TimestampSpec``). Nothing else is extracted
automatically — a ``json`` codec still merges its fields (opt-in by codec), and any label
like ``route_id`` comes only from a profile filter. A ``json`` line that fails to parse
keeps its raw ``message`` plus Logstash's ``_jsonparsefailure`` tag.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from vmctl import __version__
from vmctl.filters import apply_filters

if TYPE_CHECKING:
    from vmctl.codecs import Frame
    from vmctl.config import Filter, Input, TimestampSpec

ECS_VERSION = "8.11"

# Logstash's tag for a line the json codec could not parse (same string as its filter).
JSON_PARSE_FAILURE = "_jsonparsefailure"

# Envelope fields a merged JSON frame must never overwrite (incl. the raw `message`).
_RESERVED = {"@timestamp", "message", "host", "agent", "log", "ecs", "labels", "event", "tags"}
# A leading ISO-8601 timestamp at the start of a text line (comma or dot millis).
_LEADING_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[.,]\d+(?:Z|[+-]\d{2}:?\d{2})?)")


def build_event(
    frame: Frame,
    *,
    host: str,
    profile: str,
    dataset: str,
    file_path: str,
    now: datetime | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Wrap a frame in an ECS event with vmctl's collection metadata (put fields).
    `@timestamp` defaults to the collection time; `enrich` replaces it with the log's
    own time when parseable. `now` is injectable for deterministic tests."""
    ts = (now or datetime.now(timezone.utc)).isoformat()
    event: dict[str, Any] = {"@timestamp": ts}
    # The whole raw line is always in `message` — parsed or not (ADR 0010).
    event["message"] = frame.raw
    event["event"] = {"dataset": dataset, "created": ts}
    event["host"] = {"name": host}
    event["agent"] = {"type": "vmctl", "version": __version__}
    event["log"] = {"file": {"path": file_path}}
    event["labels"] = {"profile": profile}
    event["ecs"] = {"version": ECS_VERSION}
    if tags:
        event["tags"] = list(tags)
    return event


def event_tags(frame: Frame, *, codec_name: str, configured: list[str] | None = None) -> list[str]:
    """The input's configured tags, plus Logstash's `_jsonparsefailure` when a `json`
    codec handed back an unparsed line."""
    tags = list(configured or [])
    if codec_name == "json" and frame.parsed is None and JSON_PARSE_FAILURE not in tags:
        tags.append(JSON_PARSE_FAILURE)
    return tags


def enrich(
    event: dict[str, Any],
    frame: Frame,
    *,
    filters: list[Filter],
    file_path: str,
    timestamp: TimestampSpec | None = None,
) -> dict[str, Any]:
    """Parse step: merge a JSON frame's fields, set the log's `@timestamp`, then run the
    profile's filters. No content is parsed automatically beyond the timestamp (ADR 0010)."""
    if frame.parsed:
        _merge_json(event, frame.parsed)
    _apply_event_time(event, timestamp)
    apply_filters(event, filters, path=file_path)
    return event


def assemble(
    frame: Frame,
    *,
    host: str,
    profile: str,
    inp: Input,
    file_path: str,
    now: datetime | None = None,
    filters: list[Filter] | None = None,
) -> dict[str, Any]:
    """build_event + enrich — a framed record to a finished ECS event."""
    event = build_event(
        frame,
        host=host,
        profile=profile,
        dataset=inp.type,
        file_path=file_path,
        now=now,
        tags=event_tags(frame, codec_name=inp.codec.name, configured=inp.tags),
    )
    return enrich(
        event, frame, filters=filters or [], file_path=file_path, timestamp=inp.timestamp
    )


def _merge_json(event: dict[str, Any], parsed: dict[str, Any]) -> None:
    for key, value in parsed.items():
        if key not in _RESERVED:
            event[key] = value


def raw_line(event: dict[str, Any]) -> str:
    """The record's raw text — always in `message` (ADR 0010)."""
    value = event.get("message")
    return value if isinstance(value, str) else ""


def _apply_event_time(event: dict[str, Any], spec: TimestampSpec | None) -> None:
    """Set `@timestamp` from the log's own event time. Configured per input (`spec`), else
    auto-detected. A miss leaves `@timestamp` at the collection time (`event.created`)."""
    parsed: datetime | None = None
    if spec is not None and spec.field is not None:
        value = event.get(spec.field)
        parsed = _parse_iso(value) if isinstance(value, str) else None
    elif spec is not None and spec.pattern is not None and spec.format is not None:
        m = re.search(spec.pattern, raw_line(event))
        if m:
            text = m.group(1) if m.groups() else m.group(0)
            parsed = _strptime(text, spec.format)
    else:
        # Default: a merged JSON `timestamp` field, else a leading ISO in the raw line.
        candidate = event.get("timestamp") if isinstance(event.get("timestamp"), str) else None
        parsed = _parse_iso(candidate) if candidate else None
        if parsed is None:
            m = _LEADING_TS.match(raw_line(event))
            if m:
                parsed = _parse_iso(m.group(1))
    if parsed is not None:
        event["@timestamp"] = parsed.isoformat()


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.strip().replace(",", "."))
    except ValueError:
        return None


def _strptime(value: str, fmt: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip(), fmt)
    except ValueError:
        return None
