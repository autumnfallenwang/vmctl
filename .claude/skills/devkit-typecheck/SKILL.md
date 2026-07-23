---
name: devkit-typecheck
description: Use when the user says "typecheck", "type check", "check types", or when `devkit-task`'s check loop invokes this skill. Validates static type contracts without running the code.
allowed-tools: Bash
---

Run the typecheck command for vmctl. Validates the codebase's static type contracts.

## Commands

- **python (pyright)**: `uv run pyright`

## Reporting

After running:

- **Exit 0** → report "Typecheck passed." and stop.
- **Non-zero exit** → show the first 20 lines of output. Surface the type errors verbatim — do not attempt to silently fix them.

## Notes

- This skill is invoked by `devkit-task`'s check loop as part of the standard verification sequence. It is also user-facing via natural language ("typecheck", "check types").
- Some languages have no separate typecheck step (the build IS the typecheck). In that case the command above runs the build — same outcome.
- If multiple language sections are listed, run each in order. A non-zero exit from any section stops the sequence.
