## What changed

<!-- One or two sentences. The commit messages carry the reasoning; this is
     the summary somebody reads before opening the diff. -->

## Why

<!-- The problem, not the solution. If it fixes something that was on the
     phone, say what it looked like. -->

## How it was verified

<!-- Which of these actually ran, and what they said. Delete the rest. -->

- [ ] `uv run pytest -q`
- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `node --test tests/browser_runtime.test.cjs` (touches page scripts)
- [ ] `scripts/audit_shots.js` re-captured (changes what a page looks like)
- [ ] `scripts/check_overflow.js` (changes layout or copy length)
- [ ] `/security-review` (touches routes, auth, the CSP, or the robot)
- [ ] Tried on the phone

<!-- Anything you could not verify here belongs in the PR body, not left
     unsaid. "Unexecuted in this environment" is a complete sentence. -->
