import os
import re
import datetime
import psycopg2
import psycopg2.extras
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)
DB_URL = os.environ["DATABASE_URL"]

# How long a story stays visible in Main/Reviews/Video before aging out of
# the feed entirely, regardless of read state. Decided with the user on
# 10 Aug 2026 as a single mechanism to solve two asks at once: stopping
# old low-signal stuff from cluttering the recent feed, and giving read
# stories a natural way to disappear over time, without needing a
# separate per-item timer or a manual "clear" action - the underlying
# rows are never deleted, just filtered out of view once past this
# window, so nothing is lost for the themes page below. Read state only
# affects dimming (is_read below), not whether a story is in the window
# at all - a read story ages out exactly the same way an unread one does.
FEED_WINDOW_DAYS = 2

# Small inline stopword list for the themes word-frequency stat - kept
# separate from ingest.py's clustering stopwords deliberately, since the
# two services don't share code or dependencies (no sklearn in the web
# app), and this list is tuned for headline word frequency, not
# similarity clustering.
WORD_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "for", "to", "and", "or", "with",
    "is", "are", "at", "its", "new", "review", "trailer", "official",
    "launch", "launches", "release", "released", "date", "gameplay",
    "reveal", "revealed", "announced", "announcement", "coming", "after",
    "from", "this", "that", "how", "why", "what", "your", "you", "we",
    "will", "has", "have", "been", "be", "was", "were", "but", "not",
    "all", "more", "just", "get", "gets", "first", "full", "update",
    "week", "into", "out", "up", "now", "still", "than", "their",
}


