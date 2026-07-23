# 0004 — Output event schema: ECS (100% ELK-compatible)

- **Status:** accepted
- **Date:** 2026-07-22
- **Deciders:** project founder

## Context

[ADR 0003](./0003-log-source-config-model.md) fixed the config model (Logstash-style, in YAML) and stated that output is an ECS event, but deferred the exact field set. This ADR locks that field set. Goal: **vmctl output is 100% ELK/ECS-compatible** — a record could be sent to Elasticsearch/Kibana unchanged, with nothing invented.

## Decision

Every vmctl record is an **ECS event**. Fields fall into two groups.

**Filled automatically by vmctl (the collection metadata):**

| Field | Value |
|---|---|
| `@timestamp` | event time — from the record when present, else collection time |
| `message` | the raw log line — **superseded, see the 2026-07-23 amendment in Notes** |
| `event.original` | untouched copy of the raw line — **superseded, see the 2026-07-23 amendment in Notes** |
| `event.created` | collection time |
| `host.name` | the **remote host the log came from** (e.g. `ig1`) — *not* vmctl's machine |
| `agent.type` / `agent.version` | `"vmctl"` / the vmctl version — vmctl is the collector |
| `log.file.path` | remote source file path (`log.offset` when position is tracked) |
| `ecs.version` | the ECS schema version targeted |

**Filled from the profile/rules (config):**

| Field | Value |
|---|---|
| `event.dataset` | the rule's `type` (e.g. `ig.system`, `ig.route`, `ig.audit`) |
| `labels.profile` | the profile name (the deployment) |
| `labels.route_id` | extracted by a filter — grok on `log.file.path` for `route-<id>.log`, or the json field `ig.routeId` for audit |
| `tags` | any user-supplied tags |

**Domain fields go under `labels.*`** — ECS's sanctioned bucket for ad-hoc key/values — **not** a bespoke namespace. This keeps us 100% ECS-compatible with nothing invented. A field may be promoted to a custom namespace later only if it earns it.

**Remote-collection mapping (the key point):** vmctl is agentless and remote, so ECS's `host` vs `agent` split is used exactly as intended — `host.*` = the monitored IG server, `agent.*` = vmctl the collector. No schema bending. (ECS's `observer.*` is the alternative for remote collectors; `host` + `agent` is the simpler correct fit here.)

**Already-ECS source:** IG's audit log already emits ECS-shaped fields (`client.ip`, `server.ip`, `http.request.method`, `transactionId`). With `codec: json` these merge straight into the event, so for audit records vmctl only adds the collection wrapper. Text `route-*.log` contributes `message` plus grok-extracted fields.

Example — an `audit-access` record:

```json
{
  "@timestamp": "2026-07-22T23:42:21.127Z",
  "message": "{ ...raw audit json... }",
  "event":   { "dataset": "ig.audit", "created": "2026-07-22T23:45:00Z" },
  "host":    { "name": "ig1" },
  "agent":   { "type": "vmctl", "version": "0.0.1" },
  "log":     { "file": { "path": "/opt/ig-instance/logs/audit/access.audit.json" } },
  "labels":  { "profile": "test_ig", "route_id": "00-proxy" },
  "ecs":     { "version": "8.11" },
  "transactionId": "b102f11f-...-5", "http": { "...": "..." }, "client": { "ip": "127.0.0.1" }
}
```

Example — a `route-log` (text) record:

```json
{
  "@timestamp": "2026-07-23T00:04:42.571Z",
  "message": "2026-07-23T00:04:42,571Z | INFO | ... @00-proxy | ...(request)...",
  "event":   { "dataset": "ig.route" },
  "host":    { "name": "ig1" },
  "agent":   { "type": "vmctl", "version": "0.0.1" },
  "log":     { "file": { "path": "/opt/ig-instance/logs/route-00-proxy.log" } },
  "labels":  { "profile": "test_ig", "route_id": "00-proxy" },
  "ecs":     { "version": "8.11" }
}
```

## Consequences

