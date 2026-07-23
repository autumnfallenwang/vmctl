# 0005 — Collection & search execution model

- **Status:** accepted
- **Date:** 2026-07-22
- **Deciders:** project founder

## Context

[0003](./0003-log-source-config-model.md) fixed how sources are declared (profiles / rules / codecs); [0004](./0004-ecs-output-schema.md) fixed the output event (ECS). This ADR fixes **how vmctl actually runs its two modes — stream and search — with no Elasticsearch in the middle to store or index anything.** It also settles the previously deferred questions of *where filtering happens* and *what the search interface is*.

## Decision

### Two modes, one pipeline

Both modes share the same core: `resolve profile → per host, expand each rule's glob → read with the rule's codec (framing) → build the ECS event`. They differ only at the two ends:

- **`tail`** = `mode: tail` (the Logstash file-input option in the rule) → remote `tail -F`: follow, live, unbounded, continuous output to terminal/file.
- **`search`** = `mode: read` → bounded historical read of the file(s) + a KQL query that keeps only matches → a bounded result set to terminal/file/JSON.

`mode: tail` vs `mode: read` *is* the tail-vs-search switch, and it already lives in the rule (0003).

### CLI commands

The two user-facing subcommands are fixed as **`tail`** and **`search`** — **not** "stream" or "query":

- `vmctl tail <profile> …` — the follow mode (`mode: tail`); log lines streamed to terminal/file.
- `vmctl search <profile> -q '<KQL>' …` — the read mode (`mode: read`); KQL-filtered results.

`tail` mirrors both `tail -F` and the rule's `mode: tail`; `search` names the action. "stream" and "query" are avoided as command words (a KQL *query* is still the argument to `search`).

### Query language: KQL, evaluated index-less

- Search queries use **KQL** (Kibana Query Language) — ELK-compatible: `field:value`, booleans, ranges, wildcards, `exists`.
- With no index or store, KQL is evaluated **against the ECS events in memory** — a linear scan — not against a stored index.
- The query is a **runtime argument**, scoped to the whole profile by default and narrowed *inside the query* via ECS-field predicates (`event.dataset:ig.audit`, `labels.route_id:00-proxy`). It is **not** baked into a rule. Rules describe sourcing/framing; the query is what you ask at run time.

### Put vs parse (this decides what can be pushed down)

Every field is one of two kinds — and this is load-bearing:

- **Put** — collector-*generated*, **not** present in the log text: `host.name`, `agent.*`, `log.file.path`, `event.created`, and — by ELK **default** — `@timestamp` (the time the line was *read*). Automatic.
- **Parse** — *extracted from the raw line* via configured filters (`grok` / `json` / `date`): the log's own timestamp, `message` terms, JSON field values, grok'd fields. Configured.

**vmctl parses an event-time `@timestamp`** from the log (the Logstash `date`-filter equivalent) rather than accepting the default read-time value — because event time is what a debugging tool needs, and because *a parsed value lives in the text and is therefore pushable to the source*. Where the timestamp is parsed from is per log shape (leading token for text; the `timestamp` JSON field for audit) and declared in config.

### Three-tier predicate resolution

A query predicate resolves in exactly **one** of three places, chosen by whether its field is put/structural or parsed:

1. **Planner (vmctl itself — no remote command).** Put / structural fields vmctl already knows: `host.name` → which hosts to SSH to; `event.dataset` / `labels.route_id` (route logs, id from filename) → which files to open, by inverting the rule's extraction. Resolved by *choosing what to read*.
2. **Remote command (server-side, base tools).** Parsed / in-the-text fields: a `@timestamp` range → `awk`; `message` / JSON values → `grep` / `awk`. The value is physically in the file, so the filter runs at the source.
3. **Client exact evaluation.** The full KQL predicate, precisely, after building the ECS events.

The **same field can resolve in different tiers by log type**: `routeId` for a *route log* is in the filename → tier 1; for the *audit log* it is a JSON field → tier 2.

### Pushdown soundness

