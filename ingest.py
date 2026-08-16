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
IGDB_CLIENT_ID = os.environ.get("IGDB_CLIENT_ID")
IGDB_CLIENT_SECRET = os.environ.get("IGDB_CLIENT_SECRET")

# Game Developer, The Indie Informer, and Indie Game Reviewer added 12
# Aug 2026, following a discussion about diversifying sources rather
# than just adding volume. Checked live first, same as always:
#
# Game Developer (gamedeveloper.com, formerly Gamasutra) - tiered
# "trusted": a real professional trade publication (industry/craft
# news - layoffs, acquisitions, design deep-dives - a genuinely
# different angle from our existing consumer-press sources), owned by
# Informa Tech Target (confirmed via Wikipedia), independent of the
# Ziff Davis/Future plc/Valnet/Hookshot Media concentration already
# found among our other sources. Publishes several times daily.
#
# The Indie Informer and Indie Game Reviewer - both tiered "niche":
# small, genuinely independent teams (Indie Informer is Patreon-funded;
# Indie Game Reviewer's own About page describes it as "an
# independently operated website," running since 2007), covering indie
# games exclusively - the specific gap asked for. Indie Game Reviewer
# publishes roughly weekly rather than daily - lower cadence than our
# other sources, worth knowing going in, but still genuine, verified
# activity (confirmed via actual feed pubDates, not a stale-looking
# featured/pinned carousel on the homepage, which turned out to be
# misleading on its own).
#
# r/IndieDev and indie YouTube curator Jupiter Hadley were both
# checked and deliberately NOT added: r/IndieDev's real content is
# almost entirely self-promotional WIP showcases (GIFs/screenshots of
# one dev's own project) rather than news that could ever cluster with
# anything else - adding it would just recreate the single-source
# noise problem MIN_SOURCES_DEFAULT already exists to manage. Jupiter
# Hadley's current uploads are 100% numbered "Part N" jam playthroughs
# - a complete WALKTHROUGH_PATTERN match, meaning virtually nothing
# from the channel would ever surface, same outcome as FightinCowboy
# earlier.
#
# GamesIndustry.biz added 12 Aug 2026, tiered "trusted" (consistent
# with Game Developer - both are professional industry-trade press,
# not consumer gaming news, regardless of shared ownership with
# differently-tiered siblings). Deliberately added DESPITE being part
# of the Gamer Network/IGN Entertainment/Ziff Davis group already
# represented by IGN, Eurogamer, Rock Paper Shotgun, and VG247 - the
# user's own reasoning: having it explicitly flagged as part of that
# group via the ownership-transparency feature is *more* useful than
# treating the overlap as a reason to exclude it. The point of that
# feature is surfacing exactly this kind of connection, not avoiding
# sources that would reveal one. Checked live first regardless: real
# RSS feed at /feed, publishing several times a day, genuinely current.
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

# YouTube RSS via channel_id - no API key, no OAuth, no quota. Channel IDs
# found by loading each channel page and reading the link rel=alternate
# type=application/rss+xml tag YouTube includes by default - the handle
# (@name) is not the same as the channel_id needed here. Verified live on
# 10 Aug 2026: all 7 parse cleanly with feedparser (unlike Reddit's Atom
# variant, which needed manual ElementTree parsing - YouTube's is standard).
# Some entries are YouTube Shorts, not full videos - left in for now rather
# than adding filtering complexity before seeing if it's actually a problem.
#
# Fextralife and Bellular News added 11 Aug 2026, tiered "niche" for
# consistency with Kinda Funny Games - all three are YouTube-native
# creator channels rather than institutional press outlets, even where
# large/well-regarded (Fextralife: 1.17m subs; Bellular News: 537k),
# which is the same distinction already drawn between "trusted"
# (IGN, Digital Foundry, VGC, Game Informer - all outlets with an
# editorial history predating YouTube) and "niche" elsewhere.
#
# FightinCowboy deliberately NOT added, checked live first: all 6 most
# recent uploads at check time were numbered "Let's Play Part N" videos -
# 100% matches for WALKTHROUGH_PATTERN below, meaning virtually nothing
# from the channel would ever actually surface in the clustered feed.
# Fextralife was almost added under the same suspicion (also known for
# guide/wiki content) but checking its actual recent uploads first showed
# the opposite - genuinely review/analysis/round-up-heavy, zero
# walkthrough-pattern matches in the sample checked. Good reminder that
# a channel's general reputation isn't a substitute for checking its
# actual current output before deciding.
#
# DF Clips added 12 Aug 2026 - Digital Foundry's own secondary channel
# ("Clips, reaction and highlights from Digital Foundry" per its own
# description), tiered "trusted" to match the main Digital Foundry
# channel since it's the same institutional outlet, not a separate
# creator. Checked live first same as always: 6 most recent titles were
# all genuine tech/hardware/gaming commentary ("Half-Life Alyx Running
# On Meta Quest 3?!", "PC Settings Tweaking vs Console Curation"), zero
# WALKTHROUGH_PATTERN matches, posting multiple times a day.
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

