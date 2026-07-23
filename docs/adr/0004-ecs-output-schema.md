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
| `message` | the raw log line |
| `event.original` | untouched copy of the raw line |
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
