"""Field discovery tests — inference, catalog shape, and sampling (docs/adr/0008)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from dslq import exists, q
from fakes import FakeConnection, FakeTransport

from vmctl.config import Codec, Host, Input, Profile
from vmctl.fields import FieldCatalog, leaves, run_fields, type_family
from vmctl.query import matches


def test_type_family_inference() -> None:
    assert type_family(True) == "boolean"
    assert type_family(500) == "long"
    assert type_family(1.5) == "double"
    assert type_family("2026-07-23T00:04:42.571Z") == "date"
    assert type_family("2026-07-23T00:04:42,571Z") == "date"  # comma millis
    assert type_family("SUCCESSFUL") == "keyword"
    # A numeric-looking string is a string — keyword, not long (ES default mapping).
    assert type_family("200") == "keyword"
    assert type_family("2026-07-23") == "keyword"  # date-only, not a full timestamp


def test_leaves_flattens_arrays_to_queryable_path() -> None:
    event = {"http": {"request": {"headers": {"host": ["ig1:9080", "alt:9080"]}}}}
    assert sorted(leaves(event)) == [
        ("http.request.headers.host", "alt:9080"),
        ("http.request.headers.host", "ig1:9080"),
    ]
    # No `.0` index ever appears in a path.
    assert all(not part.isdigit() for path, _ in leaves(event) for part in path.split("."))


def _audit_event(status: str = "200", **extra: Any) -> dict[str, Any]:
    event = {
        "@timestamp": "2026-07-23T00:04:42.571000+00:00",
        "event": {"dataset": "ig-audit"},
        "host": {"name": "h1"},
        "response": {"statusCode": status, "elapsedTime": 4},
        "ig": {"routeId": "00-proxy"},
    }
    event.update(extra)
    return event


def test_catalog_single_dataset() -> None:
    cat = FieldCatalog()
    for _ in range(10):
        cat.add_event(_audit_event(), dataset="ig-audit", host="h1")
    caps = cat.to_field_caps()

    assert caps["indices"] == ["ig-audit"]
    assert caps["fields"]["response.statusCode"] == {
        "keyword": {"metadata_field": False, "searchable": True, "aggregatable": False}
    }
    assert caps["fields"]["response.elapsedTime"]["long"]["searchable"] is True
    assert caps["fields"]["@timestamp"]["date"]["aggregatable"] is False
    assert caps["vmctl"]["docs_sampled"] == 10
    assert caps["vmctl"]["coverage"]["response.statusCode"] == 1.0
    assert "200" in caps["vmctl"]["examples"]["response.statusCode"]


def test_catalog_field_in_one_dataset_lists_indices() -> None:
    cat = FieldCatalog()
    cat.add_event(_audit_event(), dataset="ig-audit", host="h1")
    cat.add_event(
        {"event": {"dataset": "ig-system"}, "message": "hi", "@timestamp": "2026-07-23T00:00:00Z"},
        dataset="ig-system",
        host="h1",
    )
    caps = cat.to_field_caps()

    # response.* is audit-only -> its capability lists the dataset.
    assert caps["fields"]["response.statusCode"]["keyword"]["indices"] == ["ig-audit"]
    # @timestamp is in both datasets with one family -> uniform -> no `indices` key.
    assert "indices" not in caps["fields"]["@timestamp"]["date"]


def test_catalog_type_conflict() -> None:
    cat = FieldCatalog()
    cat.add_event({"code": 500, "event": {"dataset": "a"}}, dataset="a", host="h1")
    cat.add_event({"code": "down", "event": {"dataset": "b"}}, dataset="b", host="h1")
    code = cat.to_field_caps()["fields"]["code"]

    assert set(code) == {"long", "keyword"}
    assert code["long"]["indices"] == ["a"]
    assert code["keyword"]["indices"] == ["b"]


def test_catalog_top_level_shape() -> None:
    cat = FieldCatalog()
    cat.add_event(_audit_event(), dataset="ig-audit", host="h1")
    caps = cat.to_field_caps()

    assert set(caps) == {"indices", "fields", "vmctl"}
    assert set(caps["vmctl"]) == {
        "docs_sampled",
        "hosts",
        "coverage",
        "examples",
        "host_conflicts",
    }
    # The whole thing is a single JSON line (valid NDJSON per ADR 0007).
    assert "\n" not in json.dumps(caps)


def test_catalog_host_conflict() -> None:
    cat = FieldCatalog()
    cat.note_host("h1")
    cat.note_host("h2")
    cat.add_event({"only_h1": "x", "event": {"dataset": "d"}}, dataset="d", host="h1")
    cat.add_event({"both": "y", "event": {"dataset": "d"}}, dataset="d", host="h1")
    cat.add_event({"both": "z", "event": {"dataset": "d"}}, dataset="d", host="h2")
    conflicts = cat.to_field_caps()["vmctl"]["host_conflicts"]

    assert "only_h1" in conflicts  # present on h1, absent on h2
    assert "both" not in conflicts  # on both hosts


def test_coverage_reflects_rarity() -> None:
    cat = FieldCatalog()
    for i in range(5):
        event: dict[str, Any] = {"event": {"dataset": "d"}}
        if i == 0:
            event["rare"] = "seen once"
        cat.add_event(event, dataset="d", host="h1")
    assert cat.to_field_caps()["vmctl"]["coverage"]["rare"] == 0.2


# --- run_fields against fakes -------------------------------------------------

AUDIT = '{"timestamp":"2026-07-23T00:00:01.000Z","response":{"statusCode":"200"},"ig":{"routeId":"r"}}'


def _profile(*hosts: str) -> Profile:
    return Profile(
        name="p",
        hosts=[Host(h, "u", password="x") for h in (hosts or ("h1",))],
        inputs=[
            Input(type="ig-audit", path=["audit/*.json"], codec=Codec(name="json")),
            Input(type="ig-system", path=["*.log"], codec=Codec(name="plain")),
        ],
        base_dir="/logs",
    )


def _transport(**kw: Any) -> FakeTransport:
    def factory(host: str) -> FakeConnection:
        def stdout(cmd: str) -> str:
            if cmd.startswith("cd "):  # glob command
                return "audit/access.audit.json\n" if "audit" in cmd else "route-system.log\n"
            return f"{AUDIT}\n" if "audit" in cmd else "2026-07-23T00:00:01,000Z | INFO | hi\n"

        return FakeConnection(host, run_stdout=stdout)

    return FakeTransport(conn_factory=factory, **kw)


def _run(transport: FakeTransport, profile: Profile, **kw: Any) -> tuple[int, dict[str, Any]]:
    captured: list[dict[str, Any]] = []
    rc = asyncio.run(
        run_fields(
            transport, profile, fallback_password=None, write=captured.append, **kw
        )
    )
    assert len(captured) == 1  # exactly one object emitted
    return rc, captured[0]


def test_run_fields_samples_all_hosts() -> None:
    transport = _transport()
    rc, caps = _run(transport, _profile("h1", "h2"), sample=250)
    assert rc == 0
    assert caps["vmctl"]["hosts"] == ["h1", "h2"]
    assert set(caps["indices"]) == {"ig-audit", "ig-system"}
    # The sample size reaches the remote command.
    assert any("tail -n 250 " in c for conn in transport.connections for c in conn.run_cmds)
    assert caps["fields"]["response.statusCode"]["keyword"]["indices"] == ["ig-audit"]


def test_run_fields_type_filter() -> None:
    rc, caps = _run(_transport(), _profile(), type_filter="ig-audit")
    assert rc == 0
    assert caps["indices"] == ["ig-audit"]


def test_run_fields_unknown_type_errors() -> None:
    errors: list[str] = []
    rc = asyncio.run(
        run_fields(
            _transport(),
            _profile(),
            fallback_password=None,
            type_filter="nope",
            write=lambda _r: None,
            report_error=errors.append,
        )
    )
    assert rc == 1
    assert any("nope" in e for e in errors)


def test_run_fields_isolates_host_error() -> None:
    transport = _transport(connect_error_hosts={"h1"})
    errors: list[str] = []
    captured: list[dict[str, Any]] = []
    rc = asyncio.run(
        run_fields(
            transport,
            _profile("h1", "h2"),
            fallback_password=None,
            write=captured.append,
            report_error=errors.append,
        )
    )
    assert rc == 1  # h1 failed
    assert any("h1" in e for e in errors)
    assert captured[0]["vmctl"]["hosts"] == ["h2"]  # h2 still contributed


def test_every_reported_field_is_queryable() -> None:
    """Round-trip: every discovered field can be filtered on."""
    cat = FieldCatalog()
    event = _audit_event(headers={"host": ["ig1:9080"]})
    cat.add_event(event, dataset="ig-audit", host="h1")
    caps = cat.to_field_caps()

    for field in caps["fields"]:
        node = q(exists(field))
        assert matches(node, event), f"{field} reported but not matchable"
