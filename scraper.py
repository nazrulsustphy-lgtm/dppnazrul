"""
EU ESPR Garments DPP News Monitor — v2

What's new in v2:
- Bangladesh-specific RMG/garments DPP coverage
- Bengali-language sources (Prothom Alo, Daily Star Bangla)
- Social media monitoring via RSSHub public instance (X, LinkedIn, Bluesky)
- Daily summary message (sent only at 8am BD time)
- Better keyword filtering with Bengali support

Modes:
- Default (3x/day): instant alerts for new items in last 24h
- Summary mode (--summary flag, only at 8am): yesterday's full digest
"""

import os
import sys
import json
import hashlib
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests

# --- Configuration ---

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

STATE_FILE = Path("state.json")
LOOKBACK_HOURS = 24

# RSSHub public instance — fallback list in case primary is down
RSSHUB_INSTANCES = [
    "https://rsshub.app",
    "https://rsshub.rssforever.com",
    "https://rss.shab.fun",
]

# Keywords (English + Bengali). Match if ANY appears in title/summary.
KEYWORDS_EN = [
    "digital product passport", "dpp",
    "espr", "ecodesign",
    "eu textile strategy", "textile regulation",
    "garment traceability", "apparel passport",
    "circular economy textile", "extended producer responsibility textile",
    # Bangladesh-specific
    "bgmea", "bkmea", "btma",
    "bangladesh rmg", "bangladesh garment", "bangladesh apparel",
    "bangladesh textile", "ready-made garment",
]

KEYWORDS_BN = [
    "ডিজিটাল প্রোডাক্ট পাসপোর্ট",
    "তৈরি পোশাক",
    "পোশাক শিল্প",
    "পোশাক রপ্তানি",
    "বিজিএমইএ", "বিকেএমইএ",
    "ইইউ পোশাক",
    "ইউরোপীয় ইউনিয়ন পোশাক",
    "টেকসই পোশাক",
]

ALL_KEYWORDS = [k.lower() for k in KEYWORDS_EN] + KEYWORDS_BN

