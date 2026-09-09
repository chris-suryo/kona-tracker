---
name: resume
description: Start-of-session re-entry — load where this project left off from Otto before doing anything else. Use when the user says /resume, "catch me up", or opens a session on a project mid-stream.
---

# /resume

The goal: begin the session already knowing the project's last state — next
step, blockers, and the most recent session note — instead of reconstructing.

## Local session (dos on PATH, Otto reachable at localhost:3123)

Run `dos resume <project>` (Bash) and read the output. Confirm back to the
user in one line: the next step you're picking up and any blocker you're
respecting. If the recorded next step conflicts with what the user is asking
for now, say so — the user's current intent wins, but name the divergence.

## Cloud session (no dos, Otto unreachable)

Ask the user to paste the output of `dos resume <project>` (they run it in
PowerShell on their PC), or the project card's content from Otto's board.
Then proceed as above. If they have nothing to paste, say you're starting
without prior state — don't guess at it.

## Rules

- Never invent prior state. The note you load is the record; absence of a
  record means a fresh start, and you say so.
- Blockers in the record are real until the user says otherwise — don't
  quietly retry something the last session marked "don't retry".
