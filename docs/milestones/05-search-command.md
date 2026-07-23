---
milestone: 5
title: search command (read + KQL + pushdown)
status: done
started: 2026-07-23
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

- [x] `vmctl search test_ig -q 'event.dataset:ig-audit and response.statusCode:200'` returns the correct matches from both hosts. *(Field paths corrected to the real audit shape: the dataset is the input `type` `ig-audit`, and IG writes a top-level `response.statusCode` — as a string — not `http.response.statusCode`.)*
- [x] A time-window query demonstrably pushes down (only candidate lines transferred, verified against a full-scan baseline giving identical results). *(A 10s window transferred 3.3% of the bytes — 5 of 151 lines.)*
- [x] A `labels.route_id` query on route logs selects only that route's file (tier-1 file selection).
- [x] KQL parser + evaluator have unit tests (incl. boolean/range/wildcard); a marked integration test runs against the live VMs.
- [x] Pushdown is proven sound: pushed-down results equal a naive full-scan-then-filter on the same corpus. *(`test_pushdown_is_sound` runs the same query with and without `--no-pushdown` and asserts set equality.)*

## Non-goals (this milestone)
- Aggregations / counts / ranking (out of scope per ADR 0005).
- Offset registry / resumable collection (→ M07).

## Progress

- 2026-07-23: Milestone opened.
- 2026-07-23: Tracks A+B shipped — the client-side KQL engine, no SSH yet. **A**: `kql.py`
  tokenizer + recursive-descent parser producing a *pure-data* AST (`Match`/`Not`/`And`/`Or`)
  so tiers 1–3 can each walk the same tree; supports `field:value`, quoted values,
  `and`/`or`/`not` (case-insensitive, `not` > `and` > `or`), parentheses, ranges
  (`>=`/`<=`/`>`/`<`, spaces optional), wildcards, and exists (`field:*`). **B**: `query.py`
  tier-3 exact evaluator — `matches(node, event)` plus `resolve_field`, which resolves dotted
  paths against both nested and flat-dotted ECS shapes; numeric compare when both sides are
  numeric, else lexicographic (exactly ADR 0005's UTC-ISO time mechanics). 26 new tests
  (86 fast total); lint/typecheck/tests green first pass.
  Subset bounds (deliberate): no implicit-AND, no bare free-text terms, no value grouping
  `field:(a or b)`. Remaining for M05: C (tier-1 planner), D (tier-2 pushdown), E (CLI).
- 2026-07-23: Tracks C+D+E shipped — `vmctl search` is live. **C** `planner.py`: three-valued
  pruning of hosts/inputs/files from top-level AND conjuncts; a field the planner can't see is
  UNKNOWN, never false, so a wrong prune can't lose matches. Route-log file selection reuses
  `apply_filters` *forward* against each candidate path instead of inverting the grok — the same
  field is tier-1 for `ig-route` (id in the filename) and tier-3 for `ig-audit` (id in the body),
  with no special-casing. **D** `pushdown.py`: `awk` time window on the shared 19-char ISO prefix
  (sidesteps the audit's dot-millis vs text logs' comma-millis), multiline-safe by *carrying* the
  timestamp line's decision onto `[CONTINUED]` and blank continuation lines; guarded `grep -F`
  terms for `json` inputs only. Truncating bounds is already the outward widening ADR 0005 asks
  for (flooring is monotonic). **E** `search.py` + CLI: `vmctl search <profile> -q KQL
  [--type|--since|--until|--output|--file|--no-pushdown]`, matches buffered and emitted in
  `@timestamp` order. 33 new tests (118 fast) — the pushdown tests **execute the generated awk**
  against the real corpus rather than string-comparing commands — plus 3 live tests. Verified
  live against both VMs; a 10s window transferred 3.3% of the bytes. Two decisions recorded as
  ADR 0005 amendments (`mode` is not a search filter; pushdown scope). **All exit criteria met.**

## Outcome

Shipped `vmctl search` — index-less KQL over logs on the boxes, with ADR 0005's three-tier
predicate resolution fully realised: the **planner** decides what to read (hosts, inputs, files),
**pushdown** filters at the source with `awk`/`grep`, and the **client** evaluates every result
exactly. Tiers 1–2 only ever narrow; tier 3 alone decides, so an over-eager pushdown costs
bandwidth, never correctness. `vmctl search <profile> -q KQL [--type|--since|--until|--output|
--file|--no-pushdown]`, results merged across hosts in `@timestamp` order. 118 fast tests +
5 live.

Deviations from the original scope, all recorded as ADR 0005 amendments: `search` **ignores
`mode`** (a literal `mode: read` reading would have matched zero inputs in every profile we
have, for no gain); term-grep pushdown is **restricted to single-line `json` inputs**, because a
`grep` would silently split multi-line text events by dropping their `[CONTINUED]` and blank
continuation lines. Two exit criteria named fields that don't exist in the real audit log
(`http.response.statusCode`, dataset `ig.audit`) and were corrected against the corpus —
IG writes a top-level `response.statusCode`, as a *string*.

Lessons worth caching. **A live-lab measurement needs isolating before it becomes a claim.** Two
ad-hoc pushdown measurements returned zero rows and I inferred "the IG audit handler buffers
~20 s" from them. Measured properly afterwards — fire one request, poll the remote file until
the line appears — the flush is **~1.06 s, and consistent to a hundredth across five trials**;
host clocks are in sync to 0.00 s. The 20 s figure does not reproduce and was wrong. What went
wrong in the original runs was never isolated, so the honest conclusion is about method, not IG:
don't promote a number from a one-shot script that has several uncontrolled variables in it.
The integration test still closes its window a minute in the past — that guard is right on its
own merits (it makes the test independent of flush latency entirely), just not for the reason
first written down.

Also: **a pushdown is only as trustworthy as its test**, so the tier-2 tests execute the
generated `awk` against the real corpus rather than string-comparing commands. Known wart:
`_remote_path` is duplicated in `tail.py` and `search.py`.

Closed: 2026-07-23
