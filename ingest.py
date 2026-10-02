import os
import re
import time
import feedparser
import requests
import xml.etree.ElementTree as ET
import psycopg2
import socket
from datetime import datetime, timezone, timedelta
from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS
from sklearn.metrics.pairwise import cosine_similarity

# Global socket timeout (added 22 Aug 2026) - feedparser.parse() has no
# per-call timeout parameter of its own, and a single slow/unresponsive
# feed (confirmed live: the exact source varied between runs - once
# after DF Clips, once at Bellular News) was silently hanging the whole
# ingestion process indefinitely, blocking every source and step after
# it, including everything scheduled after. This sets a ceiling on any socket
# operation the process opens, including feedparser's internal fetches,
# so a slow source times out and gets caught by that source's own
# try/except instead of stalling everything downstream forever.
socket.setdefaulttimeout(20)

DB_URL = os.environ["DATABASE_URL"]
OPENCRITIC_API_KEY = os.environ.get("OPENCRITIC_API_KEY")
OPENCRITIC_HOST = "opencritic-api.p.rapidapi.com"

RSS_SOURCES = [
    {"name": "IGN", "tier": "trusted", "url": "https://www.ign.com/rss/articles/feed?tags=games"},
    {"name": "Polygon", "tier": "trusted", "url": "https://www.polygon.com/feed/"},
    {"name": "PC Gamer", "tier": "trusted", "url": "https://www.pcgamer.com/rss/"},
    {"name": "Eurogamer", "tier": "trusted", "url": "https://www.eurogamer.net/feed"},
    {"name": "GameSpot", "tier": "trusted", "url": "https://www.gamespot.com/feeds/game-news/"},
    {"name": "GamesRadar", "tier": "trusted", "url": "https://www.gamesradar.com/rss/"},
    {"name": "Kotaku", "tier": "trusted", "url": "https://kotaku.com/feed"},
    {"name": "TheGamer", "tier": "trusted", "url": "https://www.thegamer.com/feed/"},
    {"name": "Rock Paper Shotgun", "tier": "niche", "url": "https://www.rockpapershotgun.com/feed"},
    {"name": "NintendoLife", "tier": "niche", "url": "https://www.nintendolife.com/feeds/latest"},
    {"name": "VG247", "tier": "niche", "url": "https://www.vg247.com/feed"},
    {"name": "Push Square", "tier": "niche", "url": "https://www.pushsquare.com/feeds/latest"},
    {"name": "Pure Xbox", "tier": "niche", "url": "https://www.purexbox.com/feeds/latest"},
    {"name": "PCGamesN", "tier": "niche", "url": "https://www.pcgamesn.com/feed"},
    {"name": "Game Developer", "tier": "trusted", "url": "https://www.gamedeveloper.com/feeds/rss.xml"},
    {"name": "The Indie Informer", "tier": "niche", "url": "https://theindieinformer.com/feed/"},
    {"name": "Indie Game Reviewer", "tier": "niche", "url": "https://indiegamereviewer.com/feed/"},
    {"name": "GamesIndustry.biz", "tier": "trusted", "url": "https://www.gamesindustry.biz/feed"},
]

REDDIT_SOURCES = [
    {"name": "r/Games", "tier": "community", "url": "https://www.reddit.com/r/Games/.rss"},
    {"name": "r/pcgaming", "tier": "community", "url": "https://www.reddit.com/r/pcgaming/.rss"},
    {"name": "r/NintendoSwitch", "tier": "community", "url": "https://www.reddit.com/r/NintendoSwitch/.rss"},
    {"name": "r/PS5", "tier": "community", "url": "https://www.reddit.com/r/PS5/.rss"},
]

