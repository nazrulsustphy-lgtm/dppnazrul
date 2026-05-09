"""
EU ESPR Garments DPP News Monitor — v3

What's new in v3:
- Priority-based sectioning in messages:
  1. International news (all)
  2. Social media (Reddit + LinkedIn, max 3)
  3. Bangladesh & Bengali (rest)
- Reddit search via native RSS (no RSSHub needed)
- LinkedIn via RSSHub (best-effort, skipped if fails)

Modes:
- Default (instant): real-time alerts for new items in last 24h
- Summary (--summary): yesterday's grouped digest, sent at 8:05am BD
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
SOCIAL_MAX = 3  # max social media items per message

# RSSHub fallback list (used for LinkedIn only)
RSSHUB_INSTANCES = [
    "https://rsshub.app",
    "https://rsshub.rssforever.com",
    "https://rss.shab.fun",
]

# Section categories — feed -> section
SEC_INTL = "international"
SEC_SOCIAL = "social"
SEC_BD = "bangladesh"

KEYWORDS_EN = [
    "digital product passport", "dpp",
    "espr", "ecodesign",
    "eu textile strategy", "textile regulation",
    "garment traceability", "apparel passport",
    "circular economy textile", "extended producer responsibility textile",
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

# --- Feed definitions ---
# Each feed has: name, url, section, pre_filtered (skip keyword match), rsshub (fallback enabled)

FEEDS = [
    # ========== INTERNATIONAL (Section 1) ==========
    # Google News English (pre-filtered by query)
    {
        "name": "GoogleNews: DPP textiles",
        "url": "https://news.google.com/rss/search?q=%22Digital+Product+Passport%22+textiles+when:1d&hl=en&gl=US&ceid=US:en",
        "section": SEC_INTL, "pre_filtered": True,
    },
    {
        "name": "GoogleNews: ESPR garments",
        "url": "https://news.google.com/rss/search?q=ESPR+(garments+OR+apparel+OR+textiles)+when:1d&hl=en&gl=US&ceid=US:en",
        "section": SEC_INTL, "pre_filtered": True,
    },
    {
        "name": "GoogleNews: EU textile strategy",
        "url": "https://news.google.com/rss/search?q=%22EU+textile+strategy%22+when:1d&hl=en&gl=US&ceid=US:en",
        "section": SEC_INTL, "pre_filtered": True,
    },
    {
        "name": "GoogleNews: Ecodesign textiles",
        "url": "https://news.google.com/rss/search?q=Ecodesign+textiles+regulation+when:1d&hl=en&gl=US&ceid=US:en",
        "section": SEC_INTL, "pre_filtered": True,
    },
    # Industry sources (filter by keyword)
    {
        "name": "Just-Style",
        "url": "https://www.just-style.com/feed/",
        "section": SEC_INTL, "pre_filtered": False,
    },
    {
        "name": "Sourcing Journal",
        "url": "https://sourcingjournal.com/feed/",
        "section": SEC_INTL, "pre_filtered": False,
    },
    {
        "name": "Apparel Resources",
        "url": "https://apparelresources.com/feed/",
        "section": SEC_INTL, "pre_filtered": False,
    },

    # ========== SOCIAL MEDIA (Section 2, max 3) ==========
    # Reddit native RSS (reliable, no RSSHub)
    {
        "name": "Reddit: ESPR/DPP search",
        "url": "https://www.reddit.com/search.rss?q=ESPR+OR+%22Digital+Product+Passport%22+OR+%22EU+textile%22&sort=new&t=day",
        "section": SEC_SOCIAL, "pre_filtered": True,
    },
    {
        "name": "Reddit: r/sustainability DPP",
        "url": "https://www.reddit.com/r/sustainability/search.rss?q=DPP+OR+ESPR+OR+textile&restrict_sr=1&sort=new&t=day",
        "section": SEC_SOCIAL, "pre_filtered": True,
    },
    # LinkedIn via RSSHub (best-effort, may fail)
    {
        "name": "LinkedIn: DPP search",
        "url": "https://rsshub.app/linkedin/posts/digital-product-passport",
        "section": SEC_SOCIAL, "pre_filtered": True, "rsshub": True,
    },
    # X (Twitter) via RSSHub - kept under social
    {
        "name": "X: @CIRPASS_EU",
        "url": "https://rsshub.app/twitter/user/CIRPASS_EU",
        "section": SEC_SOCIAL, "pre_filtered": False, "rsshub": True,
    },

    # ========== BANGLADESH & BENGALI (Section 3) ==========
    # Bangladesh-focused English Google News
    {
        "name": "GoogleNews: Bangladesh RMG EU/ESPR",
        "url": "https://news.google.com/rss/search?q=(Bangladesh+RMG+OR+%22Bangladesh+garment%22)+(ESPR+OR+%22Digital+Product+Passport%22+OR+EU)+when:1d&hl=en&gl=US&ceid=US:en",
        "section": SEC_BD, "pre_filtered": True,
    },
    {
        "name": "GoogleNews: BGMEA/BKMEA EU",
        "url": "https://news.google.com/rss/search?q=(BGMEA+OR+BKMEA)+(EU+OR+sustainability+OR+ESPR)+when:1d&hl=en&gl=US&ceid=US:en",
        "section": SEC_BD, "pre_filtered": True,
    },
    {
        "name": "GoogleNews: Bangladesh apparel EU export",
        "url": "https://news.google.com/rss/search?q=%22Bangladesh+apparel%22+EU+export+when:1d&hl=en&gl=US&ceid=US:en",
        "section": SEC_BD, "pre_filtered": True,
    },
    # Bengali Google News
    {
        "name": "GoogleNews BN: তৈরি পোশাক ইইউ",
        "url": "https://news.google.com/rss/search?q=%E0%A6%A4%E0%A7%88%E0%A6%B0%E0%A6%BF+%E0%A6%AA%E0%A7%8B%E0%A6%B6%E0%A6%BE%E0%A6%95+%E0%A6%87%E0%A6%87%E0%A6%89+when:1d&hl=bn&gl=BD&ceid=BD:bn",
        "section": SEC_BD, "pre_filtered": True,
    },
    {
        "name": "GoogleNews BN: পোশাক রপ্তানি ইউরোপ",
        "url": "https://news.google.com/rss/search?q=%E0%A6%AA%E0%A7%8B%E0%A6%B6%E0%A6%BE%E0%A6%95+%E0%A6%B0%E0%A6%AA%E0%A7%8D%E0%A6%A4%E0%A6%BE%E0%A6%A8%E0%A6%BF+%E0%A6%87%E0%A6%89%E0%A6%B0%E0%A7%8B%E0%A6%AA+when:1d&hl=bn&gl=BD&ceid=BD:bn",
        "section": SEC_BD, "pre_filtered": True,
    },
    {
        "name": "GoogleNews BN: বিজিএমইএ",
        "url": "https://news.google.com/rss/search?q=%E0%A6%AC%E0%A6%BF%E0%A6%9C%E0%A6%BF%E0%A6%8F%E0%A6%AE%E0%A6%87%E0%A6%8F+when:1d&hl=bn&gl=BD&ceid=BD:bn",
        "section": SEC_BD, "pre_filtered": True,
    },
    # Bangladeshi newspaper feeds (filter by keyword)
    {
        "name": "Prothom Alo (Bangla)",
        "url": "https://prod-qt-images.s3.amazonaws.com/production/prothomalo-bangla/feed.xml",
        "section": SEC_BD, "pre_filtered": False,
    },
    {
        "name": "Prothom Alo English",
        "url": "https://en.prothomalo.com/api/v1/collections/home/rss",
        "section": SEC_BD, "pre_filtered": False,
    },
]

SECTION_META = {
    SEC_INTL:   {"emoji": "🌍", "label": "INTERNATIONAL", "order": 1, "limit": None},
    SEC_SOCIAL: {"emoji": "📱", "label": "SOCIAL MEDIA",  "order": 2, "limit": SOCIAL_MAX},
    SEC_BD:     {"emoji": "🇧🇩", "label": "BANGLADESH & BENGALI", "order": 3, "limit": None},
}

# --- Helpers ---

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            print("WARN: state.json corrupted, starting fresh")
    return {"seen": {}, "yesterday_items": []}

def save_state(state):
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

def fetch_feed(feed):
    """Fetch a feed. For RSSHub feeds, try fallback instances if primary fails."""
    headers = {"User-Agent": "Mozilla/5.0 DPP-Monitor/3.0"}

    if feed.get("rsshub"):
        path = feed["url"].split("rsshub.app", 1)[-1]
        for instance in RSSHUB_INSTANCES:
            url = instance + path
            try:
                parsed = feedparser.parse(url, request_headers=headers)
                if parsed.entries or not parsed.bozo:
                    return parsed
            except Exception as e:
                print(f"  RSSHub {instance} failed: {e}")
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

# --- Collection ---

def collect_new_items(state):
    """Fetch all feeds, return list of new items each tagged with section."""
    seen = state["seen"]
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    now_iso = datetime.now(timezone.utc).isoformat()
    new_items = []

    for feed in FEEDS:
        print(f"Fetching: {feed['name']} [{feed['section']}]")
        parsed = fetch_feed(feed)

        if not parsed.entries:
            if parsed.bozo:
                print(f"  Failed (bozo)")
            else:
                print(f"  Empty")
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

            if not feed.get("pre_filtered", False):
                if not matches_keyword(entry):
                    seen[iid] = now_iso
                    continue

            new_items.append({
                "section": feed["section"],
                "source": feed["name"],
                "title": entry.get("title", "(no title)").strip(),
                "link": entry.get("link", ""),
                "pub": pub.isoformat() if pub else "unknown",
                "id": iid,
            })

        time.sleep(1)

    return new_items, now_iso

# --- Section organization ---

def organize_by_section(items):
    """Group items by section, apply per-section limits, return ordered sections."""
    by_section = {SEC_INTL: [], SEC_SOCIAL: [], SEC_BD: []}
    for item in items:
        sec = item["section"]
        if sec in by_section:
            by_section[sec].append(item)

    # Apply per-section limit
    for sec, meta in SECTION_META.items():
        if meta["limit"] and len(by_section[sec]) > meta["limit"]:
            by_section[sec] = by_section[sec][:meta["limit"]]

    # Return in priority order
    ordered = sorted(SECTION_META.items(), key=lambda x: x[1]["order"])
    return [(sec, by_section[sec], meta) for sec, meta in ordered]

def format_section(sec, items, meta):
    """Render one section as HTML for Telegram."""
    if not items:
        return ""
    header = f"\n<b>{meta['emoji']} {meta['label']}"
    if meta['limit']:
        header += f" (top {len(items)})"
    header += f"</b>\n"
    body = ""
    for item in items:
        body += f"• <a href=\"{item['link']}\">{item['title']}</a>\n  <i>{item['source']}</i>\n"
    return header + body + "\n"

def send_grouped(items, top_header):
    """Send items grouped by section, chunked across messages if needed."""
    sections = organize_by_section(items)
    total_sent = sum(len(s[1]) for s in sections)
    if total_sent == 0:
        return 0

    # Build full message
    parts = [top_header]
    for sec, sec_items, meta in sections:
        rendered = format_section(sec, sec_items, meta)
        if rendered:
            parts.append(rendered)
    full = "".join(parts)

    if len(full) <= 3900:
        send_telegram(full)
        return total_sent

    # Need chunking — send header alone, then each section as own message
    send_telegram(top_header)
    time.sleep(2)
    for sec, sec_items, meta in sections:
        rendered = format_section(sec, sec_items, meta)
        if not rendered:
            continue
        if len(rendered) <= 3900:
            send_telegram(rendered)
            time.sleep(2)
        else:
            # Split this section item-by-item
            current = f"<b>{meta['emoji']} {meta['label']}</b>\n"
            for item in sec_items:
                line = f"• <a href=\"{item['link']}\">{item['title']}</a>\n  <i>{item['source']}</i>\n"
                if len(current) + len(line) > 3900:
                    send_telegram(current)
                    time.sleep(2)
                    current = ""
                current += line
            if current.strip():
                send_telegram(current)
                time.sleep(2)
    return total_sent

# --- Modes ---

def run_instant_mode():
    state = load_state()
    new_items, now_iso = collect_new_items(state)
    print(f"\nFound {len(new_items)} new items total")

    if not new_items:
        save_state(state)
        return

    # Count visible items after section limits
    sections = organize_by_section(new_items)
    visible_count = sum(len(s[1]) for s in sections)

    header = f"🔔 <b>DPP/ESPR Updates</b> ({visible_count} new)\n"
    sent = send_grouped(new_items, header)

    # Mark ALL collected items as seen (even those trimmed by section limit, to avoid re-sending)
    for item in new_items:
        state["seen"][item["id"]] = now_iso

    # Append to yesterday tracking (full list, not just visible)
    state.setdefault("yesterday_items", []).extend(new_items)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    state["yesterday_items"] = [
        i for i in state["yesterday_items"]
        if i.get("pub", "9999") >= cutoff or i.get("pub") == "unknown"
    ]

    save_state(state)

def run_summary_mode():
    state = load_state()
    items = state.get("yesterday_items", [])

    if not items:
        send_telegram("📊 <b>Daily DPP Summary</b>\n\nগত ২৪ ঘণ্টায় কোনো নতুন update আসেনি।")
        state["yesterday_items"] = []
        save_state(state)
        return

    # For summary: NO section limit applied (show everything)
    # But still in priority order
    by_section = {SEC_INTL: [], SEC_SOCIAL: [], SEC_BD: []}
    for item in items:
        sec = item.get("section", SEC_BD)
        if sec in by_section:
            by_section[sec].append(item)

    total = len(items)
    header = (
        f"📊 <b>Daily DPP/ESPR Summary</b>\n"
        f"<i>Last 24 hours · {total} items</i>\n"
    )

    parts = [header]
    for sec, meta in sorted(SECTION_META.items(), key=lambda x: x[1]["order"]):
        sec_items = by_section[sec]
        if not sec_items:
            continue
        parts.append(f"\n<b>{meta['emoji']} {meta['label']} ({len(sec_items)})</b>\n")
        for item in sec_items:
            parts.append(f"• <a href=\"{item['link']}\">{item['title']}</a>\n  <i>{item['source']}</i>\n")

    full = "".join(parts)

    if len(full) <= 3900:
        send_telegram(full)
    else:
        # Chunk: header + each section split as needed
        send_telegram(header)
        time.sleep(2)
        for sec, meta in sorted(SECTION_META.items(), key=lambda x: x[1]["order"]):
            sec_items = by_section[sec]
            if not sec_items:
                continue
            current = f"<b>{meta['emoji']} {meta['label']} ({len(sec_items)})</b>\n"
            for item in sec_items:
                line = f"• <a href=\"{item['link']}\">{item['title']}</a>\n  <i>{item['source']}</i>\n"
                if len(current) + len(line) > 3900:
                    send_telegram(current)
                    time.sleep(2)
                    current = ""
                current += line
            if current.strip():
                send_telegram(current)
                time.sleep(2)

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
