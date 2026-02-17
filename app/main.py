import os
import time
import json
import sqlite3
import logging
from typing import Optional
from urllib.parse import urlparse

import requests
import feedparser
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("gamespot-webhook")


def require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


# ---------------- SQLite ----------------
def db_connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS posted_items (
            item_id TEXT PRIMARY KEY,
            title   TEXT,
            link    TEXT,
            posted_at INTEGER
        )
        """
    )
    conn.commit()
    return conn


def db_has(conn: sqlite3.Connection, item_id: str) -> bool:
    cur = conn.execute("SELECT 1 FROM posted_items WHERE item_id = ? LIMIT 1", (item_id,))
    return cur.fetchone() is not None


def db_add(conn: sqlite3.Connection, item_id: str, title: str, link: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO posted_items(item_id, title, link, posted_at) VALUES (?, ?, ?, ?)",
        (item_id, title, link, int(time.time())),
    )
    conn.commit()


# ---------------- RSS ----------------
def normalize_id(entry) -> str:
    # id/guid -> link -> fallback
    for key in ("id", "guid"):
        val = entry.get(key)
        if val:
            return str(val).strip()

    link = entry.get("link")
    if link:
        return str(link).strip()

    title = (entry.get("title") or "").strip()
    published = (entry.get("published") or entry.get("updated") or "").strip()
    return f"{title}::{published}"


def fetch_rss(rss_url: str, user_agent: str, timeout: int = 20):
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
    }
    r = requests.get(rss_url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return feedparser.parse(r.content)


def sort_entries_newest_first(entries):
    def key(e):
        t = e.get("published_parsed") or e.get("updated_parsed")
        return t if t is not None else time.gmtime(0)

    return sorted(entries, key=key, reverse=True)


# ---------------- Discord Webhook ----------------
def post_to_discord_webhook(
    webhook_url: str,
    title: str,
    link: str,
    username: Optional[str] = None,
    avatar_url: Optional[str] = None,
    timeout: int = 20,
) -> None:
    content = f"**{title}**\n{link}"

    payload = {"content": content}
    if username:
        payload["username"] = username
    if avatar_url:
        payload["avatar_url"] = avatar_url

    headers = {"Content-Type": "application/json"}
    resp = requests.post(webhook_url, data=json.dumps(payload), headers=headers, timeout=timeout)

    # Rate limit handling
    if resp.status_code == 429:
        try:
            data = resp.json()
            retry_after = float(data.get("retry_after", 2.0))
        except Exception:
            retry_after = 2.0
        log.warning(f"Discord rate limited (429). Sleeping {retry_after:.2f}s then retrying once...")
        time.sleep(retry_after)
        resp = requests.post(webhook_url, data=json.dumps(payload), headers=headers, timeout=timeout)

    if resp.status_code not in (200, 204):
        raise RuntimeError(f"Discord webhook failed: {resp.status_code} {resp.text[:300]}")


def main():
    load_dotenv()

    webhook_url = require_env("WEBHOOK_URL")
    rss_url = require_env("RSS_URL")
    sqlite_path = require_env("SQLITE_PATH")

    check_interval = int(os.getenv("CHECK_INTERVAL_SECONDS", "300"))
    max_posts = int(os.getenv("MAX_POSTS_PER_CYCLE", "4"))
    delay_between = float(os.getenv("DELAY_BETWEEN_POSTS_SECONDS", "3"))

    user_agent = os.getenv("USER_AGENT", "PythonRSSWebhook/1.0")
    discord_username = os.getenv("DISCORD_USERNAME", "").strip() or None
    discord_avatar = os.getenv("DISCORD_AVATAR_URL", "").strip() or None

    parsed = urlparse(webhook_url)
    if not parsed.scheme.startswith("http"):
        raise RuntimeError("WEBHOOK_URL invalid (must be https://...)")

    conn = db_connect(sqlite_path)

    log.info("Starting GameSpot RSS -> Discord Webhook")
    log.info(f"RSS_URL = {rss_url}")
    log.info(f"CHECK_INTERVAL_SECONDS = {check_interval}, MAX_POSTS_PER_CYCLE = {max_posts}, DELAY = {delay_between}s")
    log.info(f"SQLITE_PATH = {sqlite_path}")

    while True:
        try:
            feed = fetch_rss(rss_url, user_agent=user_agent)
            entries = getattr(feed, "entries", []) or []

            if not entries:
                log.info("No entries found in RSS this cycle.")
                time.sleep(check_interval)
                continue

            entries = sort_entries_newest_first(entries)

            posted_count = 0
            for entry in entries:
                if posted_count >= max_posts:
                    break

                item_id = normalize_id(entry)
                title = (entry.get("title") or "").strip()
                link = (entry.get("link") or "").strip()

                if not title or not link:
                    continue

                if db_has(conn, item_id):
                    continue

                post_to_discord_webhook(
                    webhook_url=webhook_url,
                    title=title,
                    link=link,
                    username=discord_username,
                    avatar_url=discord_avatar,
                )
                db_add(conn, item_id, title, link)
                posted_count += 1

                log.info(f"Posted: {title}")
                time.sleep(delay_between)

            if posted_count == 0:
                log.info("Nothing new to post this cycle.")
            else:
                log.info(f"Cycle done. Posted {posted_count} new item(s).")

        except Exception as e:
            log.exception(f"Cycle error: {e}")

        time.sleep(check_interval)


if __name__ == "__main__":
    main()
