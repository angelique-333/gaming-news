import os
import time
import sqlite3
import requests
import feedparser
from dotenv import load_dotenv
from bs4 import BeautifulSoup

load_dotenv()

WEBHOOK_URL = os.getenv("WEBHOOK_URL")
DISCORD_USERNAME = os.getenv("DISCORD_USERNAME", "Gaming News")
RSS_URL = os.getenv("RSS_URL")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", 300))
MAX_POSTS = int(os.getenv("MAX_POSTS_PER_CYCLE", 4))
DELAY = int(os.getenv("DELAY_BETWEEN_POSTS_SECONDS", 3))
SQLITE_PATH = os.getenv("SQLITE_PATH", "data/state.db")
USER_AGENT = os.getenv("USER_AGENT", "OracleBot")

DEFAULT_IMAGE = "https://upload.wikimedia.org/wikipedia/commons/2/2a/GameSpot_logo.svg"

os.makedirs(os.path.dirname(SQLITE_PATH), exist_ok=True)

conn = sqlite3.connect(SQLITE_PATH)
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS posted (
    id TEXT PRIMARY KEY
)
""")
conn.commit()

headers = {"User-Agent": USER_AGENT}


def already_posted(entry_id):
    cur.execute("SELECT 1 FROM posted WHERE id = ?", (entry_id,))
    return cur.fetchone() is not None


def mark_posted(entry_id):
    cur.execute("INSERT OR IGNORE INTO posted VALUES (?)", (entry_id,))
    conn.commit()


def extract_image_from_page(url):
    try:
        r = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        og = soup.find("meta", property="og:image")
        if og:
            return og["content"]
    except:
        pass
    return DEFAULT_IMAGE


def send_embed(entry):
    image_url = extract_image_from_page(entry.link)

    embed = {
        "title": entry.title,
        "url": entry.link,
        "description": entry.summary[:300] + "...",
        "color": 0x00ff9f,
        "image": {"url": image_url},
        "footer": {"text": "GameSpot"}
    }

    payload = {
        "username": DISCORD_USERNAME,
        "embeds": [embed]
    }

    r = requests.post(WEBHOOK_URL, json=payload, headers=headers, timeout=10)
    if r.status_code not in (200, 204):
        print("Erro ao enviar:", r.status_code, r.text)
    else:
        print("Posted:", entry.title)


def main():
    print("Bot iniciado...")
    while True:
        feed = feedparser.parse(RSS_URL)
        count = 0

        for entry in feed.entries:
            entry_id = entry.get("id") or entry.get("link")
            if already_posted(entry_id):
                continue

            send_embed(entry)
            mark_posted(entry_id)
            count += 1

            if count >= MAX_POSTS:
                break

            time.sleep(DELAY)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
