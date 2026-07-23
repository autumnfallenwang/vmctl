# vmctl

A CLI for streaming and searching ForgeRock logs across identical SSH-reachable
deployments, when you don't have ELK.

vmctl connects to each host in a deployment **directly over SSH**, reads the log
files there using only base tools (`tail`, `grep`, `awk`), and emits
**ECS-shaped JSON** labelled with its source — so logs scattered across identical
servers (e.g. an IG cluster behind a load balancer) can be streamed and searched
from one place.

It is a **machine interface** ([ADR 0007](docs/adr/0007-machine-only-interface.md)):
every command emits NDJSON (one JSON object per line) on stdout, and `search` takes
an Elasticsearch **Query DSL** filter. Designed to be driven by scripts and agents;
pipe through `jq` when a human needs to read it.

## Usage

Point vmctl at a **profile** — a named deployment (its hosts + which log files to
read) — in a YAML config. A minimal profile:

```yaml
profiles:
  test_ig:
    hosts:
      - { host: 192.168.77.11, user: vmctl }   # password: optional inline
      - { host: 192.168.77.12, user: vmctl }
    base_dir: /opt/ig-instance/logs
    inputs:
      - type: ig-audit
        path: ["audit/*.audit.json*"]
        codec: json
```

Passwords are the user's responsibility: set one inline per host, or export
`VMCTL_SSH_PASSWORD`, or let vmctl prompt.

```sh
# what files does each input match, on each host?
vmctl discover test_ig --config vmctl.yml

# follow the logs live, merged across hosts (Ctrl-C to stop)
vmctl tail test_ig --config vmctl.yml --type ig-audit

# discover what you can filter on, in _field_caps shape
vmctl fields test_ig --config vmctl.yml | jq '.fields | keys'

# search with a Query DSL filter — time bounds live inside the filter
vmctl search test_ig --config vmctl.yml --filter '{"bool":{"filter":[
  {"term":{"event.dataset":"ig-audit"}},
  {"range":{"@timestamp":{"gte":"2026-07-23T00:00:00"}}}]}}' | jq -c '{ts:.["@timestamp"], host:.host.name}'
```

`search` supports `term`, `terms`, `range`, `exists`, `wildcard`, `prefix`, `bool`
and `match_all`; the full-text and scoring clauses are rejected with a reason, since
vmctl has no index or analyzer. See
[ADR 0007](docs/adr/0007-machine-only-interface.md) for the supported subset.

## Status

M01–M09 shipped: config + SSH transport, ECS framing, and the four subcommands
above, verified against a two-host lab. See:

- [`docs/architecture.md`](docs/architecture.md) — system shape and constraints
- [`docs/adr/`](docs/adr/) — decision records
- [`docs/milestones/`](docs/milestones/) — current plan and progress

## Development

```sh
uv sync                              # create the venv, install vmctl + dev tools
uv run vmctl --version               # run the CLI
uv run ruff check .                  # lint
uv run pyright                       # typecheck
uv run pytest -m 'not integration'   # fast tests
```

vmctl targets Python **3.12+** and installs into a plain `venv` via `pip` for
deployment (uv is a development-time tool only).
