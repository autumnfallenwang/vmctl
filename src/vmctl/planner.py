"""Tier-1 predicate resolution — the planner (docs/adr/0005).

Resolves the put/structural half of a query by *choosing what to read*: which hosts to
connect to and which files to open, with no remote command involved. `host.name`,
`event.dataset`, `labels.profile`, `log.file.path` are known before a byte is read; so is
`labels.route_id` for route logs, where the id lives in the filename.

Pruning is **three-valued and conservative**: a predicate is only allowed to drop a host or
a file when it is *definitely* false against what the planner already knows. A field the
planner cannot see (`response.statusCode`, say) is UNKNOWN, never false — dropping on
unknown would silently lose true matches, and ADR 0005 puts correctness before efficiency.

Only top-level AND conjuncts are considered. A predicate under an `or` or a `not` cannot
justify pruning on its own, so those subtrees are treated as opaque.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from vmctl.filters import apply_filters
from vmctl.kql import And, Match, Node
from vmctl.query import matches, resolve_field

if TYPE_CHECKING:
    from vmctl.config import Filter, Input


def conjuncts(node: Node) -> list[Match]:
    """The `Match` leaves joined by top-level ANDs. `Or`/`Not` subtrees yield nothing:
    neither can be evaluated clause-by-clause without changing the query's meaning."""
    if isinstance(node, Match):
        return [node]
    if isinstance(node, And):
        found: list[Match] = []
        for clause in node.clauses:
            found.extend(conjuncts(clause))
        return found
    return []


def partial_event(
    *,
    host: str,
    profile: str,
    dataset: str | None = None,
    file_path: str | None = None,
    filters: list[Filter] | None = None,
) -> dict[str, Any]:
    """Build the put-fields-only view the planner can decide against.

    When a file path is known, the profile's real filters run against it — so a grok on
    `path` fills in `labels.route_id` exactly as the full pipeline would, with no need to
    invert the pattern. For a log whose route id lives in the record body instead (audit
    JSON), the grok simply doesn't match and the field stays absent — i.e. UNKNOWN.
    """
    event: dict[str, Any] = {"host": {"name": host}, "labels": {"profile": profile}}
    if dataset is not None:
        event["event"] = {"dataset": dataset}
    if file_path is not None:
        event["log"] = {"file": {"path": file_path}}
        apply_filters(event, list(filters or []), path=file_path)
    return event


def survives(node: Node, partial: dict[str, Any]) -> bool:
    """False only when some conjunct is *definitely* false against `partial`."""
    for conjunct in conjuncts(node):
        if resolve_field(partial, conjunct.field) is None:
            continue  # not knowable at plan time — defer to tiers 2/3
        if not matches(conjunct, partial):
            return False
    return True


def host_survives(node: Node, *, host: str, profile: str) -> bool:
    """Whether this host is worth connecting to at all."""
    return survives(node, partial_event(host=host, profile=profile))


def input_survives(node: Node, *, host: str, profile: str, inp: Input) -> bool:
    """Whether this input's files are worth globbing (resolves `event.dataset`)."""
    return survives(node, partial_event(host=host, profile=profile, dataset=inp.type))


def file_survives(
    node: Node,
    *,
    host: str,
    profile: str,
    inp: Input,
    file_path: str,
    filters: list[Filter] | None = None,
) -> bool:
    """Whether this specific file is worth reading (resolves path-derived labels)."""
    return survives(
        node,
        partial_event(
            host=host,
            profile=profile,
            dataset=inp.type,
            file_path=file_path,
            filters=filters,
        ),
    )
