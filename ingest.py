import os
import re
import time
import feedparser
import requests
import xml.etree.ElementTree as ET
import psycopg2
from datetime import datetime, timezone, timedelta
from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS
from sklearn.metrics.pairwise import cosine_similarity

DB_URL = os.environ["DATABASE_URL"]
OPENCRITIC_API_KEY = os.environ.get("OPENCRITIC_API_KEY")
OPENCRITIC_HOST = "opencritic-api.p.rapidapi.com"

# IGDB credentials (added 16 Aug 2026, for the release calendar - see
# fetch_upcoming_releases below). Free for non-commercial use under the
# Twitch Developer Services Agreement - verified live before building
# anything, same discipline as OpenCritic and every source above.
# Requires a Twitch account with 2FA enabled and an app registered at
# dev.twitch.tv/console (Client Type: Confidential). Rate limit is a
# generous 4 requests/second - nowhere near a constraint for a feature
# that only needs to refresh once a day.
IGDB_CLIENT_ID = os.environ.get("IGDB_CLIENT_ID")
IGDB_CLIENT_SECRET = os.environ.get("IGDB_CLIENT_SECRET")

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

REVIEW_SCORE_INTERVAL_SECONDS = 3600
MAX_OPENCRITIC_LOOKUPS_PER_DAY = 10

# Release calendar (added 16 Aug 2026, fixed same day). Real bug found
# live on 17 Aug 2026: sorting by game.hypes desc to prioritize the
# fetch budget seemed sound, but IGDB places NULL hype values *first*
# in a descending sort rather than last - verified directly: our top
# 500 had a minimum hype of 0 with 267 null-hype entries consuming the
# budget, while genuinely anticipated titles (Mortal Shell II, hype 80;
# "Control Resonant", hype 201) were sitting excluded past the cutoff.
# Fixed by excluding untracked-hype entries entirely via
# game.hypes != null in the where clause, so the budget is spent purely
# on games IGDB has real anticipation data for. Also added game.slug and
# game.summary so the web app can link to the game's real IGDB page and
# show a short description without a second API call. Lookback trimmed
# to 1 day (down from 7) - the web app itself only ever displays
# release_date >= today, so fetching much further back was pointless
# stored-but-unused data.
CALENDAR_WINDOW_DAYS = 60
CALENDAR_LOOKBACK_DAYS = 1
CALENDAR_FETCH_LIMIT = 500
RELEASE_CALENDAR_INTERVAL_SECONDS = 86400

_igdb_token_cache = {"access_token": None, "expires_at": 0}


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
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO articles (source, source_tier, title, url, summary, published_at, is_video, is_walkthrough, image_url)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (url) DO NOTHING;
            """,
            (source, tier, title, url, summary, published_at, is_video, is_walkthrough, image_url),
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


def get_igdb_token():
    now = time.time()
    if _igdb_token_cache["access_token"] and now < _igdb_token_cache["expires_at"] - 60:
        return _igdb_token_cache["access_token"]

    resp = requests.post(
        "https://id.twitch.tv/oauth2/token",
        params={
            "client_id": IGDB_CLIENT_ID,
            "client_secret": IGDB_CLIENT_SECRET,
            "grant_type": "client_credentials",
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    _igdb_token_cache["access_token"] = data["access_token"]
    _igdb_token_cache["expires_at"] = now + data["expires_in"]
    return _igdb_token_cache["access_token"]


def fetch_upcoming_releases(conn):
    if not IGDB_CLIENT_ID or not IGDB_CLIENT_SECRET:
        print("[skip] IGDB_CLIENT_ID/IGDB_CLIENT_SECRET not set, skipping release calendar")
        return

    token = get_igdb_token()
    now_ts = int(time.time())
    start_ts = now_ts - CALENDAR_LOOKBACK_DAYS * 86400
    end_ts = now_ts + CALENDAR_WINDOW_DAYS * 86400

    resp = requests.post(
        "https://api.igdb.com/v4/release_dates",
        headers={
            "Client-ID": IGDB_CLIENT_ID,
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        data=(
            "fields game.name, game.cover.url, game.game_type, game.hypes, game.slug, game.summary, platform.name, date;"
            f" where date > {start_ts} & date < {end_ts} & game.game_type = 0 & game.hypes != null;"
            " sort game.hypes desc; limit " + str(CALENDAR_FETCH_LIMIT) + ";"
        ),
        timeout=20,
    )
    resp.raise_for_status()
    rows = resp.json()

    upserted = 0
    with conn.cursor() as cur:
        for row in rows:
            game = row.get("game") or {}
            name = game.get("name")
            date_ts = row.get("date")
            release_id = row.get("id")
            if not name or not date_ts or not release_id:
                continue
            release_date = datetime.fromtimestamp(date_ts, tz=timezone.utc).date()
            platform = (row.get("platform") or {}).get("name")
            cover_url = game.get("cover", {}).get("url") if game.get("cover") else None
            if cover_url:
                if cover_url.startswith("//"):
                    cover_url = "https:" + cover_url
                cover_url = cover_url.replace("t_thumb", "t_cover_big")
            game_slug = game.get("slug")
            summary = game.get("summary")
            hype = game.get("hypes")
            cur.execute(
                """
                INSERT INTO game_releases (igdb_release_id, game_name, platform, release_date, cover_url, game_slug, summary, hype)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (igdb_release_id) DO UPDATE SET
                    game_name = EXCLUDED.game_name,
                    platform = EXCLUDED.platform,
                    release_date = EXCLUDED.release_date,
                    cover_url = EXCLUDED.cover_url,
                    game_slug = EXCLUDED.game_slug,
                    summary = EXCLUDED.summary,
                    hype = EXCLUDED.hype,
                    fetched_at = now()
                """,
                (release_id, name, platform, release_date, cover_url, game_slug, summary, hype),
            )
            upserted += 1
    conn.commit()
    print(f"[ok] release calendar: {upserted} entries upserted")


def main():
    conn = psycopg2.connect(DB_URL)
    ensure_schema(conn)
    last_review_score_check = None
    last_calendar_check = None
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

        due_calendar = (
            last_calendar_check is None
            or (now - last_calendar_check).total_seconds() >= RELEASE_CALENDAR_INTERVAL_SECONDS
        )
        if due_calendar:
            try:
                fetch_upcoming_releases(conn)
            except Exception as e:
                print(f"[error] release calendar: {e}")
            last_calendar_check = now
        else:
            print("[skip] release calendar: not due yet")

        time.sleep(900)


if __name__ == "__main__":
    main()
