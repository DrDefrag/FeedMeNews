import os
import re
import time
import feedparser
import requests
import xml.etree.ElementTree as ET
import psycopg2
from datetime import datetime, timezone
from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS
from sklearn.metrics.pairwise import cosine_similarity

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
]

HEADERS = {"User-Agent": "gaming-news-aggregator/0.1 (personal project)"}
ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}

# Small pause between requests to the same host so we don't trip rate
# limits by hitting it repeatedly in immediate succession. Press outlets
# and YouTube haven't shown any sensitivity to this; Reddit has, so it
# gets its own, longer delay below.
REQUEST_DELAY_SECONDS = 5

# Found empirically on 10 Aug 2026: 5s between Reddit requests was fine
# with only 2 subreddits, but after adding r/NintendoSwitch and r/PS5
# (4 subreddits total), 3 of the 4 started hitting 429s consistently
# across multiple full runs - only the first request in the sequence
# succeeded reliably. 5s isn't enough spacing once several Reddit requests
# happen in the same short window; giving Reddit specifically more room
# between requests than the press feeds need.
REDDIT_REQUEST_DELAY_SECONDS = 15

# Story clustering settings. Tuned empirically against real data on 9 Aug
# 2026: threshold 0.4 gives ~25 clusters out of ~290 articles, with the
# large multi-source clusters (4+ outlets on the same real story) coming
# out clean.
CLUSTER_WINDOW_DAYS = 4
CLUSTER_SIMILARITY_THRESHOLD = 0.4

# Some game-announcement titles are almost entirely boilerplate
# ("<Game> - Official Release Date Trailer") which previously caused
# unrelated games to cluster together purely on shared template words.
# Extending the stopword list to cover this class of boilerplate fixed it
# without breaking genuine multi-source clusters (verified against real
# data, 9 Aug 2026). Known remaining gap found 10 Aug 2026: multi-game
# showcase events (e.g. "THQ Nordic Showcase 2026") can still merge
# different games' trailer coverage together, since the shared event name
# is specific meaningful text, not generic filler we can safely strip the
# same way - deferred, needs its own proper fix, not a quick stopword add.
EXTRA_STOPWORDS = {
    "official", "release", "date", "trailer", "reveal", "gameplay",
    "announcement", "announced", "launches", "launch", "coming", "new",
}
STOPWORDS = list(ENGLISH_STOP_WORDS.union(EXTRA_STOPWORDS))
STOPWORDS_SET = set(STOPWORDS)

# Walkthroughs/playthroughs are serial (Part 1, Part 2, ...) rather than
# episodic like everything else we ingest - clustering them would either
# flood the feed with near-identical singleton cards, or worse, merge them
# into a nonsense "story" that isn't really one. Detected the same way as
# review titles (a simple pattern match) and excluded from clustering
# entirely below - the raw rows are still kept in the articles table, just
# never linked to a story, so nothing is thrown away, it's just not shown.
WALKTHROUGH_PATTERN = re.compile(
    r"\b(walkthrough|playthrough|let'?s play|full\s+playthrough|part\s*\d+)\b",
    re.IGNORECASE,
)

# Review score lookups (OpenCritic via RapidAPI). Free tier: 25 searches/day,
# 200 requests/day, non-commercial use only. Detection (is_review flag) is
# free and runs every ingestion cycle so review stories move into the
# Reviews section quickly; the actual OpenCritic query is the part that
# costs quota, so it runs on its own slower cadence with a tracked daily
# budget. Lowered from 20 to 10 on 10 Aug 2026 after the user flagged
# being at 85% of the RapidAPI daily allowance - 20/25 was only ever an
# 80% self-imposed ceiling by design, too close for comfort especially
# now that more video sources mean more titles containing "review" per
# day than before.
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
        # archived_at: added to support a since-removed separate Read tab.
        # No longer used by the app (dismissed_at alone means "hide
        # immediately" everywhere now) - left in place, harmless, not
        # worth a migration to remove.
        cur.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;")
        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS is_video BOOLEAN NOT NULL DEFAULT FALSE;")
        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS is_walkthrough BOOLEAN NOT NULL DEFAULT FALSE;")
        cur.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS is_video BOOLEAN NOT NULL DEFAULT FALSE;")
        # image_url (added 11 Aug 2026). Checked live against all 25
        # sources before building this: 14/14 press RSS and 7/7 YouTube
        # channels reliably include a real image; Reddit's .rss format
        # has none at all (checked the full raw feed, not just one
        # entry, across two subreddits - genuinely zero, not a fluke).
        # We hotlink the outlet's own URL here, never download or
        # re-host the actual image file ourselves.
        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS image_url TEXT;")
        # liked_at (added 11 Aug 2026). A third explicit signal alongside
        # read_at (passive click-through) and dismissed_at (explicit
        # negative) - an explicit positive signal, toggled via a Like
        # button on each feed card. Stronger training data for the
        # Themes page's future interest-profile idea than read_at alone,
        # since opening something isn't the same as actually liking it.
        cur.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS liked_at TIMESTAMPTZ;")
    conn.commit()


