---
name: devkit-knowledge-capture
description: Use when the user says "remember this", "capture this", "save to knowledge", "log a lesson", or when claude detects a correction worth caching for future sessions. Writes one atomic knowledge entry under knowledge/ and updates the KNOWLEDGE.md index.
allowed-tools: Read, Write, Edit
---

Capture an atomic knowledge entry into `knowledge/<slug>.md` and register it in `knowledge/KNOWLEDGE.md`. Knowledge entries are the committed, team-visible counterpart to Claude Code's per-machine auto-memory.

## When to invoke

- The user explicitly says "remember this" / "save to knowledge".
- The user corrects an approach in a way that should bind future sessions → type `feedback`.
- The user shares non-code project context worth preserving (deadlines, constraints, stakeholders) → type `project`.
- The user provides a URL / dashboard / ticket pointer → type `reference`.
- The user shares facts about themselves (role, expertise, preferences) → type `user`.

## Phases

### 1. Identify the content

If `$ARGUMENTS` was passed, use it. Otherwise ask the user one question:

> "What should I capture, and what type — user / feedback / project / reference?"

### 2. Pick a slug

Short, kebab-case, descriptive. Examples: `narrow-scope-preferred`, `arch-infra-repo-pointer`, `q3-cutover-deadline`.

Check `knowledge/` for collisions. If a similar slug already exists, propose updating that entry rather than creating a new one.

### 3. Write `knowledge/<slug>.md`

```markdown
---
name: <slug>
description: <one-line summary — used for relevance recall>
metadata:
  type: user | feedback | project | reference
---

<body>
```

For `feedback` and `project` types, structure the body as:

- The rule or fact (one sentence)
- **Why:** the reason — incident, preference, constraint, deadline
- **How to apply:** when and where this should kick in

Link related entries with `[[other-slug]]` where relevant. Unresolved links are fine — they mark future capture candidates.

### 4. Update the index

Append a one-line pointer to `knowledge/KNOWLEDGE.md`:

```
- [<Title>](<slug>.md) — <one-line hook>
```

If the index has sections (`## Feedback`, `## Project`, etc.), insert under the matching one. If flat, append at the end.

### 5. Confirm

Report: "Captured `knowledge/<slug>.md` (type: <type>) and updated KNOWLEDGE.md."

## Notes

- Knowledge entries are **deletable when stale** — unlike ADRs which are immutable history. If a captured rule turns out to be wrong, delete the file and remove the index line.
- Keep `KNOWLEDGE.md` under 200 lines. It loads at every session start via `CLAUDE.md`'s `@knowledge/KNOWLEDGE.md` import; topic files load on demand.
- Don't capture transient session state (current task progress, in-flight decisions). That belongs in the active milestone file, not knowledge.
- This skill writes to the **project repo** (committed to git). For per-developer-machine knowledge, the user should use Claude Code's own `/memory` affordance instead.