- **Positive:** records are drop-in for Elasticsearch/Kibana; nothing invented; anyone who knows ECS can read vmctl output; audit records need almost no mapping since IG already emits ECS-ish fields; `host`/`agent` cleanly model agentless remote collection.
- **Costs / limits:** we inherit ECS naming and verbosity; domain fields live under `labels.*` (string-typed) until/unless promoted; `@timestamp` must be parsed differently per log shape (audit has an ISO timestamp; text logs need parsing).
- **Still living (in `docs/architecture.md`, not frozen here):** the exact per-log-type field population, timestamp parsing rules, the pinned `ecs.version`, and the `labels` → custom-namespace promotion policy.

## Notes

- Completes [0003](./0003-log-source-config-model.md), which deferred the field set. Builds on [0001](./0001-initial-stack.md), [0002](./0002-dev-test-infra.md).
- Reference: ECS base / log / event / host / agent field sets.

### Amended 2026-07-23 — `message` XOR `event.original`, never both

**Supersedes the `message` and `event.original` rows of the decision table above.**

The table mandated *both* `message` (the raw line) and `event.original` (an untouched copy of the same raw line). Both worked examples in this ADR show only `message` and no `event.original` — the table and the examples contradicted each other, and the implementation followed the table. The result was that a parsed audit record stored its raw line **three times**: escaped in `message`, escaped again in `event.original`, and a third time as the merged top-level fields — an event **3.9× the size of the line it describes**, measured on a real record.

That is not what ELK does, so it violated this ADR's own stated goal. Corrected rule, matching Logstash:

| Case | Emit |
|---|---|
| codec parsed the record (`json`) | merged fields + `event.original`; **no `message`** |
| codec did not parse (`json` failure) | `message` = raw line + tag `_jsonparsefailure`; no `event.original` |
| `plain` / `multiline` | `message` = the (joined) line; no `event.original` |

Also corrected: `tags` was listed in the config-filled table below but never emitted — the configured `Input.tags` are now written to the event, and are where the failure tag lands.

**Evidence** (researched 2026-07-23; provenance marked, because it differs by claim):

- **Logstash `json` codec, doc-verified:** *"If this codec recieves a payload from an input that is not valid JSON, then it will fall back to plain text and add a tag `_jsonparsefailure`. Upon a JSON failure, the payload will be stored in the `message` field."* — [plugins-codecs-json](https://www.elastic.co/docs/reference/logstash/plugins/plugins-codecs-json). `message` is the *failure* destination; on success the parsed keys are the event.
- **`event.original` on success — source-verified only, NOT stated in the docs.** The Elastic-maintained plugin sets `@original_field = ecs_select[disabled: nil, v1: '[event][original]']` and writes the raw line there. This applies because **Logstash 8+ runs all plugins in ECS v8 mode by default** ([ecs-ls](https://www.elastic.co/docs/reference/logstash/ecs-ls)).
- **ECS field status, doc-verified:** `message` is `level: core` — *core is not required*. Only **`@timestamp` and `ecs.version`** carry `required: true` (verified by scanning every file in `elastic/ecs/schemas/`). `event.original` ships `index: false, doc_values: false` — *"This field is not indexed and doc_values are disabled."* ([ecs-base](https://www.elastic.co/docs/reference/ecs/ecs-base), [ecs-event](https://www.elastic.co/docs/reference/ecs/ecs-event)).
- **ECS on structured logs, doc-verified:** *"For structured logs without an original message field, other fields can be concatenated to form a human-readable summary of the event."* No Elastic guidance anywhere endorses putting a raw JSON blob in `message`.
- **Elastic's integration tooling rejects the duplication outright:** package-spec rule `JSE00001` fails a build when a pipeline renames `message` → `event.original` without a paired `remove` of `message`.

**Why Logstash and not Elastic Agent.** Elastic Agent integrations make the raw line opt-in (`preserve_original_event`, default `false`) and *rename* `message` → `event.original`. That is a different product layer with a different answer. [ADR 0003](./0003-log-source-config-model.md) fixes **Logstash as the sole reference** ("not Filebeat, not anything else"), so the codec behavior binds us: `event.original` is always present for parsed records rather than opt-in. Consequence worth stating plainly — following Logstash costs more bytes than the Elastic Agent default would (~2.8× the raw line rather than ~1.9×). Fidelity was the requirement; size was not.

**Not adopted:** Logstash also stamps `@version` on every event. It is not an ECS field, so vmctl does not emit it.
