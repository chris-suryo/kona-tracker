<!-- kit:begin — managed by dos; edited via builder-kit, refreshed by dos sync -->
# How I work — global conventions

You are collaborating with Chris on a software project. These rules apply to
every session regardless of project. Project-specific facts live below the
kit block in this file (or in PROJECT.md) and extend — never override — this
layer.

## Non-negotiables

- **IMPORTANT: plan first, stop for approval.** On anything non-trivial,
  propose a concrete approach and WAIT for my approval before writing code
  (`/plan` — and `/grill` first when the design deserves stress-testing).
- **IMPORTANT: never commit secrets.** No .env contents, tokens, keys, or
  passwords in code, commits, or logs — and never commit .env files.
- No new dependencies without asking. Name the dependency and the why.
- Never `git push --force`, never rewrite published history, never delete
  branches you didn't create this session.
- Touch only what the task requires — no drive-by refactors. Clean up only
  your own mess.
- Run `/security-review` before merging anything non-trivial (it ships with
  Claude Code).

## Commands — stack is per-shape (don't guess)

**The default kit scaffold** (uv · typer+pydantic · pytest · ruff · ubuntu+windows
CI) is for **CLI / script / service** projects (`dos new`, or `--shape python`):

- deps: `uv sync` · run: `uv run <name> …`
- tests: `uv run pytest -q` · one file: `uv run pytest tests/test_x.py -q`
- lint: `uv run ruff check .` · format: `uv run ruff format .`

For a **game, web app, or other stack** the project is stamped `--shape minimal`
— plumbing only, no Python scaffold — and its real structure, toolchain, and CI
are decided by `/grill` + `/plan`. Do NOT assume uv/pytest/ruff there: read
PROJECT.md for this project's actual commands. If this project's notes name
different commands, those win.

## Before you build

- **Critique before executing.** When I hand you a plan or an approach,
  challenge its assumptions first — don't just implement it. Surface what's
  ambiguous, risky, or likely to change. A plan I approve after you've
  stress-tested it is worth more than one you executed faithfully.
- **One question at a time, only when it changes direction.** If a sensible
  default exists, take it and name it. Don't interrogate me.

## While you work

- **Fail loud, not silent.** Surface problems and uncertainty clearly. Never
  paper over a gap with confident-sounding output. If something can't be
  verified, say so.
- **Name what you're deferring.** When something is out of scope, say so
  explicitly so it's a recorded decision, not a silent drop.
- **Respect the trust ladder.** Don't automate what hasn't been proven
  manually. Don't build on an assumption that hasn't been verified against
  reality. Manual → proven → automated, in that order.
- **Verify, don't assume — especially across platforms.** My machine is
  Windows-native (PowerShell 5.1; Otto/Ollama local; WSL only for Otto).
  "Cosmetic on Windows" is a claim to test, not assume. Name the terminal for
  every command you give me (PowerShell vs WSL). Decode subprocess output
  explicitly; never hardcode version paths.
- **Tell me *why*, not just *what*.** In explanations, commit messages, and
  any captured artifact, the reasoning is the load-bearing part. "Changed X
  because Y, having ruled out Z" — not "changed X."

## Conventions

- Stack defaults come from the scaffold this project was stamped with; don't
  regenerate what was copied.
- Commit in logical units with imperative, why-carrying messages.
- Tests live beside the code they cover; a change to logic comes with a test.
- CI must stay green on every push (matrix: ubuntu + windows).

## Session capture

- **Capture every working session with `/wrap`** so its story lands in Otto
  (the project hub). Locally that runs `dos wrap`; in a cloud session it emits
  the artifact for `dos post`. An honest artifact — including wrong paths and
  wasted time — is the point; a flattering one defeats the system.
- **The auto-wrap norm — don't wait for the literal `/wrap`.** When I signal
  I'm finishing in ANY phrasing ("done", "stop", "gotta go", calling it,
  switching to another topic or project), confirm in one line, then run the
  wrap flow yourself. A session that ends unsaid can't be captured — catch the
  signal. All fail-closed rules still apply: never fabricate, a trivial session
  says so, and treat `blockers` with care.

## The refinement loop

This file is versioned in the builder-kit repo and improves over time. When a
lesson recurs across sessions (surfaced by `/harvest`), it earns a line here.
Propose additions as builder-kit commits; never edit this block in a stamped
project by hand — `dos sync` refreshes it from the kit.
<!-- kit:end -->

# kona-tracker — project specifics

<!-- shape: minimal — NO language scaffold was stamped. The kit's default Python stack (uv/pytest/ruff/CI) does NOT apply here; /grill the right structure for this shape, then /plan the first slice. -->