CSS = """
:root {
--bg: #f7f6f2;
--card: #ffffff;
--border: #e4e1d8;
--text: #1a1a18;
--text-secondary: #6b6a63;
--trust: #378ADD;
--trust-bg: #E6F1FB;
--trust-fg: #0C447C;
--niche: #D4537E;
--niche-bg: #FBEAF0;
--niche-fg: #72243E;
--comm: #D85A30;
--comm-bg: #FAECE7;
--comm-fg: #712B13;
--mighty-bg: #EAF3DE;
--mighty-fg: #27500A;
--strong-bg: #E1F5EE;
--strong-fg: #085041;
--fair-bg: #FAEEDA;
--fair-fg: #633806;
--weak-bg: #FCEBEB;
--weak-fg: #791F1F;
}
@media (prefers-color-scheme: dark) {
:root {
--bg: #161614;
--card: #201f1c;
--border: #37352e;
--text: #f0efe9;
--text-secondary: #9a9890;
--trust-bg: #0C447C;
--trust-fg: #B5D4F4;
--niche-bg: #72243E;
--niche-fg: #ED93B1;
--comm-bg: #712B13;
--comm-fg: #F5C4B3;
--mighty-bg: #27500A;
--mighty-fg: #C0DD97;
--strong-bg: #085041;
--strong-fg: #9FE1CB;
--fair-bg: #633806;
--fair-fg: #FAC775;
--weak-bg: #791F1F;
--weak-fg: #F7C1C1;
}
}
* { box-sizing: border-box; }
body {
margin: 0;
font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
background: var(--bg);
color: var(--text);
}
a { color: inherit; text-decoration: none; }
header {
padding: 20px 16px 12px;
max-width: 640px;
margin: 0 auto;
}
header h1 {
font-size: 20px;
font-weight: 600;
margin: 0 0 4px;
}
header p {
font-size: 13px;
color: var(--text-secondary);
margin: 0;
}
.tabs {
display: flex;
gap: 4px;
padding: 4px 16px 0;
max-width: 640px;
margin: 0 auto;
border-bottom: 1px solid var(--border);
overflow-x: auto;
}
.tab {
font-size: 14px;
font-weight: 600;
padding: 8px 12px;
border-radius: 8px 8px 0 0;
color: var(--text-secondary);
white-space: nowrap;
}
.tab.active {
color: var(--text);
background: var(--card);
border: 1px solid var(--border);
border-bottom-color: var(--card);
margin-bottom: -1px;
}
.view-row {
display: flex;
gap: 16px;
padding: 12px 16px;
max-width: 640px;
margin: 0 auto;
}
.view-link {
font-size: 13px;
color: var(--text-secondary);
}
.view-link.active {
color: var(--text);
font-weight: 600;
text-decoration: underline;
}
.legend {
display: flex;
gap: 14px;
font-size: 12px;
color: var(--text-secondary);
padding: 0 16px 14px;
max-width: 640px;
margin: 0 auto;
}
.dot {
width: 8px; height: 8px; border-radius: 50%;
display: inline-block; margin-right: 5px;
}
main {
max-width: 640px;
margin: 0 auto;
padding: 0 16px 40px;
}
.card {
position: relative;
display: block;
background: var(--card);
border: 1px solid var(--border);
border-radius: 14px;
padding: 16px;
margin-bottom: 14px;
transition: opacity 0.2s ease, transform 0.2s ease;
}
.card.read {
opacity: 0.5;
}
.card-link {
display: block;
}
.card-link.with-discard {
padding-top: 54px;
}
.discard-btn {
position: absolute;
top: 8px;
left: 8px;
width: 44px;
height: 44px;
border-radius: 50%;
border: none;
background: var(--border);
color: var(--text-secondary);
font-size: 20px;
line-height: 1;
display: flex;
align-items: center;
justify-content: center;
cursor: pointer;
z-index: 2;
padding: 0;
}
.card h2 {
font-size: 16px;
font-weight: 600;
margin: 0 0 6px;
line-height: 1.4;
}
.meta {
font-size: 13px;
color: var(--text-secondary);
margin: 0 0 10px;
}
.bar {
height: 6px;
border-radius: 4px;
overflow: hidden;
display: flex;
margin-bottom: 10px;
}
.chips {
display: flex;
flex-wrap: wrap;
gap: 6px;
}
.chip {
font-size: 12px;
font-weight: 600;
padding: 4px 10px;
border-radius: 20px;
}
.score-chip {
font-size: 12px;
font-weight: 700;
padding: 4px 10px;
border-radius: 20px;
display: inline-block;
margin-bottom: 10px;
}
.back {
display: block;
font-size: 14px;
font-weight: 600;
color: var(--text-secondary);
padding: 16px 16px 0;
max-width: 640px;
margin: 0 auto;
}
.synopsis {
font-size: 15px;
line-height: 1.6;
color: var(--text);
margin: 4px 0 22px;
}
.score-block {
display: flex;
align-items: center;
gap: 14px;
background: var(--card);
border: 1px solid var(--border);
border-radius: 14px;
padding: 16px;
margin: 4px 0 18px;
}
.score-circle {
width: 56px;
height: 56px;
border-radius: 50%;
display: flex;
align-items: center;
justify-content: center;
font-size: 20px;
font-weight: 700;
flex-shrink: 0;
}
.score-tier {
font-size: 13px;
font-weight: 600;
margin: 0 0 4px;
}
.score-link {
font-size: 13px;
text-decoration: underline;
color: var(--text-secondary);
}
.source-row {
display: block;
background: var(--card);
border: 1px solid var(--border);
border-radius: 14px;
padding: 14px 16px;
margin-bottom: 10px;
}
.source-row .src-name {
font-size: 12px;
font-weight: 600;
padding: 3px 9px;
border-radius: 20px;
display: inline-block;
margin-bottom: 8px;
}
.source-row .src-title {
font-size: 14.5px;
font-weight: 500;
line-height: 1.4;
margin: 0 0 4px;
}
.source-row .src-meta {
font-size: 12px;
color: var(--text-secondary);
}
.section-label {
font-size: 12px;
font-weight: 600;
color: var(--text-secondary);
margin: 22px 0 10px;
text-transform: uppercase;
letter-spacing: 0.04em;
}
.theme-note {
font-size: 13px;
color: var(--text-secondary);
line-height: 1.5;
margin: 4px 0 4px;
}
.theme-list {
background: var(--card);
border: 1px solid var(--border);
border-radius: 14px;
padding: 4px 16px;
margin-bottom: 4px;
}
.theme-list-row {
display: flex;
justify-content: space-between;
align-items: center;
padding: 12px 0;
border-bottom: 1px solid var(--border);
font-size: 14px;
}
.theme-list-row:last-child {
border-bottom: none;
}
.theme-count {
font-size: 13px;
color: var(--text-secondary);
font-weight: 600;
}
"""

