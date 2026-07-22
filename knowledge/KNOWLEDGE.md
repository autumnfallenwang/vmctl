# Project knowledge

This file is the **index** of team-shared knowledge for this project. It loads at every session start (via `CLAUDE.md`'s `@knowledge/KNOWLEDGE.md` import). The first ~200 lines are visible to Claude on session start; topic files load on demand.

## How knowledge entries work

Each entry is a separate file in this directory: `<slug>.md`. Use kebab-case for the slug.

**File format:**

```markdown
---
name: <short-kebab-case-slug>
description: <one-line summary — used for relevance recall>
metadata:
  type: user | feedback | project | reference
---

<body — for feedback/project, structure as: rule/fact, then **Why:** and **How to apply:** lines.
Link related entries with [[other-slug]].>
```

**Types:**

- `user` — who the user is (role, expertise, preferences)
- `feedback` — corrections + confirmed approaches the agent should follow
- `project` — ongoing work, goals, constraints not derivable from code or git
- `reference` — pointers to external resources (URLs, dashboards, tickets)

**Lifecycle:** entries are **deletable when stale**. Unlike ADRs (immutable history), knowledge entries are a live cache of what's currently relevant. If a captured rule turns out to be wrong, delete the file and remove its line from this index.

**Relation to Claude Code's auto-memory:** this directory is the **committed, team-visible** counterpart to Claude Code's per-machine auto-memory at `~/.claude/projects/<slug>/memory/`. The two are complementary — auto-memory is per-developer; this is shared across the team.

## How to capture

- Say "remember this" or "capture this as knowledge" in conversation.
- Or invoke `/devkit-knowledge-capture` directly.

The skill picks a slug, writes the file with the right frontmatter, and updates this index.

---

## Index

*(No entries yet. The first entry will land here after `/devkit-init` seeds `project-profile.md`.)*
