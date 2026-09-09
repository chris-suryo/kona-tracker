#!/bin/sh
# DeveloperOS SessionStart hook — inject the standard + orientation at the top of
# every session. Committed to .claude/settings.json, so it fires in BOTH local and
# cloud (claude.ai/code) sessions. A hook's stdout is added to the model's context
# at session start; this guarantees the session sees PROJECT.md (which, unlike
# CLAUDE.md, does NOT auto-load) and, locally, live re-entry state.
#
# Dependency-free on purpose: the rules/orientation payload never touches dos, so
# it can't fail on a machine (the cloud) that has no dos binary. The dos-resume
# payload is added only when dos is actually on PATH. See docs/NORTH-STAR.md.
#
# Self-naming: the project name is the repo folder name (which `dos new` makes
# equal to the Otto project name). So this is ONE identical file for every
# project — no per-project substitution — and the builder-kit ships it verbatim.

DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
# lowercased so a capital-cased clone (e.g. the cloud's "Developer-OS") still
# matches the Otto project name, which is always lowercase.
PROJECT_NAME=$(basename "$DIR" | tr '[:upper:]' '[:lower:]')

echo "== $PROJECT_NAME: session orientation =="
echo "Standing rules are in CLAUDE.md (already loaded). Before acting: read the"
echo "PROJECT.md below (especially Locations), confirm the next step still makes"
echo "sense, and plan-first on anything non-trivial."
echo
echo "END-OF-SESSION NORM (seamless-loop Phase 2): when the user signals they're"
echo "finishing — 'done', 'stop', 'gotta go', a topic/project switch, ANY phrasing,"
echo "not just /wrap — proactively run the /wrap skill: confirm in one line, then"
echo "wrap. A session that ends unsaid can't be captured — catch the signal."
echo

if [ -f "${DIR}/PROJECT.md" ]; then
  echo "----- PROJECT.md -----"
  cat "${DIR}/PROJECT.md"
  echo "----- end PROJECT.md -----"
else
  echo "(no PROJECT.md yet — add one; it is this project's orientation + Locations)"
fi

# Local lane only: auto-pull the current branch so new code/skills (like a
# freshly-built /reflect) show up with zero manual steps — and SAY SO, so
# there's always a visible receipt instead of silent drift. --ff-only refuses
# (loudly, in pull_out) rather than touching anything if local commits or
# uncommitted edits would be at risk — never destructive. Cloud sessions clone
# fresh every time, so this is a no-op there by construction (no .git-backed
# CLAUDE_PROJECT_DIR with a stale remote to race).
if [ "${CLAUDE_CODE_REMOTE}" != "true" ] && [ -d "${DIR}/.git" ]; then
  before_sha=$(git -C "${DIR}" rev-parse HEAD 2>/dev/null)
  pull_out=$(git -C "${DIR}" pull --ff-only --quiet 2>&1)
  pull_status=$?
  after_sha=$(git -C "${DIR}" rev-parse HEAD 2>/dev/null)
  if [ "${pull_status}" -ne 0 ]; then
    echo
    echo "⚠ auto-pull skipped: ${pull_out}"
    echo "  (uncommitted local changes, no upstream, or offline — check with 'git status' / 'git pull' by hand)"
  elif [ -n "${before_sha}" ] && [ "${before_sha}" != "${after_sha}" ]; then
    n=$(git -C "${DIR}" rev-list --count "${before_sha}..${after_sha}" 2>/dev/null)
    echo
    echo "↓ pulled ${n:-some} new commit(s) from origin — you're up to date"
  fi
fi

# BOTH lanes: the session handoff (seamless-loop Phase 1, docs/seamless-loop.md).
# Every wrap writes the session's story to .dos/outbox/<utc>Z-*.json IN THE REPO,
# so the newest artifact IS the previous session's handoff — readable from a
# fresh cloud clone (phone included), no PC, no Otto. Runs AFTER the auto-pull
# above so a just-pulled artifact is included. Filenames are UTC-stamped, so
# glob order is chronological; the last one wins. Dependency-free (no jq): we
# name the file and tell the session to read it — the model parses JSON better
# than a shell field-dump would.
latest_artifact=""
for f in "${DIR}/.dos/outbox"/*.json; do
  [ -e "$f" ] && latest_artifact="$f"
done
if [ -n "${latest_artifact}" ]; then
  echo
  echo "----- session handoff (where the last session left off) -----"
  echo "Newest session artifact: .dos/outbox/$(basename "${latest_artifact}")"
  echo "READ that file FIRST for re-entry: it carries the last session's goal,"
  echo "decisions, lessons, next_task, and blockers. Confirm its next_task still"
  echo "makes sense before acting on it."
  echo "----- end handoff -----"
fi

# Local lane only: inject live re-entry state when dos + its registry are present.
# Cloud sessions set CLAUDE_CODE_REMOTE=true and have no dos binary — skip silently.
if [ "${CLAUDE_CODE_REMOTE}" != "true" ] && command -v dos >/dev/null 2>&1; then
  resume_out=$(dos resume "${PROJECT_NAME}" 2>/dev/null)
  if [ -n "${resume_out}" ]; then
    echo
    echo "----- dos resume ${PROJECT_NAME} -----"
    echo "${resume_out}"
    echo "----- end dos resume -----"
  fi
fi

exit 0
