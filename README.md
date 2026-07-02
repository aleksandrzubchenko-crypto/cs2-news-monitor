# CS2 News Monitor + Telegram Autoposter

Monitors the CS2 scene every ~5 minutes, detects **only new newsworthy items**,
drafts a short English post and **autoposts** it to a Telegram channel.

No dependencies — pure Python 3 (stdlib). Optional: set `ANTHROPIC_API_KEY` to
have posts written by an LLM; otherwise a smart template is used.

All brand/site specifics are injected via environment variables, so the code
itself stays generic.

## What it does
- Sources (free, no auth): Reddit r/GlobalOffensive, Steam/Valve news (appid 730), HLTV RSS, Google News (CS2, last 24h).
- Dedupe: `seen.json` (never posts the same item twice).
- Newsworthiness filter: keyword scoring (rosters, majors, MVP, patches, cases/skins, bans) + threshold. Official Valve updates always pass.
- Anti-spam: `MAX_POSTS_PER_RUN` (default 2 per cycle).
- Autoposts to a channel via the Telegram Bot API.

## Setup
1. Create a Telegram channel.
2. @BotFather → `/newbot` → get the **token**.
3. Add the bot as **admin** of the channel (Post Messages permission).
4. Channel id: public → `@yourchannel`; private → numeric `-100...`.

## Environment variables
```
TELEGRAM_BOT_TOKEN=123456:ABC...      # required
TELEGRAM_CHANNEL=@yourchannel         # required (or -100XXXXXXXXXX)
SITE_URL=                             # optional — CTA link
BRAND_NAME=                           # optional — brand name for LLM voice
ANTHROPIC_API_KEY=                    # optional — posts written by an LLM
MAX_POSTS_PER_RUN=2                   # optional — anti-spam
POLL_SECONDS=300                      # optional — loop interval (5 min)
```
Keep secrets out of the repo: use a local `.env` (gitignored) or your host's
secret store. `SITE_URL` and `BRAND_NAME` are best kept as secrets too.

## Run locally
```bash
python3 monitor.py --once     # single cycle (for cron / testing)
python3 monitor.py            # loop every POLL_SECONDS
```

## Deploy 24/7

### GitHub Actions (free)
`.github/workflows/monitor.yml` runs a cycle every 5 min (best-effort) and
commits `seen.json` back for dedupe.
- Use a **public** repo (free unlimited Actions minutes). No secrets live in the code.
- Repo → Settings → Secrets and variables → Actions: add `TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_CHANNEL`, and (optional) `SITE_URL`, `BRAND_NAME`, `ANTHROPIC_API_KEY`.
- Settings → Actions → General → Workflow permissions → **Read and write**.
- Actions tab → run the workflow once to test.

### VPS (always-on, recommended for production)
```bash
git clone <repo> && cd <repo>
export TELEGRAM_BOT_TOKEN=... TELEGRAM_CHANNEL=@...
python3 monitor.py            # or run as a systemd service (Restart=always)
```

### Railway / Render
Deploy from GitHub, start command `python3 monitor.py`, add the env variables.

## Tuning
- Voice / CTA templates: `CTA`, `EMOJI`, `draft_template` in `monitor.py`.
- What counts as news: `KEYWORDS` and `MIN_SCORE`.
- Sources: the `SOURCES` list (easy to add more feeds).
