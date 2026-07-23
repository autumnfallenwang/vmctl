"""Output sinks for ECS events: NDJSON (ELK-compatible) and a human-readable line.

Both return a string without a trailing newline; the caller (the `tail`/`search`
commands) writes lines to a terminal or file.
"""

from __future__ import annotations

import json
from typing import Any

from vmctl.event import raw_line


def to_ndjson(event: dict[str, Any]) -> str:
    """One ECS event as a compact JSON line."""
    return json.dumps(event, separators=(",", ":"), default=str)


def to_human(event: dict[str, Any]) -> str:
    """A readable one-line summary: '<ts>  <host>  <dataset>[<route>]  | <first line>'."""
    ts = event.get("@timestamp", "")
    host = _get(event, "host", "name") or "?"
    dataset = _get(event, "event", "dataset") or "?"
    route = _get(event, "labels", "route_id")
    tag = f"{dataset}[{route}]" if route else str(dataset)
    # A parsed record carries no `message`; its raw text lives in `event.original`.
    first_line = raw_line(event).split("\n", 1)[0]
    return f"{ts}  {host}  {tag}  | {first_line}"


def _get(event: dict[str, Any], *keys: str) -> Any:
    cur: Any = event
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur
