"""Tier-2 predicate pushdown — filtering at the source with base tools (docs/adr/0005).

Builds the remote read command for one file: an `awk` time window plus, where provably
safe, literal `grep -F` terms. Everything here must be a **sound superset** — it may hand
back extra lines (tier 3 drops them) but must never drop a true match. Where soundness is
unclear, nothing is pushed and the bytes simply travel.

Two properties of the real logs shape this:

- IG writes uniform UTC ISO-8601, so timestamps sort **lexicographically** — the remote
  side compares plain strings, no date math. The audit JSON uses dot-millis
  (`2026-07-23T00:04:54.741Z`) while the text logs use comma-millis
  (`2026-07-23T00:04:42,571Z`), so comparison is done on the shared 19-character
  `YYYY-MM-DDTHH:MM:SS` prefix, which is identical in both.
- A text event spans several physical lines: `[CONTINUED]` continuations, **and blank
  lines** (logback only prefixes a newline followed by a non-newline). Continuations carry
  no timestamp, so the window decision is taken on a timestamp line and then *carried* onto
  every following line — never re-derived. A plain `grep` would shred these events, which
  is why term pushdown is restricted to single-line (`json`) inputs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from vmctl.predicate import Node
from vmctl.planner import conjuncts

# A leading ISO date, spelled without `{n}` intervals so any POSIX awk accepts it.
_TS_LINE = "/^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T/"
_PREFIX_LEN = 19  # YYYY-MM-DDTHH:MM:SS

# Fields vmctl generates rather than reads out of the line — their values are nowhere in
# the file, so grepping for one would drop every line.
_PUT_FIELDS = {"@timestamp", "event.dataset", "event.created", "event.original", "labels.profile"}
_PUT_PREFIXES = ("host.", "agent.", "log.", "ecs.")

_SAFE_TERM = re.compile(r"^[A-Za-z0-9._:@/+ -]+$")
_INTEGER = re.compile(r"^-?\d+$")


@dataclass(frozen=True)
class Window:
    """A time window as 19-char ISO prefixes, ready for lexicographic comparison."""

    since: str | None = None
    until: str | None = None

    @property
    def empty(self) -> bool:
        return self.since is None and self.until is None


def bound_to_prefix(value: datetime) -> str:
    """Truncate a bound to `YYYY-MM-DDTHH:MM:SS` in UTC.

    Truncation alone is already the outward widening ADR 0005 asks for: flooring is
    monotonic, so `t >= since` implies `floor(t) >= floor(since)` (and likewise above),
    meaning a boundary match can never be truncated out of the window.
    """
    at = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def window_from(since: datetime | None, until: datetime | None) -> Window:
    return Window(
        since=bound_to_prefix(since) if since is not None else None,
        until=bound_to_prefix(until) if until is not None else None,
    )


def window_from_query(node: Node, *, field: str = "@timestamp") -> Window:
    """Derive the remote time window from `@timestamp` range predicates in the filter.

    The query carries its own bounds, so a `range` on `@timestamp` reaches the remote
    `awk` instead of only being checked on the client. Exclusive bounds (`>`/`<`) are
    treated as inclusive — a widening, which keeps the pushdown a sound superset; tier
    3 still applies the exact comparison.
    """
    since: str | None = None
    until: str | None = None
    for conjunct in conjuncts(node):
        if conjunct.field != field:
            continue
        prefix = conjunct.value[:_PREFIX_LEN]
        if len(prefix) < _PREFIX_LEN:
            continue  # too coarse to compare against a full timestamp prefix
        if conjunct.op in (">=", ">"):
            since = prefix if since is None else max(since, prefix)
        elif conjunct.op in ("<=", "<"):
            until = prefix if until is None else min(until, prefix)
    return Window(since=since, until=until)


def pushable_terms(node: Node, *, codec_name: str) -> list[str]:
    """Literal values that must appear verbatim in a matching raw line.

    Deliberately narrow — a term is pushed only when every soundness condition holds:
    single-line framing, a top-level AND conjunct, no wildcard, a field that is actually
    read out of the text, an unambiguous textual form, and a shell-safe value.
    """
    if codec_name != "json":  # a grep would break multi-line event framing
        return []
    terms: list[str] = []
    for conjunct in conjuncts(node):
        value = conjunct.value
        if conjunct.op != ":" or value == "*":
            continue
        if "*" in value or "?" in value:  # wildcards aren't substrings
            continue
        if _is_put_field(conjunct.field):
            continue
        if not _SAFE_TERM.match(value):
            continue
        if _is_ambiguous_number(value):
            continue
        terms.append(value)
    return terms


def build_read_command(
    file_path: str,
    *,
    codec_name: str,
    window: Window | None = None,
    terms: list[str] | None = None,
) -> str:
    """The remote command that reads `file_path`, pre-filtered where it is safe to be."""
    _reject_quote(file_path, "path")
    window = window or Window()
    terms = terms or []

    if window.empty:
        cmd = f"cat '{file_path}'"
    else:
        program = _json_program(window) if codec_name == "json" else _text_program(window)
        cmd = f"awk '{program}' '{file_path}'"

    for term in terms:
        _reject_quote(term, "term")
        cmd += f" | grep -F -e '{term}'"
    return cmd


def _text_program(window: Window) -> str:
    # Decide on a timestamp line, then carry that decision onto continuation lines —
    # including blank ones, which are part of the event and carry no marker.
    return (
        "BEGIN{keep=1}"
        f"{_TS_LINE}{{ts=substr($0,1,{_PREFIX_LEN});keep=1;"
        f"if(length(ts)=={_PREFIX_LEN}){{keep=({_condition(window)})}}}}"
        "{if(keep)print}"
    )


def _json_program(window: Window) -> str:
    # One object per line, so each line decides for itself. A line whose timestamp can't
    # be read (truncated/garbled JSON) is kept — tier 3 gets to see it.
    return (
        "{keep=1;"
        'if(match($0,/"timestamp"[ ]*:[ ]*"/)){'
        f"ts=substr($0,RSTART+RLENGTH,{_PREFIX_LEN});"
        f"if(length(ts)=={_PREFIX_LEN}){{keep=({_condition(window)})}}}}"
        "if(keep)print}"
    )


def _condition(window: Window) -> str:
    tests = []
    if window.since is not None:
        tests.append(f'ts>="{window.since}"')
    if window.until is not None:
        tests.append(f'ts<="{window.until}"')
    return " && ".join(tests)


def _is_put_field(field: str) -> bool:
    return field in _PUT_FIELDS or field.startswith(_PUT_PREFIXES)


def _is_ambiguous_number(value: str) -> bool:
    """True for numbers whose textual form isn't pinned down — `500.0` in the parsed
    object could be `5e2` in the file, so grepping the rendered form would be unsound.
    Plain integers are safe."""
    try:
        float(value)
    except ValueError:
        return False
    return _INTEGER.match(value) is None


def _reject_quote(value: str, what: str) -> None:
    if "'" in value:
        raise ValueError(f"refusing a {what} containing a single quote: {value!r}")
