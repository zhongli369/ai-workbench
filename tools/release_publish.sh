#!/usr/bin/env bash
# AI Workbench — GitHub Public Preview publish script (v0.1.0-preview.1)
#
# One-shot, idempotent, non-destructive. Run AFTER authentication:
#   gh auth login -h github.com -p https -w        (on a trusted network)
# then:
#   bash tools/release_publish.sh
#
# Env:
#   RELAY   — http proxy for GitHub traffic (default http://127.0.0.1:18923;
#             set RELAY= to go direct when direct connectivity works).
#   REPO    — target repo (default zhongli369/ai-workbench).
#   TAG     — release tag (default v0.1.0-preview.1).
#
# The script NEVER force-pushes, never rewrites history, never prints or
# stores credentials, and refuses to publish over a repo it does not own.
set -euo pipefail

REPO="${REPO:-zhongli369/ai-workbench}"
TAG="${TAG:-v0.1.0-preview.1}"
RELAY="${RELAY:-http://127.0.0.1:18923}"
OWNER="${REPO%%/*}"
cd "$(dirname "$0")/.."

step() { printf '\n=== %s ===\n' "$1"; }
die()  { printf 'PUBLISH ABORT: %s\n' "$1" >&2; exit 1; }

gitenv() { # run git/gh with optional relay, never persistently configured
  if [ -n "$RELAY" ]; then
    HTTPS_PROXY="$RELAY" HTTP_PROXY="$RELAY" "$@"
  else
    "$@"
  fi
}
gitc() { if [ -n "$RELAY" ]; then git -c http.proxy="$RELAY" "$@"; else git "$@"; fi; }

step "gate 0: prerequisites"
command -v gh >/dev/null || die "gh CLI not found"
command -v git >/dev/null || die "git not found"
[ -n "$(gitenv gh auth token 2>/dev/null)" ] || die \
  "not authenticated — run: gh auth login -h github.com -p https -w (trusted network)"
LOGIN=$(gitenv gh api user --jq .login 2>/dev/null) || die "cannot reach GitHub (network? RELAY=$RELAY)"
[ "$LOGIN" = "$OWNER" ] || die "authenticated as '$LOGIN', expected '$OWNER'"
echo "authenticated as $LOGIN"

step "gate 1: local quality gates on the snapshot"
python -m pytest tests/ -q | tail -1
python -m pytest harness-core/tests/ -q | tail -1
python tools/check_hygiene.py | tail -1

step "gate 2: snapshot commit"
SHA=$(git rev-parse HEAD)
echo "snapshot: $SHA ($(git log -1 --format=%s))"
git diff --quiet && git diff --cached --quiet || die "working tree dirty — commit first"

step "gate 3: remote repo (create or verify ownership — never overwrite)"
if gitenv gh repo view "$REPO" --json name >/dev/null 2>&1; then
  echo "repo exists — verifying ownership and history compatibility"
  gitenv gh repo view "$REPO" --json owner --jq .owner.login | grep -qx "$OWNER" \
    || die "repo $REPO exists but is not owned by $OWNER"
else
  echo "creating public repo $REPO"
  gitenv gh repo create "$REPO" --public \
    --description "AI Workbench — ECC prompt-engineering layer + deterministic harness-core (public preview)" \
    || die "repo creation failed"
fi

step "gate 4: push (non-destructive)"
git remote get-url origin >/dev/null 2>&1 || git remote add origin "https://github.com/$REPO.git"
git branch --list main | grep -q main || git branch main "$SHA"
gitc push -u origin main || die "push refused — remote has unknown history; inspect manually (no force-push allowed)"
gitc push origin "$SHA:refs/heads/fusion" 2>/dev/null || true

step "gate 5: tag + pre-release"
if gitc ls-remote --tags origin "$TAG" | grep -q "$TAG"; then
  REMOTE_TAG_SHA=$(gitc ls-remote --tags origin "$TAG" | awk '{print $1}')
  [ "$REMOTE_TAG_SHA" = "$SHA" ] || die "tag $TAG already points elsewhere ($REMOTE_TAG_SHA) — never retag"
  echo "tag $TAG already correct"
else
  git tag -a "$TAG" -m "AI Workbench public preview" "$SHA" 2>/dev/null || \
    git tag -f "$TAG" "$SHA" >/dev/null  # local-only retag before first push
  gitc push origin "$TAG"
fi
NOTES="../ai-workbench-fusion/docs/launch/RELEASE_NOTES_${TAG}.md"
[ -f "$NOTES" ] || NOTES=""
if gitenv gh release view "$TAG" >/dev/null 2>&1; then
  echo "release $TAG already exists — leaving untouched"
else
  if [ -n "$NOTES" ]; then
    gitenv gh release create "$TAG" --prerelease --title "AI Workbench $TAG" --notes-file "$NOTES"
  else
    gitenv gh release create "$TAG" --prerelease --title "AI Workbench $TAG" --generate-notes
  fi
fi

step "gate 6: independent public verification (unauthenticated)"
sleep 5
CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 ${RELAY:+-x $RELAY} "https://github.com/$REPO")
[ "$CODE" = "200" ] || die "public URL check failed (HTTP $CODE): https://github.com/$REPO"
RCODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 ${RELAY:+-x $RELAY} "https://github.com/$REPO/releases/tag/$TAG")
[ "$RCODE" = "200" ] || die "release URL check failed (HTTP $RCODE)"

printf '\nPUBLISH GATES: PUBLIC_REPO_CREATED=ok CODE_PUSHED=ok TAG_PUBLISHED=ok RELEASE_PUBLISHED=ok PUBLIC_VERIFIED=ok\n'
printf 'repo:     https://github.com/%s\n' "$REPO"
printf 'release:  https://github.com/%s/releases/tag/%s\n' "$REPO" "$TAG"
printf 'snapshot: %s\n' "$SHA"
