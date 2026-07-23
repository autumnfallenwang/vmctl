# 0007 — Machine-only interface: Query DSL in, NDJSON out

- **Status:** accepted
- **Date:** 2026-07-23
- **Deciders:** project founder

## Context

[ADR 0005](./0005-collection-and-search-execution.md) chose **KQL** as the search query language and, in a later amendment, made **NDJSON the default output** while keeping a human-readable rendering behind `--output human`. Both decisions assumed vmctl serves two audiences at once: a person debugging at a terminal, and an AI agent or pipeline consuming records.

That assumption is now retired. **vmctl is a machine interface.** Its consumers are agents, scripts and pipelines; a human reading raw output is not a case worth designing for. `docs/architecture.md` already frames the tool as "easy for both humans and AI agents to drive" — this ADR resolves that tension in favour of the machine, because every place the two pull apart, serving both costs a second code path, a second format to document, and a second way for the two to disagree.

Two concrete forces made the split visible:

- **Query input.** KQL is a *Kibana UI* language, built so a person can type a filter into a search bar. Elasticsearch's own query-language table lists KQL's API endpoint as `N/A`; the wire format that Elasticsearch actually accepts is **Query DSL** — JSON. An agent emitting JSON is emitting the native format; an agent emitting KQL is emitting a UI convenience that then has to be translated.
- **Output.** The human renderer (`<@timestamp>  <host>  <dataset>[<route>]  | <first line>`) is a lossy *view* of a record whose full content is already in the NDJSON. It exists only to be read by eye.

## Decision

**Query DSL (JSON) is the only query input. NDJSON (one ECS event per line) is the only output.**

- **In:** a filter expressed as Elasticsearch **Query DSL**, the same JSON that would go in the body of `POST /<index>/_search`. The KQL parser and the `-q` flag are removed.
- **Out:** NDJSON only. `to_human` and the `--output` flag are removed from `tail` and `search`.

### Supported DSL subset — filter context only

vmctl has **no index, no field mappings and no analyzer**, so it implements the constructs whose meaning survives that, and **rejects the rest with an explicit error naming the construct**:

| Supported | Meaning |
|---|---|
| `bool` with `filter` / `must` / `must_not` / `should` (+ `minimum_should_match`) | AND / AND / NOT / OR |
| `term`, `terms` | exact value, exact value in a set |
| `range` (`gte` / `gt` / `lte` / `lt`) | comparison — numeric when both sides are numeric, else lexicographic |
| `exists` | field is present |
| `wildcard`, `prefix` | pattern match |
| `match_all` | everything |

`must` and `filter` are both treated as AND: the difference between them in Elasticsearch is *scoring*, and vmctl does not score — a log line either matches or it does not.

**Deliberately rejected**, rather than approximated:

- **`match` and the full-text family** (`match_phrase`, `multi_match`, `query_string`, …). `match` means *analyzed* comparison — tokenised, lowercased, possibly stemmed, against a mapping. Without an analyzer, a `match` that quietly did exact comparison would look like Elasticsearch and behave differently. A wrong answer that resembles a right one is worse than a refusal.
- **Scoring-only constructs** — `boost`, `function_score`, `dis_max`, `boosting`. Meaningless without ranking.
- **Index-topology constructs** — `nested`, `has_child`, `has_parent`, `percolate`, joins.

An unsupported construct is an **error**, never a silent no-op: a filter that silently matched everything would return wrong results that look plausible.

### Compatibility is a subset claim, not an equivalence claim

The **syntax** is genuine Query DSL: anything vmctl accepts is a valid Elasticsearch query. The **semantics** are not universally identical, because Elasticsearch's semantics are defined by an index and field mappings that vmctl does not have. Stated precisely so nobody has to discover it the hard way:

