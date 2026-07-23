"""Build the ECS event around a framed log record (docs/adr/0004).

``build_event`` adds the **put** fields (metadata vmctl generates: host, agent,
file, timestamps, dataset, profile) plus the raw message. ``enrich`` is the
**parse** step: merge a JSON frame's fields, derive the log's own ``@timestamp``,
and extract ``labels.route_id``. ``assemble`` runs both.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from vmctl import __version__
from vmctl.filters import apply_filters

if TYPE_CHECKING:
    from vmctl.codecs import Frame
    from vmctl.config import Filter, Input

ECS_VERSION = "8.11"

# Envelope fields a merged JSON frame must never overwrite.
_RESERVED = {"@timestamp", "message", "host", "agent", "log", "ecs", "labels", "event"}
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
) -> dict[str, Any]:
    """Wrap a frame in an ECS event with vmctl's collection metadata (put fields).
    `@timestamp` defaults to the collection time; `enrich` replaces it with the log's
    own time when parseable. `now` is injectable for deterministic tests."""
    ts = (now or datetime.now(timezone.utc)).isoformat()
    return {
        "@timestamp": ts,
        "message": frame.raw,
        "event": {"dataset": dataset, "original": frame.raw, "created": ts},
        "host": {"name": host},
        "agent": {"type": "vmctl", "version": __version__},
        "log": {"file": {"path": file_path}},
        "labels": {"profile": profile},
        "ecs": {"version": ECS_VERSION},
    }


def enrich(
    event: dict[str, Any],
    frame: Frame,
    *,
    filters: list[Filter],
    file_path: str,
) -> dict[str, Any]:
    """Parse step: merge JSON fields, set the log's `@timestamp`, extract route_id."""
    if frame.parsed:
        _merge_json(event, frame.parsed)
    _apply_event_time(event)
    _mirror_route_id(event)
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
        frame, host=host, profile=profile, dataset=inp.type, file_path=file_path, now=now
    )
    return enrich(event, frame, filters=filters or [], file_path=file_path)


def _merge_json(event: dict[str, Any], parsed: dict[str, Any]) -> None:
    for key, value in parsed.items():
        if key not in _RESERVED:
            event[key] = value


def _apply_event_time(event: dict[str, Any]) -> None:
    # Prefer a merged JSON `timestamp` field (audit); else a leading ISO in the message.
    candidate = event.get("timestamp") if isinstance(event.get("timestamp"), str) else None
    parsed = _parse_iso(candidate) if candidate else None
    if parsed is None:
        m = _LEADING_TS.match(event.get("message", ""))
        if m:
            parsed = _parse_iso(m.group(1))
    if parsed is not None:
        event["@timestamp"] = parsed.isoformat()


def _mirror_route_id(event: dict[str, Any]) -> None:
    ig = event.get("ig")
    if isinstance(ig, dict) and "routeId" in ig:
        event.setdefault("labels", {})["route_id"] = ig["routeId"]


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.strip().replace(",", "."))
    except ValueError:
        return None
