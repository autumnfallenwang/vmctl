"""Tests for the minimal grok / filter subset."""

from __future__ import annotations

from vmctl.config import Filter
from vmctl.filters import apply_filters, grok_to_regex, matches_condition


def test_grok_data_and_greedydata() -> None:
    m = grok_to_regex(r"route-%{DATA:route_id}\.log").search("/logs/route-00-proxy.log")
    assert m is not None and m.group("route_id") == "00-proxy"  # non-greedy stops at .log
    m2 = grok_to_regex(r"%{GREEDYDATA:rest}").search("anything here")
    assert m2 is not None and m2.group("rest") == "anything here"


def test_condition_type_alias() -> None:
    event = {"event": {"dataset": "ig-route"}}
    assert matches_condition('[type] == "ig-route"', event) is True
    assert matches_condition('[type] == "ig-audit"', event) is False
    assert matches_condition(None, event) is True


def test_apply_filters_extracts_route_id_into_labels() -> None:
    event = {"event": {"dataset": "ig-route"}, "message": "x", "labels": {"profile": "p"}}
    filters = [
        Filter(condition='[type] == "ig-route"', grok={"path": r"route-%{DATA:route_id}\.log"})
    ]
    apply_filters(event, filters, path="/opt/ig-instance/logs/route-00-proxy.log")
    assert event["labels"]["route_id"] == "00-proxy"
    assert event["labels"]["profile"] == "p"  # existing labels preserved


def test_apply_filters_skips_non_matching_condition() -> None:
    event = {"event": {"dataset": "ig-audit"}, "message": "x", "labels": {}}
    filters = [
        Filter(condition='[type] == "ig-route"', grok={"path": r"route-%{DATA:route_id}\.log"})
    ]
    apply_filters(event, filters, path="/logs/route-x.log")
    assert "route_id" not in event["labels"]  # condition didn't match
