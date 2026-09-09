---
name: harvest
description: Read recent dos session artifacts from Otto and propose builder-kit improvements — recurring lessons that should become skills or CLAUDE.md rules, conventions that keep getting violated, dead-weight skills. Run periodically (weekly), not per-session.
---

# /harvest

Pull recent session artifacts from Otto (the project_updates log / briefing),
across all projects, for the review window (default: last 14 days). Locally,
`dos resume <project>` and Otto's briefing at http://localhost:3123 are the
reading surfaces; ask the user to paste them if you can't reach Otto.

Analyze for patterns — NOT one-off events:

1. **Recurring lessons** — a "why we stopped" or "don't retry" that shows up
   in 3+ sessions signals a missing skill or a CLAUDE.md rule. Propose the
   concrete addition.
2. **Repeated violations** — a convention in CLAUDE.md that keeps getting
   broken suggests the rule is unclear or unenforced. Propose a sharpening.
3. **Dead weight** — a skill that never fired, or fired and didn't help.
   Propose removal.
4. **New skill candidates** — a manual workflow repeated across sessions with
   no skill covering it. Propose writing one.

Output a short report: each finding, the evidence (which sessions), and the
proposed kit change. **Propose only** — changes to the kit are commits the
user approves in the builder-kit repo, so they have history and can be
reverted. Never auto-edit the kit.

This is what makes the kit grow from real friction instead of guesswork. If
there are too few real artifacts to see patterns, say exactly that and stop —
do not invent findings.
