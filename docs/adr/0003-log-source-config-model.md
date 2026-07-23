# 0003 — Log source config model (profiles + rules)

- **Status:** accepted
- **Date:** 2026-07-22
- **Deciders:** project founder

## Context

vmctl needs a config that says, per deployment, **which log files to collect on each host and how to label them** — the file-input stage of a log shipper. Rather than invent a format, we adopt the established **Logstash `file` input / Filebeat `inputs`** model (glob-based file discovery + labeling + path/field extraction), in a simplified form.

Scope of this ADR is **only the config model** — profiles and rules. The output envelope, its field names, the collection transport, the offset registry, and the search interface are **not** decided here.

## Decision

Config is YAML. Two levels:

- A **profile** is one deployment: a set of `hosts` plus a list of `rules`.
- A **rule** is one logset. It carries:
  - `pattern` — a glob (relative to a `base_dir`) matching the logfiles, `*`-suffixed to include rotated forms. **Files are discovered by expanding the glob per host at run time**, not pre-enumerated — routes/files that are deployed or deleted are picked up or dropped automatically.
  - `type` — a label for the logset (e.g. `route-system-log`, `route-log`, `audit`).
  - `format` — `text` or `json`.
  - a **metadata-extraction recipe** — how to derive per-record fields (notably `routeId`) from one of: the **filename** (regex capture), a **json field** (path), or a **constant**. The recipe is defined once and applies to every file/record the pattern matches — no per-route rule needed.

Illustrative shape (from the test env):

```yaml
profiles:
  test_ig:
    hosts:
      - { host: 192.168.77.11, user: vmctl }
      - { host: 192.168.77.12, user: vmctl }
    base_dir: /opt/ig-instance/logs
    rules:
      - type: route-system-log
        pattern: "route-system.log*"
        format: text
      - type: route-log
        pattern: "route-*.log*"
        exclude: "route-system.log*"
        format: text
        route_from: { source: filename, regex: "route-(?P<routeId>.+?)\\.log" }
      - type: audit-access
        pattern: "audit/*.audit.json*"
        format: json
        route_from: { source: field, path: "ig.routeId" }
```

This is a deliberate subset of Filebeat/Logstash inputs (paths + tags + grok-on-path / json-decode). No bespoke format is invented.

## Consequences

- **Positive:** a familiar, proven model; dynamic route/file coverage from static config; one rule covers all current and future routes; agentless-friendly (the glob is expanded remotely over SSH).
- **Limits:** metadata is only what the glob + extraction recipe can express; per-host glob expansion adds a remote call per run.
- **Explicitly deferred (NOT decided here):** the output envelope and its field schema, field naming (ECS-aligned vs custom), the collection transport (`tail -F` / `grep`), the offset/resume registry, and the search query interface.

## Notes

- Builds on [0001](./0001-initial-stack.md) and [0002](./0002-dev-test-infra.md). Derived from the Logstash `file` input and Filebeat `inputs` patterns.
- The field-level envelope schema will be settled later and tracked in `docs/architecture.md`, not frozen here.