DISCARD_JS = """
<script>
document.addEventListener("click", function (e) {
  var btn = e.target.closest(".discard-btn");
  if (!btn) return;
  e.preventDefault();
  e.stopPropagation();
  var url = btn.getAttribute("data-action");
  var card = btn.closest(".card");
  fetch(url, { method: "POST" }).then(function (r) {
    if (r.ok && card) {
      card.style.opacity = "0";
      card.style.transform = "scale(0.96)";
      setTimeout(function () { card.remove(); }, 200);
    }
  });
});
</script>
"""

FEED_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FeedMeNews</title>
<style>""" + CSS + """</style>
</head>
<body>
<header>
<h1>FeedMeNews</h1>
<p>Gaming coverage across {{ source_count }} sources, grouped by story</p>
</header>
<div class="tabs">
<a href="/" class="tab {{ 'active' if active_tab == 'main' else '' }}">Main</a>
<a href="/reviews" class="tab {{ 'active' if active_tab == 'reviews' else '' }}">Reviews</a>
<a href="/video" class="tab {{ 'active' if active_tab == 'video' else '' }}">Video</a>
<a href="/themes" class="tab {{ 'active' if active_tab == 'themes' else '' }}">Themes</a>
</div>
<div class="view-row">
<a href="{{ base_path }}" class="view-link {{ 'active' if view == 'recent' else '' }}">Most recent</a>
<a href="{{ base_path }}?view=covered" class="view-link {{ 'active' if view == 'covered' else '' }}">Most covered</a>
</div>
<div class="legend">
<span><span class="dot" style="background:var(--trust)"></span>Trusted</span>
<span><span class="dot" style="background:var(--niche)"></span>Niche</span>
<span><span class="dot" style="background:var(--comm)"></span>Community</span>
</div>
<main>
{% for story in stories %}
<div class="card {{ 'read' if story.is_read else '' }}">
<button class="discard-btn" data-action="/story/{{ story.id }}/discard" aria-label="Discard">&times;</button>
<a class="card-link with-discard" href="/story/{{ story.id }}">
{% if story.opencritic_score and story.opencritic_score > 0 %}
<span class="score-chip" style="background:var(--{{ (story.opencritic_tier or 'strong')|lower }}-bg); color:var(--{{ (story.opencritic_tier or 'strong')|lower }}-fg);">{{ story.opencritic_score|round|int }}{% if story.opencritic_tier %} &middot; {{ story.opencritic_tier }}{% endif %}</span><br>
{% endif %}
<h2>{{ story.title }}</h2>
<p class="meta">{{ story.n }} source{{ 's' if story.n != 1 else '' }} &middot; {{ story.time_ago }}</p>
<div class="bar">
{% if story.trusted_n %}<div style="flex:{{ story.trusted_n }};background:var(--trust);"></div>{% endif %}
{% if story.niche_n %}<div style="flex:{{ story.niche_n }};background:var(--niche);"></div>{% endif %}
{% if story.community_n %}<div style="flex:{{ story.community_n }};background:var(--comm);"></div>{% endif %}
</div>
<div class="chips">
{% for src, tier in story.sources %}
<span class="chip" style="background:var(--{{ tier }}-bg); color:var(--{{ tier }}-fg);">{{ src }}</span>
{% endfor %}
</div>
</a>
</div>
{% endfor %}
{% if not stories %}
<p class="meta">Nothing here yet.</p>
{% endif %}
</main>
""" + DISCARD_JS + """
</body>
</html>"""

THEMES_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Themes - FeedMeNews</title>
<style>""" + CSS + """</style>
</head>
<body>
<header>
<h1>FeedMeNews</h1>
<p>Gaming coverage across {{ source_count }} sources, grouped by story</p>
</header>
<div class="tabs">
<a href="/" class="tab">Main</a>
<a href="/reviews" class="tab">Reviews</a>
<a href="/video" class="tab">Video</a>
<a href="/themes" class="tab active">Themes</a>
</div>
<main style="padding-top:16px;">
{% if total == 0 %}
<p class="meta">Nothing to show yet - read or discard a few stories first.</p>
{% else %}
<p class="theme-note">Based on {{ total }} stories read or discarded so far.
This is a single shared profile for now - there's no login yet, so it
reflects everyone who's used this installation, not a personal account.</p>

<p class="section-label">By trust tier</p>
<div class="theme-list">
{% for label, n in tier_counts %}
<div class="theme-list-row"><span>{{ label }}</span><span class="theme-count">{{ n }}</span></div>
{% endfor %}
</div>

<p class="section-label">By content type</p>
<div class="theme-list">
{% for label, n in type_counts %}
<div class="theme-list-row"><span>{{ label }}</span><span class="theme-count">{{ n }}</span></div>
{% endfor %}
</div>

<p class="section-label">Top outlets</p>
<div class="theme-list">
{% for label, n in top_outlets %}
<div class="theme-list-row"><span>{{ label }}</span><span class="theme-count">{{ n }}</span></div>
{% endfor %}
</div>

<p class="section-label">Recurring words</p>
<div class="chips">
{% for word, n in top_words %}
<span class="chip" style="background:var(--border); color:var(--text-secondary);">{{ word }} &middot; {{ n }}</span>
{% endfor %}
</div>
{% endif %}
</main>
</body>
</html>"""

