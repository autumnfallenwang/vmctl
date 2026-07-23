# 0008 — Field discovery: `vmctl fields`, shaped as `_field_caps`

- **Status:** accepted
- **Date:** 2026-07-23
- **Deciders:** project founder

## Context

[ADR 0007](./0007-machine-only-interface.md) made Elasticsearch Query DSL the only way to ask vmctl a question. That assumes the asker knows what fields exist. **Someone who has never seen the log cannot write a filter at all**, and that is the majority case for the tool's stated audience — an AI agent pointed at an unfamiliar deployment.

The schema splits in two, and only half is knowable in advance:

- **The ECS envelope is fixed** by [ADR 0004](./0004-ecs-output-schema.md) and identical for every log vmctl emits: `@timestamp`, `event.dataset`, `event.created`, `host.name`, `agent.*`, `log.file.path`, `labels.profile`, `ecs.version`. Measured on the test lab: exactly **9 fields, shared by all three inputs**. Anyone who knows ECS can write half a filter blind.
- **The log's own fields are invisible until inspected.** Measured: `ig-audit` carries **31** fields (22 beyond the envelope — `response.statusCode`, `http.request.*`, `client.*`, `ig.*`, `transactionId`…), `ig-route` **11**, `ig-system` **10**. There is no way to know `response.statusCode` exists without reading a record.

Elasticsearch answers this with a machine-readable schema API. vmctl's only answer today is `search --filter '{"match_all":{}}' | head -1 | jq`, which is worse than it looks: it reflects **one** record (a field missing there appears not to exist), it flattens arrays to `http.request.headers.host.0` — **not** the queryable path — and, per Elastic's own docs, sampling a document is not even their recommended discovery method.

### The unit of schema is the *input*

Measured across the lab: field sets differ fundamentally **per input** (31 / 11 / 10 fields) and were **identical across hosts** for all three. That is what ADR 0002's "identical deployments" premise predicts — but identical-by-assumption is worth *verifying*, since config drift or a version skew between hosts would show up exactly here.

| Elasticsearch | vmctl |
|---|---|
| index / data stream | **input** (`event.dataset`) — the unit of schema |
| shard / backing index | host × file |
| cluster | profile |
| mapping conflict across indices | field or type differing across hosts |

## Decision

Add **`vmctl fields <profile> [--type T] [--sample N]`**, which samples records and reports what is queryable in Elasticsearch's **`_field_caps` response shape**.

`_field_caps` is Elastic's designated "what can I query?" call — one request spanning every index, returning per field a type plus which indices disagree. Profile is the argument because a profile is the thing that *has* inputs; `--type` narrows to one, mirroring `GET /<index>/_field_caps` versus `GET /_field_caps`.

### Output

A single JSON object — which is valid NDJSON, so [ADR 0007](./0007-machine-only-interface.md) is satisfied without compromise. Output here is bounded (tens of fields), unlike search results, so one object is right.

```json
{"indices":["ig-audit","ig-route","ig-system"],
 "fields":{
   "@timestamp":{"date":{"metadata_field":false,"searchable":true,"aggregatable":false}},
   "response.statusCode":{"keyword":{"metadata_field":false,"searchable":true,
                                     "aggregatable":false,"indices":["ig-audit"]}},
   "message":{"keyword":{"metadata_field":false,"searchable":true,
                         "aggregatable":false,"indices":["ig-route","ig-system"]}}},
 "vmctl":{"docs_sampled":1000,"hosts":["192.168.77.11","192.168.77.12"],
          "coverage":{"response.statusCode":1.0},
          "examples":{"response.statusCode":["200","404"]},
          "host_conflicts":[]}}
```

Conventions, each chosen to match observed Elasticsearch behaviour:

