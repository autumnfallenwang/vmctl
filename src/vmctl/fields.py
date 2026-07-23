"""Field discovery — what is queryable, in `_field_caps` shape (docs/adr/0008).

`vmctl fields` samples records from every host × input, walks each assembled ECS event to
its queryable leaf paths, infers an Elasticsearch type-family per field, and reports the
result in Elasticsearch's `_field_caps` response shape. It is the answer to "I don't know
this log — what can I filter on?", which ADR 0007 otherwise leaves unanswered.

The compatibility is a *shape* claim, not a *guarantee* claim: `_field_caps` reports a
declared mapping, this reports an observed sample. A field absent from the sample is not
proven absent — hence the `vmctl.docs_sampled` / `vmctl.coverage` hedges, which
`_field_caps` has no equivalent for because a mapping needs none.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections import defaultdict
from collections.abc import Callable, Iterator
from typing import Any

from vmctl.codecs import frame_lines, make_codec
from vmctl.config import Host, Profile
from vmctl.discovery import apply_excludes, build_glob_command
from vmctl.event import assemble
from vmctl.transport import Connection, Transport, TransportError

# The put fields event.py always sets — the half of the schema knowable without sampling.
ECS_ENVELOPE = frozenset(
    {
        "@timestamp",
        "event.dataset",
        "event.created",
        "host.name",
        "agent.type",
        "agent.version",
        "log.file.path",
        "labels.profile",
        "ecs.version",
    }
)
EXAMPLES_PER_FIELD = 3

# A full ISO-8601 date/time — anything looser stays a keyword.
_ISO_TS = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")


def _remote_path(base_dir: str, rel: str) -> str:
    path = rel if base_dir in ("", ".") else f"{base_dir.rstrip('/')}/{rel}"
    if "'" in path:
        raise ValueError(f"refusing to read a path containing a single quote: {path!r}")
    return path


def leaves(obj: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    """Yield ``(dotted_path, scalar_value)`` for every queryable leaf.

    A list yields its elements under the *same* path — never ``.0`` — because that is the
    path a query filters on (tier 3 matches any element). Dicts recurse; scalars yield.
    """
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = f"{prefix}.{key}" if prefix else key
            yield from leaves(value, child)
    elif isinstance(obj, list):
        for value in obj:
            yield from leaves(value, prefix)
    elif prefix:
        yield prefix, obj


def type_family(value: Any) -> str:
    """The Elasticsearch type-family name for a value, inferred from its JSON type.

    Strings are ``keyword``, never ``text`` (we compare exact, unanalyzed). A numeric-looking
    string like ``"200"`` is still ``keyword`` — it *is* a string, matching ES dynamic
    mapping with the default ``numeric_detection: false``. Only strings shaped like an
    ISO-8601 timestamp become ``date``.
    """
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "long"
    if isinstance(value, float):
        return "double"
    if isinstance(value, str) and _ISO_TS.match(value):
        return "date"
    return "keyword"


class FieldCatalog:
    """Accumulates sampled events into a `_field_caps`-shaped report. No transport — the
    orchestration feeds it; the shape logic is here and unit-testable in isolation."""

    def __init__(self) -> None:
        # field -> family -> {"datasets": set, "hosts": set, "count": int}
        self._fields: dict[str, dict[str, dict[str, Any]]] = defaultdict(
            lambda: defaultdict(lambda: {"datasets": set(), "hosts": set(), "count": 0})
        )
        self._examples: dict[str, list[Any]] = defaultdict(list)
        self._datasets: set[str] = set()
        self._sampled_hosts: set[str] = set()
        self._docs_sampled = 0
        self._docs_per_dataset: dict[str, int] = defaultdict(int)

    def note_host(self, host: str) -> None:
        """Record that a host was reached — so an absent field can be told apart from a
        host that was never sampled."""
        self._sampled_hosts.add(host)

    def add_event(self, event: dict[str, Any], *, dataset: str, host: str) -> None:
        self._datasets.add(dataset)
        self._sampled_hosts.add(host)
        self._docs_sampled += 1
        self._docs_per_dataset[dataset] += 1
        for path, value in leaves(event):
            entry = self._fields[path][type_family(value)]
            entry["datasets"].add(dataset)
            entry["hosts"].add(host)
            entry["count"] += 1
            examples = self._examples[path]
            if len(examples) < EXAMPLES_PER_FIELD and value not in examples:
                examples.append(value)

    def to_field_caps(self) -> dict[str, Any]:
        all_datasets = self._datasets
        fields: dict[str, Any] = {}
        coverage: dict[str, float] = {}
        host_conflicts: list[str] = []

        for name, families in sorted(self._fields.items()):
            # A field is "uniform" — and so omits `indices` — when it has exactly one
            # type-family and that family is present in every sampled dataset.
            uniform = len(families) == 1 and next(iter(families.values()))["datasets"] == all_datasets
            fields[name] = {
                family: self._capability(info["datasets"], uniform)
                for family, info in sorted(families.items())
            }
            field_datasets = set().union(*(f["datasets"] for f in families.values()))
            field_hosts = set().union(*(f["hosts"] for f in families.values()))
            denom = sum(self._docs_per_dataset[d] for d in field_datasets)
            total = sum(f["count"] for f in families.values())
            coverage[name] = round(total / denom, 4) if denom else 0.0
            if field_hosts != self._sampled_hosts:
                host_conflicts.append(name)

        return {
            "indices": sorted(all_datasets),
            "fields": fields,
            "vmctl": {
                "docs_sampled": self._docs_sampled,
                "hosts": sorted(self._sampled_hosts),
                "coverage": coverage,
                "examples": {name: self._examples[name] for name in sorted(self._examples)},
                "host_conflicts": sorted(host_conflicts),
            },
        }

    def _capability(self, datasets: set[str], uniform: bool) -> dict[str, Any]:
        cap: dict[str, Any] = {
            "metadata_field": False,
            "searchable": True,  # everything is scanned
            "aggregatable": False,  # vmctl does not aggregate
        }
        if not uniform:
            cap["indices"] = sorted(datasets)
        return cap


async def run_fields(
    transport: Transport,
    profile: Profile,
    *,
    fallback_password: str | None,
    type_filter: str | None = None,
    sample: int = 500,
    write: Callable[[dict[str, Any]], None],
    report_error: Callable[[str], None] = lambda _m: None,
) -> int:
    """Sample every matching input across every host and emit one `_field_caps` object.

    Returns 1 if any host failed (the report still covers the hosts that succeeded), else 0.
    """
    inputs = [i for i in profile.inputs if type_filter is None or i.type == type_filter]
    if type_filter is not None and not inputs:
        report_error(f"no input of type '{type_filter}' in profile '{profile.name}'")
        return 1

    base_dir = profile.base_dir or "."
    catalog = FieldCatalog()
    scanned: list[str] = []
    had_error = False
    lock = asyncio.Lock()

    async def sample_file(conn: Connection, host: str, inp: Any, file_path: str) -> None:
        outcome = await conn.run(f"tail -n {sample} '{file_path}'")
        codec = make_codec(inp.codec)
        events = [
            assemble(
                frame,
                host=host,
                profile=profile.name,
                inp=inp,
                file_path=file_path,
                filters=profile.filters,
            )
            for frame in frame_lines(codec, outcome.stdout.splitlines())
        ]
        async with lock:  # the catalog is shared across concurrent host workers
            scanned.append(f"{host}:{file_path}")
            for event in events:
                catalog.add_event(event, dataset=inp.type, host=host)

    async def host_worker(host: Host) -> None:
        nonlocal had_error
        password = host.password or fallback_password
        if password is None:
            had_error = True
            report_error(f"{host.host}: no password available")
            return

        conn: Connection | None = None
        try:
            conn = await transport.connect(host.host, host.user, password)
            async with lock:
                catalog.note_host(host.host)
            for inp in inputs:
                globbed = await conn.run(build_glob_command(base_dir, inp.path))
                files = apply_excludes(
                    [ln for ln in globbed.stdout.splitlines() if ln], inp.exclude
                )
                for rel in files:
                    await sample_file(conn, host.host, inp, _remote_path(base_dir, rel))
        except TransportError as exc:
            had_error = True
            report_error(f"{host.host}: {exc}")
        finally:
            if conn is not None:
                with contextlib.suppress(Exception):
                    await conn.close()

    await asyncio.gather(*(host_worker(h) for h in profile.hosts))

    result = catalog.to_field_caps()
    write(result)
    report_error(
        f"sampled {len(scanned)} file(s); {len(result['fields'])} field(s) "
        f"across {len(result['indices'])} dataset(s)"
    )
    return 1 if had_error else 0
