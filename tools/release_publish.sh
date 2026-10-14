#!/usr/bin/env bash
# AI Workbench — GitHub publish tool (v0.1.0-preview.1)
#
# Reusable, resumable, idempotent, non-destructive.
#
# Usage:
#   gh auth login -h github.com -p https -w        (once, on a trusted network)
#   bash tools/release_publish.sh                  (run / resume)
#   bash tools/release_publish.sh --reset-state    (discard resume state)
#
# Env:
#   RELAY   — http proxy for GitHub traffic (default http://127.0.0.1:18923;
#             set RELAY= to go direct when direct connectivity works).
#   REPO    — target repo (default zhongli369/ai-workbench).
#   TAG     — release tag (default v0.1.0-preview.1).
#
# Resume: each completed gate drops a marker under .release-state/ (gitignored).
# Re-running skips completed gates; a network failure reports the exact gate
# that failed and resumes from there on the next run.
#
# Exit codes: 0 ok · 2 auth missing/wrong · 3 network unreachable ·
#             4 local quality gate failed · 5 remote conflict (unknown history,
#             foreign repo, foreign tag — never overwritten) · 6 dirty tree.
#
# The script NEVER force-pushes, never rewrites history, never re-tags a
# published tag, never prints or stores credentials, and refuses to publish
# over anything it does not own.
set -euo pipefail

REPO="${REPO:-zhongli369/ai-workbench}"
TAG="${TAG:-v0.1.0-preview.1}"
RELAY="${RELAY:-http://127.0.0.1:18923}"
OWNER="${REPO%%/*}"
cd "$(dirname "$0")/.."
STATE=".release-state"

if [ "${1:-}" = "--reset-state" ]; then rm -rf "$STATE"; echo "state cleared"; exit 0; fi
mkdir -p "$STATE"
grep -qx '.release-state/' .gitignore 2>/dev/null || echo '.release-state/' >> .gitignore

step() { printf '\n=== %s ===\n' "$1"; }
die()  { printf 'PUBLISH ABORT [%s]: %s\n' "$2" "$1" >&2; exit "$2"; }
done_gate() { [ -f "$STATE/$1" ]; }
mark()  { date -u +%FT%TZ > "$STATE/$1"; echo "gate $1 done — resume marker written"; }

gitenv() { if [ -n "$RELAY" ]; then HTTPS_PROXY="$RELAY" HTTP_PROXY="$RELAY" "$@"; else "$@"; fi; }
gitc()   { if [ -n "$RELAY" ]; then git -c http.proxy="$RELAY" "$@"; else git "$@"; fi; }

step "gate 0: prerequisites (auth + reachability)"
command -v gh  >/dev/null || die "gh CLI not found" 2
command -v git >/dev/null || die "git not found" 2
[ -n "$(gitenv gh auth token 2>/dev/null)" ] || die \
  "not authenticated — run: gh auth login -h github.com -p https -w (trusted network)" 2
LOGIN=$(gitenv gh api user --jq .login 2>/dev/null) \
  || die "cannot reach GitHub (network down? RELAY='$RELAY'; try RELAY= for direct)" 3
[ "$LOGIN" = "$OWNER" ] || die "authenticated as '$LOGIN', expected '$OWNER'" 2
echo "authenticated as $LOGIN"

step "gate 1: local quality gates on the snapshot"
if done_gate 1_local; then echo "skip (done)"; else
  python -m pytest tests/ -q | tail -1            || die "tests/ failed" 4
  python -m pytest harness-core/tests/ -q | tail -1 || die "harness-core tests failed" 4
  python tools/check_hygiene.py | tail -1          || die "hygiene gate failed" 4
  python tools/check_docs_drift.py | tail -1       || die "docs drift gate failed" 4
  mark 1_local
fi

step "gate 2: snapshot commit"
SHA=$(git rev-parse HEAD)
echo "snapshot: $SHA ($(git log -1 --format=%s))"
git diff --quiet && git diff --cached --quiet || die "working tree dirty — commit first" 6
if done_gate 2_snap; then
  [ "$(cat "$STATE/2_snap_sha" 2>/dev/null)" = "$SHA" ] \
    || die "HEAD moved since the quality gates passed — re-run with --reset-state" 5
