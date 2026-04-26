#!/usr/bin/env bash
# Build the static site and publish it to the `gh-pages` branch on origin.
#
# Run from project root:
#     ./scripts/deploy-site.sh
#
# This script never touches your current working tree: it operates on a
# temporary git worktree, creates an orphan commit there, force-pushes it
# to refs/heads/gh-pages on origin, and removes the worktree.
#
# First-run prereq: GitHub Pages must be enabled with Source = "Deploy from
# branch", branch = `gh-pages`, folder = `/ (root)`. The bootstrap step at
# the end of this script will configure that automatically via `gh api` if
# Pages is not yet enabled. Re-runs are idempotent.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DEFAULT_REMOTE=origin
DEPLOY_BRANCH=gh-pages

if [ ! -f phase0.sqlite ]; then
  echo "deploy-site: phase0.sqlite not found at project root."
  echo "             Load + rate the data first (see scripts/phase0/README.md)."
  exit 1
fi

echo "==> Generating site/ from phase0.sqlite ..."
python3 scripts/phase0/generate_site.py >/dev/null
test -f site/index.html
test -f site/.nojekyll
echo "    site/ ready ($(find site -type f | wc -l | tr -d ' ') files)."

# Resolve the GitHub repo slug from the configured remote.
REMOTE_URL="$(git config --get "remote.${DEFAULT_REMOTE}.url")"
case "$REMOTE_URL" in
  *github.com[:/]*) ;;
  *)
    echo "deploy-site: remote ${DEFAULT_REMOTE} (${REMOTE_URL}) is not a GitHub URL."
    exit 1
    ;;
esac
REPO_SLUG="$(echo "$REMOTE_URL" | sed -E 's#.*github\.com[:/]##; s#\.git$##')"
echo "==> Repo: $REPO_SLUG  remote: $DEFAULT_REMOTE  branch: $DEPLOY_BRANCH"

# Set up a temporary worktree pointing at HEAD's commit so git plumbing works.
TMP_WT="$(mktemp -d -t rallyrank-deploy.XXXXXX)"
BUILD_BRANCH="_ghpages_build_$$"
cleanup() {
  git worktree remove --force "$TMP_WT" >/dev/null 2>&1 || true
  git branch -D "$BUILD_BRANCH" >/dev/null 2>&1 || true
  # Also nuke any orphan _ghpages_build branches left by prior failed runs.
  for b in $(git branch --list '_ghpages_build*' --format='%(refname:short)' 2>/dev/null); do
    git branch -D "$b" >/dev/null 2>&1 || true
  done
  rm -rf "$TMP_WT"
}
trap cleanup EXIT

# Pre-clean any leftover build branches from failed prior runs.
for b in $(git branch --list '_ghpages_build*' --format='%(refname:short)' 2>/dev/null); do
  git branch -D "$b" >/dev/null 2>&1 || true
done

git worktree add --detach "$TMP_WT" HEAD >/dev/null
(
  cd "$TMP_WT"
  # Become an orphan branch so we don't carry main's history into gh-pages.
  git checkout --orphan "$BUILD_BRANCH" >/dev/null
  git rm -rf --quiet --cached . || true
  # Wipe the worktree (preserve only the .git pointer file).
  find . -mindepth 1 -maxdepth 1 ! -name ".git" -exec rm -rf {} +
  cp -R "$REPO_ROOT/site/." .
  test -f .nojekyll  # safety: the marker must come along
  git add -A
  SOURCE_REV="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
  TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  git -c user.name="RallyRank deploy" \
      -c user.email="deploy@rallyrank.local" \
      commit -m "deploy: ${TS} (from ${SOURCE_REV})" --quiet
  echo "==> Force-pushing $(git rev-parse HEAD | cut -c1-7) to ${DEFAULT_REMOTE}/${DEPLOY_BRANCH}"
  git push --force "${DEFAULT_REMOTE}" "HEAD:refs/heads/${DEPLOY_BRANCH}"
)

# Bootstrap or refresh GitHub Pages config (idempotent). Try PUT first (works
# whether Pages is already enabled or not in many cases); fall back to POST
# only if PUT reports "page not found", and treat 409 (already enabled) as a
# no-op success.
echo "==> Checking GitHub Pages configuration ..."
PUT_OUT="$(gh api -X PUT "repos/${REPO_SLUG}/pages" \
    -F "source[branch]=${DEPLOY_BRANCH}" \
    -F "source[path]=/" 2>&1)" && PUT_OK=1 || PUT_OK=0

if [ "$PUT_OK" = "1" ]; then
  echo "    Pages source updated -> branch=${DEPLOY_BRANCH}, path=/."
elif echo "$PUT_OUT" | grep -qi "not found\|404"; then
  echo "    Pages not yet enabled. Enabling ..."
  POST_OUT="$(gh api -X POST "repos/${REPO_SLUG}/pages" \
      -F "source[branch]=${DEPLOY_BRANCH}" \
      -F "source[path]=/" 2>&1)" && POST_OK=1 || POST_OK=0
  if [ "$POST_OK" = "1" ] || echo "$POST_OUT" | grep -qi "already enabled\|409"; then
    echo "    Pages enabled."
  else
    echo "    WARNING: failed to enable Pages: $POST_OUT"
  fi
else
  # Some other error (permissions, transient)
  echo "    WARNING: failed to update Pages config: $PUT_OUT"
fi

# Print the live URL.
PAGES_URL="$(gh api "repos/${REPO_SLUG}/pages" --jq .html_url 2>/dev/null || true)"
if [ -n "$PAGES_URL" ]; then
  echo ""
  echo "==> Done. URL: $PAGES_URL"
  echo "    GitHub Pages typically takes 30-60s to refresh after a push."
else
  OWNER="${REPO_SLUG%%/*}"
  REPO="${REPO_SLUG##*/}"
  echo ""
  echo "==> Done. URL (once Pages provisions): https://${OWNER}.github.io/${REPO}/"
fi