def extract_image_url(entry):
    """Pull a hotlinkable image URL out of a feedparser entry.

    Checked in priority order against real feeds on 11 Aug 2026: standard
    media:thumbnail (most outlets and all YouTube channels), media:content
    (GameSpot, Eurogamer, Rock Paper Shotgun, VG247), image enclosures
    (Kotaku, TheGamer), then finally a raw <img> inside the HTML summary
    as a last resort. Returns None if nothing is found - callers store
    that as-is rather than guessing, so a story with no image just shows
    no image slot, never a broken one.
    """
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
    # YouTube's channel Atom feeds parse fine with feedparser (unlike
    # Reddit's), verified live on 10 Aug 2026 against all 7 channels.
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
    # Reddit blocks anonymous requests to its .json endpoints from most
    # datacenter/hosting IP ranges, but its older .rss (Atom) endpoint is
    # not subject to the same block, just normal rate limits. We parse it
    # directly with ElementTree since feedparser doesn't reliably detect
    # entries in this particular Atom feed variant. No image extraction
    # here - checked live on 11 Aug 2026, Reddit's .rss format carries no
    # thumbnail/media/enclosure/img data at all across the full raw feed,
    # not just a single entry, across two different subreddits. A genuine
    # gap, not worth extra plumbing for - image_url stays NULL for these.
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
    """Group articles covering the same real-world story together.

    Recomputes clustering from scratch over a rolling time window every
    run (cheap at our scale: low hundreds of rows). To keep story_id
    values stable across runs rather than reshuffling every time, any
    cluster that already has one or more story_id values assigned keeps
    the smallest (earliest-created) one as canonical, and every member of
    that cluster gets updated to match it. Walkthroughs are excluded
    entirely (see WALKTHROUGH_PATTERN above) - they never get a story_id,
    so they never surface anywhere, by design.
    """
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
    """Flag review-titled stories immediately, every cycle - free, no API
    calls. This is what makes a story show up in the Reviews section
    quickly; the (quota-limited) score lookup below is a separate, slower
    step that can catch up later without delaying the story appearing.
    Source-agnostic - a video review's title matches exactly the same way
    a text review's does.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE stories SET is_review = TRUE WHERE title ILIKE %s AND is_review = FALSE",
            ("%review%",),
        )
    conn.commit()


def mark_video_stories(conn):
    """Flag any story that has at least one video-sourced article, every
    cycle - free, just a join. A story can be both is_review and is_video
    at once (a video review) - that's intentional, it should surface in
    both the Reviews and Video tabs rather than forcing an either/or.
    """
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
    """Pull a clean game name out of a review-style headline.

    Handles "Review: Game Name - subtitle", "Game Name Review: subtitle",
    and "<word> Review: Game Name" (e.g. "Mini Review: Dragon House").
    Imperfect on purpose - simple heuristic, backed up by
    match_is_plausible() below so a bad extraction produces no result
    rather than a wrong one.
    """
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
    """Reject a search match that shares no real word with the query.

    Found empirically on 9 Aug 2026: without this check, "Mini Review:
    Dragon House..." matched to the unrelated game "Minit" (similar
    string, zero shared words), and "Asus ROG Zephyrus G16 (2026) review"
    (a laptop, not a game) matched to an unrelated game called "Cosmic
    Zephyr DX" purely on fuzzy name similarity. Requiring at least one
    exact shared word (after removing stopwords) catches both without
    needing a calibrated similarity threshold. Known remaining gap: two
    different real games sharing one generic word (e.g. "Dragon Hopper"
    vs "Dragon Sinker") can still pass - accepted as a v1 tradeoff.
    """
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
