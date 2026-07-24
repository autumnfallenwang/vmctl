# 0011 — `search --limit`: bounded early-exit trades global time-order

- **Status:** accepted
- **Date:** 2026-07-24
- **Deciders:** Aaron Wang

## Context

Real-environment use surfaced a footgun (M12 finding #5): a broad `search` (e.g.
`{"exists": {"field": "component"}}`) against large multi-host files has no way to be bounded at the
tool level. It scans every candidate byte on every host, buffers **every** match in memory, and only
then emits — so an exploratory "just show me a few" appears to hang and often has to be killed. A
shell limiter (`head`, `Select-Object -First N`) doesn't help: the process keeps scanning and
emitting regardless.

The obvious fix — "add `--limit N` that stops scanning once N matches are found" — collides with an
existing behavioural contract: `run_search` collects matches from all hosts (which run concurrently),
sorts them by `@timestamp`, and emits in chronological order. You cannot both **stop early** and
**guarantee the N globally-earliest** results, because the earliest match might live in a file you'd
skip by stopping. So `--limit` forces a choice:

- **(a) Cap output only** — scan everything, sort, emit the first N. Preserves "N earliest" but does
  **not** fix the hang: the expensive full scan still happens. Defeats the purpose.
- **(b) Bounded early-exit** — stop issuing remote reads once N matches are collected, then sort and
  truncate those to N. Fixes the cost, but the N returned are *some* N (the earliest among what was
  scanned before stopping), not provably the global earliest.

## Decision

Implement **(b)**: `--limit N` stops the scan once N matches have been collected across hosts, then
time-sorts and truncates the collected set to N. `--limit` is opt-in; without it, `search` keeps its
current exhaustive, fully-ordered behaviour unchanged.

The ordering caveat is documented at the point of use (`--help` + README): *`--limit` returns some N
matches, not guaranteed the N earliest — tighten the `@timestamp` range in the filter for a
deterministic window.* Option (a) was rejected because the stated motivation is cost/hang, which (a)
does not address.

## Consequences

- **Easier:** broad, exploratory queries become cheap and safe — bounded work, bounded memory,
  prompt exit. No more `--file` + manual truncation just to sample a dataset's shape.
- **Harder / to live with:** `--limit` results are not a stable, globally-ordered top-N. Because
  hosts scan concurrently, the exact set (and count, which may momentarily exceed N before the stop
  is observed, then truncates) can vary run to run. This is the deliberate trade for early exit.
- **Unchanged:** default `search` (no `--limit`) still returns the complete, `@timestamp`-ordered
  result set — the soundness contract of the three-tier pushdown is untouched.
- **Risk to track:** users who assume `--limit` means "earliest N" get surprised. Mitigated by the
  documented caveat and by recommending a bounded `@timestamp` range for determinism.

## Notes

- Relates to [ADR 0005](./0005-collection-and-search-execution.md) (collection/search execution model)
  and [milestone 12](../milestones/12-field-findings-fixes.md).

- **2026-07-24 follow-up (research).** Evaluated a streaming **k-way merge** as the "best" design —
  each source yields events in `@timestamp` order, a heap merges them, early-exit returns a *true*
  global top-N. **Rejected as unsound.** vmctl stamps any line whose timestamp can't be parsed with
  the **collection time** (`now()`) — see `testenv/corpus/broken.jsonl` — so a source is **not**
  monotonic in `@timestamp`: one garbage line spikes hours ahead, its stream-head is never the
  heap minimum, so it stalls the merge and starves the lines after it. (Concurrent logback writers
  add ms-scale inversions, and dateless-leading logs like `am-debug`/`am-container` get
  collection-time throughout.) No cheap reorder window survives the `now()` spike. So this ADR's
  central claim is *more* fundamental than first stated — a streaming merge cannot cheaply restore
  the global top-N either. The idea is **rejected, not deferred.**
- The **sound** fix for the memory/hang that motivated all this is smaller and separate: stream
  each file's read (`conn.stream` instead of `conn.run`, still **sequential** per host, so no new
  SSH-channel pressure) so a broad query never materializes a whole 238 MB file in memory — with
  **no ordering change and no monotonicity assumption**. Note `--limit` bounds the *result* buffer
  but not the *per-file read* buffer; the streaming read is what bounds the latter.