- **Top level is exactly `indices` + `fields`** — the only two documented keys, both required. vmctl-specific additions live under a namespaced `vmctl` key so a strict consumer ignores them cleanly. (Note: the API reference's *description* of the top-level `indices` is copy-pasted from the per-field key and is wrong; the example shows it is the flat list of resolved indices. We follow the example.)
- **`indices` is emitted only when datasets/hosts disagree**, omitted when uniform. The prose says *"or null if all indices have the same type family"* but **every documented example omits the key entirely**; we follow the examples. For a multi-host tool this reads naturally — agreement is the common case, disagreement is the signal.
- **Type keys are Elasticsearch type-family names**: `keyword`, `date`, `long`, `double`, `boolean`. Families are a formal concept — *"certain field types that behave identically are described using a type family"* — and only `keyword` and `text` have more than one member, so family names are otherwise just the type names. **Strings are always `keyword`, never `text`**, which is both accurate (we compare exact and unanalyzed) and self-documenting about why `match` is rejected. We do **not** invent a `string` family; ES has no such thing.
- **`searchable: true` / `aggregatable: false` / `metadata_field: false` are hardcoded, not inferred.** They describe index configuration, which vmctl has none of. The values are honest — everything is scannable, nothing is aggregated — but they are constants, not measurements, and are documented as such rather than fabricated from data shape.
- **Arrays are reported at their queryable path** (`http.request.headers.host`, never `...host.0`), matching the multi-valued semantics tier 3 implements.
- Keys we do not emit: `non_searchable_indices`, `non_aggregatable_indices` (constant, so never in conflict), `time_series_*`, `non_dimension_indices`, `metric_conflicts_indices`, `meta`. All are documented but presuppose an index.

## Consequences

- **Positive:** the tool becomes self-describing — an agent can discover the schema and then query it, with no external documentation and no prior knowledge of the log. Output is parseable by anything that already understands `_field_caps`. Host-level disagreement becomes visible instead of assumed.
- **The compatibility claim is narrower than it looks, and this is the important consequence.** `_field_caps` reports a schema that was **declared**; `vmctl fields` reports one that was **observed**:

  | | Elasticsearch | vmctl |
  |---|---|---|
  | Source | the index mapping | a sample of N records |
  | Mapped field with no documents | returned (default `include_empty_fields=true`) | **invisible** |
  | Rare field | returned like any other | **may be missed** |
  | Completeness | authoritative | probabilistic |

  The closest ES analogue to our behaviour is `include_empty_fields=false` — and even that is *"fields that never had a value in any shards"*, an ever-had-a-value high-water mark that ignores deletes and updates, whereas sampling reports *current* presence. **They will disagree, and ES over-reports.** Sharpest statement of the asymmetry, from the docs: *"Fields that don't have any mapping are never included"* — the exact inverse of vmctl, where a mapping does not exist and only data is visible.

  Hence: **shape-compatible, not guarantee-compatible.** A consumer that trusts this output the way it trusts `_field_caps` will eventually be wrong about a rare field. `vmctl.docs_sampled` and `vmctl.coverage` exist so that risk is visible rather than implicit; they have no `_field_caps` equivalent because a mapping needs no such hedge.
- **Cost:** a sampling read per host × input on every invocation — cheap (`tail -n N`), but not free, and the result can change between runs as logs rotate.
- **Risk:** inferred types can be wrong for a field that is numeric in most records and a string in one. The `_field_caps` conflict model handles this correctly — both types appear — provided the sample is large enough to see both.

## Notes

- Builds on [0004](./0004-ecs-output-schema.md) (the ECS envelope is the half of the schema knowable in advance) and [0007](./0007-machine-only-interface.md) (DSL in, NDJSON out — a single JSON object satisfies both).
- Executed in [milestone 09](../milestones/09-field-discovery.md).
- **Verified against Elastic docs, 2026-07-23**, including two assumptions this ADR originally got wrong: a type entry has **11** documented keys, not the 6 first assumed; and type families do **not** collapse `integer`/`long` — only `keyword` and `text` are multi-member families.
- **Not adopted:** an `index_filter` analogue ("which fields exist among events matching X"). It is documented for `_field_caps`, but Elastic notes the filtering there is *"done on a best-effort basis… this API may return an index even if the provided filter matches no document"* — a caveat we would inherit. A refinement, not a first version.
- **No `_mapping` analogue is possible.** `_mapping` returns a declared schema; vmctl has none to return. This ADR deliberately implements the observational API and not the declarative one.
