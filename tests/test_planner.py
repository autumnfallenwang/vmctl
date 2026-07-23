"""Tier-1 planner tests — pruning hosts/inputs/files from the query (docs/adr/0005)."""

from __future__ import annotations

from vmctl.config import Codec, Filter, Input
from vmctl.kql import Match, parse
from vmctl.planner import conjuncts, file_survives, host_survives, input_survives

ROUTE_FILTER = Filter(
    condition='[type] == "ig-route"', grok={"path": r"route-%{DATA:route_id}\.log"}
)
ROUTE_INPUT = Input(
    type="ig-route",
    path=["route-*.log*"],
    codec=Codec(name="multiline", pattern=r"^\d{4}", negate=True),
)
AUDIT_INPUT = Input(type="ig-audit", path=["audit/*.audit.json*"], codec=Codec(name="json"))


def test_conjuncts_extracts_top_level_ands() -> None:
    assert conjuncts(parse("a:1 and b:2 and c:3")) == [
        Match("a", ":", "1"),
        Match("b", ":", "2"),
        Match("c", ":", "3"),
    ]


def test_conjuncts_stops_at_or_and_not() -> None:
    # Neither branch of an `or` may prune on its own, and a negated clause says nothing
    # about what must be present.
    assert conjuncts(parse("a:1 or b:2")) == []
    assert conjuncts(parse("not a:1")) == []
    assert conjuncts(parse("a:1 and (b:2 or c:3)")) == [Match("a", ":", "1")]


def test_host_pruned_by_host_name() -> None:
    query = parse("host.name:192.168.77.11 and response.statusCode:500")
    assert host_survives(query, host="192.168.77.11", profile="test_ig")
    assert not host_survives(query, host="192.168.77.12", profile="test_ig")


def test_unknown_field_never_prunes() -> None:
    # `response.statusCode` lives in the record body — invisible to the planner, so it
    # must never drop a host, an input, or a file.
    query = parse("response.statusCode:500")
    assert host_survives(query, host="h1", profile="p")
    assert input_survives(query, host="h1", profile="p", inp=AUDIT_INPUT)
    assert file_survives(
        query,
        host="h1",
        profile="p",
        inp=AUDIT_INPUT,
        file_path="/logs/audit/access.audit.json",
        filters=[ROUTE_FILTER],
    )


def test_dataset_prunes_other_inputs() -> None:
    query = parse("event.dataset:ig-audit")
    assert input_survives(query, host="h1", profile="p", inp=AUDIT_INPUT)
    assert not input_survives(query, host="h1", profile="p", inp=ROUTE_INPUT)


def test_file_pruned_by_route_id_from_path() -> None:
    query = parse("labels.route_id:00-proxy")

    def survives(name: str) -> bool:
        return file_survives(
            query,
            host="h1",
            profile="p",
            inp=ROUTE_INPUT,
            file_path=f"/logs/{name}",
            filters=[ROUTE_FILTER],
        )

    assert survives("route-00-proxy.log")
    assert not survives("route-01-other.log")


def test_file_route_id_wildcard() -> None:
    query = parse("labels.route_id:00-*")
    assert file_survives(
        query,
        host="h1",
        profile="p",
        inp=ROUTE_INPUT,
        file_path="/logs/route-00-proxy.log",
        filters=[ROUTE_FILTER],
    )
    assert not file_survives(
        query,
        host="h1",
        profile="p",
        inp=ROUTE_INPUT,
        file_path="/logs/route-99-other.log",
        filters=[ROUTE_FILTER],
    )


def test_audit_route_id_does_not_prune() -> None:
    # For the audit log the route id is a JSON field, not part of the filename, so the
    # grok doesn't fire and the file must be read. Same field, different tier by log type.
    query = parse("labels.route_id:00-proxy")
    assert file_survives(
        query,
        host="h1",
        profile="p",
        inp=AUDIT_INPUT,
        file_path="/logs/audit/access.audit.json",
        filters=[ROUTE_FILTER],
    )
