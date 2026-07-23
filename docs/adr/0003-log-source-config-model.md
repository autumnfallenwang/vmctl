# 0003 — Log config model: follow Logstash (ELK-compatible), in YAML

- **Status:** accepted
- **Date:** 2026-07-22
- **Deciders:** project founder

## Context

vmctl reads log files across hosts and emits records. The decision is to **completely follow the ELK / Logstash model and make vmctl ELK-compatible**, rather than invent a format or blend multiple tools. **Logstash is the single reference — not Filebeat, not anything else.** The one deliberate deviation: we author config in **YAML** (vmctl's choice), where Logstash uses its own config DSL. Field names and semantics still track Logstash 1:1.

This ADR locks the **config model** (how log sources and rules are declared). The exhaustive ECS field list is left to the living design doc.

## Decision

- **Reference model:** the Logstash pipeline — **input → filter → output** — and the **Elastic Common Schema (ECS)** for events. No Filebeat, no bespoke format.
- **Config format:** **YAML** (our only divergence from Logstash, which uses its own DSL). YAML keys map 1:1 to Logstash option names.
- **A profile** = a deployment: a set of `hosts` plus a Logstash-style pipeline.
- **A rule = a Logstash `file` input**, YAML-rendered, using Logstash's own option names:
  - `path` (glob array, `*`-suffixed to include rotated files), `exclude`, `start_position` (`beginning`/`end`), `mode` (`tail`/`read`), `codec` (`plain`/`json`/`multiline`) + `delimiter`, `type`, `tags`. See **Event framing** below for codec detail.
  - Files are discovered by glob expansion (Logstash's discovery); read position is tracked **sincedb-style**.
- **Metadata extraction** follows Logstash **filters** — e.g. `grok` on `path` to pull `routeId` from a filename, the `json` codec/filter for structured records. Not a bespoke extraction recipe.
- **Output** is an **ECS event** (ELK-compatible): the raw line as `message`, plus `log.file.path`, `host.name`, `event.dataset` / `type`, and any filter-added fields — so records could be sent to Elasticsearch unchanged.

Illustrative shape (from the test env):

```yaml
profiles:
  test_ig:
    hosts:
      - { host: 192.168.77.11, user: vmctl }
      - { host: 192.168.77.12, user: vmctl }
    inputs:                                    # Logstash file inputs, in YAML
      - path: [ "/opt/ig-instance/logs/route-system.log*" ]
        type: route-system-log
        mode: tail
        start_position: end
        codec: multiline                       # [CONTINUED] continuation lines
      - path: [ "/opt/ig-instance/logs/route-*.log*" ]
        exclude: [ "route-system.log*" ]
        type: route-log
        mode: tail
        codec: multiline
      - path: [ "/opt/ig-instance/logs/audit/*.audit.json*" ]
        type: audit-access
        mode: tail
        codec: json
    filters:                                   # Logstash filters, in YAML
      - if: '[type] == "route-log"'
        grok: { match: { "path": 'route-%{DATA:routeId}\.log' } }
      # audit-access: routeId already present as [ig][routeId] from the json codec
```

## Event framing (codecs)

vmctl **implements Logstash's codecs**, so every log shape — JSON or plain or multi-line — is handled by config, never by tool code changes. Each rule sets a `codec` (and optional `delimiter`, default `\n`) that decides two things: how the file's bytes are split into events, and whether each event is parsed. This is distinct from **parsing** (filters / `grok`) — a text event may stay a raw `message` with field extraction left optional.

The three codecs mirror Logstash exactly:

- **`plain`** *(default)* — one event per line (split on `delimiter`); the raw line goes into `message`, no parsing. For ordinary single-line text logs.
- **`json`** — one event per line, parsed as a JSON object whose fields merge into the event (see [0004](./0004-ecs-output-schema.md)); the raw line is kept in `event.original`. For the audit log.
- **`multiline`** — joins several physical lines into one event. Sub-options are Logstash's:
  - `pattern` — regex identifying a line
  - `negate` — `true` / `false`
  - `what` — `previous` | `next` (which event non-matching / matching lines attach to)
  - `max_lines`, `auto_flush_interval` — as in Logstash

Per-log-type mapping in the test env:

```yaml
# audit — one JSON object per line
codec: json

# route-*.log / route-system.log — one logical event spans several physical
# lines ([CONTINUED] continuations, exception stacks); anchor on the timestamp
codec:
  multiline:
    pattern: '^\d{4}-\d{2}-\d{2}T'   # a line starting with an ISO date = new event
    negate: true                      # lines that DON'T match...
    what: previous                    # ...append to the previous event

# a plain single-line text log
codec: plain
```

**vmctl must implement `plain`, `json`, and `multiline` (plus `delimiter`) with Logstash-equivalent semantics**, so supporting a new log shape is a config change, not a code change — the whole point of mirroring the ELK model.

## Consequences

- **Positive:** ELK-compatible by construction — output could ship to Elasticsearch unchanged; a proven, documented model; nothing invented; anyone who knows Logstash already knows our config. Because framing is codec-driven, **a new log shape (JSON, plain, or multi-line) is a config change, not a code change.**
- **Costs / limits:** we inherit Logstash's concepts (sincedb, codecs, filters, ECS) even where a lighter model would do; the YAML↔Logstash key mapping needs to be documented and kept faithful.
- **Still living (in `docs/architecture.md`, not frozen here):** the exact ECS field set, the full YAML↔Logstash option mapping, the SSH collection transport, and the search interface.

## Notes

- **Revised 2026-07-22** from an initial "simplified subset of Filebeat/Logstash" framing to **full Logstash/ELK alignment** with Logstash as the sole reference and YAML config.
- **Added 2026-07-22** the *Event framing (codecs)* section — `plain` / `json` / `multiline` + `delimiter`, mirroring Logstash and configurable per rule; vmctl must implement these codecs so new log shapes are config, not code.
- Builds on [0001](./0001-initial-stack.md) and [0002](./0002-dev-test-infra.md). Reference: the Logstash `file` input plugin and ECS.
