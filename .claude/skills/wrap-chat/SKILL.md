---
name: wrap-chat
description: End-of-chat capture for DeveloperOS from a REGULAR Claude chat (claude.ai, not Claude Code) — lands this conversation's story on Otto's project board. Use when the user says /wrap, "wrap this up", "save this to my board", or is ending a planning/brainstorm chat they want captured.
---

# /wrap-chat — capture a regular Claude chat into Otto

You are in a NORMAL Claude chat (claude.ai app or web — no repo checkout, no
dos CLI, no reach to Otto). The user's project hub (Otto) is fed through a
git-based outbox: you write one JSON file into their inbox repository on
GitHub, and their PC picks it up within about a minute, automatically.

## 1. Determine the project

The artifact must name one of the user's registered dos projects (lowercase,
hyphens, e.g. `flow`, `developer-os`, `caltrak`). Usually the chat makes it
obvious. If you are not sure, ASK — a wrong name is worse than a question.
If the chat isn't about any particular project, ask whether to file it under
their catch-all (`otto-inbox`).

## 2. Author the artifact — honest and terse

You lived this chat; summarize it truthfully. Planning chats count as work:
decisions made, approaches rejected, and open questions ARE the story. Never
invent progress — this note feeds the user's project memory.

**Encoding rule: ASCII-safe JSON** — escape non-ASCII as `\uXXXX`, prefer
plain ASCII punctuation. A single JSON object:

| field | type | rules |
|---|---|---|
| `project` | string | REQUIRED in this lane — the registered dos project name from step 1 |
| `goal` | string | what this chat set out to figure out, one line |
| `completed` | list[str] | what got worked out — terse bullets |
| `discovered` | list[str] | facts/insights that weren't known before |
| `decisions` | list[str] | choices that remain true after the chat |
| `lessons` | list[str] | reusable learnings |
| `files_changed` | list[str] | usually [] in a chat — leave empty rather than inventing |
| `open_questions` | list[str] | what's still unresolved |
| `intent` | string | WHY the chat ended where it did |
| `next_task` | string | the single most useful next step, one line |
| `blockers` | string \| null | REQUIRED — null ONLY if nothing blocks the project (null clears any recorded blocker) |
| `resume_minutes` | int | honest 5-90 estimate to get back into this thinking |
| `dont_retry` | list[str] | approaches considered and rejected |
| `session_id` | string | optional — a short label for this chat if you have one |

## 3. Deliver — GitHub first, paste as fallback

**Self-check FIRST — never hand over a partial artifact.** Before you write or
paste anything, verify the JSON is ONE complete, valid object: it starts with
`{` and ends with `}`, every string/quote/bracket is closed, and all required
fields are present (`project`, `goal`, `blockers`, `next_task`, `resume_minutes`,
`session_id`). If you cannot produce the whole object in one piece (e.g. it's
getting cut off), say so plainly and re-emit it complete — do NOT deliver a
truncated artifact. `dos post` fail-closes on invalid JSON, so a partial one
just costs the user a dead round-trip.

**Preferred (automatic):** if this chat can use GitHub tools (the GitHub
connector), create a new file in the repository **chris-suryo/otto-inbox**,
branch `main`:

- path: `.dos/outbox/<UTC>Z-chat.json` — timestamp `YYYYMMDDTHHMMSSZ`,
  e.g. `.dos/outbox/20260712T153000Z-chat.json`
- content: the artifact JSON from step 2
- commit message: `dos outbox: chat artifact`

Then tell the user: "Filed to your board — it'll show up on the <project>
card within a minute or two." Done.

**Fallback (no GitHub access in this chat):** print the artifact as a single
fenced ```json block and tell the user:

```
COPY the JSON above, then on your PC (PowerShell):
  Get-Clipboard | dos post <project>
```

## Rules

- Never fabricate work; a fabricated note poisons the board's briefing.
- `blockers` must reflect the PROJECT's real state — an accidental null
  clears a real blocker.
- One artifact per chat wrap; if the user wraps again later in the same
  chat, author a fresh artifact covering what happened since.