Tier-1/2 pushdown must be a **sound superset** — it may never drop a true match, though it may pass extras (tier 3 removes them). If it is unclear that a pushdown is sound, **do not push it**: fetch more and filter on the client. Correctness before efficiency. Concretely: a pushed-down time window is **widened outward** (floor the lower bound, ceil the upper) so string-prefix truncation can never drop a boundary match.

### Time-window mechanics (worked)

- IG writes uniform **UTC ISO-8601**, so timestamps **sort lexicographically** → the server compares them as plain strings with `awk`, no date math. (The text and audit formats differ only in the millisecond separator; comparing the shared 19-char `YYYY-MM-DDTHH:MM:SS` prefix sidesteps that.)
- **Text logs (multiline-safe):** on a timestamp line, decide in/out of window; print *every* line (including `[CONTINUED]` continuations, which carry no timestamp) with the current event's decision — so multi-line events are never split.
- **Audit JSON:** extract the `timestamp` field per line and compare.
- **Assumption:** uniform UTC ISO format. If a log used local time, offsets, or mixed formats, string comparison would break and the value would have to be parsed before filtering (losing the cheap pushdown). Validate this per new log shape.

## Consequences

- **Positive:** ELK-compatible querying (KQL) with **zero storage**; agentless works precisely because parsed fields push to the source while put fields are resolved by the planner; the "derive metadata from the source, don't invent it" discipline ([0004](./0004-ecs-output-schema.md)) is exactly what makes pushdown possible.
- **Limits:** no index-speed random access, aggregations, or relevance ranking; each cold search re-reads files (linear, O(bytes)); only what is currently on the boxes (plus still-present rotated files) is searchable; pushdown of typed/structured predicates is approximate (grep can't do typed comparisons), with exactness deferred to the client; correctness of time pushdown rests on the UTC-ISO assumption.
- **Optional:** a small client-side cache of already-pulled events for repeated queries (a by-choice, ephemeral local store) — not required; the store-less path is fully functional.

## Notes

- Settles the **"where does filtering happen"** (answer: a sound pushdown on the servers *plus* exact evaluation on the client) and **"search query interface"** (answer: KQL) items deferred in earlier docs.
- **Added 2026-07-22:** fixed the CLI subcommand names as **`tail`** and **`search`** (not "stream"/"query").
- **Amended 2026-07-23 (`mode` is not a search filter).** "*`mode: tail` vs `mode: read` **is** the tail-vs-search switch*" is softened in implementation: **`search` reads every input regardless of `mode`**, narrowed by `--type` or an `event.dataset` predicate. Taken literally, a profile whose inputs all declare `mode: tail` — which is every profile we have — would make `vmctl search` match nothing, and forcing each logset to be declared twice (once per mode) buys nothing: any file that can be tailed can also be read. `mode` therefore stays a declaration of intent for `tail`, and the bounded-read-plus-KQL execution model above is unchanged.
- **Added 2026-07-23 (pushdown scope, as built in M05).** Tier 2 pushes (a) the time window, for every codec, and (b) literal `grep -F` terms **only** for single-line `json` inputs. Term pushdown is withheld for `plain`/`multiline` because a `grep` would drop the `[CONTINUED]` **and blank** continuation lines that belong to a multi-line event, silently splitting it; and it is withheld for generated ("put") fields, wildcards, non-`:` operators, and non-integer numbers, whose textual form in the file isn't guaranteed. Each exclusion is the "if it is unclear that a pushdown is sound, do not push it" rule applied.
- **Added 2026-07-23 (NDJSON is the default output).** Both `tail` and `search` default to `--output ndjson` — one ECS event per line — with `--output human` as the opt-in scannable rendering (`<@timestamp>  <host.name>  <event.dataset>[<route_id>]  | <first line>`). The tool's stated purpose is to be equally usable by a person and by an AI agent, and of those two the agent (and every pipe, `jq` filter and file sink) needs the structured form; a human can ask for the pretty one. Defaulting the other way silently decorates piped output. Note the human line is a *view*: the prefix fields are all present inside the JSON, so nothing is lost by either choice.
- Builds on [0003](./0003-log-source-config-model.md) (rules / codecs / `mode`) and [0004](./0004-ecs-output-schema.md) (ECS fields). Reference: KQL, the Logstash `date` filter, and predicate pushdown in federated query engines.
