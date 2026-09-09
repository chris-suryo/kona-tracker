---
name: grill
description: Stress-test a plan or design by interrogating the user relentlessly, one question at a time, before anything gets built. Use when the user says /grill, "grill me", "stress-test this plan", or is about to commit to a non-trivial design that hasn't been challenged yet.
---

# /grill

*Adapted from Matt Pocock's `grilling` skill (github.com/mattpocock/skills,
MIT, © 2026 Matt Pocock) — with a handoff into this kit's `/plan`.*

**First move — check the stamped scaffold against the spec's shape.** If the
repo carries a Python scaffold (`pyproject.toml`, `src/`, python-matrix CI) but
the spec is a game / web / other non-Python shape, that mismatch is decision #1:
confirm ripping the scaffold out (it should have been `dos new --shape minimal`)
before any design question — project structure, CI, and commands all hang off
it. New projects stamped with the right shape won't hit this; older or
mis-stamped repos still will.

Interview me relentlessly about every aspect of this plan until we reach a
shared understanding. Walk down each branch of the design tree, resolving
dependencies between decisions one-by-one. For each question, provide your
recommended answer.

Ask the questions ONE AT A TIME, waiting for my answer before continuing —
asking multiple questions at once is bewildering.

If a *fact* can be found by exploring the codebase, look it up rather than
asking me. The *decisions*, though, are mine — put each one to me and wait
for my answer.

Do not build anything until I confirm we have reached a shared understanding.

## Handoff to /plan

When I confirm shared understanding, do NOT start coding. Run `/plan`:
condense everything we just resolved into its goal / approach / assumptions /
scope / risks format and stop for my approval. Grill surfaces the
ambiguities; plan commits to the approach. They compose — never compete.
