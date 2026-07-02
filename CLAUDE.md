# Deploy task for Claude Code

This folder is a CS2 news → Telegram autoposter. Goal: deploy it to a **public**
GitHub repo and start it on GitHub Actions.

## Do this
Run the deploy script from this folder:

```bash
bash deploy.sh
```

It will: create a public repo `cs2-news-monitor`, push the code, set the Telegram
secrets from `.env`, enable Actions write permission, and trigger the first run.

## Rules
- **Never commit `.env`** (contains the bot token). It is gitignored — keep it so.
- Repo must be **public** (free unlimited Actions minutes; no secrets live in code).
- Secrets come from `.env` → set as GitHub Actions secrets, not committed.
- Prerequisite: `gh` (GitHub CLI) must be authenticated (`gh auth status`). If not,
  run `gh auth login` first.

## After deploy
- Check the repo's **Actions** tab for a green run.
- Check the Telegram channel `@fstestsss` for the first news posts.
- The workflow re-runs every ~5 min (cron, best-effort).
