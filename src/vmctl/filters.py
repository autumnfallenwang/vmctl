"""A minimal, faithful subset of Logstash filters (docs/adr/0005).

Supports just what vmctl needs today: the grok macros ``%{DATA:name}`` /
``%{GREEDYDATA:name}`` (plus a few common ones), ``if [field] == "value"``
conditions, and grok run against the file `path` or the `message`. Captured names
are written into ``labels.*``. Logstash field names are aliased to our ECS event
(``[type]`` → ``event.dataset``, ``path`` → the file path). The full grok/condition
engine is a later refinement.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vmctl.config import Filter

_GROK_TOKEN = re.compile(r"%\{(\w+):(\w+)\}")
_GROK_TYPES = {
    "DATA": ".+?",
    "GREEDYDATA": ".+",
    "WORD": r"\w+",
    "INT": r"\d+",
    "NOTSPACE": r"\S+",
}

_CONDITION = re.compile(r"""^\s*((?:\[\w+\])+)\s*==\s*(['"])(.*?)\2\s*$""")
_FIELD_REF = re.compile(r"\[(\w+)\]")


def grok_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a grok pattern to a regex, keeping non-macro text as-is."""

    def repl(m: re.Match[str]) -> str:
        grok_type, name = m.group(1), m.group(2)
        expr = _GROK_TYPES.get(grok_type)
        if expr is None:
            raise ValueError(f"unsupported grok pattern %{{{grok_type}:{name}}}")
        return f"(?P<{name}>{expr})"

    return re.compile(_GROK_TOKEN.sub(repl, pattern))


def matches_condition(condition: str | None, event: dict[str, Any]) -> bool:
    """Evaluate a filter's ``if`` (``None`` = always). Only ``[field] == "value"``."""
    if condition is None:
        return True
    m = _CONDITION.match(condition)
    if m is None:
        raise ValueError(f"unsupported filter condition: {condition!r}")
    fields = _FIELD_REF.findall(m.group(1))
    return _resolve_field(fields, event) == m.group(3)


def apply_filters(event: dict[str, Any], filters: list[Filter], *, path: str) -> None:
    """Run each matching filter's grok against the file `path` / `message`, writing
    the captured named groups into ``event['labels']``."""
    sources = {"path": path, "message": event.get("message", "")}
    labels = event.setdefault("labels", {})
    for filt in filters:
        if filt.grok is None or not matches_condition(filt.condition, event):
            continue
        for field_name, grok_pattern in filt.grok.items():
            target = sources.get(field_name)
            if not isinstance(target, str):
                continue
            match = grok_to_regex(grok_pattern).search(target)
            if match:
                labels.update(match.groupdict())


def _resolve_field(fields: list[str], event: dict[str, Any]) -> Any:
    if fields == ["type"]:  # Logstash `type` → our ECS event.dataset
        return event.get("event", {}).get("dataset")
    cur: Any = event
    for f in fields:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(f)
    return cur