# Release calendar (added 16 Aug 2026) - a first cut, deliberately
# simple. Verified live before building: IGDB's API is free for
# non-commercial use under the Twitch Developer Services Agreement,
# rate-limited to 4 requests/second (far more than we need for a daily
# refresh), and uses a standard OAuth2 client-credentials grant - app-
# only auth, no interactive user login involved, fully automatable here.
# Runs on its own slow, once-a-day cadence since release dates don't
# change every 15 minutes the way news/video does. CALENDAR_WINDOW_DAYS
# is how far ahead we look; CALENDAR_LOOKBACK_DAYS keeps a short trailing
# window of very recent releases too, so the calendar page has some
# "just released" context rather than starting completely blank at
# exactly today. No genre/platform filtering and no attempt to exclude
# DLC/bundle entries for this v1 - IGDB's own category/game_type fields
# could do that, deliberately skipped rather than filter on an enum
# value not yet verified against a real live response.
CALENDAR_WINDOW_DAYS = 60
CALENDAR_LOOKBACK_DAYS = 7
RELEASE_CALENDAR_INTERVAL_SECONDS = 86400

_igdb_token_cache = {"token": None, "expires_at": 0}


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
        # game_releases (added 16 Aug 2026) - backs the Calendar tab.
        # One row per IGDB release_dates entry, which already represents
        # one specific game+platform+date combination on IGDB's own side
        # - igdb_id is that row's own id, used directly as the dedupe
        # key rather than constructing a synthetic one. A game releasing
        # on multiple platforms genuinely produces multiple rows here,
        # one per platform - accepted as a v1 simplification rather than
        # merging platforms into a single display row.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS game_releases (
                id SERIAL PRIMARY KEY,
                igdb_id INTEGER UNIQUE NOT NULL,
                game_name TEXT NOT NULL,
                platform TEXT,
                release_date DATE,
                release_date_human TEXT,
                cover_url TEXT,
                fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
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
    if _igdb_token_cache["token"] and now < _igdb_token_cache["expires_at"]:
        return _igdb_token_cache["token"]

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
    _igdb_token_cache["token"] = data["access_token"]
    _igdb_token_cache["expires_at"] = now + data["expires_in"] - 300
    return _igdb_token_cache["token"]


def fetch_upcoming_releases(conn):
    if not IGDB_CLIENT_ID or not IGDB_CLIENT_SECRET:
        print("[skip] release calendar: IGDB_CLIENT_ID/IGDB_CLIENT_SECRET not set")
        return

    token = get_igdb_token()
    now = datetime.now(timezone.utc)
    start = int((now - timedelta(days=CALENDAR_LOOKBACK_DAYS)).timestamp())
    end = int((now + timedelta(days=CALENDAR_WINDOW_DAYS)).timestamp())

    resp = requests.post(
        "https://api.igdb.com/v4/release_dates",
        headers={
            "Client-ID": IGDB_CLIENT_ID,
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        data=(
            "fields game.name, game.cover.image_id, platform.name, date, human; "
            f"where date > {start} & date < {end}; "
            "sort date asc; "
            "limit 200;"
        ),
        timeout=20,
    )
    resp.raise_for_status()
    rows = resp.json()

    with conn.cursor() as cur:
        for row in rows:
            game = row.get("game") or {}
            game_name = game.get("name")
            if not game_name:
                continue
            platform = (row.get("platform") or {}).get("name")
            cover = game.get("cover") or {}
            cover_url = (
                f"https://images.igdb.com/igdb/image/upload/t_cover_big/{cover['image_id']}.jpg"
                if cover.get("image_id") else None
            )
            release_date = None
            if row.get("date"):
                release_date = datetime.fromtimestamp(row["date"], tz=timezone.utc).date()
            cur.execute(
                """
                INSERT INTO game_releases (igdb_id, game_name, platform, release_date, release_date_human, cover_url)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (igdb_id) DO UPDATE SET
                    game_name = EXCLUDED.game_name,
                    platform = EXCLUDED.platform,
                    release_date = EXCLUDED.release_date,
                    release_date_human = EXCLUDED.release_date_human,
                    cover_url = EXCLUDED.cover_url,
                    fetched_at = now()
                """,
                (row["id"], game_name, platform, release_date, row.get("human"), cover_url),
            )
    conn.commit()
    print(f"[ok] release calendar: {len(rows)} entries")


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
