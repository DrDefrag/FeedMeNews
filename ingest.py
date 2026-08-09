import os
import time
import feedparser
import requests
import xml.etree.ElementTree as ET
import psycopg2
from datetime import datetime, timezone

DB_URL = os.environ["DATABASE_URL"]

RSS_SOURCES = [
    {"name": "IGN", "tier": "trusted", "url": "https://www.ign.com/rss/articles/feed?tags=games"},
    {"name": "Polygon", "tier": "trusted", "url": "https://www.polygon.com/feed/"},
    {"name": "PC Gamer", "tier": "trusted", "url": "https://www.pcgamer.com/rss/"},
    {"name": "Rock Paper Shotgun", "tier": "niche", "url": "https://www.rockpapershotgun.com/feed"},
]

REDDIT_SOURCES = [
    {"name": "r/Games", "tier": "community", "url": "https://www.reddit.com/r/Games/.rss"},
    {"name": "r/pcgaming", "tier": "community", "url": "https://www.reddit.com/r/pcgaming/.rss"},
]

HEADERS = {"User-Agent": "gaming-news-aggregator/0.1 (personal project)"}
ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}


def ensure_schema(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id SERIAL PRIMARY KEY,
                source TEXT NOT NULL,
                source_tier TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT UNIQUE NOT NULL,
                summary TEXT,
                published_at TIMESTAMPTZ,
                fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
        """)
    conn.commit()


def upsert_article(conn, source, tier, title, url, summary, published_at):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO articles (source, source_tier, title, url, summary, published_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (url) DO NOTHING;
            """,
            (source, tier, title, url, summary, published_at),
        )
    conn.commit()


def fetch_rss(conn, source):
    feed = feedparser.parse(source["url"])
    for entry in feed.entries:
        title = entry.get("title", "").strip()
        url = entry.get("link", "").strip()
        summary = (entry.get("summary", "") or "")[:400]
        published = None
        if entry.get("published_parsed"):
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        if title and url:
            upsert_article(conn, source["name"], source["tier"], title, url, summary, published)


def fetch_reddit(conn, source):
    resp = requests.get(source["url"], headers=HEADERS, timeout=15)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    for entry in root.findall("a:entry", ATOM_NS):
        title_el = entry.find("a:title", ATOM_NS)
        link_el = entry.find("a:link", ATOM_NS)
        updated_el = entry.find("a:updated", ATOM_NS)
        title = (title_el.text or "").strip() if title_el is not None else ""
        url = link_el.get("href") if link_el is not None else ""
        published = None
        if updated_el is not None and updated_el.text:
            try:
                published = datetime.fromisoformat(updated_el.text)
            except ValueError:
                published = None
        if title and url:
            upsert_article(conn, source["name"], source["tier"], title, url, "", published)


def run_once(conn):
    for source in RSS_SOURCES:
        try:
            fetch_rss(conn, source)
            print(f"[ok] {source['name']}")
        except Exception as e:
            print(f"[error] {source['name']}: {e}")

    for source in REDDIT_SOURCES:
        try:
            fetch_reddit(conn, source)
            print(f"[ok] {source['name']}")
        except Exception as e:
            print(f"[error] {source['name']}: {e}")


def main():
    conn = psycopg2.connect(DB_URL)
    ensure_schema(conn)
    while True:
        print(f"--- ingestion run: {datetime.now(timezone.utc).isoformat()} ---")
        run_once(conn)
        time.sleep(900)


if __name__ == "__main__":
    main()