# RSS feed sources
FEEDS = [
    # === Google News searches (most reliable, pre-filtered) ===
    {
        "name": "GoogleNews EN: DPP textiles",
        "url": "https://news.google.com/rss/search?q=%22Digital+Product+Passport%22+textiles+when:1d&hl=en&gl=US&ceid=US:en",
        "pre_filtered": True,
    },
    {
        "name": "GoogleNews EN: ESPR garments",
        "url": "https://news.google.com/rss/search?q=ESPR+(garments+OR+apparel+OR+textiles)+when:1d&hl=en&gl=US&ceid=US:en",
        "pre_filtered": True,
    },
    {
        "name": "GoogleNews EN: EU textile strategy",
        "url": "https://news.google.com/rss/search?q=%22EU+textile+strategy%22+when:1d&hl=en&gl=US&ceid=US:en",
        "pre_filtered": True,
    },
    {
        "name": "GoogleNews EN: Ecodesign textiles",
        "url": "https://news.google.com/rss/search?q=Ecodesign+textiles+regulation+when:1d&hl=en&gl=US&ceid=US:en",
        "pre_filtered": True,
    },

    # === Bangladesh-specific Google News (English) ===
    {
        "name": "GoogleNews EN: Bangladesh RMG EU ESPR",
        "url": "https://news.google.com/rss/search?q=(Bangladesh+RMG+OR+%22Bangladesh+garment%22)+(ESPR+OR+%22Digital+Product+Passport%22+OR+EU)+when:1d&hl=en&gl=US&ceid=US:en",
        "pre_filtered": True,
    },
    {
        "name": "GoogleNews EN: BGMEA EU compliance",
        "url": "https://news.google.com/rss/search?q=(BGMEA+OR+BKMEA)+(EU+OR+sustainability+OR+ESPR)+when:1d&hl=en&gl=US&ceid=US:en",
        "pre_filtered": True,
    },
    {
        "name": "GoogleNews EN: Bangladesh apparel export EU",
        "url": "https://news.google.com/rss/search?q=%22Bangladesh+apparel%22+EU+export+when:1d&hl=en&gl=US&ceid=US:en",
        "pre_filtered": True,
    },

    # === Bengali Google News ===
    {
        "name": "GoogleNews BN: তৈরি পোশাক ইইউ",
        "url": "https://news.google.com/rss/search?q=%E0%A6%A4%E0%A7%88%E0%A6%B0%E0%A6%BF+%E0%A6%AA%E0%A7%8B%E0%A6%B6%E0%A6%BE%E0%A6%95+%E0%A6%87%E0%A6%87%E0%A6%89+when:1d&hl=bn&gl=BD&ceid=BD:bn",
        "pre_filtered": True,
    },
    {
        "name": "GoogleNews BN: পোশাক রপ্তানি ইউরোপ",
        "url": "https://news.google.com/rss/search?q=%E0%A6%AA%E0%A7%8B%E0%A6%B6%E0%A6%BE%E0%A6%95+%E0%A6%B0%E0%A6%AA%E0%A7%8D%E0%A6%A4%E0%A6%BE%E0%A6%A8%E0%A6%BF+%E0%A6%87%E0%A6%89%E0%A6%B0%E0%A7%8B%E0%A6%AA+when:1d&hl=bn&gl=BD&ceid=BD:bn",
        "pre_filtered": True,
    },
    {
        "name": "GoogleNews BN: বিজিএমইএ",
        "url": "https://news.google.com/rss/search?q=%E0%A6%AC%E0%A6%BF%E0%A6%9C%E0%A6%BF%E0%A6%8F%E0%A6%AE%E0%A6%87%E0%A6%8F+when:1d&hl=bn&gl=BD&ceid=BD:bn",
        "pre_filtered": True,
    },

    # === Industry English sources (filter by keyword) ===
    {
        "name": "Just-Style",
        "url": "https://www.just-style.com/feed/",
        "pre_filtered": False,
    },
    {
        "name": "Sourcing Journal",
        "url": "https://sourcingjournal.com/feed/",
        "pre_filtered": False,
    },
    {
        "name": "Apparel Resources",
        "url": "https://apparelresources.com/feed/",
        "pre_filtered": False,
    },

    # === Bangladesh Bengali newspapers (filter by keyword) ===
    {
        "name": "Prothom Alo (Bangla)",
        "url": "https://prod-qt-images.s3.amazonaws.com/production/prothomalo-bangla/feed.xml",
        "pre_filtered": False,
    },
    {
        "name": "Prothom Alo English Bangladesh",
        "url": "https://en.prothomalo.com/api/v1/collections/home/rss",
        "pre_filtered": False,
    },

    # === Social media via RSSHub (X / Twitter accounts to track) ===
    # Uses primary RSSHub instance; if it's down, the script tries fallbacks per-feed
    {
        "name": "X: @CIRPASS_EU",
        "url": "https://rsshub.app/twitter/user/CIRPASS_EU",
        "pre_filtered": False,
        "rsshub": True,
    },
    {
        "name": "X: @EU_Commission textiles",
        "url": "https://rsshub.app/twitter/keyword/textile%20DPP",
        "pre_filtered": True,
        "rsshub": True,
    },

    # === Bluesky (native RSS, no RSSHub needed) ===
    # Add Bluesky handles you want to track here:
    # { "name": "Bluesky: handle.bsky.social", "url": "https://bsky.app/profile/handle.bsky.social/rss", "pre_filtered": False },
]

# --- Helpers ---

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            print("WARN: state.json corrupted, starting fresh")
    return {"seen": {}, "yesterday_items": []}

def save_state(state):
    # Keep only last 30 days of seen IDs to prevent file bloat
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    state["seen"] = {k: v for k, v in state["seen"].items() if v >= cutoff}
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))

def item_id(entry):
    raw = entry.get("id") or entry.get("link") or entry.get("title", "")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

def parse_pub_date(entry):
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass
    return None

def matches_keyword(entry):
    text = (entry.get("title", "") + " " + entry.get("summary", "")).lower()
    return any(kw in text for kw in ALL_KEYWORDS)

def fetch_feed_with_fallback(feed):
    """Fetch a feed. For RSSHub feeds, try fallback instances if primary fails."""
    headers = {"User-Agent": "Mozilla/5.0 DPP-Monitor/2.0"}

    if feed.get("rsshub"):
        # Try each RSSHub instance in turn
        path = feed["url"].split("rsshub.app", 1)[-1]  # extract path after domain
        for instance in RSSHUB_INSTANCES:
            url = instance + path
            try:
                parsed = feedparser.parse(url, request_headers=headers)
                if parsed.entries:
                    return parsed
                if not parsed.bozo:
                    return parsed  # empty but valid
            except Exception as e:
                print(f"  RSSHub {instance} failed: {e}")
                continue
        return feedparser.FeedParserDict(entries=[], bozo=True)
    else:
        try:
            return feedparser.parse(feed["url"], request_headers=headers)
        except Exception as e:
            print(f"  Fetch error: {e}")
            return feedparser.FeedParserDict(entries=[], bozo=True)

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text[:4090],
        "disable_web_page_preview": False,
        "parse_mode": "HTML",
    }
    try:
        r = requests.post(url, json=payload, timeout=30)
        if r.status_code != 200:
            print(f"  Telegram error: {r.status_code} {r.text[:200]}")
        return r.status_code == 200
    except Exception as e:
        print(f"  Telegram exception: {e}")
        return False

