# vmctl

A CLI for streaming and searching ForgeRock logs across identical SSH-reachable
deployments, when you don't have ELK.

vmctl connects to each host in a deployment **directly over SSH**, reads the log
files there using only base tools (`tail`, `grep`), and emits JSON records
labelled with their source — so logs scattered across identical servers (e.g. an
IG cluster behind a load balancer) can be streamed and searched from one place.

## Status

Early development. See:

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