| Case | vmctl | Elasticsearch |
|---|---|---|
| Scalar `keyword`-like fields (nearly all of ECS, and every IG audit field) | equivalent | equivalent |
| Multi-valued (array) fields | matches if **any** element matches | same |
| `exists` on `[]` or `[null]` | absent | absent |
| `term` on an **analyzed `text`** field | matches the whole stored string | usually **no match** — the index holds analyzed tokens |
| Numeric/string coercion | numeric when both sides parse as numbers | driven by the field mapping |
| Result order | `@timestamp` ascending | relevance score |

The `text`-field row is irreconcilable: the correct answer depends on an analyzer chain that only exists inside an index. It is the same reason `match` is rejected outright — and the reason this ADR claims *"a compatible subset with mapping-free semantics"* rather than "100% compatible".

The array and empty-array rows were **wrong in the first implementation** and fixed on 2026-07-23; they are listed here because they are exactly the kind of silent divergence this table exists to prevent.

### Accepted shapes

Both a full search body and a bare query clause are accepted, because both are things a user or agent will paste:

```json
{"query": {"bool": {"filter": [{"term": {"event.dataset": "ig-audit"}}]}}}
{"bool": {"filter": [{"term": {"event.dataset": "ig-audit"}}]}}
```

Keys outside `query` in a full search body (`size`, `sort`, `aggs`, `_source`, …) are **rejected**, not ignored — they imply behaviour vmctl does not have, and silently dropping `size: 10` would badly mislead.

### Time window

A `range` on `@timestamp` inside the filter **is** the time window: it feeds the tier-2 remote `awk` pushdown directly, so the query carries its own bounds. Elasticsearch date math (`now-1d/d`) is **not** supported — absolute ISO-8601 only; unsupported date expressions are an error.

## Consequences

- **Positive:** one input format and one output format, both already the ELK wire formats — nothing to translate, nothing bespoke to document. Removes a parser, a renderer, a CLI flag and two code paths. The query becomes self-contained: bounds travel inside it instead of in sibling flags. Copy-paste works both ways with Kibana DevTools.
- **Negative — this is a real cost, not a rounding error:** a hand-typed query goes from `-q 'response.statusCode:500'` to a JSON object. Interactive use gets materially worse; that is the accepted price of the machine-only framing, and `jq` remains the reader of last resort for output.
- **Removes shipped, tested code.** The KQL parser (`kql.py`) and its tests were completed and committed in M05, one day before this reversal. The AST it produced is *kept* — the planner, pushdown and evaluator all walk it — so what is deleted is the front end, not the engine.
- **Risk:** the rejected-construct list must stay honest as the DSL surface grows. The failure mode to guard against is accepting a construct and half-implementing it; the test suite asserts that each rejected construct raises.
- **`discover` is unchanged for now** — it prints a per-host file listing, not events. Whether it also becomes NDJSON is deferred, and flagged in the milestone.

## Notes

- **Supersedes** the "Query language: KQL, evaluated index-less" decision in [0005](./0005-collection-and-search-execution.md), and its 2026-07-23 amendment making NDJSON the *default* output (it is now the *only* output). The rest of 0005 — two modes, three-tier resolution, pushdown soundness, time-window mechanics — stands unchanged, and the three tiers are untouched by this ADR.
- Does not affect [0004](./0004-ecs-output-schema.md): the emitted event shape is still ECS, still `message` XOR `event.original`.
- **Verified against Elastic docs, 2026-07-23:** Query DSL travels in the request body of `GET|POST /<index>/_search`; the URI form `?q=` is *Lucene* syntax, "does not support the full Elasticsearch Query DSL", and silently overrides a body query. In `bool`, *"Each query defined under a `filter` acts as a logical AND"*, and `filter` differs from `must` only in that scoring is ignored. The docs warn `term` is the wrong tool for analyzed `text` fields — which is precisely why `match` cannot be faked here.
- **Noted, not adopted:** Elasticsearch 9.1+ and Serverless expose a native `kql` query (`{"query":{"kql":{"query":"..."}}}`) that is "parsed using the Kibana Query Language and rewritten into standard Query DSL". If KQL is ever wanted again, that is the Elastic-sanctioned way back in — as a construct *inside* the DSL, not as a competing CLI flag.