STORY_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ story.title }} - FeedMeNews</title>
<style>""" + CSS + """</style>
</head>
<body>
<a class="back" href="/" onclick="if (window.history.length > 1) { history.back(); return false; }">&larr; Back</a>
<main style="padding-top:14px;">
<h1 style="font-size:19px;font-weight:600;line-height:1.35;margin:0 0 8px;">{{ story.title }}</h1>
<p class="meta">{{ n }} source{{ 's' if n != 1 else '' }}</p>
<div class="bar">
{% if trusted_n %}<div style="flex:{{ trusted_n }};background:var(--trust);"></div>{% endif %}
{% if niche_n %}<div style="flex:{{ niche_n }};background:var(--niche);"></div>{% endif %}
{% if community_n %}<div style="flex:{{ community_n }};background:var(--comm);"></div>{% endif %}
</div>
{% if story.opencritic_score and story.opencritic_score > 0 %}
<div class="score-block">
<div class="score-circle" style="background:var(--{{ (story.opencritic_tier or 'strong')|lower }}-bg); color:var(--{{ (story.opencritic_tier or 'strong')|lower }}-fg);">{{ story.opencritic_score|round|int }}</div>
<div>
{% if story.opencritic_tier %}<p class="score-tier">{{ story.opencritic_tier }}</p>{% endif %}
<a class="score-link" href="{{ story.opencritic_url }}" target="_blank" rel="noopener">View on OpenCritic &#8599;</a>
</div>
</div>
{% endif %}
{% if synopsis %}
<p class="synopsis">{{ synopsis }}</p>
{% endif %}
<p class="section-label">Covered by</p>
{% for a in articles %}
<a class="source-row" href="{{ a.url }}" target="_blank" rel="noopener">
<span class="src-name" style="background:var(--{{ a.source_tier }}-bg); color:var(--{{ a.source_tier }}-fg);">{{ a.source }}</span>
<p class="src-title">{{ a.title }}</p>
<p class="src-meta">{{ a.time_ago }} &middot; <span style="text-decoration:underline;">Read on {{ a.source }} &#8599;</span></p>
</a>
{% endfor %}
</main>
</body>
</html>"""


def humanize(delta_seconds):
    if delta_seconds < 3600:
        return f"{max(1, int(delta_seconds // 60))}m ago"
    if delta_seconds < 86400:
        return f"{int(delta_seconds // 3600)}h ago"
    return f"{int(delta_seconds // 86400)}d ago"


def strip_html(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def valid_view():
    v = request.args.get("view", "recent")
    return v if v in ("recent", "covered") else "recent"


def fetch_stories(tab, view):
    if tab == "reviews":
        tab_where = "AND s.is_review = TRUE"
    elif tab == "video":
        tab_where = "AND s.is_video = TRUE"
    else:
        tab_where = "AND s.is_review = FALSE AND s.is_video = FALSE"

    order_by = "n DESC, latest DESC" if view == "covered" else "latest DESC"

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        f"""
        SELECT
            s.id,
            s.title,
            s.opencritic_score,
            s.opencritic_tier,
            s.read_at,
            count(*) AS n,
            count(*) FILTER (WHERE a.source_tier = 'trusted') AS trusted_n,
            count(*) FILTER (WHERE a.source_tier = 'niche') AS niche_n,
            count(*) FILTER (WHERE a.source_tier = 'community') AS community_n,
            max(COALESCE(a.published_at, a.fetched_at)) AS latest
        FROM stories s
        JOIN articles a ON a.story_id = s.id
        WHERE 1=1 {tab_where}
        AND s.dismissed_at IS NULL
        GROUP BY s.id, s.title, s.opencritic_score, s.opencritic_tier, s.read_at
        HAVING max(COALESCE(a.published_at, a.fetched_at)) > now() - interval '{FEED_WINDOW_DAYS} days'
        ORDER BY {order_by}
        LIMIT 30
        """
    )
    story_rows = cur.fetchall()

    stories = []
    now = datetime.datetime.now(datetime.timezone.utc)
    for row in story_rows:
        cur.execute(
            "SELECT DISTINCT source, source_tier FROM articles WHERE story_id = %s ORDER BY source",
            (row["id"],),
        )
        sources = [(r["source"], r["source_tier"]) for r in cur.fetchall()]
        delta = (now - row["latest"]).total_seconds() if row["latest"] else 0
        stories.append({
            "id": row["id"],
            "title": row["title"],
            "n": row["n"],
            "trusted_n": row["trusted_n"],
            "niche_n": row["niche_n"],
            "community_n": row["community_n"],
            "sources": sources,
            "time_ago": humanize(delta),
            "opencritic_score": row["opencritic_score"],
            "opencritic_tier": row["opencritic_tier"],
            "is_read": row["read_at"] is not None,
        })

    cur.execute("SELECT count(DISTINCT source) FROM articles")
    source_count = cur.fetchone()["count"]

    cur.close()
    conn.close()
    return stories, source_count


@app.route("/")
def index():
    view = valid_view()
    stories, source_count = fetch_stories(tab="main", view=view)
    return render_template_string(
        FEED_TEMPLATE, stories=stories, source_count=source_count,
        active_tab="main", base_path="/", view=view,
    )


@app.route("/reviews")
def reviews():
    view = valid_view()
    stories, source_count = fetch_stories(tab="reviews", view=view)
    return render_template_string(
        FEED_TEMPLATE, stories=stories, source_count=source_count,
        active_tab="reviews", base_path="/reviews", view=view,
    )


@app.route("/video")
def video():
    view = valid_view()
    stories, source_count = fetch_stories(tab="video", view=view)
    return render_template_string(
        FEED_TEMPLATE, stories=stories, source_count=source_count,
        active_tab="video", base_path="/video", view=view,
    )


@app.route("/themes")
def themes():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute(
        "SELECT count(*) AS n FROM stories WHERE read_at IS NOT NULL OR dismissed_at IS NOT NULL"
    )
    total = cur.fetchone()["n"]

    cur.execute("SELECT count(DISTINCT source) FROM articles")
    source_count = cur.fetchone()["count"]

    tier_counts = []
    type_counts = []
    top_outlets = []
    top_words = []

    if total > 0:
        cur.execute(
            """
            SELECT a.source_tier AS tier, count(DISTINCT s.id) AS n
            FROM stories s
            JOIN articles a ON a.story_id = s.id
            WHERE s.read_at IS NOT NULL OR s.dismissed_at IS NOT NULL
            GROUP BY a.source_tier
            ORDER BY n DESC
            """
        )
        tier_counts = [(r["tier"].capitalize(), r["n"]) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT
                count(*) FILTER (WHERE is_review) AS review_n,
                count(*) FILTER (WHERE is_video) AS video_n,
                count(*) FILTER (WHERE NOT is_review AND NOT is_video) AS main_n
            FROM stories
            WHERE read_at IS NOT NULL OR dismissed_at IS NOT NULL
            """
        )
        row = cur.fetchone()
        type_counts = [
            ("Main news", row["main_n"]),
            ("Reviews", row["review_n"]),
            ("Video", row["video_n"]),
        ]

        cur.execute(
            """
            SELECT a.source AS source, count(DISTINCT s.id) AS n
            FROM stories s
            JOIN articles a ON a.story_id = s.id
            WHERE s.read_at IS NOT NULL OR s.dismissed_at IS NOT NULL
            GROUP BY a.source
            ORDER BY n DESC
            LIMIT 8
            """
        )
        top_outlets = [(r["source"], r["n"]) for r in cur.fetchall()]

        cur.execute(
            "SELECT title FROM stories WHERE read_at IS NOT NULL OR dismissed_at IS NOT NULL"
        )
        word_counts = {}
        for r in cur.fetchall():
            for w in re.findall(r"[a-zA-Z']+", r["title"].lower()):
                if len(w) < 3 or w in WORD_STOPWORDS:
                    continue
                word_counts[w] = word_counts.get(w, 0) + 1
        top_words = sorted(word_counts.items(), key=lambda x: -x[1])[:14]

    cur.close()
    conn.close()

    return render_template_string(
        THEMES_TEMPLATE,
        total=total,
        source_count=source_count,
        tier_counts=tier_counts,
        type_counts=type_counts,
        top_outlets=top_outlets,
        top_words=top_words,
    )


