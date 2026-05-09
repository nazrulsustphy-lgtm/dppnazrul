"""
EU ESPR Garments DPP News Monitor
Runs on GitHub Actions, sends new items to Telegram.
Only items from last 24 hours, never duplicates.
"""

import os
import json
import hashlib
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus

import feedparser
import requests

# --- Configuration ---

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

STATE_FILE = Path("state.json")
LOOKBACK_HOURS = 24

# Keywords that MUST appear (case-insensitive) in title or summary
KEYWORDS = [
    "digital product passport",
    "dpp",
    "espr",
    "ecodesign",
    "eu textile strategy",
    "textile regulation",
    "garment traceability",
    "apparel passport",
]

# RSS feed sources
FEEDS = [
    # --- Google News searches (most reliable) ---
    {
        "name": "GoogleNews: DPP textiles",
        "url": "https://news.google.com/rss/search?q=%22Digital+Product+Passport%22+textiles+when:1d&hl=en&gl=US&ceid=US:en",
    },
    {
        "name": "GoogleNews: ESPR garments",
        "url": "https://news.google.com/rss/search?q=ESPR+(garments+OR+apparel+OR+textiles)+when:1d&hl=en&gl=US&ceid=US:en",
    },
    {
        "name": "GoogleNews: EU textile strategy",
        "url": "https://news.google.com/rss/search?q=%22EU+textile+strategy%22+when:1d&hl=en&gl=US&ceid=US:en",
    },
    {
        "name": "GoogleNews: Ecodesign textiles",
        "url": "https://news.google.com/rss/search?q=Ecodesign+textiles+regulation+when:1d&hl=en&gl=US&ceid=US:en",
    },

    # --- Industry sources (add their RSS URLs after verification) ---
    # Note: verify these URLs are still active before using
    {
        "name": "Just-Style",
        "url": "https://www.just-style.com/feed/",
    },
    {
        "name": "Sourcing Journal",
        "url": "https://sourcingjournal.com/feed/",
    },
    {
        "name": "Apparel Resources",
        "url": "https://apparelresources.com/feed/",
    },

    # --- Add your LinkedIn/X bridges here ---
    # Example: RSSHub instance for a LinkedIn company page or X account
    # { "name": "X: @CIRPASS_EU", "url": "https://rsshub.app/twitter/user/CIRPASS_EU" },
]

# --- Helpers ---

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"seen": {}}

def save_state(state):
    # Keep only last 30 days of seen IDs to prevent file bloat
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    state["seen"] = {k: v for k, v in state["seen"].items() if v >= cutoff}
    STATE_FILE.write_text(json.dumps(state, indent=2))

def item_id(entry):
    """Stable ID for an entry — prefer guid/id, fall back to link, then title hash."""
    raw = entry.get("id") or entry.get("link") or entry.get("title", "")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

def parse_pub_date(entry):
    """Return entry's publication time as timezone-aware datetime, or None."""
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None

def matches_keyword(entry):
    text = (entry.get("title", "") + " " + entry.get("summary", "")).lower()
    return any(kw.lower() in text for kw in KEYWORDS)

def send_telegram(text):
    """Send a single message. Telegram limit: 4096 chars."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text[:4090],
        "disable_web_page_preview": False,
        "parse_mode": "HTML",
    }
    r = requests.post(url, json=payload, timeout=30)
    if r.status_code != 200:
        print(f"  Telegram error: {r.status_code} {r.text}")
    return r.status_code == 200

# --- Main ---

def main():
    state = load_state()
    seen = state["seen"]
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    now_iso = datetime.now(timezone.utc).isoformat()

    new_items = []

    for feed in FEEDS:
        print(f"Fetching: {feed['name']}")
        try:
            # User-Agent helps avoid some blocks
            parsed = feedparser.parse(
                feed["url"],
                request_headers={"User-Agent": "Mozilla/5.0 DPP-Monitor/1.0"},
            )
        except Exception as e:
            print(f"  ERROR: {e}")
            continue

        if parsed.bozo:
            print(f"  Warning: feed parse issue — {parsed.bozo_exception}")

        for entry in parsed.entries:
            iid = item_id(entry)

            # Skip if already seen
            if iid in seen:
                continue

            # Skip if older than 24 hours
            pub = parse_pub_date(entry)
            if pub and pub < cutoff_time:
                # Mark as seen so we don't re-check next run
                seen[iid] = now_iso
                continue

            # For non-Google-News sources, also require keyword match
            # (Google News already filtered by query)
            if "news.google.com" not in feed["url"]:
                if not matches_keyword(entry):
                    seen[iid] = now_iso
                    continue

            new_items.append({
                "source": feed["name"],
                "title": entry.get("title", "(no title)"),
                "link": entry.get("link", ""),
                "pub": pub.isoformat() if pub else "unknown",
                "id": iid,
            })

        # Be polite to servers
        time.sleep(1)

    print(f"\nFound {len(new_items)} new items")

    # Send to Telegram — only links as you requested
    if not new_items:
        print("Nothing new. Done.")
        save_state(state)
        return

    # Group into messages (4096 char limit per message)
    header = f"🔔 <b>DPP/ESPR Updates</b> ({len(new_items)} new, last 24h)\n\n"
    chunks = []
    current = header

    for item in new_items:
        line = f"• <a href=\"{item['link']}\">{item['title']}</a>\n  <i>{item['source']}</i>\n\n"
        if len(current) + len(line) > 3900:
            chunks.append(current)
            current = ""
        current += line
    if current:
        chunks.append(current)

    for chunk in chunks:
        if send_telegram(chunk):
            # Mark items in this chunk as seen
            for item in new_items:
                seen[item["id"]] = now_iso
        time.sleep(2)  # avoid Telegram rate limit

    save_state(state)
    print("Done.")

if __name__ == "__main__":
    main()
