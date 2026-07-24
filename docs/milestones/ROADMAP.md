# vmctl build roadmap (index)

The ordered build, one file per milestone (see each `NN-*.md` for steps + exit
criteria). This file is just the overview: the ADR baseline, the milestone index,
and the dependency order.

## Design baseline (the ADRs, consolidated)

| ADR | Decision |
|---|---|
| [0001](../adr/0001-initial-stack.md) | Python 3.12, uv (dev) / pip-venv (deploy), ruff + pyright + pytest |
| [0002](../adr/0002-dev-test-infra.md) | Two Rocky 9 IG hosts via Vagrant+libvirt — the test lab |
| [0003](../adr/0003-log-source-config-model.md) | Config = Logstash file-input model in YAML: profiles → rules; codecs `plain`/`json`/`multiline` |
| [0004](../adr/0004-ecs-output-schema.md) | Output = ECS event; put vs parse fields; domain fields under `labels.*` |
| [0005](../adr/0005-collection-and-search-execution.md) | Commands `tail` / `search`; KQL index-less; three-tier pushdown |
| [0006](../adr/0006-runtime-transport-asyncssh.md) | `asyncssh` transport, async core, `pyyaml` config, `argparse` CLI |
| [0007](../adr/0007-machine-only-interface.md) | Machine-only: Query DSL (JSON) is the sole input, NDJSON the sole output |
| [0008](../adr/0008-field-discovery.md) | `vmctl fields` — schema discovery in `_field_caps` shape (observed, not declared) |
| [0009](../adr/0009-am-to-the-test-lab.md) | Add ForgeRock AM to the lab — validate general-purpose via a profile-only change |
| [0010](../adr/0010-minimal-default-parsing.md) | Minimal-by-default parsing: raw always in `message`, `@timestamp` the only default parse, rest declared |

## Milestone index

| # | Milestone | Goal | ADRs | Status |
|---|---|---|---|---|
| [M01](01-test-infra-and-framework.md) | Dev/test infra + framework | Lab + empty `src`-layout framework | 0001, 0002 | ✅ done |
| [M02](02-config-and-transport.md) | Config & transport | Load config, reach hosts, discover files | 0003, 0006 | ▶ active |
| [M03](03-framing-and-ecs-envelope.md) | Framing & ECS envelope | Codecs + metadata envelope (fixture-driven) | 0003, 0004, 0005 | planned |
| [M04](04-tail-command.md) | `tail` command | Live merged stream across hosts | 0005 | planned |
| [M05](05-search-command.md) | `search` command | KQL + three-tier pushdown, no store | 0005 | planned |
| [M06](06-packaging-and-deploy.md) | Packaging & deploy | Wheel, pip/venv, 0.1.0, release CI | 0001 | ✅ done |
| [M07](07-resumable-offset-registry.md) | Offset registry | Resumable exactly-once (optional) | 0005 | ⊘ skipped |
| [M08](08-dsl-query-interface.md) | Machine-only interface | Query DSL in, NDJSON out | 0007 | ✅ done |
| [M09](09-field-discovery.md) | Field discovery | `vmctl fields` — what is queryable | 0008 | ✅ done |
| [M10](10-am-support.md) | AM support | Validate general-purpose: AM logs via a profile-only change | 0009 | ▶ active |
| [M11](11-minimal-default-parsing.md) | Minimal-default parsing | Raw always in message, @timestamp the only default parse | 0010 | planned |

M08 ran ahead of M06/M07 (both unstarted), and M09 follows it; they keep the existing
numbering so committed cross-references stay valid.

## Dependency order

```
M01 ✅ ──▶ M02 (config+transport) ──▶ M04 (tail) ──▶ M05 (search) ──▶ M06 (package)
                                 ╲                 ╱
                                  ▶ M03 (codecs+envelope) ─┘        M07 (optional)
```
M02 and M03 are independent (transport vs fixture-driven transform) and both feed M04.
