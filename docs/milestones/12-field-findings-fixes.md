---
milestone: 12
title: Field findings — fixes + scaling follow-ups
status: done
started: 2026-07-24
closed: 2026-07-24
---

# M12 — Field findings (fixes + scaling follow-ups)

First real-environment use of vmctl (a live ForgeRock SSO deployment, outside the two-VM lab)
surfaced **five** findings — 1 bug, 2 defects, 2 enhancements. Each was reviewed against the source
before scoping (verdicts below); the raw write-ups live in the gitignored `screenshots/` folder.

All five are **shipped** (Part 1). Two of them (#2, #5) had real design forks, so they went through a
research round; the resulting *correct scalable* answers are **Part 2**, also shipped. Bug work follows
reproduce → fix → verify.

## The five findings (verified against the code)

| # | Kind | Verdict after code review | Fix site |
|---|---|---|---|
| 1 | **Bug** (High) | **Confirmed.** `_remote_path` joins `base_dir` unconditionally; an **absolute** input glob comes back absolute from the remote glob, so the join doubles it (`/base//abs/path`) → reads a nonexistent file → `0 match(es)`, no error. Missed by the suite because every committed profile uses *relative* globs under `base_dir`. | `search.py`, `tail.py` |
| 2 | **Defect** (Medium) | **Confirmed.** `tail` opens one SSH channel per matched file (`create_process`), all concurrent on one connection; >10 files trips OpenSSH's default `MaxSessions=10`. `search` is immune (reads sequentially). | `tail.py`, `config.py` |
| 3 | **Defect** (Low-Med) | **Real, but the write-up's fix is already half-shipped.** PowerShell mangles inline `--filter '{...}'` quotes reaching the `.exe` (external, not a vmctl code bug). vmctl *already* reads the filter from stdin when both flags are omitted — so the remedy exists; what's missing is **docs** + the explicit `--filter -` sentinel. | `cli.py`, `README.md` |
| 4 | **Enhancement** (Low) | **Confirmed.** No host-scoping flag — `search`/`tail` always span every `profile.hosts`. | `cli.py`, `search.py`, `tail.py` |
| 5 | **Enhancement** (Low-Med) | **Real, with a design fork.** No `--limit`. `search` buffers every match then time-sorts globally before emitting, so "stop scanning at N" can't also keep the global order. Decision recorded in [ADR 0011](../adr/0011-search-result-limit.md). | `cli.py`, `search.py` |

---

# Part 1 — The five fixes ✅ shipped

- **#1 Bug — absolute-glob path doubling.** Both `_remote_path`s skip the join when `rel` is already
  absolute, keeping the single-quote guard. Reproduced red first, then fixed, then green.
- **#2 Defect — tail vs MaxSessions (interim).** Profile-level `max_concurrent_files` (default 8);
  `tail` refuses an over-cap host with one clear, actionable error instead of N cryptic
  `open failed`s. *(A "semaphore queue" was rejected — it starves the never-completing `tail -F`
  streams. The real fix is Part 2A.)*
- **#3 Defect — `--filter` on Windows/PowerShell.** `--filter -` sentinel reads stdin; PowerShell
  gotcha + `--filter-file`/stdin remedies documented in `--help` and README.
- **#4 Enhancement — host scoping.** `--host <name>` (repeatable **and** comma-separated) on
  `search` and `tail`; unknown host is a loud error, consistent with `--type`.
- **#5 Enhancement — bounded result count.** `--limit N` on `search` per
  [ADR 0011](../adr/0011-search-result-limit.md): stop once N matches are collected, then time-sort
  and truncate — "earliest N found", not a global top-N.

## Exit criteria — Part 1

- [x] #1 reproduce test written and shown red, then green after the fix; both `_remote_path`s skip the join for absolute paths.
- [x] #2 `max_concurrent_files` parsed from config (default 8); `tail` refuses an over-cap host with one clear error; unit-tested.
- [x] #3 `--filter -` reads stdin; PowerShell caveat documented in `--help` + README.
- [x] #4 `--host` scopes both commands (repeatable + comma list); unknown host errors; unit-tested.
- [x] #5 `--limit N` bounds `search` per ADR 0011; unit-tested.
- [x] Check loop green (ruff + pyright + fast pytest); README/ROADMAP updated.

---

# Part 2 — Scaling follow-ups ✅ shipped

The answers the research round validated. Both are **scale** fixes for real-deployment sizes;
neither changes output semantics.

## A. `tail`: multiplex one `tail -F` per input ([ADR 0012](../adr/0012-tail-multiplex-per-input.md))

Replaces Part 1's `max_concurrent_files` stopgap with the real fix — channels per host drop from
Σfiles (67+) to #inputs (1–5), clearing `MaxSessions` without touching the remote host.

- `_tail_cmd(file, …)` → `_tail_cmd_multi(paths, start_position)`: `tail -n {start} -F 'f1' 'f2' …`,
  reusing the existing single-quote refusal per path.
- `stream_file_events` (per file) → `stream_input_events(conn, *, host, profile, inp, file_paths)`:
  - one `make_codec(inp.codec)` per path in a `dict[str, Codec]`;
  - `current = paths[0]` when the input matches exactly one file (a single-file `tail` prints **no**
    header), else `None` until the first header;
  - treat a line as a header only when it matches `^==> (.*) <==$` **and** the path is in the known
    set passed to this `tail` (spoof guard);
  - one-line lookahead to swallow the blank separator that precedes every header but the first;
  - `flush()` **every** codec on stream end (preserves today's trailing-multiline behaviour).
- `tail_session`: group pending files by input → one `pump` task **per input**, not per file.
- Re-purpose `max_concurrent_files` into a per-input chunk size / channel-count guard; relax
  `_TooManyFiles` to fire only on a channel-count breach. `transport.py` and `codecs.py` unchanged.

## B. `search`: stream the per-file read ([ADR 0011](../adr/0011-search-result-limit.md) follow-up)

The sound half of #5 — the k-way merge was rejected as unsound; this is what actually fixes the
memory/hang.

- `read_file`: `conn.run` → `conn.stream`, feeding the codec incrementally instead of materialising
  the whole filtered file as one string. Stays **sequential** per host, so no new channel pressure.
- Output ordering **unchanged** (matches still buffer + global sort); only the per-file read buffer
  becomes bounded. Lets `--limit` bail mid-file instead of after slurping the rest.

## Exit criteria — Part 2

- [x] **Gate for A — live Rocky 9 check first:** confirmed on ig1 (coreutils **8.32**) — header is
      `==> a.log <==` (verbatim absolute arg), emitted **only on a switch** (`a2`+`a3` shared one
      header), **every header but the first preceded by exactly one blank separator**, **no header
      at all for a single-file tail**, and rotation notices (`has become inaccessible` / `has
      appeared`) on **stderr** while data stayed on stdout. ADR 0012 validated as written.
- [x] `tail` streams all of an input's files over **one** channel per input; per-file attribution
      (`log.file.path`, filename `route_id`) and multiline framing unchanged; a file count above the
      old cap no longer refuses the host (12 files → 1 channel, rc 0).
- [x] Header-spoof guard covered by a test (a log line equal to `==> <path> <==` is only honoured
      when that path was passed to the tail).
- [x] `search`: measured against the live lab on a 108 MB / 400k-line file — `stream()` moved peak
      RSS **+1.3 MB**, the old `run()` **+247 MB** (~2.3× file size). Streaming read bounds it;
      output semantics unchanged.
- [x] Check loop green (ruff clean, pyright 0, 197 fast tests); README updated (`tail` bounded by
      #inputs not #files; `max_concurrent_files` re-documented as a channel cap).

## Risks — Part 2

- Coreutils version drift (8.32 lab vs 9.11 tested) — the gating criterion above.
- Multiline partial event across a rotation boundary — **pre-existing**, not a regression; confirm
  acceptable for the lab's multiline route logs.
- inotify limits (`max_user_instances` / `max_user_watches`) on the locked-down RHEL image; per-input
  tails use *fewer* instances than today's per-file tails, so no new pressure expected.
- ARG_MAX for a glob matching thousands of files — the per-input chunking valve covers it.

---

## Non-goals

- Restoring a true global top-N for `search --limit` — rejected as unsound in
  [ADR 0011](../adr/0011-search-result-limit.md) (parse-miss lines get a collection-time
  `@timestamp`, so sources aren't monotonic).
- Multi-connection-per-host fan-out for `tail` — rejected in
  [ADR 0012](../adr/0012-tail-multiplex-per-input.md).

## Progress

- 2026-07-24: Reviewed all five findings against source before scoping — confirmed #1 (High
  bug, silent data loss), #2, #4; corrected #3 (stdin already ships — remedy is docs + the
  `--filter -` sentinel) and #5 (early-exit can't keep the global time-order → [ADR 0011](../adr/0011-search-result-limit.md)).
- 2026-07-24: **Bug #1 reproduced red first** (`_remote_path("/base","/abs")` doubled to
  `/base//abs`; end-to-end read hit `cat '/opt/ssologs//opt/sso/...'`), then fixed in both
  `search.py`/`tail.py` (skip the join when the discovered path is already absolute), then green.
- 2026-07-24: **All five shipped.** #2 `max_concurrent_files` (config, default 8) — `tail`
  gathers matched files per host and refuses over-cap with one actionable error instead of N
  cryptic `open failed`s. #3 `--filter -` reads stdin + PowerShell caveat in `--help`/README. #4
  `--host` (repeatable + comma list) on both commands, unknown host is a loud error. #5 `--limit N`
  on `search` per ADR 0011. Check loop green: ruff clean, pyright 0, 193 fast tests (was 174).
- 2026-07-24 (research follow-up): researched the two findings with real design forks. **#5:** the
  streaming **k-way merge is rejected as unsound** — parse-miss lines get a `now()` `@timestamp`
  (`testenv/corpus/broken.jsonl`), so sources aren't monotonic and a heap merge stalls/misorders; the
  sound path is a streaming per-file read (Part 2B). **#2:** multiplex one `tail -F` per **input**,
  routing by the `==> path <==` header — channels per host drop 67 → ~1-5 with no sshd change;
  multi-connection fan-out rejected ([ADR 0012](../adr/0012-tail-multiplex-per-input.md)) → Part 2A.
- 2026-07-24: Milestone **reopened** and merged with the former M13 — Part 1 (shipped) + Part 2
  (open) now live in one place.
- 2026-07-24: **Part 2 shipped.** Gate first: probed `tail -F` on ig1 (coreutils 8.32) and confirmed
  every assumption ADR 0012 rests on. **A —** `stream_file_events` → `stream_input_events`: one
  `tail -F` per input over a single channel, per-file codec dict, `current`-file pointer set by
  headers restricted to the known path set (spoof guard), one-line lookahead to drop tail's blank
  separator, single-file pre-assign, flush-all on stream end; `tail_session` groups by input;
  `max_concurrent_files` now caps *channels*. **B —** `read_file` reads via `conn.stream` (wrapped in
  `aclosing`) instead of `conn.run`, feeding the codec incrementally and bailing mid-file once
  `--limit` is satisfied; `Connection.stream` retyped `AsyncGenerator` for deterministic close.
  Measured on the lab: 108 MB read cost **+1.3 MB** streaming vs **+247 MB** buffered. 197 fast tests
  green (was 193).

## Outcome — Part 2

Both scalable answers shipped, each gated on evidence rather than assumption. **A:** the
`tail -F` behaviour ADR 0012 depends on was probed on the actual target (Rocky 9, coreutils 8.32)
*before* any code — headers on switch only, blank separator, no header for a single file, notices on
stderr — all confirmed; `tail` now follows an entire input over one channel, so 67 route logs cost
one session instead of 67 and `MaxSessions` stops being a ceiling. **B:** the k-way merge stayed
rejected; the streaming per-file read was measured on a 108 MB file (+1.3 MB vs +247 MB), proving it
fixes the memory blowup that `--limit` alone could not, with output semantics untouched.

## Outcome — Part 1

Shipped all five field findings. The headline win is **bug #1** — a High-severity silent
zero-results bug when an input uses an absolute `path` glob under a set `base_dir`; fixed
reproduce-first in both read and tail paths. Notable deviations from the raw write-ups, made after
code review: #2's suggested "semaphore queue" was rejected (starves infinite `tail -F`) in favour of
a loud, configurable cap; #3 turned out already half-solved (stdin shipped) so it became docs + a
`-` sentinel; #5's "stop scanning at N" was reconciled with the existing global time-sort via
ADR 0011. Part 2 carries the two scalable answers that research validated.
