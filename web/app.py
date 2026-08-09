import os
import re
import datetime
import psycopg2
import psycopg2.extras
from flask import Flask, render_template_string

app = Flask(__name__)
DB_URL = os.environ["DATABASE_URL"]

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
  --niche: #7F77DD;
  --niche-bg: #EEEDFE;
  --niche-fg: #3C3489;
  --comm: #D85A30;
  --comm-bg: #FAECE7;
  --comm-fg: #712B13;
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
    --niche-bg: #3C3489;
    --niche-fg: #CECBF6;
    --comm-bg: #712B13;
    --comm-fg: #F5C4B3;
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
  display: block;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 16px;
  margin-bottom: 14px;
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
"""

PAGE_TEMPLATE = """<!doctype html>
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
<div class="legend">
<span><span class="dot" style="background:var(--trust)"></span>Trusted</span>
<span><span class="dot" style="background:var(--niche)"></span>Niche</span>
<span><span class="dot" style="background:var(--comm)"></span>Community</span>
</div>
<main>
{% for story in stories %}
<a class="card" href="/story/{{ story.id }}">
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
{% endfor %}
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
<a class="back" href="/">&larr; All stories</a>
<main style="padding-top:14px;">
<h1 style="font-size:19px;font-weight:600;line-height:1.35;margin:0 0 8px;">{{ story.title }}</h1>
<p class="meta">{{ n }} source{{ 's' if n != 1 else '' }}</p>
<div class="bar">
{% if trusted_n %}<div style="flex:{{ trusted_n }};background:var(--trust);"></div>{% endif %}
{% if niche_n %}<div style="flex:{{ niche_n }};background:var(--niche);"></div>{% endif %}
{% if community_n %}<div style="flex:{{ community_n }};background:var(--comm);"></div>{% endif %}
</div>
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

@app.route("/")
def index():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT
            s.id,
            s.title,
            count(*) AS n,
            count(*) FILTER (WHERE a.source_tier = 'trusted') AS trusted_n,
            count(*) FILTER (WHERE a.source_tier = 'niche') AS niche_n,
            count(*) FILTER (WHERE a.source_tier = 'community') AS community_n,
            max(COALESCE(a.published_at, a.fetched_at)) AS latest
        FROM stories s
        JOIN articles a ON a.story_id = s.id
        GROUP BY s.id, s.title
        ORDER BY n DESC, latest DESC
        LIMIT 30
    """)
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
        })

    cur.execute("SELECT count(DISTINCT source) FROM articles")
    source_count = cur.fetchone()["count"]

    cur.close()
    conn.close()

    return render_template_string(PAGE_TEMPLATE, stories=stories, source_count=source_count)

@app.route("/story/<int:story_id>")
def story_detail(story_id):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id, title FROM stories WHERE id = %s", (story_id,))
    story = cur.fetchone()
    if story is None:
        cur.close()
        conn.close()
        return "Story not found", 404

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
