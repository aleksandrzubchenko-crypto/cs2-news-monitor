#!/usr/bin/env bash
# One-command deploy: create a PUBLIC GitHub repo, push, set secrets,
# enable Actions write access, and trigger the first run.
# Requires: gh (GitHub CLI) authenticated, git. Run from this folder.
set -euo pipefail
cd "$(dirname "$0")"

REPO_NAME="${REPO_NAME:-cs2-news-monitor}"

# --- load private values from .env (never committed; see .gitignore) --------
if [[ ! -f .env ]]; then echo "ERROR: .env not found in $(pwd)"; exit 1; fi
set -a; source .env; set +a
: "${TELEGRAM_BOT_TOKEN:?set in .env}"
: "${TELEGRAM_CHANNEL:?set in .env}"

# --- commit (.env / seen.json excluded by .gitignore) -----------------------
git init -q 2>/dev/null || true
git add .
git commit -qm "CS2 news monitor" || echo "nothing new to commit"
git branch -M main

# --- create public repo and push under the authenticated gh user ------------
gh repo create "$REPO_NAME" --public --source=. --remote=origin --push
OWNER="$(gh api user -q .login)"
echo "Repo: https://github.com/$OWNER/$REPO_NAME"

# --- secrets (only what the test needs; CTA/source are OFF) ------------------
gh secret set TELEGRAM_BOT_TOKEN -b"$TELEGRAM_BOT_TOKEN" -R "$OWNER/$REPO_NAME"
gh secret set TELEGRAM_CHANNEL   -b"$TELEGRAM_CHANNEL"   -R "$OWNER/$REPO_NAME"
# Optional (enable later): SITE_URL, BRAND_NAME, ANTHROPIC_API_KEY
[[ -n "${SITE_URL:-}" ]]          && gh secret set SITE_URL         -b"$SITE_URL"          -R "$OWNER/$REPO_NAME" || true
[[ -n "${ANTHROPIC_API_KEY:-}" ]] && gh secret set ANTHROPIC_API_KEY -b"$ANTHROPIC_API_KEY" -R "$OWNER/$REPO_NAME" || true

# --- let Actions write (needed to commit seen.json back) --------------------
gh api -X PUT "repos/$OWNER/$REPO_NAME/actions/permissions/workflow" \
  -f default_workflow_permissions=write -F can_approve_pull_request_reviews=false

# --- trigger the first run now ----------------------------------------------
sleep 3
gh workflow run monitor.yml -R "$OWNER/$REPO_NAME" || \
  echo "Trigger it manually: Actions tab -> CS2 news monitor -> Run workflow"

echo "Done. Check the Actions tab and your Telegram channel (@fstestsss)."