@app.route("/story/<int:story_id>/discard", methods=["POST"])
def discard_story(story_id):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("UPDATE stories SET dismissed_at = now() WHERE id = %s", (story_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify(ok=True)


@app.route("/story/<int:story_id>")
def story_detail(story_id):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """
        SELECT id, title, is_review, is_video, opencritic_score, opencritic_tier, opencritic_url
        FROM stories WHERE id = %s
        """,
        (story_id,),
    )
    story = cur.fetchone()
    if story is None:
        cur.close()
        conn.close()
        return "Story not found", 404

    cur.execute(
        "UPDATE stories SET read_at = COALESCE(read_at, now()) WHERE id = %s",
        (story_id,),
    )
    conn.commit()

    cur.execute(
        """
        SELECT source, source_tier, title, url, summary,
               COALESCE(published_at, fetched_at) AS published_at
        FROM articles
        WHERE story_id = %s
        ORDER BY published_at ASC
        """,
        (story_id,),
    )
    articles = cur.fetchall()
    cur.close()
    conn.close()

    trusted_n = sum(1 for a in articles if a["source_tier"] == "trusted")
    niche_n = sum(1 for a in articles if a["source_tier"] == "niche")
    community_n = sum(1 for a in articles if a["source_tier"] == "community")

    tier_rank = {"trusted": 0, "niche": 1, "community": 2}
    ranked = sorted(articles, key=lambda a: (tier_rank.get(a["source_tier"], 3), -len(a["summary"] or "")))
    synopsis = None
    for a in ranked:
        cleaned = strip_html(a["summary"])
        if cleaned:
            synopsis = cleaned
            break

    now = datetime.datetime.now(datetime.timezone.utc)
    for a in articles:
        delta = (now - a["published_at"]).total_seconds() if a["published_at"] else 0
        a["time_ago"] = humanize(delta)

    return render_template_string(
        STORY_TEMPLATE,
        story=story,
        articles=articles,
        synopsis=synopsis,
        n=len(articles),
        trusted_n=trusted_n,
        niche_n=niche_n,
        community_n=community_n,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
