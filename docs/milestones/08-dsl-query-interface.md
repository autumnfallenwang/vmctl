---
milestone: 8
title: machine-only interface (Query DSL in, NDJSON out)
status: done
started: 2026-07-23
---

# M08 — machine-only interface (Query DSL in, NDJSON out)

Implements [ADR 0007](../adr/0007-machine-only-interface.md): vmctl is a machine
interface. `search` takes **Elasticsearch Query DSL** as its only filter, and every
command emits **NDJSON** as its only output. Runs ahead of M06/M07, which are
unstarted — the numbering keeps their committed cross-references intact.

## Scope

### A. DSL front end
- `dsl.py`: `parse_dsl(payload) -> Node` over the shared AST. `bool`, `term`, `terms`,
  `range`, `exists`, `wildcard`, `prefix`, `match_all`. Full body or bare clause.
- Unsupported constructs raise, naming the construct and why.

### B. AST extraction
- `kql.py` → `ast.py`: keep `Match`/`Not`/`And`/`Or`, drop the tokenizer and parser.
  The three tiers are untouched — they only ever walked the AST.

### C. Output
- NDJSON only. `to_human` and every `--output` flag removed; `discover` emits NDJSON too.

### D. Self-contained queries
- The time window is derived from `@timestamp` `range` predicates in the filter; the
  `--since`/`--until` flags are gone.

## Exit criteria

- [x] `vmctl search` accepts Query DSL via `--filter`, `--filter-file` and stdin.
- [x] Every unsupported construct fails loudly with a reason; none silently matches all.
- [x] NDJSON is the only output; no `--output` flag exists on any subcommand.
- [x] A `@timestamp` range in the filter reaches the remote `awk` (verified by test and live).
- [x] Full check loop green; live suite green, including the soundness comparison.

## Progress

- 2026-07-23: Milestone opened and completed. `dsl.py` (+ `ast.py` extracted from
  `kql.py`, which is deleted along with its 18 tests); `--filter` / `--filter-file` /
  stdin; `to_human`, `--output`, `--since`, `--until` removed; `discover` now NDJSON.
  Tier tests rewritten to build filters through `parse_dsl` — they exercise the real
  input path instead of a test-only convenience. 146 fast tests (was 124) + 5 live.

## Outcome

vmctl now speaks one language in and one out, both of them ELK wire formats: Query DSL
in, ECS NDJSON out. The three tiers did not change at all — the AST was already the
seam, so swapping the front end cost one module and no engine work, which is the payoff
for having kept the AST pure data in M05.

Two improvements fell out of the change rather than being aimed at. **The filter now
carries its own time bounds**: a `range` on `@timestamp` feeds the tier-2 `awk` window,
which the KQL path never did — a `@timestamp` predicate used to be evaluated only on the
client while the remote window came solely from CLI flags. And **tier 3 now compares
timestamps as instants** rather than lexicographically, so a bound written `...Z` and an
event written `...+00:00` order correctly; the remote pass stays lexicographic, which is
sound because it only has to be a superset.

Deliberately rejected rather than approximated: `match` and the full-text family (no
analyzer), scoring constructs (no ranking), index topology (no index). Each raises with
a reason. The alternative — accepting `match` and quietly doing exact comparison — would
have produced wrong answers that look like Elasticsearch's, which is worse than a refusal.

Cost, stated plainly: this deleted `kql.py` and its 18 tests one day after they shipped
in M05, and hand-typing a filter is now materially more verbose. That was the accepted
price of the machine-only framing.

Fixed in passing: `test_pushdown_is_sound` drove fresh traffic and then excluded it with
a window ending a minute in the past — a guard written when the audit-flush latency was
mismeasured as ~20s. Now that it is measured at ~1.06s, the test waits for the flush and
bounds exactly the traffic it generated.

Closed: 2026-07-23
