---
milestone: 11
title: Minimal-by-default parsing (raw + timestamp; extraction declared)
status: planned
started: TBD
---

# M11 — Minimal-by-default parsing

Implement [ADR 0010](../adr/0010-minimal-default-parsing.md): the raw line is always in
`message`, `@timestamp` is the only field parsed from content by default (and is per-input
configurable), and every other extraction is profile-declared. The ECS put/metadata envelope
([ADR 0004](../adr/0004-ecs-output-schema.md)) is unchanged.

## Scope

### A. `message` is always the raw line
- `event.py build_event`: set `message = frame.raw` for **every** record (parsed or not).
- Remove `event.original` (the duplicate). Remove the `_jsonparsefailure`-only-has-message branch —
  `message` is now unconditional; the failure tag stays.
- `raw_line()` / the `to_human`(gone) / grok-`message` source / timestamp fallback all read `message`.

### B. Remove default content-parsing
- Delete `_mirror_route_id` from `enrich`. No `ig.routeId` (or anything else) is auto-extracted.
- `_RESERVED` / merge logic unchanged (JSON codec still merges — opt-in by codec).

### C. `@timestamp` — the one default parse, made configurable
- Keep the sensible default: a merged `timestamp` field, else a leading ISO token.
- Add a per-input **`timestamp`** config so other shapes parse correctly:
  - `timestamp.field: <name>` — take event-time from this parsed JSON field.
  - `timestamp.pattern: <regex>` + `timestamp.format: <strptime>` — extract + parse from the raw line.
  - When nothing matches (line has no full timestamp, e.g. time-only), fall back to `event.created`
    (read time) — the honest default, documented, not silent-wrong for the configured case.
- `config.py`: parse the new `Input.timestamp` block (optional; default = today's auto-detect).

### D. Move IG's route_id into the profile
- `vmctl.example.yml` (+ the gitignored `vmctl.yml`): add a filter to `test_ig` that mirrors
  `[ig][routeId]` → `labels.route_id` for `ig-audit`, alongside the existing `route-*.log` filename
  grok. Behaviour preserved; now declared. Requires a small `filters.py` addition: mirror a JSON
  field to a label (not only grok on `path`/`message`).

## Exit criteria

- [ ] Every event carries the raw line in `message` (json and text); no `event.original`.
- [ ] No field is extracted from content by default except `@timestamp`; `ig.routeId` auto-mirror is gone.
- [ ] A per-input `timestamp` config yields a correct event-time `@timestamp` for a text log that
      does not lead with ISO (verified against catalina / DS errors on the AM lab).
- [ ] `test_ig` reproduces `labels.route_id` via a declared filter — IG behaviour unchanged.
- [ ] `test_am` audit still parses `@timestamp` from its `timestamp` field with no per-input config.
- [ ] Check loop green; the corpus/pipeline tests updated to the new contract; live tests green.

## Non-goals (this milestone)
- Deriving a full date for time-only logs from filenames/rotation (read-time fallback is acceptable).
- Any change to the ECS put/metadata envelope — it stays as ADR 0004 defines it.
- A general Logstash `date`-filter clone beyond the per-input timestamp config above.

## Progress

- 2026-07-24: Shipped all four tracks. **A**: `message` now always holds the raw line (parsed
  and unparsed); `event.original` removed. **B**: deleted `_mirror_route_id` — nothing but
  `@timestamp` is parsed from content by default; dropped `event.original` from pushdown's
  `_PUT_FIELDS`. **C**: `TimestampSpec` (`field` | `pattern`+`format`) per input, threaded
  `assemble → enrich → _apply_event_time`; default auto-detect unchanged; a miss falls back to
  read time. **D**: grok sources now accept a `[a][b]` field ref, so `test_ig` declares audit
  `route_id` via `grok: {'[ig][routeId]': '%{GREEDYDATA:route_id}'}` (mirror→filter, transparent
  to the pipeline tests). 174 fast tests (was 148) + 7 live, green first pass. **Verified live:**
  IG audit — raw in `message`, `route_id` via the filter, no `event.original`; DS `errors` —
  `@timestamp` parsed to event time (`00:14:45` from `[24/Jul/2026:00:14:45 +0000]`) once the
  per-input `timestamp` config is declared. All exit criteria met.
