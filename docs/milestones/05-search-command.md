---
milestone: 5
title: search command (read + KQL + pushdown)
status: planned
started: TBD
---

# M05 — `search` command (read + KQL + pushdown)

`vmctl search <profile> -q '<KQL>'` finds matching events across a deployment's hosts,
with no Elasticsearch — KQL evaluated index-less, filters pushed to the source where
sound. Implements the search mode, KQL, and three-tier pushdown of
[ADR 0005](../adr/0005-collection-and-search-execution.md). See [ROADMAP.md](ROADMAP.md).

## Scope

### A. KQL parser (subset)
- `field:value`, quoted values, `and`/`or`/`not`, ranges (`>=`/`<=`/`>`/`<`), wildcards, `exists` (`field:*`).

### B. Predicate evaluator — tier 3 (client, exact)
- Evaluate the parsed KQL against ECS events in memory; the authoritative, exact pass.

### C. Planner — tier 1 (put/structural)
- Resolve predicates on generated fields without a remote command: `host.name` → which hosts to connect to; `event.dataset` / `labels.route_id` (route logs) → which files to open (rule inversion).

### D. Pushdown — tier 2 (parsed/in-text)
- Translate parsed-field predicates to remote `find` / `grep` / `awk`: time window via lexicographic ISO comparison (multiline-safe), term greps. **Sound superset only** — never drop a true match; widen bounds outward; tier 3 refines.

### E. CLI + output
- `vmctl search <profile> -q '<KQL>' [--since/--until] [--output ndjson|human]` (`mode: read`); emit matches; report which hosts/files were scanned.

## Exit criteria

- [ ] `vmctl search test_ig -q 'event.dataset:ig.audit and http.response.statusCode:500'` returns the correct matches from both hosts.
- [ ] A time-window query demonstrably pushes down (only candidate lines transferred, verified against a full-scan baseline giving identical results).
- [ ] A `labels.route_id` query on route logs selects only that route's file (tier-1 file selection).
- [ ] KQL parser + evaluator have unit tests (incl. boolean/range/wildcard); a marked integration test runs against the live VMs.
- [ ] Pushdown is proven sound: pushed-down results equal a naive full-scan-then-filter on the same corpus.

## Non-goals (this milestone)
- Aggregations / counts / ranking (out of scope per ADR 0005).
- Offset registry / resumable collection (→ M07).

## Progress

- (not started)
