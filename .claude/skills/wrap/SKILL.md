---
name: wrap
description: End-of-session capture for DeveloperOS — land this session's story in Otto. Locally it runs `dos wrap`; in a cloud session it emits the SessionArtifact JSON for `dos post`. Use when the user says /wrap, "wrap it up", "wrap this session" — or signals they're finishing in ANY phrasing ("I'm done", "stop", "gotta go", "calling it", switching to another topic/project): that stop-intent triggers this skill proactively (confirm in one line, then wrap — the auto-wrap norm, docs/seamless-loop.md Phase 2).
---

# /wrap — capture this session into Otto

The user is ending a working session. Your job: make sure this session's story
lands in Otto (the project hub) through dos, using whichever lane fits where
you are running. The map of the whole system is `docs/SYSTEM-MAP.md`.

## 1. Detect the lane

Check whether the `dos` CLI exists (`command -v dos` / `where.exe dos`) and
whether Otto answers at `http://localhost:3123/api/health`.

- Both true → **LOCAL lane** (you're on the user's PC).
- Otherwise → **CLOUD lane** (typical for claude.ai/code sessions: no dos
  binary, Otto unreachable — the transcript never touches the user's disk).

## 2a. LOCAL lane

Run `dos wrap` (add `-p <project>` if name resolution could be ambiguous) and
show its output. If it fails closed, show the error and hint verbatim and stop
— never retry with hand-written content on this lane; fail-closed is the
product working.

Then run `dos flush` — the wrap moment is the natural sync point, so any cloud
/wrap artifacts waiting on GitHub ride in right now instead of at the next
scheduled tick. (Harmless when there's nothing pending: "spool is empty".)

## 2b. CLOUD lane

Author the session's `SessionArtifact` yourself — you lived this session, so
you are the best summarizer available. Be honest and terse.

**Step 1 — commit to the repo's outbox (the automatic lane).** If you're in a
writable git repo (typical for cloud sessions), write the artifact JSON to
`.dos/outbox/<UTC>Z-session.json` (timestamp format `YYYYMMDDTHHMMSSZ`, e.g.
`20260712T091500Z-session.json`), then commit and push it on the current
branch (message: `dos outbox: session artifact`). dos on the user's PC imports
and posts it automatically the next time it flushes after this branch reaches
their machine (merge, pull, or checkout) — no relay needed. If the commit or
push fails, skip this step silently; the fence below still works.

**Step 2 — always ALSO emit the fence (the instant lane).** The outbox has
merge/pull latency; the paste relay updates the board immediately and doubles
as the human review step. Emit EXACTLY ONE fenced ```json block, a single
object with these fields.

**Self-check before you emit it — never hand over a partial artifact.** Verify
the JSON is ONE complete, valid object: starts with `{`, ends with `}`, every
quote/bracket closed, all required fields present (esp. `blockers`,
`next_task`). If it's getting cut off, say so and re-emit it whole — a truncated
artifact just fail-closes `dos post` and costs a dead round-trip.

**Encoding rule: the JSON must be ASCII-safe** — escape every non-ASCII
character as `\uXXXX` (what `json.dumps` with `ensure_ascii=True` produces),
and prefer plain ASCII punctuation (`-`, `...`, `"`) in the text itself. The
artifact travels through a Windows PowerShell 5.1 clipboard pipe that silently
replaces characters it can't encode — an em-dash or ✓ would arrive as `?` and
be delivered as a degraded note with no error anywhere. ASCII survives every
relay.

| field | type | rules |
|---|---|---|
| `goal` | string | what the session set out to do, one line |
| `completed` | list[str] | what actually got done — terse bullets |
| `discovered` | list[str] | facts learned that weren't known before |
| `decisions` | list[str] | choices that remain true after the session |
| `lessons` | list[str] | reusable how-to / don't-do-X learnings |
| `files_changed` | list[str] | files edited or created |
| `open_questions` | list[str] | unresolved questions to carry forward |
| `intent` | string | WHY the session ended where it did |
| `next_task` | string | the single most useful next step, one line |
| `blockers` | string \| null | **REQUIRED — never omit.** null ONLY if nothing blocks the project (null clears any previously recorded blocker in Otto) |
| `resume_minutes` | int | honest 0-90 estimate to get back into flow (0 if the work is done / nothing to resume) |
| `dont_retry` | list[str] | approaches tried and failed — don't repeat |
| `session_id` | string | optional — include if you know it |

Then print the relay instruction for the user, filling in the project name
(mention whether the outbox commit succeeded — if it did, pasting is optional:
the board updates by itself once the branch lands, or right now via the paste):

```
READ the JSON before posting — especially `blockers`. You are the only
objectivity check in this lane. Then, on your PC:
  1. COPY the JSON block above (select it, Ctrl+C) — don't paste it at the
     prompt; the clipboard is how it travels.
  2. PowerShell:  Get-Clipboard | dos post <project> --dry-run   (preview)
  3.              Get-Clipboard | dos post <project>             (deliver)
  If step 2 says "invalid JSON", the copy didn't take — fall back to saving
  it to a file (-Encoding UTF8 matters; PS 5.1 defaults to ASCII):
  Get-Clipboard | Set-Content -Encoding UTF8 $env:TEMP\a.json  then
  dos post <project> -a $env:TEMP\a.json
```

## Rules (both lanes)

- Never invent work that didn't happen; a fabricated note poisons Otto's
  briefing (the same fail-closed principle `dos wrap` enforces).
- **You are summarizing your own work — report wrong paths, dead ends, and
  wasted time honestly; that is exactly what `dont_retry` and `lessons`
  exist for.** A transcript-reading summarizer sees the wandering; a session
  grading itself tends to omit it. A self-flattering artifact defeats the
  system (the note's `via post` stamp exists so this drift stays auditable).
- If the session was trivial, say so in `goal` and leave the lists empty.
- Treat `blockers` with care: it must reflect the project's real state at
  session end, because an accidental null clears a real blocker.
