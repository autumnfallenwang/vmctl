# vmctl

A CLI for streaming and searching ForgeRock logs across identical SSH-reachable deployments, when you don't have ELK

## Stack

- **Primary language:** python
- **Package manager:** uv

## Commands

Day-to-day work runs through the `claude-devkit` skills at `.claude/skills/devkit-*`. Invoke them by name:

- **`/devkit-task`** — the daily workhorse: read context, plan, gate on user approval, implement, run the check loop.
- **`/devkit-commit`** — wrap up a work cycle: inspect diff, draft commit message, optionally capture knowledge / update milestone, commit.

Verification skills are invoked as sub-skills of `/devkit-task`, but you can also call them directly with natural language:

- "lint" / "fix the lint" → `devkit-lint`
- "typecheck" → `devkit-typecheck`
- "run the tests" / "fast tests" → `devkit-test`

## Structure

The repo is scaffold-only right now — no source tree exists yet, so the layout below is the plan rather than a description. `docs/` holds the living architecture doc, the append-only ADR history, and milestone work plans; `knowledge/` holds atomic team-shared facts indexed by `KNOWLEDGE.md`; `.claude/` holds the devkit skills and hooks. The Python package will land under `src/vmctl/`, with tests in `tests/`, packaging via a PEP 621 `pyproject.toml`, and the deployment-profile YAML config read from a user-supplied path. [NEEDS CLARIFICATION: module breakdown inside `src/vmctl/` — settle it in the first milestone.]

## Working with this repo

This project uses **milestone-driven** development:

- **One milestone at a time.** Milestones live in `docs/milestones/NN-*.md`. The active milestone holds the current scope, exit criteria, and progress notes.
- **Plan before code.** `/devkit-task`'s Phase 3 plan-approval gate is non-negotiable, even for one-line fixes. The plan loop catches misunderstandings before they cost real time.
- **Verify before claiming done.** `/devkit-task` runs lint → typecheck → test before reporting success. Retry up to 3x on failure, then surface.
- **Architecture changes need an ADR.** If a significant decision was made (lib choice, boundary move, approach pivot), write a new `docs/adr/NNNN-*.md` from `docs/adr/0000-template.md`.
- **Knowledge is the team-shared memory.** `knowledge/<slug>.md` holds atomic facts, lessons, corrections, references. Capture via natural language ("remember this") or `/devkit-knowledge-capture`. Index at `knowledge/KNOWLEDGE.md`.

### Which file does this go in?

When something needs recording, walk down in order:

1. **A decision** (we chose A over B for reason R) → new ADR.
2. **What we're currently building** (this milestone's scope/plan/notes) → the active `docs/milestones/NN-*.md`.
3. **A change to the system's shape** (components, boundaries) → edit `docs/architecture.md` in place.
4. **A small correction or preference** the agent should remember → new knowledge entry, `type=feedback`.
5. **Non-code project context** (deadlines, constraints, stakeholders) → new knowledge entry, `type=project`.
6. **A URL / ticket / dashboard pointer** → new knowledge entry, `type=reference`.
7. **None of the above** → it probably doesn't need recording.

## Docs

- [`docs/architecture.md`](docs/architecture.md) — current system shape
- [`docs/adr/`](docs/adr/) — append-only decision history
- [`docs/milestones/`](docs/milestones/) — work plans + progress notes
- [`knowledge/KNOWLEDGE.md`](knowledge/KNOWLEDGE.md) — team-shared knowledge index

@knowledge/KNOWLEDGE.md