VIDEO_SOURCES = [
    {"name": "IGN", "tier": "trusted", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCKy1dAqELo0zrOtPkf0eTMw"},
    {"name": "GameSpot", "tier": "trusted", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCbu2SsF-Or3Rsn3NxqODImw"},
    {"name": "VGC", "tier": "trusted", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCuzaJiIORaXi7DsuEs03Gow"},
    {"name": "Digital Foundry", "tier": "trusted", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UC9PBzalIcEQCsiIkq36PyUA"},
    {"name": "Kinda Funny Games", "tier": "niche", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCT6QFE3peNry9PdO5uGj96g"},
    {"name": "Game Informer", "tier": "trusted", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCK-65DO2oOxxMwphl2tYtcw"},
    {"name": "Polygon", "tier": "trusted", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCuVxaQDraOja6xKidcmoufA"},
    {"name": "Fextralife", "tier": "niche", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UClkUHCETNUph8vM-4gQpwUA"},
    {"name": "Bellular News", "tier": "niche", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UC3nPaf5MeeDTHA2JN7clidg"},
    {"name": "DF Clips", "tier": "trusted", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCLdBr5f6RcP6l_TAP4GkhDQ"},
]

HEADERS = {"User-Agent": "gaming-news-aggregator/0.1 (personal project)"}
ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}

REQUEST_DELAY_SECONDS = 5
REDDIT_REQUEST_DELAY_SECONDS = 15

CLUSTER_WINDOW_DAYS = 4
CLUSTER_SIMILARITY_THRESHOLD = 0.4
# Hard ceiling on how many articles a single story can absorb (added 26 Aug
# 2026, after a real production incident: two stories drifted to 712 and
# 186 articles each, pulled in from 26 and 16 completely unrelated outlets
# respectively. Root cause is inherent to transitive union-find clustering
# with no size limit - each new ingestion cycle only needs to match ONE
# existing member of an already-large cluster to get absorbed into it, so
# a slightly-too-permissive similarity match can let a story snowball
# across many cycles into an unbounded blob. This never happens to a
# genuinely single, broadly-covered story - even the biggest crossover
# announcements land well under 30 articles across every source this
# install tracks. Once a candidate story is at or above this cap, new
# matching articles get their own fresh story instead of joining it,
# rather than being silently dropped.
MAX_STORY_SIZE = 30

EXTRA_STOPWORDS = {
    "official", "release", "date", "trailer", "reveal", "gameplay",
    "announcement", "announced", "launches", "launch", "coming", "new",
}
STOPWORDS = list(ENGLISH_STOP_WORDS.union(EXTRA_STOPWORDS))
STOPWORDS_SET = set(STOPWORDS)

WALKTHROUGH_PATTERN = re.compile(
    r"\b(walkthrough|playthrough|let'?s play|full\s+playthrough|part\s*\d+)\b",
    re.IGNORECASE,
)

# Recurring community-thread exclusion (added 2 Oct 2026, same treatment
# as walkthroughs above). Found live: a "Daily Question Thread" story
# had swept together FOUR separate days' worth of r/NintendoSwitch's
# own recurring thread (09/22-09/25), a "Friend Request Weekend" post,
# a "what are you playing" thread, and Push Square's own weekly "Talking
# Point" column - all genuinely different individual posts, wrongly
# merged into one story. Root cause: these titles are so repetitive and
# low-information that TF-IDF can't tell separate instances apart - not
# enough distinguishing vocabulary to avoid false matches across unlike
# posts, let alone across different days of the SAME recurring thread.
# Unlike the story-size bug, this isn't about unbounded growth (this one
# sat under the cap at 28 members) - it's a quality problem with what
# gets clustered at all, so the fix is the same one already used for
# walkthroughs: never let this content become a "story" in the first
# place. Applied regardless of is_video, since the pattern shows up in
# both plain-text Reddit posts and at least one press outlet's own
# recurring column.
RECURRING_THREAD_PATTERN = re.compile(
    r"\b(daily\s+question\s+thread|friend\s+request\s+weekend|"
    r"what\s*(?:'re|\s+are)\s+you\s+playing|talking\s+point)\b",
    re.IGNORECASE,
)

REVIEW_SCORE_INTERVAL_SECONDS = 3600
MAX_OPENCRITIC_LOOKUPS_PER_DAY = 10


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
        cur.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS is_review BOOLEAN NOT NULL DEFAULT FALSE;")
        cur.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS opencritic_score REAL;")
        cur.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS opencritic_tier TEXT;")
        cur.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS opencritic_url TEXT;")
        cur.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS opencritic_review_count INTEGER;")
        cur.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS opencritic_game_name TEXT;")
        cur.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS opencritic_checked_at TIMESTAMPTZ;")
        cur.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS read_at TIMESTAMPTZ;")
        cur.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS dismissed_at TIMESTAMPTZ;")
        cur.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;")
        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS is_video BOOLEAN NOT NULL DEFAULT FALSE;")
        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS is_walkthrough BOOLEAN NOT NULL DEFAULT FALSE;")
        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS is_recurring_thread BOOLEAN NOT NULL DEFAULT FALSE;")
        cur.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS is_video BOOLEAN NOT NULL DEFAULT FALSE;")
        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS image_url TEXT;")
        cur.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS liked_at TIMESTAMPTZ;")
        cur.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS like_count INTEGER NOT NULL DEFAULT 0;")
        cur.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS dislike_count INTEGER NOT NULL DEFAULT 0;")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS game_releases (
                id SERIAL PRIMARY KEY,
                igdb_release_id INTEGER UNIQUE NOT NULL,
                game_name TEXT NOT NULL,
                platform TEXT,
                release_date DATE NOT NULL,
                cover_url TEXT,
                fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
        """)
        cur.execute("ALTER TABLE game_releases ADD COLUMN IF NOT EXISTS game_slug TEXT;")
        cur.execute("ALTER TABLE game_releases ADD COLUMN IF NOT EXISTS summary TEXT;")
        cur.execute("ALTER TABLE game_releases ADD COLUMN IF NOT EXISTS alt_names TEXT[];")
        cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    google_sub TEXT UNIQUE NOT NULL,
                    email TEXT NOT NULL,
                    name TEXT,
                    avatar_url TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    last_login_at TIMESTAMPTZ
                );
            """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_story_state (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
                read_at TIMESTAMPTZ,
                dismissed_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (user_id, story_id)
            );
            """)
    conn.commit()

def extract_image_url(entry):
    if getattr(entry, "media_thumbnail", None):
        url = entry.media_thumbnail[0].get("url")
        if url:
            return url
    if getattr(entry, "media_content", None):
        for m in entry.media_content:
            url = m.get("url")
            if url:
                return url
    if getattr(entry, "enclosures", None):
        for enc in entry.enclosures:
            if "image" in (enc.get("type") or ""):
                url = enc.get("href") or enc.get("url")
                if url:
                    return url
    html = entry.get("summary", "") or ""
    if getattr(entry, "content", None):
        html += entry.content[0].get("value", "") or ""
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html)
    return m.group(1) if m else None


def upsert_article(conn, source, tier, title, url, summary, published_at, is_video=False, image_url=None):
    is_walkthrough = bool(is_video and WALKTHROUGH_PATTERN.search(title))
    is_recurring_thread = bool(RECURRING_THREAD_PATTERN.search(title))
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO articles (source, source_tier, title, url, summary, published_at, is_video, is_walkthrough, is_recurring_thread, image_url)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (url) DO NOTHING;
            """,
            (source, tier, title, url, summary, published_at, is_video, is_walkthrough, is_recurring_thread, image_url),
        )
    conn.commit()


def fetch_rss(conn, source):
    feed = feedparser.parse(source["url"])
    for entry in feed.entries:
        title = entry.get("title", "").strip()
        url = entry.get("link", "").strip()
        summary = (entry.get("summary", "") or "")[:400]
        image_url = extract_image_url(entry)
        published = None
        if entry.get("published_parsed"):
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        if title and url:
            upsert_article(conn, source["name"], source["tier"], title, url, summary, published, image_url=image_url)


def fetch_video(conn, source):
    feed = feedparser.parse(source["url"])
    for entry in feed.entries:
        title = entry.get("title", "").strip()
        url = entry.get("link", "").strip()
        summary = (entry.get("summary", "") or "")[:400]
        image_url = extract_image_url(entry)
        published = None
        if entry.get("published_parsed"):
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        if title and url:
            upsert_article(conn, source["name"], source["tier"], title, url, summary, published, is_video=True, image_url=image_url)


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
        time.sleep(REQUEST_DELAY_SECONDS)

    for source in VIDEO_SOURCES:
        try:
            fetch_video(conn, source)
            print(f"[ok] {source['name']} (video)")
        except Exception as e:
            print(f"[error] {source['name']} (video): {e}")
        time.sleep(REQUEST_DELAY_SECONDS)

    for source in REDDIT_SOURCES:
        try:
            fetch_reddit(conn, source)
            print(f"[ok] {source['name']}")
        except Exception as e:
            print(f"[error] {source['name']}: {e}")
        time.sleep(REDDIT_REQUEST_DELAY_SECONDS)


def cluster_recent_articles(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, title, story_id
            FROM articles
            WHERE COALESCE(published_at, fetched_at) > now() - interval '%s days'
            AND is_walkthrough = FALSE
            AND is_recurring_thread = FALSE
            """
            % CLUSTER_WINDOW_DAYS
        )
        rows = cur.fetchall()

    if len(rows) < 2:
        return

    ids = [r[0] for r in rows]
    titles = [r[1] for r in rows]
    existing_story_ids = [r[2] for r in rows]

    vectorizer = TfidfVectorizer(stop_words=STOPWORDS)
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
        canonical_story_id = None
        existing_count = 0
        if known_ids:
            with conn.cursor() as cur:
                for sid in sorted(known_ids):
                    cur.execute("SELECT count(*) FROM articles WHERE story_id = %s", (sid,))
                    count = cur.fetchone()[0]
                    if count < MAX_STORY_SIZE:
                        canonical_story_id = sid
                        existing_count = count
                        break

        # Fix (23 Aug 2026, extended 18 Sep 2026): the size check above
        # only throttles growth INTO an already-existing story across
        # multiple runs. Two real incidents have now exploited two
        # different gaps in that:
        #  1. A single pass's own transitive union-find grouping could
        #     form one giant BRAND NEW cluster in one shot - loosely-
        #     similar titles chain together (A~B, B~C, C~D...) until
        #     dozens of unrelated articles land in one group, all with
        #     no existing story_id yet, so the size check never runs.
        #     (story 322 reached 700+ articles, story 4278 reached 228.)
        #  2. Even after capping brand-new stories, reusing an EXISTING
        #     under-cap story had no cap of its own on the incoming
        #     group's size - if even one member of a 56-person group
        #     matched a story that currently held, say, 12 articles,
        #     all 56 got attached in one shot, sailing straight past 30.
        #     (confirmed live 18 Sep 2026: two stories reached 56 and 36
        #     members this way, after a 3-day ingestion outage let a
        #     large backlog form in a single catch-up run.)
        # The fix for both is the same: cap how many members from THIS
        # group can be attached to the chosen target - the full 30 for a
        # brand-new story, or whatever room remains for an existing one -
        # regardless of which branch is taken. Anything past the cap is
        # left unclustered (story_id stays NULL) rather than force-split
        # arbitrarily, so it's simply invisible this cycle and gets a
        # fair, fresh reconsideration next run once the window has moved
        # and unrelated titles have diluted the false similarity chain.
        # Fix (2 Oct 2026): when a group spans several already-separate
        # stories for the same long-running saga (a big game's launch
        # week genuinely produces trailers, previews, news and a review
        # as distinct real stories, each individually under the cap but
        # collectively exceeding it when they transitively chain into
        # one pass's group), truncating by whatever order the database
        # happens to return rows in could silently and repeatedly starve
        # out a brand-new article in favour of one that's already settled
        # somewhere else. Confirmed live: a fresh "Gears of War: E-Day
        # Review" sat with no story_id for hours, losing out to already-
        # clustered members of the same group on every single cycle.
        # Members with no existing story_id are never-clustered and have
        # nothing to lose by being bumped to next cycle except delay;
        # members that already have one keep it regardless of whether
        # they make this cut. So give the never-clustered ones first
        # claim on whatever room is available.
        members = sorted(members, key=lambda i: existing_story_ids[i] is not None)
        room = MAX_STORY_SIZE - existing_count
        members = members[:room] if room > 0 else []
        if not members:
            continue

        if canonical_story_id is None:
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


def mark_review_stories(conn):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE stories SET is_review = TRUE WHERE title ILIKE %s AND is_review = FALSE",
            ("%review%",),
        )
    conn.commit()


def mark_video_stories(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE stories s SET is_video = TRUE
            WHERE s.is_video = FALSE
            AND EXISTS (SELECT 1 FROM articles a WHERE a.story_id = s.id AND a.is_video = TRUE)
            """
        )
    conn.commit()


def extract_game_name(title):
    t = title.strip()
    m = re.match(r"^(?:\w+\s+)?review\s*[:\-\u2013\u2014]\s*(.+)$", t, re.IGNORECASE)
    if m:
        candidate = m.group(1)
    else:
        parts = re.split(r"\breview(?:s)?\b", t, maxsplit=1, flags=re.IGNORECASE)
        candidate = parts[0] if parts else t
    candidate = re.sub(r"^(our|the)\s+", "", candidate, flags=re.IGNORECASE)
    candidate = re.split(r"\s[\-\u2013\u2014:]\s", candidate)[0]
    candidate = re.sub(r"\s*\([^)]*\)\s*$", "", candidate)
    candidate = candidate.strip(" -\u2013\u2014:,.'\"")
    return candidate


def match_is_plausible(query, matched_name):
    def tokens(s):
        return set(re.findall(r"[a-z0-9]+", s.lower()))

    query_tokens = tokens(query) - STOPWORDS_SET
    name_tokens = tokens(matched_name)
    return bool(query_tokens and (query_tokens & name_tokens))


def search_opencritic(name):
    resp = requests.get(
        f"https://{OPENCRITIC_HOST}/game/search",
        params={"criteria": name},
        headers={
            "x-rapidapi-host": OPENCRITIC_HOST,
            "x-rapidapi-key": OPENCRITIC_API_KEY,
        },
        timeout=15,
    )
    resp.raise_for_status()
    results = resp.json()
    return results[0] if results else None


def get_opencritic_game(game_id):
    resp = requests.get(
        f"https://{OPENCRITIC_HOST}/game/{game_id}",
        headers={
            "x-rapidapi-host": OPENCRITIC_HOST,
            "x-rapidapi-key": OPENCRITIC_API_KEY,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def opencritic_lookups_today(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM stories WHERE opencritic_checked_at::date = now()::date"
        )
        return cur.fetchone()[0]


def enrich_review_scores(conn):
    if not OPENCRITIC_API_KEY:
        print("[skip] OPENCRITIC_API_KEY not set, skipping review score lookup")
        return

    already_today = opencritic_lookups_today(conn)
    remaining_budget = MAX_OPENCRITIC_LOOKUPS_PER_DAY - already_today
    if remaining_budget <= 0:
        print(f"[skip] review scores: daily budget of {MAX_OPENCRITIC_LOOKUPS_PER_DAY} already used today")
        return

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, title FROM stories
            WHERE is_review = TRUE AND opencritic_checked_at IS NULL
            ORDER BY updated_at DESC
            LIMIT %s
            """,
            (remaining_budget,),
        )
        rows = cur.fetchall()

    for story_id, title in rows:
        game_name = extract_game_name(title)
        try:
            match = search_opencritic(game_name) if game_name else None
            if match and match_is_plausible(game_name, match["name"]):
                detail = get_opencritic_game(match["id"])
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE stories
                        SET opencritic_score = %s,
                            opencritic_tier = %s,
                            opencritic_url = %s,
                            opencritic_review_count = %s,
                            opencritic_game_name = %s,
                            opencritic_checked_at = now()
                        WHERE id = %s
                        """,
                        (
                            detail.get("topCriticScore"),
                            detail.get("tier"),
                            detail.get("url"),
                            detail.get("numReviews"),
                            detail.get("name"),
                            story_id,
                        ),
                    )
                conn.commit()
                print(f"[ok] review score: {title!r} -> {detail.get('name')} ({detail.get('tier')})")
            else:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE stories SET opencritic_checked_at = now() WHERE id = %s",
                        (story_id,),
                    )
                conn.commit()
                reason = "no search result" if not match else f"implausible match {match['name']!r}"
                print(f"[no match] review score: {title!r} (searched {game_name!r}, {reason})")
        except Exception as e:
            print(f"[error] review score for {title!r}: {e}")
        time.sleep(REQUEST_DELAY_SECONDS)


def main():
    conn = psycopg2.connect(DB_URL)
    ensure_schema(conn)
    last_review_score_check = None
    while True:
        print(f"--- ingestion run: {datetime.now(timezone.utc).isoformat()} ---")
        run_once(conn)
        try:
            cluster_recent_articles(conn)
            print("[ok] clustering")
        except Exception as e:
            print(f"[error] clustering: {e}")
        try:
            mark_review_stories(conn)
            print("[ok] review detection")
        except Exception as e:
            print(f"[error] review detection: {e}")
        try:
            mark_video_stories(conn)
            print("[ok] video detection")
        except Exception as e:
            print(f"[error] video detection: {e}")

        now = datetime.now(timezone.utc)
        due = (
            last_review_score_check is None
            or (now - last_review_score_check).total_seconds() >= REVIEW_SCORE_INTERVAL_SECONDS
        )
        if due:
            try:
                enrich_review_scores(conn)
                print("[ok] review scores")
            except Exception as e:
                print(f"[error] review scores: {e}")
            last_review_score_check = now
        else:
            print("[skip] review scores: not due yet")

        time.sleep(900)


if __name__ == "__main__":
    main()
