---
milestone: 9
title: field discovery (vmctl fields)
status: done
started: 2026-07-23
---

# M09 — field discovery (`vmctl fields`)

`vmctl fields <profile>` reports what is queryable, in Elasticsearch's `_field_caps`
response shape. Implements [ADR 0008](../adr/0008-field-discovery.md).

Without it, someone who does not already know the log's structure cannot write a filter
at all: the ECS envelope is knowable in advance ([ADR 0004](../adr/0004-ecs-output-schema.md)),
but the log's own fields — `response.statusCode`, `ig.routeId`, `http.request.method` —
are invisible until a record is inspected. Elasticsearch answers this with `_field_caps`
and `_mapping`; vmctl currently answers it with a `jq` incantation that is both folklore
and misleading (one record only, and it flattens arrays to unqueryable `headers.host.0`
paths). For a tool whose premise is that an agent drives it, an agent that cannot
discover the schema cannot use the tool.

## Scope

### A. Sampling
- Per host × input: glob files (reuse `discovery.build_glob_command` / `apply_excludes`),
  read the tail of each via the transport, frame with the input's codec, assemble ECS
  events — the same pipeline `search` uses, so what is reported is exactly what is
  queryable.
- `--sample N` bounds records read per input (default 500).

### B. Field inference
- Walk each event to its **queryable dotted leaf paths**. An array contributes its
  element paths, never `.0` indices — matching the array semantics tier 3 implements.
- Infer an Elasticsearch **type-family** name per field: `keyword` / `date` / `long` /
  `double` / `boolean`. Strings are always `keyword`, never `text`, and there is no
  invented `string` family — ES has none.
- Track, per field: which datasets carry it, which hosts carry it, how many sampled
  records contain it, and a few example values.

### C. `_field_caps`-shaped output
- One JSON object (valid NDJSON — a single line). Top level is **exactly** `indices` +
  `fields`; type-keyed entries carry `metadata_field` / `searchable` / `aggregatable`,
  the latter three **hardcoded** (`false` / `true` / `false`) because they describe
  index configuration vmctl does not have — honest constants, never inferred from data.
- Per-field `indices` is **emitted only on disagreement**, omitted when uniform: the
  prose says "null", every documented example omits the key, and we follow the examples.
- vmctl-only additions (`docs_sampled`, `coverage`, `examples`, `hosts`,
  `host_conflicts`) live under a namespaced `vmctl` key so a strict `_field_caps`
  consumer ignores them cleanly.

### D. CLI
- `vmctl fields <profile> [--type T] [--sample N] [--config PATH]`, consistent with the
  other subcommands. Samples every host by default — that is the only way host drift
  becomes visible.

## Exit criteria

- [ ] `vmctl fields test_ig` reports all three datasets and their fields from both hosts.
- [ ] Output parses as a `_field_caps` response: `indices` + `fields`, type-keyed entries.
- [ ] A field in only one dataset lists only that dataset; a type conflict across
      datasets appears under both type keys.
- [ ] Array fields are reported at their queryable path (`http.request.headers.host`),
      not `...host.0` — asserted against the real audit log.
- [ ] `--type` narrows to one input; `--sample` bounds the read and is reported.
- [ ] Every field reported is actually usable in a `search --filter` (round-trip test).
- [ ] `indices` is absent for a field common to all datasets, present for a partial one.
- [ ] Check loop green; a marked integration test runs against the live VMs.

## Non-goals (this milestone)
- An `index_filter` analogue (fields among events matching a query) — documented for
  `_field_caps`, but Elastic notes it is best-effort and "may return an index even if
  the provided filter matches no document"; a caveat not worth inheriting yet.
- A `_mapping` analogue — vmctl has no declared schema to report, only an observed one.
- Aggregations or value distributions beyond a few examples (Kibana Discover's job).
- The index-presupposing `_field_caps` keys: `non_searchable_indices`,
  `non_aggregatable_indices`, `time_series_*`, `non_dimension_indices`,
  `metric_conflicts_indices`, `meta`.

## Progress

- 2026-07-23: Shipped — `vmctl fields` (`fields.py` + CLI). `FieldCatalog` (pure, ingests
  events → `_field_caps`-shaped dict) plus `run_fields`, which mirrors `search`'s host/glob
  pipeline but reads `tail -n {sample}` and accumulates instead of matching. `leaves()`
  flattens arrays to the queryable path (no `.0`); `type_family()` infers ES families
  (`keyword`/`date`/`long`/`double`/`boolean`), strings→keyword. `indices` omitted on
  agreement, present on conflict. 16 new tests (164 fast) + 2 live. **Verified live**:
  3 datasets, both hosts, 1193 records, 32 fields; round-trip discover→search returns hits.
  The live run surfaced the conflict model working for real — `message` reports both `date`
  (route/system lines lead with an ISO timestamp) and `keyword` (route `[CONTINUED]` lines),
  each with its datasets. All exit criteria met.

## Outcome

Shipped `vmctl fields` — the tool is now self-describing. An agent pointed at an unfamiliar
deployment can discover the schema (`fields`) and then query it (`search`), with no prior
knowledge of the log and no external documentation. Output is Elasticsearch's `_field_caps`
response shape — parseable by anything that already understands it — via a pure `FieldCatalog`
accumulator fed by `run_fields`, which reuses `search`'s host/glob/frame/assemble pipeline and
swaps the match step for field accumulation. The three tiers and the search path are untouched.

Faithful to ADR 0008's *shape-compatible, not guarantee-compatible* framing: the report is
inferred from a sample, so `vmctl.docs_sampled` / `coverage` hedge what a real mapping would not
need to. The `_field_caps` conflict model earned its keep on live data — `message` is reported
as both `date` and `keyword` across the route/system logs, honestly, rather than being forced to
one type.

No deviations from the plan. Known wart, deliberately left: `_remote_path` is now duplicated a
third time (tail/search/fields) — extracting it is a boundary move for a separate cycle.

Closed: 2026-07-23
