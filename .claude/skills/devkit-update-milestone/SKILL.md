---
name: devkit-update-milestone
description: Use when devkit-task finishes a task within a milestone, when devkit-commit ships a meaningful unit of work, or when the user says "update the milestone notes" / "log progress on the milestone".
allowed-tools: Read, Edit, Bash(ls *)
---

Append progress notes to the active milestone file under `docs/milestones/`. Optionally marks a milestone as closed when its exit criteria have shipped.

## Identify the active milestone

1. List `docs/milestones/NN-*.md` files.
2. The active milestone is the highest-numbered file whose `status:` frontmatter is not `done`. (If frontmatter is missing, treat the highest-numbered file as active.)
3. If no milestone files exist, do nothing. Report: "no active milestone — nothing to update."

## Append a progress note

If `$ARGUMENTS` is provided, treat it as the note text. Otherwise ask the user one question:

> "What should the milestone note say?"

Append the note under the `## Progress` section. Create the section if it doesn't exist yet, immediately after the milestone's main body.

Format:

```
- 2026-05-26: <note text>
```

Use today's date. Keep each note to one line where possible.

## Close-out (conditional)

If the note suggests the milestone has shipped — e.g. "shipped /logout endpoint, all exit criteria met" — ask the user:

> "Does this complete this milestone? If yes, I'll set status: done and write the Outcome section."

On confirmation:

1. Set `status: done` in the frontmatter (add the field if missing).
2. Append an `## Outcome` section with a 1-3 sentence summary: what shipped, deviations from the original plan, lessons learned (a brief link to a `devkit-knowledge-capture` follow-up if appropriate).
3. Date the close-out (`Closed: 2026-05-26`).

## Notes

- Milestone files are **historical record** — never delete a closed milestone. The `ls docs/milestones/` view is the project-wide progress log.
- The active milestone is implicit (highest-numbered open file). To switch to a new milestone, the user invokes `devkit-milestone-brainstorm` (M3 skill) or creates a new file by hand.
- This skill never creates milestone files — only appends to existing ones. Creating a new milestone is `devkit-milestone-brainstorm`'s job.
