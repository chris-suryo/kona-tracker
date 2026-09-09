---
name: plan
description: Before writing code on any non-trivial task, produce a short plan and stop for approval. Fires when the user asks to build, implement, refactor, or change anything beyond a trivial edit, or types /plan.
---

# /plan

When invoked (or when a task is non-trivial), do NOT write code yet. Produce:

1. **Goal** — one sentence: what "done" looks like.
2. **Approach** — the concrete path, named. If there's a fork, present 2–3
   options with the tradeoff, and recommend one.
3. **Assumptions** — what you're taking as given. Flag any you're unsure of.
4. **Scope** — what this does and, explicitly, what it does NOT touch.
5. **Risks / unknowns** — what could go wrong or needs verifying first.

Then stop and wait for approval. Revise on feedback before writing any code.

When the plan is approved, also **write it into the repo** as
`docs/<slice>-plan.md` and commit it — not only the session-local plan file. A
separate build session on a fresh clone can't see the session-local plan; the
in-repo copy is what survives the handoff. Point PROJECT.md `next:` at it.

Keep it short — a screen, not a document. The point is a shared model before
implementation, not ceremony.