else
  echo "$SHA" > "$STATE/2_snap_sha"; mark 2_snap
fi

step "gate 3: remote repo (create or verify ownership — never overwrite)"
if done_gate 3_repo; then echo "skip (done)"; else
  if gitenv gh repo view "$REPO" --json name >/dev/null 2>&1; then
    echo "repo exists — verifying ownership"
    gitenv gh repo view "$REPO" --json owner --jq .owner.login | grep -qx "$OWNER" \
      || die "repo $REPO exists but is not owned by $OWNER" 5
  else
    echo "creating public repo $REPO"
    gitenv gh repo create "$REPO" --public \
      --description "AI Workbench — governed, on-demand engineering workbench for Claude Code (public preview)" \
      || die "repo creation failed (network? rerun to resume)" 3
  fi
  mark 3_repo
fi

step "gate 4: push (non-destructive)"
if done_gate 4_push; then echo "skip (done)"; else
  git remote get-url origin >/dev/null 2>&1 || git remote add origin "https://github.com/$REPO.git"
  git branch --list main | grep -q main || git branch main "$SHA"
  gitc push -u origin main \
    || die "push refused — remote has unknown history; inspect manually (no force-push allowed)" 5
  gitc push origin "$SHA:refs/heads/fusion" 2>/dev/null || true
  mark 4_push
fi

step "gate 5: tag + pre-release"
if done_gate 5_rel; then echo "skip (done)"; else
  if gitc ls-remote --tags origin "$TAG" | grep -q "$TAG"; then
    REMOTE_TAG_SHA=$(gitc ls-remote --tags origin "$TAG" | awk '{print $1}')
    [ "$REMOTE_TAG_SHA" = "$SHA" ] \
      || die "tag $TAG already points elsewhere ($REMOTE_TAG_SHA) — never retag a published tag" 5
    echo "tag $TAG already correct"
  else
    git tag -a "$TAG" -m "AI Workbench public preview" "$SHA" 2>/dev/null || \
      git tag -f "$TAG" "$SHA" >/dev/null  # local-only retag before first push
    gitc push origin "$TAG" || die "tag push failed (network? rerun to resume)" 3
  fi
  NOTES="../ai-workbench-fusion/docs/launch/RELEASE_NOTES_${TAG}.md"
  [ -f "$NOTES" ] || NOTES=""
  if gitenv gh release view "$TAG" >/dev/null 2>&1; then
    echo "release $TAG already exists — leaving untouched"
  elif [ -n "$NOTES" ]; then
    gitenv gh release create "$TAG" --prerelease --title "AI Workbench $TAG" --notes-file "$NOTES" \
      || die "release creation failed (network? rerun to resume)" 3
  else
    gitenv gh release create "$TAG" --prerelease --title "AI Workbench $TAG" --generate-notes \
      || die "release creation failed (network? rerun to resume)" 3
  fi
  mark 5_rel
fi

step "gate 6: independent public verification (unauthenticated)"
sleep 5
CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 ${RELAY:+-x $RELAY} "https://github.com/$REPO" || true)
[ "$CODE" = "200" ] || die "public URL check failed (HTTP $CODE): https://github.com/$REPO" 3
RCODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 ${RELAY:+-x $RELAY} "https://github.com/$REPO/releases/tag/$TAG" || true)
[ "$RCODE" = "200" ] || die "release URL check failed (HTTP $RCODE)" 3
mark 6_verify

printf '\nPUBLISH GATES: PUBLIC_REPO_CREATED=ok CODE_PUSHED=ok TAG_PUBLISHED=ok RELEASE_PUBLISHED=ok PUBLIC_VERIFIED=ok\n'
printf 'repo:     https://github.com/%s\n' "$REPO"
printf 'release:  https://github.com/%s/releases/tag/%s\n' "$REPO" "$TAG"
printf 'snapshot: %s\n' "$SHA"
