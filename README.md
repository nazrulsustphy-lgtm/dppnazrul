# EU ESPR Garments DPP News Monitor

Monitors news, official EU sources, and social media for EU ESPR / Digital Product Passport (DPP) developments related to garments and textiles. Sends new items (last 24 hours only) to Telegram.

## Setup (One-time)

### 1. Create a Telegram bot
- Open Telegram, search `@BotFather`, send `/newbot`
- Choose a name + username, save the token (looks like `123456789:ABCdef...`)
- Send any message to your new bot
- Get your chat ID: open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in browser → look for `"chat":{"id":...}`

### 2. Create GitHub repo
- Create a new private repo on GitHub
- Push these files (`scraper.py`, `.github/workflows/monitor.yml`, `state.json`)

### 3. Add secrets
In GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**
- `TELEGRAM_BOT_TOKEN` = your bot token
- `TELEGRAM_CHAT_ID` = your chat ID

### 4. Initial empty state file
```bash
echo '{"seen": {}}' > state.json
git add state.json && git commit -m "init state" && git push
```

### 5. Test manually
- Go to **Actions** tab in GitHub → select "DPP News Monitor" workflow
- Click "Run workflow" to trigger manually first time
- Check the logs; check your Telegram

## How it Works

- Runs 3x daily (8am, 2pm, 8pm Bangladesh time) via GitHub Actions cron
- Fetches RSS from Google News (with `when:1d` filter), industry sources, and any RSS bridges you add
- Filters by keywords (`Digital Product Passport`, `ESPR`, `Ecodesign`, etc.)
- Deduplicates using SHA256 hashes stored in `state.json` (committed back to repo)
- Sends only links + titles to Telegram (no full content)
- First run may send a burst of items from the past 24h — that's expected

## Adding LinkedIn / X (Twitter) / Bluesky monitoring

Direct scraping of LinkedIn or X is unreliable. Use one of:

**Option A — RSSHub (self-hosted, free)**
- Deploy RSSHub on Cloudflare Workers or Vercel: https://docs.rsshub.app
- Generate feed URLs like:
  - `https://your-rsshub.workers.dev/twitter/user/CIRPASS_EU`
  - `https://your-rsshub.workers.dev/linkedin/company/european-commission`

**Option B — RSS.app (paid, easy)**
- Sign up at rss.app, paste a LinkedIn/X URL, get an RSS feed
- Free tier limited; paid starts ~$8/month

**Option C — Bluesky (best for tech-policy discussion)**
- Native RSS: `https://bsky.app/profile/<handle>/rss`
- DPP/sustainability conversations are increasingly there

Add the resulting URLs to the `FEEDS` list in `scraper.py`.

## Tuning

- **Keywords**: edit `KEYWORDS` in `scraper.py`
- **Frequency**: edit cron in `.github/workflows/monitor.yml`
  - Twice a day: `'0 4,14 * * *'`
  - Hourly: `'0 * * * *'`
- **Sources**: edit `FEEDS` list

## Cost

- **GitHub Actions**: 2000 free minutes/month for private repos (this script uses ~1 min/run × 3/day × 30 = 90 min/month → well within free tier)
- **Telegram Bot API**: Free
- **RSSHub on Cloudflare Workers**: Free (100k requests/day)

## Troubleshooting

- **No messages arriving**: Check Actions logs. Most common issue is that you haven't sent the bot a message first (Telegram requires this).
- **Same items repeated**: `state.json` isn't being committed back. Check that the workflow has `contents: write` permission.
- **Industry feed broken**: Some RSS URLs change. Verify by opening in browser.
