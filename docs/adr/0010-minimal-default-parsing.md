# 0010 — Minimal-by-default parsing: raw + timestamp only, extraction is declared

- **Status:** accepted
- **Date:** 2026-07-24
- **Deciders:** project founder

## Context

vmctl turns a raw log line into an ECS event in two moves ([ADR 0005](./0005-collection-and-search-execution.md)'s put-vs-parse split):

- **put** — metadata vmctl *generates* about the collection: `host.name`, `agent.*`,
  `log.file.path`, `event.dataset`, `event.created`, `labels.profile`, `ecs.version`, `@timestamp`.
- **parse** — fields vmctl *extracts from the log's own content*.

Over M03–M10 the *parse* side accreted behaviour that is neither raw-faithful nor product-neutral,
exposed sharply by adding AM (M10):

1. **The raw line is not always in `message`.** [ADR 0004](./0004-ecs-output-schema.md)'s 2026-07-23
   amendment made it `message` XOR `event.original` — a parsed JSON record *drops* `message`. So
   "give me the raw line" depends on whether the codec parsed it.
2. **One product's parsing is hardcoded.** `event.py` auto-mirrors `ig.routeId → labels.route_id`
   for every event, always — IG-specific content-parsing baked into the core, inert for AM.
3. **`@timestamp` is only right by luck.** vmctl parses a *leading* ISO-8601 token; AM/DS audit JSON
   works (via the `timestamp` field), but text logs whose lines lead with `HH:MM:SS` (catalina) or
   `[dd/Mon/yyyy…]` (DS errors) silently fall back to *read* time instead of *event* time.

The founder's rule resolves all three: **do the minimum by default, extract only when asked.**

## Decision

**Metadata is always present and ELK/ECS-compatible; content-parsing is minimal by default and
everything beyond the timestamp is declared in the profile.** Concretely:

- **`message` always carries the whole raw line** — for parsed (`json`) *and* unparsed records
  alike. It is never dropped. `event.original` (a duplicate copy) is removed.
- **The only field parsed from content by default is `@timestamp`.** It keeps its sensible
  auto-detection (a `timestamp` JSON field, or a leading ISO token), and becomes
  **per-input configurable** so a log whose event-time is elsewhere or in another format still
  gets a correct `@timestamp` — the one thing vmctl is *required* to get right.
- **No other content is parsed automatically.** The hardcoded `ig.routeId → labels.route_id`
  mirror is **removed**. Any extraction — a `route_id`, a promoted field, a label — happens
  **only when a profile filter declares it**, and appears only then.
- **The put/metadata envelope is unchanged and stays ECS-compatible** ([ADR 0004](./0004-ecs-output-schema.md)).
  "Nothing more added" governs *parsing*, not metadata — vmctl still labels its own output fully.
- **`codec: json` still merges the record's fields to the top level.** Choosing `codec: json` *is*
  the profile declaring "parse this content as JSON," so the merge is opt-in-by-codec, not a
  silent default — consistent with the rule. `codec: plain` yields raw-in-`message` and nothing merged.

Default output of a record, then, is: the ECS put envelope + `@timestamp` (parsed) + `message`
(raw) — plus merged fields *iff* `codec: json`, plus extracted fields *iff* a filter declares them.

## Consequences

- **Positive:** vmctl becomes genuinely product-neutral — the last IG-specific line leaves the
  core. Output is predictable: the raw line is *always* in `message`, and nothing surprising is
  invented. Event-time is correct for any log shape once its timestamp source is declared. The
  put/parse boundary is now honest — the core does put + timestamp; the profile does the rest.
- **Costs / deliberate divergences:**
  - **This supersedes [ADR 0004](./0004-ecs-output-schema.md)'s 2026-07-23 "message XOR
    event.original" amendment.** `message` is now always the raw line. This is a **deliberate
    divergence from ELK's convention** (Logstash/Elastic Agent rename `message → event.original`):
    vmctl's own opinion is that a debugging tool must always have the raw line in one predictable
    place. Recorded, chosen with eyes open.
  - **The IG profile must now declare its `route_id`** with a filter (mirror `[ig][routeId]` →
    `labels.route_id`, and the filename grok it already has) instead of relying on the removed
    auto-mirror. Behaviour is preserved but now *visible in config*.
- **Risk:** the per-input timestamp configuration must stay simple, or it re-imports the complexity
  we're removing. Some text logs (catalina) carry only a time, not a date — parsing those to a full
  instant needs the date from elsewhere (file, rotation); the milestone decides how far to go, and
  read-time fallback remains the honest default when a line genuinely lacks a full timestamp.

## Notes

- Refines [ADR 0005](./0005-collection-and-search-execution.md)'s put/parse model into a hard rule:
  *put = always (metadata, ECS); parse = timestamp-by-default + declared-only for the rest.*
- Supersedes the 2026-07-23 `message`/`event.original` amendment in [0004](./0004-ecs-output-schema.md);
  the ECS envelope from 0004 otherwise stands.
- Executed in [milestone 11](../milestones/11-minimal-default-parsing.md).