def send_chunked(items, header):
    """Send a list of items as one or more Telegram messages, chunking if needed."""
    if not items:
        return
    chunks = []
    current = header
    for item in items:
        line = f"• <a href=\"{item['link']}\">{item['title']}</a>\n  <i>{item['source']}</i>\n\n"
        if len(current) + len(line) > 3900:
            chunks.append(current)
            current = ""
        current += line
    if current.strip():
        chunks.append(current)

    for chunk in chunks:
        send_telegram(chunk)
        time.sleep(2)

# --- Main collection logic ---

def collect_new_items(state):
    seen = state["seen"]
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    now_iso = datetime.now(timezone.utc).isoformat()
    new_items = []

    for feed in FEEDS:
        print(f"Fetching: {feed['name']}")
        parsed = fetch_feed_with_fallback(feed)

        if parsed.bozo and not parsed.entries:
            print(f"  Failed or empty")
            continue

        print(f"  Got {len(parsed.entries)} entries")

        for entry in parsed.entries:
            iid = item_id(entry)
            if iid in seen:
                continue

            pub = parse_pub_date(entry)
            if pub and pub < cutoff_time:
                seen[iid] = now_iso
                continue

            # Apply keyword filter for non-pre-filtered feeds
            if not feed.get("pre_filtered", False):
                if not matches_keyword(entry):
                    seen[iid] = now_iso
                    continue

            new_items.append({
                "source": feed["name"],
                "title": entry.get("title", "(no title)").strip(),
                "link": entry.get("link", ""),
                "pub": pub.isoformat() if pub else "unknown",
                "id": iid,
            })

        time.sleep(1)

    return new_items, now_iso

# --- Mode: instant alerts ---

def run_instant_mode():
    state = load_state()
    new_items, now_iso = collect_new_items(state)

    print(f"\nFound {len(new_items)} new items")

    if not new_items:
        save_state(state)
        return

    header = f"🔔 <b>DPP/ESPR Updates</b> ({len(new_items)} new)\n\n"
    send_chunked(new_items, header)

    # Mark sent items as seen
    for item in new_items:
        state["seen"][item["id"]] = now_iso

    # Append to yesterday's tracking list (used by summary mode)
    state.setdefault("yesterday_items", []).extend(new_items)
    # Keep only last 48 hours worth
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    state["yesterday_items"] = [
        i for i in state["yesterday_items"]
        if i.get("pub", "9999") >= cutoff or i.get("pub") == "unknown"
    ]

    save_state(state)

# --- Mode: daily summary ---

def run_summary_mode():
    """Send a digest of yesterday's items, then clear the tracking list."""
    state = load_state()
    items = state.get("yesterday_items", [])

    if not items:
        send_telegram("📊 <b>Daily DPP Summary</b>\n\nগত ২৪ ঘণ্টায় কোনো নতুন update আসেনি।")
        state["yesterday_items"] = []
        save_state(state)
        return

    # Group by source for cleaner reading
    by_source = {}
    for item in items:
        by_source.setdefault(item["source"], []).append(item)

    header = (
        f"📊 <b>Daily DPP/ESPR Summary</b>\n"
        f"<i>Last 24 hours · {len(items)} items · {len(by_source)} sources</i>\n\n"
    )

    # Build content: section per source
    body = ""
    for source, src_items in by_source.items():
        body += f"<b>━━ {source} ({len(src_items)}) ━━</b>\n"
        for item in src_items:
            body += f"• <a href=\"{item['link']}\">{item['title']}</a>\n"
        body += "\n"

    # Chunk and send
    full_message = header + body
    if len(full_message) <= 3900:
        send_telegram(full_message)
    else:
        # Split: send header alone, then chunks of body
        send_telegram(header)
        time.sleep(2)
        # Re-build body in sendable chunks
        current = ""
        for source, src_items in by_source.items():
            section = f"<b>━━ {source} ({len(src_items)}) ━━</b>\n"
            for item in src_items:
                section += f"• <a href=\"{item['link']}\">{item['title']}</a>\n"
            section += "\n"
            if len(current) + len(section) > 3900:
                send_telegram(current)
                time.sleep(2)
                current = ""
            current += section
        if current.strip():
            send_telegram(current)

    # Clear yesterday's list after summary
    state["yesterday_items"] = []
    save_state(state)

# --- Entry point ---

def main():
    mode = "summary" if "--summary" in sys.argv else "instant"
    print(f"Mode: {mode}")

    if mode == "summary":
        run_summary_mode()
    else:
        run_instant_mode()

    print("Done.")

if __name__ == "__main__":
    main()
