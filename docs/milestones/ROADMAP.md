# vmctl build roadmap

The ordered plan to build vmctl from the locked design. Each milestone is a
coherent, shippable increment mapped to the ADRs it implements. Only the current
milestone lives as its own `NN-*.md` file (devkit's active-milestone convention);
the rest are promoted from here as they start.

## Design baseline (the ADRs, consolidated)

| ADR | Decision |
|---|---|
| [0001](../adr/0001-initial-stack.md) | Python 3.12, uv (dev) / pip-venv (deploy), ruff + pyright + pytest |
| [0002](../adr/0002-dev-test-infra.md) | Two Rocky 9 IG hosts via Vagrant+libvirt — the test lab |
| [0003](../adr/0003-log-source-config-model.md) | Config = Logstash file-input model in YAML: profiles → rules (`path`/`exclude`/`start_position`/`mode`/`codec`/`type`/`tags`); codecs `plain`/`json`/`multiline` |
| [0004](../adr/0004-ecs-output-schema.md) | Output = ECS event; put (generated) vs parse (from text) fields; domain fields under `labels.*` |
| [0005](../adr/0005-collection-and-search-execution.md) | Commands `tail` / `search`; KQL evaluated index-less; three-tier predicate resolution (planner / remote / client); sound pushdown |
| [0006](../adr/0006-runtime-transport-asyncssh.md) | `asyncssh` transport, async core, `pyyaml` config, `argparse` CLI |

## Milestones in order

### M01 — Dev/test infrastructure + empty framework — ✅ DONE
The `src`-layout framework (pip/venv-deployable) and the two-host Rocky 9 IG lab producing real logs. See [01-test-infra-and-framework.md](01-test-infra-and-framework.md).

### M02 — Config & transport foundation
*Implements 0003 (parsing), 0006 (transport). The plumbing everything else needs.*
1. Config models + `pyyaml` loader: profiles → hosts + rules (all rule fields); validation with clear errors.
2. `Transport` interface + `asyncssh` impl: password auth (env/prompt/file), run a command, stream stdout line-by-line, per-host timeouts + error isolation, concurrent fan-out.
3. Remote glob discovery: expand each rule's `path` per host (remote `find`); **report what matched** per host.
4. `vmctl discover <profile>` debug subcommand to prove connectivity + discovery.
- **Exit:** from a real profile YAML, connect to `ig1`+`ig2` by password and list the files each rule matches; config unit tests + a marked integration test against the live VMs.

### M03 — Framing & ECS envelope
*Implements 0003 (codecs), 0004 (ECS), 0005 (put/parse). Pure/local — fixture-driven, no transport needed.*
1. ECS event model + builder: put fields (`host.name`, `agent.*`, `log.file.path`, `event.created`, `ecs.version`), `event.dataset` (rule `type`), `labels.profile`.
2. Codecs: `plain`, `json`, `multiline` (`pattern`/`negate`/`what`) + `delimiter` — bytes/lines → events.
3. Parse: `@timestamp` (per-shape date parse), `labels.route_id` (filename grok / json field), json field merge.
4. Output sinks: NDJSON (stdout/file) + a human-readable format.
5. Capture a golden corpus + a few stress fixtures (broken JSON line, multiline, clock skew) into `testenv/corpus/`.
- **Exit:** given corpus fixtures, produce correct ECS events for all three log shapes (system text, route-capture multiline, audit json); unit tests on the fixtures.

### M04 — `tail` command (live stream)
*Implements 0005 tail mode; wires M02 + M03. First user-facing capability.*
1. `vmctl tail <profile> [--type/--rule]` (argparse).
2. Per host per rule (`mode: tail`): remote `tail -F` → codec framing → ECS envelope.
3. Merge N host streams (asyncio queue) into one output; per-host labelling.
4. Resilience: reconnect on drop, rotation follow (via `tail -F`), clean Ctrl-C.
- **Exit:** `vmctl tail test_ig` follows both hosts live; drive traffic with `testenv/engine/drive.py` → merged ECS events stream to terminal/file; integration test vs the live VMs.

### M05 — `search` command (read + KQL + pushdown)
*Implements 0005 search mode, KQL, three-tier pushdown.*
1. KQL parser (subset): `field:value`, quoted values, `and`/`or`/`not`, ranges (`>=`/`<=`), wildcards, `exists`.
2. Predicate evaluator over ECS events — tier 3 (exact).
3. Planner — tier 1: put/structural predicates → host selection + file selection (rule inversion).
4. Pushdown — tier 2: parsed/in-text predicates → remote `find`/`grep`/`awk` (time window via lexicographic ISO, multiline-safe; term grep), sound superset.
5. `vmctl search <profile> -q '<KQL>'` (`mode: read`) → matches (NDJSON/human); optional `--since`/`--until` sugar.
- **Exit:** `vmctl search test_ig -q 'event.dataset:ig.audit and http.response.statusCode:500'` returns correct matches from both hosts; a time-window query demonstrably pushes down (reduced transfer); KQL unit tests + integration vs the live VMs.

### M06 — Packaging & deploy hardening
*Implements 0001 (no-uv deploy); robustness + release.*
1. Finalize deps (`asyncssh`, `pyyaml`), build the wheel; verify `pip` install into a plain venv on a RHEL-like host (no uv).
2. `requirements.txt` export (`uv export`) for pip-only environments.
3. Credential handling (env/prompt/file; never logged), error/UX polish, `--help`, usage docs.
4. End-to-end smoke on the two-host lab; tag **0.1.0**.
- **Exit:** pip-install the wheel into a plain venv on a RHEL-like box and run `vmctl tail`/`search` end-to-end; docs complete; 0.1.0 tagged.

### M07 — Resumable collection (offset registry) — optional / stretch
*Implements 0005's optional offset registry.*
1. Client-side sincedb: `(host, file-identity via inode+size, offset)`.
2. Incremental read (`tail -c +offset`), resume, dedup across rotations.
- **Exit:** repeated `search`/collection resumes without re-reading or missing lines; strictly opt-in.

## Dependency order

```
M01 ✅ ──▶ M02 (config+transport) ──▶ M04 (tail) ──▶ M05 (search) ──▶ M06 (package)
                                 ╲                 ╱
                                  ▶ M03 (codecs+envelope) ─┘        M07 (optional)
```
M02 and M03 are independent (transport vs fixture-driven transform) and both feed M04.
