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

## Parsing: codecs, timestamps, filters

By default vmctl does the minimum ([ADR 0010](docs/adr/0010-minimal-default-parsing.md)):
the **whole raw line is always in `message`**, and the **only** field parsed from the
content is **`@timestamp`**. Everything else is opt-in, per input.

**Codec** — how the file is framed (and whether parsed):

| `codec:` | Effect |
|---|---|
| `plain` (default) | one event per line; raw line in `message` |
| `json` | one JSON object per line; **its fields are merged to the top level** (so they're directly queryable) — the raw line still stays in `message` |
| `multiline: { pattern, negate, what }` | join physical lines into one event (e.g. stack traces, `[CONTINUED]` lines); `pattern` anchors a new event |

Because `json` merges fields, **you usually don't need a filter for JSON logs** — run
`vmctl fields <profile>` to see every field, then query it directly.

**`@timestamp`** — auto-detected by default (a `timestamp` JSON field, else a leading
ISO-8601 token in the line). For a log whose event-time is elsewhere or in another format,
declare it per input; a value that can't be parsed falls back to the collection time.

```yaml
- type: am-audit
  codec: json
  timestamp: { field: timestamp }              # take @timestamp from this JSON field
- type: ds-errors                              # lines lead with [24/Jul/2026:00:14:45 +0000]
  codec: { multiline: { pattern: '^\[', negate: true, what: previous } }
  timestamp: { pattern: '\[([^\]]+)\]', format: '%d/%b/%Y:%H:%M:%S %z' }  # regex + strptime
```

**Filters** — declare any *other* extraction into `labels.*`. These are **Logstash grok**,
but vmctl implements a small subset — the only supported patterns are:

```
%{DATA:name}   %{GREEDYDATA:name}   %{WORD:name}   %{INT:name}   %{NOTSPACE:name}
```

A filter is `{ if: <condition>, grok: { <source>: <pattern> } }`:
- **condition** — `'[type] == "<dataset>"'` only (`[type]` is the input's `type`); omit `if` to always run.
- **source** — `path` (the filename), `message` (the raw line), or a field reference like
  `[ig][routeId]` (a parsed JSON field).
- Named captures land in `labels.<name>`.

```yaml
filters:
  # route_id from the filename of a text log
  - if: '[type] == "ig-route"'
    grok: { path: 'route-%{DATA:route_id}\.log' }
  # route_id from a JSON field of an audit log (GREEDYDATA = "the whole value")
  - if: '[type] == "ig-audit"'
    grok: { '[ig][routeId]': '%{GREEDYDATA:route_id}' }
```

## Install

vmctl is a wheel that installs into a plain `venv` with `pip` — no `uv` at runtime.
The target needs only **Python 3.12+** and `pip`. Grab the wheel from the repo's
[Releases](https://github.com/autumnfallenwang/vmctl/releases) page.

```sh
python3.12 -m venv /opt/vmctl-venv
/opt/vmctl-venv/bin/pip install vmctl-0.1.0-py3-none-any.whl
/opt/vmctl-venv/bin/vmctl --version
```

`pip install` puts the `vmctl` launcher in `/opt/vmctl-venv/bin/` and pulls the
runtime deps (`asyncssh`, `pyyaml`, …) from PyPI. Run it by full path, or expose the
command — symlink just it (venv otherwise hidden), or activate the venv:

```sh
sudo ln -s /opt/vmctl-venv/bin/vmctl /usr/local/bin/vmctl   # `vmctl` works everywhere
# or, for the current shell only:
source /opt/vmctl-venv/bin/activate
```

Don't move the venv folder after creating it — the launcher's interpreter path is
baked in. Re-create it at the target location instead.

**Offline / airgapped hosts** have no PyPI, so pre-stage every dependency on a
machine matching the target's OS/arch/Python (`cryptography`/`cffi` are compiled),
then install with no network:

```sh
pip download -r requirements.txt vmctl-0.1.0-py3-none-any.whl -d bundle/
# copy bundle/ to the target, then:
/opt/vmctl-venv/bin/pip install --no-index --find-links bundle/ vmctl
```

`requirements.txt` pins the full transitive tree for reproducible installs.

## Status

Through M11: config + SSH transport, ECS framing, the four subcommands above, minimal-by-default
parsing, and a validated general-purpose lab (ForgeRock IG **and** an AM site + replicated DS).
See:

- [`docs/architecture.md`](docs/architecture.md) — system shape and constraints
- [`docs/adr/`](docs/adr/) — decision records
- [`docs/milestones/`](docs/milestones/) — current plan and progress

## Development

vmctl targets Python **3.12+**. `uv` is a development-time tool only — the shipped
wheel installs into a plain `venv` via `pip` (see [Install](#install)).

```sh
uv sync                              # create the venv, install vmctl + dev tools
uv run vmctl --version               # run the CLI
uv run ruff check .                  # lint
uv run pyright                       # typecheck
uv run pytest -m 'not integration'   # fast tests
uv run pytest -m integration         # live tests (need the lab + VMCTL_SSH_PASSWORD)
```

### Build

```sh
uv build                             # -> dist/vmctl-<version>-py3-none-any.whl + .tar.gz
```

The wheel is a build artifact (`dist/` is gitignored) — never commit it. The version
comes from `__version__` in `src/vmctl/__init__.py`, not from git.

### Release

Releases are cut by pushing a version tag; CI
([`.github/workflows/release.yml`](.github/workflows/release.yml)) builds the wheel
and attaches it to a GitHub Release. It refuses to publish if the tag and
`__version__` disagree, or if the check loop (lint / typecheck / fast tests) fails.

```sh
# 1. bump __version__ in src/vmctl/__init__.py, commit, push to main
# 2. tag it and push the tag — this triggers the release workflow
git tag v0.1.0
git push origin v0.1.0
```

Regenerate the pinned deploy manifest when dependencies change:

```sh
uv export --no-hashes --no-dev --no-emit-project > requirements.txt
```
