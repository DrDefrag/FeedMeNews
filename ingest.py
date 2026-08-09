import os
import time
import feedparser
import requests
import xml.etree.ElementTree as ET
import psycopg2
from datetime import datetime, timezone
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

DB_URL = os.environ["DATABASE_URL"]

RSS_SOURCES = [
    {"name": "IGN", "tier": "trusted", "url": "https://www.ign.com/rss/articles/feed?tags=games"},
    {"name": "Polygon", "tier": "trusted", "url": "https://www.polygon.com/feed/"},
    {"name": "PC Gamer", "tier": "trusted", "url": "https://www.pcgamer.com/rss/"},
    {"name": "Eurogamer", "tier": "trusted", "url": "https://www.eurogamer.net/feed"},
    {"name": "GameSpot", "tier": "trusted", "url": "https://www.gamespot.com/feeds/game-news/"},
    {"name": "GamesRadar", "tier": "trusted", "url": "https://www.gamesradar.com/rss/"},
    {"name": "Rock Paper Shotgun", "tier": "niche", "url": "https://www.rockpapershotgun.com/feed"},
    {"name": "NintendoLife", "tier": "niche", "url": "https://www.nintendolife.com/feeds/latest"},
    {"name": "VG247", "tier": "niche", "url": "https://www.vg247.com/feed"},
]

REDDIT_SOURCES = [
    {"name": "r/Games", "tier": "community", "url": "https://www.reddit.com/r/Games/.rss"},
    {"name": "r/pcgaming", "tier": "community", "url": "https://www.reddit.com/r/pcgaming/.rss"},
]

HEADERS = {"User-Agent": "gaming-news-aggregator/0.1 (personal project)"}
ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}

# Small pause between requests to the same host (Reddit especially) so we
# don't trip rate limits by hitting it twice in immediate succession.
REQUEST_DELAY_SECONDS = 5

# Story clustering settings. Tuned empirically against real data on 9 Aug
# 2026: threshold 0.4 gives ~25 clusters out of ~290 articles, with the
# large multi-source clusters (4+ outlets on the same real story) coming
# out clean. Known limitation: very short titles that happen to share one
# distinctive phrase (e.g. "early access") can occasionally cluster two
# unrelated stories together. Tightening the time window doesn't fix this
# specific failure mode (confirmed against a real false-positive case where
# both articles published under 2 minutes apart) - it's a vocabulary-overlap
# issue on short text, not a timing issue. Accepted as a known v1 tradeoff;
# revisit with entity extraction if it turns out to matter in practice.
CLUSTER_WINDOW_DAYS = 4
CLUSTER_SIMILARITY_THRESHOLD = 0.4


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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS stories (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
        """)
        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS story_id INTEGER;")
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
    # Reddit blocks anonymous requests to its .json endpoints from most
    # datacenter/hosting IP ranges, but its older .rss (Atom) endpoint is
    # not subject to the same block, just normal rate limits. We parse it
    # directly with ElementTree since feedparser doesn't reliably detect
    # entries in this particular feed variant.
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
        time.sleep(REQUEST_DELAY_SECONDS)

    for source in REDDIT_SOURCES:
        try:
            fetch_reddit(conn, source)
            print(f"[ok] {source['name']}")
        except Exception as e:
            print(f"[error] {source['name']}: {e}")
        time.sleep(REQUEST_DELAY_SECONDS)


def cluster_recent_articles(conn):
    """Group articles covering the same real-world story together.

    Recomputes clustering from scratch over a rolling time window every
    run (cheap at our scale: low hundreds of rows). To keep story_id
    values stable across runs rather than reshuffling every time, any
    cluster that already has one or more story_id values assigned keeps
    the smallest (earliest-created) one as canonical, and every member of
    that cluster gets updated to match it.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, title, story_id
            FROM articles
            WHERE COALESCE(published_at, fetched_at) > now() - interval '%s days'
            """
            % CLUSTER_WINDOW_DAYS
        )
        rows = cur.fetchall()

    if len(rows) < 2:
        return

    ids = [r[0] for r in rows]
    titles = [r[1] for r in rows]
    existing_story_ids = [r[2] for r in rows]

    vectorizer = TfidfVectorizer(stop_words="english")
    matrix = vectorizer.fit_transform(titles)
    similarity = cosine_similarity(matrix)

    n = len(titles)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            if similarity[i][j] >= CLUSTER_SIMILARITY_THRESHOLD:
                union(i, j)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    for members in groups.values():
        known_ids = {existing_story_ids[i] for i in members if existing_story_ids[i] is not None}
        if known_ids:
            canonical_story_id = min(known_ids)
        else:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO stories (title) VALUES (%s) RETURNING id",
                    (titles[members[0]],),
                )
                canonical_story_id = cur.fetchone()[0]

        with conn.cursor() as cur:
            for i in members:
                if existing_story_ids[i] != canonical_story_id:
                    cur.execute(
                        "UPDATE articles SET story_id = %s WHERE id = %s",
                        (canonical_story_id, ids[i]),
                    )
            cur.execute(
                "UPDATE stories SET updated_at = now() WHERE id = %s",
                (canonical_story_id,),
            )
    conn.commit()


def main():
    conn = psycopg2.connect(DB_URL)
    ensure_schema(conn)
    while True:
        print(f"--- ingestion run: {datetime.now(timezone.utc).isoformat()} ---")
        run_once(conn)
        try:
            cluster_recent_articles(conn)
            print("[ok] clustering")
        except Exception as e:
            print(f"[error] clustering: {e}")
        time.sleep(900)


if __name__ == "__main__":
    main()
