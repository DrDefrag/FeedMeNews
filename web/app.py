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

# Seconds a discarded card stays in the DOM (dimmed) before actually being
# removed, giving the Undo toast below a real window to act in. The
# server-side dismissed_at is set immediately on discard regardless - this
# delay is purely cosmetic, giving the user a chance to reverse the visual
# removal before it's gone with no trace.
UNDO_WINDOW_MS = 5000

# Minimum source count for a story to show by default on the Main tab.
# Added 11 Aug 2026: with 25 sources ingesting continuously, most of what
# comes through is genuinely single-source (one outlet's own story, one
# Reddit thread) rather than multiple outlets converging on the same real
# event - closer to the raw firehose than "the news." Ground News's own
# approach was the reference point: treat breadth of independent
# coverage as the actual significance signal, not just recency. Applied
# to Main only, not Reviews/Video - a lot of genuinely good reviews and
# videos are legitimately single-source by nature (one outlet reviewing
# a niche game, one channel covering something), so filtering those the
# same way would throw out real content, not noise. Nothing is hidden
# permanently - a plain link reveals every story, single-source included.
MIN_SOURCES_DEFAULT = 2

# How many items each horizontal rail shows (added 11 Aug 2026, inspired
# by Ground News's homepage rails). Rails are a preview/teaser, not a
# replacement for the full Reviews/Video tabs - deliberately kept short
# with a "See all" link through to the real thing, rather than trying to
# cram full browsability into a scroll strip.
RAIL_LIMIT = 8

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

# Tier priority for picking one image out of a multi-source story - reuses
# the exact same rule already used for picking the synopsis in
# story_detail(), just applied to image_url instead. Images are always
# hotlinked to the outlet's own URL, never downloaded or re-hosted here.
TIER_RANK_SQL = "CASE source_tier WHEN 'trusted' THEN 0 WHEN 'niche' THEN 1 ELSE 2 END"

ICON_MAIN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"></rect><line x1="7" y1="9" x2="17" y2="9"></line><line x1="7" y1="13" x2="17" y2="13"></line><line x1="7" y1="17" x2="13" y2="17"></line></svg>'
ICON_REVIEWS = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15 9 22 9.5 17 14.5 18.5 22 12 18 5.5 22 7 14.5 2 9.5 9 9"></polygon></svg>'
ICON_VIDEO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"></circle><polygon points="10 8 16 12 10 16" fill="currentColor" stroke="none"></polygon></svg>'
ICON_THEMES = '<svg viewBox="0 0 24 24" fill="currentColor" stroke="none"><path d="M12 2l1.8 6.2L20 10l-6.2 1.8L12 18l-1.8-6.2L4 10l6.2-1.8z"></path></svg>'
ICON_X = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="6" y1="6" x2="18" y2="18"></line><line x1="18" y1="6" x2="6" y2="18"></line></svg>'
ICON_HEART = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 0 0-7.8 7.8l1 1L12 21l7.8-7.8 1-1a5.5 5.5 0 0 0 0-7.8z"></path></svg>'
ICON_UP = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="19" x2="12" y2="5"></line><polyline points="6 11 12 5 18 11"></polyline></svg>'


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
.sticky-nav {
position: sticky;
top: 0;
background: var(--bg);
z-index: 10;
padding-top: 2px;
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
display: flex;
align-items: center;
gap: 5px;
position: relative;
font-size: 14px;
font-weight: 600;
padding: 9px 12px;
color: var(--text-secondary);
white-space: nowrap;
}
.tab-icon {
width: 15px;
height: 15px;
flex-shrink: 0;
}
.tab.active {
color: var(--text);
}
.tab.active::after {
content: "";
position: absolute;
bottom: -1px;
left: 8px;
right: 8px;
height: 2px;
background: var(--text);
border-radius: 2px 2px 0 0;
}
.segmented {
display: flex;
background: var(--border);
border-radius: 10px;
padding: 3px;
margin: 10px 16px 12px;
max-width: 640px;
margin-left: auto;
margin-right: auto;
gap: 2px;
}
.segmented-option {
flex: 1;
text-align: center;
font-size: 13px;
font-weight: 600;
padding: 7px 0;
border-radius: 8px;
color: var(--text-secondary);
}
.segmented-option.active {
background: var(--card);
color: var(--text);
box-shadow: 0 1px 2px rgba(0,0,0,0.08);
}
.filter-toggle {
font-size: 12px;
color: var(--text-secondary);
padding: 0 16px 12px;
max-width: 640px;
margin: 0 auto;
}
.filter-toggle a {
text-decoration: underline;
font-weight: 600;
color: var(--text-secondary);
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
.rail-section {
margin-bottom: 22px;
}
.rail-header {
display: flex;
justify-content: space-between;
align-items: baseline;
margin-bottom: 10px;
}
.rail-title {
font-size: 15px;
font-weight: 700;
}
.rail-see-all {
font-size: 13px;
color: var(--text-secondary);
text-decoration: underline;
}
.rail-scroll {
display: flex;
gap: 10px;
overflow-x: auto;
margin: 0 -16px;
padding: 0 16px 6px;
scroll-snap-type: x proximity;
-webkit-overflow-scrolling: touch;
}
.rail-card {
flex: 0 0 auto;
width: 158px;
scroll-snap-align: start;
display: block;
background: var(--card);
border: 1px solid var(--border);
border-radius: 12px;
overflow: hidden;
}
.rail-card-image {
display: block;
width: 100%;
height: 88px;
object-fit: cover;
background: var(--border);
}
.rail-card-body {
padding: 9px 10px 11px;
}
.rail-card-title {
font-size: 12.5px;
font-weight: 600;
line-height: 1.35;
margin: 0 0 5px;
display: -webkit-box;
-webkit-line-clamp: 3;
-webkit-box-orient: vertical;
overflow: hidden;
}
.rail-card-meta {
font-size: 11px;
color: var(--text-secondary);
}
.rail-score-chip {
font-size: 11px;
font-weight: 700;
padding: 2px 8px;
border-radius: 20px;
display: inline-block;
margin-bottom: 6px;
}
.card {
position: relative;
display: block;
background: var(--card);
border: 1px solid var(--border);
border-radius: 14px;
padding: 16px;
margin-bottom: 14px;
transition: opacity 0.2s ease, transform 0.2s ease, max-height 0.32s ease, margin-bottom 0.32s ease, padding 0.32s ease;
overflow: hidden;
}
.card.read {
opacity: 0.5;
}
.card.pending-remove {
opacity: 0.35;
}
.card-image {
display: block;
width: calc(100% + 32px);
height: 160px;
object-fit: cover;
margin: -16px -16px 12px -16px;
background: var(--border);
}
.card-link {
display: block;
}
.card-link.with-buttons {
padding-top: 54px;
}
.discard-btn, .like-btn {
position: absolute;
top: 8px;
width: 44px;
height: 44px;
border-radius: 50%;
border: none;
background: rgba(0,0,0,0.4);
backdrop-filter: blur(6px);
-webkit-backdrop-filter: blur(6px);
color: #fff;
display: flex;
align-items: center;
justify-content: center;
cursor: pointer;
z-index: 2;
padding: 0;
box-shadow: 0 1px 4px rgba(0,0,0,0.25);
transition: transform 0.15s ease;
}
.discard-btn { left: 8px; }
.like-btn { right: 8px; }
.discard-btn:active, .like-btn:active {
transform: scale(0.88);
}
.discard-btn svg { width: 17px; height: 17px; }
.like-btn svg { width: 20px; height: 20px; }
.like-btn.liked { color: var(--niche); }
.like-btn.liked svg { fill: currentColor; }
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
.hero-image {
display: block;
width: 100%;
max-height: 280px;
object-fit: cover;
border-radius: 14px;
margin: 4px 0 18px;
background: var(--border);
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
.back-to-top {
position: fixed;
bottom: 24px;
right: 20px;
width: 46px;
height: 46px;
border-radius: 50%;
border: none;
background: var(--text);
color: var(--bg);
display: flex;
align-items: center;
justify-content: center;
cursor: pointer;
box-shadow: 0 3px 10px rgba(0,0,0,0.25);
opacity: 0;
pointer-events: none;
transform: translateY(12px);
transition: opacity 0.2s ease, transform 0.2s ease;
z-index: 15;
}
.back-to-top.visible {
opacity: 1;
pointer-events: auto;
transform: translateY(0);
}
.back-to-top svg { width: 20px; height: 20px; }
.toast {
position: fixed;
bottom: 24px;
left: 50%;
transform: translateX(-50%) translateY(16px);
background: var(--text);
color: var(--bg);
padding: 13px 16px;
border-radius: 12px;
font-size: 14px;
display: flex;
align-items: center;
gap: 18px;
opacity: 0;
pointer-events: none;
transition: opacity 0.2s ease, transform 0.2s ease;
z-index: 20;
box-shadow: 0 4px 16px rgba(0,0,0,0.25);
white-space: nowrap;
}
.toast.visible {
opacity: 1;
pointer-events: auto;
transform: translateX(-50%) translateY(0);
}
.toast-undo {
background: none;
border: none;
color: var(--bg);
font-weight: 700;
font-size: 14px;
cursor: pointer;
text-decoration: underline;
padding: 0;
}
"""

CARD_INTERACTIONS_JS = """
<script>
(function () {
  var toastEl = null;
  var toastTimeout = null;

  function showToast(message, onUndo) {
    if (!toastEl) {
      toastEl = document.createElement("div");
      toastEl.className = "toast";
      document.body.appendChild(toastEl);
    }
    toastEl.innerHTML = "";
    var span = document.createElement("span");
    span.textContent = message;
    var btn = document.createElement("button");
    btn.className = "toast-undo";
    btn.textContent = "Undo";
    btn.onclick = function () {
      onUndo();
      toastEl.classList.remove("visible");
    };
    toastEl.appendChild(span);
    toastEl.appendChild(btn);
    toastEl.classList.add("visible");
    clearTimeout(toastTimeout);
    toastTimeout = setTimeout(function () {
      toastEl.classList.remove("visible");
    }, """ + str(UNDO_WINDOW_MS) + """);
  }

  function collapseAndRemove(card) {
    // Rather than yanking the card's full height out of the layout in
    // one instant (which snaps everything below it upward with no
    // warning - jarring if the user has scrolled past it already), lock
    // in its current height explicitly, then animate height/margin/
    // padding down to zero alongside the fade, so any layout shift
    // happens smoothly and visibly rather than as a sudden jump.
    var height = card.offsetHeight;
    card.style.maxHeight = height + "px";
    card.offsetHeight; // force a reflow so the browser registers the starting height
    card.style.opacity = "0";
    card.style.transform = "scale(0.96)";
    card.style.maxHeight = "0px";
    card.style.marginBottom = "0px";
    card.style.paddingTop = "0px";
    card.style.paddingBottom = "0px";
    setTimeout(function () { card.remove(); }, 340);
  }

  document.addEventListener("click", function (e) {
    var discardBtn = e.target.closest(".discard-btn");
    if (discardBtn) {
      e.preventDefault();
      e.stopPropagation();
      var url = discardBtn.getAttribute("data-action");
      var card = discardBtn.closest(".card");
      var storyId = discardBtn.getAttribute("data-id");
      fetch(url, { method: "POST" }).then(function (r) {
        if (!r.ok) return;
        card.classList.add("pending-remove");
        var removeTimeout = setTimeout(function () {
          collapseAndRemove(card);
        }, """ + str(UNDO_WINDOW_MS) + """);
        showToast("Story discarded", function () {
          clearTimeout(removeTimeout);
          card.classList.remove("pending-remove");
          fetch("/story/" + storyId + "/undiscard", { method: "POST" });
        });
      });
      return;
    }

    var likeBtn = e.target.closest(".like-btn");
    if (likeBtn) {
      e.preventDefault();
      e.stopPropagation();
      var likeUrl = likeBtn.getAttribute("data-action");
      fetch(likeUrl, { method: "POST" })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.liked) {
            likeBtn.classList.add("liked");
          } else {
            likeBtn.classList.remove("liked");
          }
        });
      return;
    }
  });
})();
</script>
"""

BACK_TO_TOP_HTML = """
<button class="back-to-top" id="backToTop" aria-label="Back to top">""" + ICON_UP + """</button>
<script>
(function () {
  var btn = document.getElementById("backToTop");
  if (!btn) return;
  window.addEventListener("scroll", function () {
    if (window.scrollY > 500) {
      btn.classList.add("visible");
    } else {
      btn.classList.remove("visible");
    }
  });
  btn.addEventListener("click", function () {
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
})();
</script>
"""

TABS_HTML = """
<div class="tabs">
<a href="/" class="tab {{ 'active' if active_tab == 'main' else '' }}">""" + ICON_MAIN + """ Main</a>
<a href="/reviews" class="tab {{ 'active' if active_tab == 'reviews' else '' }}">""" + ICON_REVIEWS + """ Reviews</a>
<a href="/video" class="tab {{ 'active' if active_tab == 'video' else '' }}">""" + ICON_VIDEO + """ Video</a>
<a href="/themes" class="tab {{ 'active' if active_tab == 'themes' else '' }}">""" + ICON_THEMES + """ Themes</a>
</div>
"""

RAILS_HTML = """
{% if show_rails %}
{% if trending %}
<div class="rail-section">
<div class="rail-header"><span class="rail-title">Trending</span></div>
<div class="rail-scroll">
{% for item in trending %}
<a class="rail-card" href="/story/{{ item.id }}">
{% if item.image_url %}<img class="rail-card-image" src="{{ item.image_url }}" loading="lazy" alt="">{% endif %}
<div class="rail-card-body">
<p class="rail-card-title">{{ item.title }}</p>
<p class="rail-card-meta">{{ item.n }} source{{ 's' if item.n != 1 else '' }} &middot; {{ item.time_ago }}</p>
</div>
</a>
{% endfor %}
</div>
</div>
{% endif %}
{% if review_rail %}
<div class="rail-section">
<div class="rail-header"><span class="rail-title">Latest reviews</span><a class="rail-see-all" href="/reviews">See all &rarr;</a></div>
<div class="rail-scroll">
{% for item in review_rail %}
<a class="rail-card" href="/story/{{ item.id }}">
{% if item.image_url %}<img class="rail-card-image" src="{{ item.image_url }}" loading="lazy" alt="">{% endif %}
<div class="rail-card-body">
{% if item.opencritic_score and item.opencritic_score > 0 %}
<span class="rail-score-chip" style="background:var(--{{ (item.opencritic_tier or 'strong')|lower }}-bg); color:var(--{{ (item.opencritic_tier or 'strong')|lower }}-fg);">{{ item.opencritic_score|round|int }}</span><br>
{% endif %}
<p class="rail-card-title">{{ item.title }}</p>
<p class="rail-card-meta">{{ item.time_ago }}</p>
</div>
</a>
{% endfor %}
</div>
</div>
{% endif %}
{% if video_rail %}
<div class="rail-section">
<div class="rail-header"><span class="rail-title">New video</span><a class="rail-see-all" href="/video">See all &rarr;</a></div>
<div class="rail-scroll">
{% for item in video_rail %}
<a class="rail-card" href="/story/{{ item.id }}">
{% if item.image_url %}<img class="rail-card-image" src="{{ item.image_url }}" loading="lazy" alt="">{% endif %}
<div class="rail-card-body">
<p class="rail-card-title">{{ item.title }}</p>
<p class="rail-card-meta">{{ item.time_ago }}</p>
</div>
</a>
{% endfor %}
</div>
</div>
{% endif %}
{% endif %}
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
<div class="sticky-nav">
""" + TABS_HTML + """
<div class="segmented">
<a href="{{ recent_url }}" class="segmented-option {{ 'active' if view == 'recent' else '' }}">Most recent</a>
<a href="{{ covered_url }}" class="segmented-option {{ 'active' if view == 'covered' else '' }}">Most covered</a>
</div>
</div>
{% if show_filter_toggle %}
<div class="filter-toggle">
{% if show_all %}
Showing every story &middot; <a href="{{ toggle_url }}">Show 2+ sources only</a>
{% else %}
Showing stories with 2+ sources{% if hidden_count %} &middot; {{ hidden_count }} single-source hidden{% endif %} &middot; <a href="{{ toggle_url }}">Show all</a>
{% endif %}
</div>
{% endif %}
<div class="legend">
<span><span class="dot" style="background:var(--trust)"></span>Trusted</span>
<span><span class="dot" style="background:var(--niche)"></span>Niche</span>
<span><span class="dot" style="background:var(--comm)"></span>Community</span>
</div>
<main>
""" + RAILS_HTML + """
{% for story in stories %}
<div class="card {{ 'read' if story.is_read else '' }}">
<button class="discard-btn" data-action="/story/{{ story.id }}/discard" data-id="{{ story.id }}" aria-label="Discard">""" + ICON_X + """</button>
<button class="like-btn {{ 'liked' if story.is_liked else '' }}" data-action="/story/{{ story.id }}/like" aria-label="Like">""" + ICON_HEART + """</button>
<a class="card-link with-buttons" href="/story/{{ story.id }}">
{% if story.image_url %}
<img class="card-image" src="{{ story.image_url }}" loading="lazy" alt="">
{% endif %}
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
""" + CARD_INTERACTIONS_JS + BACK_TO_TOP_HTML + """
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
<div class="sticky-nav">
<div class="tabs">
<a href="/" class="tab">""" + ICON_MAIN + """ Main</a>
<a href="/reviews" class="tab">""" + ICON_REVIEWS + """ Reviews</a>
<a href="/video" class="tab">""" + ICON_VIDEO + """ Video</a>
<a href="/themes" class="tab active">""" + ICON_THEMES + """ Themes</a>
</div>
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
""" + BACK_TO_TOP_HTML + """
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
{% if hero_image %}
<img class="hero-image" src="{{ hero_image }}" loading="lazy" alt="">
{% endif %}
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
""" + BACK_TO_TOP_HTML + """
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


def valid_show_all():
    return request.args.get("all") == "1"


def build_url(base_path, view="recent", show_all=False):
    params = []
    if view == "covered":
        params.append("view=covered")
    if show_all:
        params.append("all=1")
    if not params:
        return base_path
    return base_path + "?" + "&".join(params)


def fetch_rail(kind):
    """A short, glanceable preview strip for the Main page - inspired by
    Ground News's homepage rails. Deliberately not a replacement for the
    full Reviews/Video tabs: short (RAIL_LIMIT items), no discard/like
    interactions, just a teaser with a "See all" link through to the
    real thing. "trending" spans all content types, sorted purely by
    how many independent sources are on a story - the same signal
    "Most covered" already sorts by, just surfaced automatically instead
    of requiring the user to go choose that view.

    Only called when the Main page is in its default "recent" view (see
    index() below) - shown alongside a coverage-sorted list, the rails
    never changed, which made switching to "Most covered" look like it
    did nothing since the most visually prominent content on screen
    stayed identical. Hiding rails specifically in "Most covered" makes
    that switch immediately, visibly obvious instead.
    """
    if kind == "reviews":
        tab_where = "AND s.is_review = TRUE"
        order_by = "latest DESC"
    elif kind == "video":
        tab_where = "AND s.is_video = TRUE"
        order_by = "latest DESC"
    else:
        tab_where = ""
        order_by = "n DESC, latest DESC"

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        f"""
        SELECT s.id, s.title, s.opencritic_score, s.opencritic_tier,
            count(*) AS n,
            max(COALESCE(a.published_at, a.fetched_at)) AS latest
        FROM stories s
        JOIN articles a ON a.story_id = s.id
        WHERE 1=1 {tab_where}
        AND s.dismissed_at IS NULL
        GROUP BY s.id, s.title, s.opencritic_score, s.opencritic_tier
        HAVING max(COALESCE(a.published_at, a.fetched_at)) > now() - interval '{FEED_WINDOW_DAYS} days'
        ORDER BY {order_by}
        LIMIT {RAIL_LIMIT}
        """
    )
    rows = cur.fetchall()

    items = []
    now = datetime.datetime.now(datetime.timezone.utc)
    for row in rows:
        cur.execute(
            f"""
            SELECT image_url FROM articles
            WHERE story_id = %s AND image_url IS NOT NULL
            ORDER BY {TIER_RANK_SQL}
            LIMIT 1
            """,
            (row["id"],),
        )
        image_row = cur.fetchone()
        delta = (now - row["latest"]).total_seconds() if row["latest"] else 0
        items.append({
            "id": row["id"],
            "title": row["title"],
            "n": row["n"],
            "image_url": image_row["image_url"] if image_row else None,
            "time_ago": humanize(delta),
            "opencritic_score": row["opencritic_score"],
            "opencritic_tier": row["opencritic_tier"],
        })

    cur.close()
    conn.close()
    return items


def fetch_stories(tab, view, show_all=False):
    if tab == "reviews":
        tab_where = "AND s.is_review = TRUE"
    elif tab == "video":
        tab_where = "AND s.is_video = TRUE"
    else:
        tab_where = "AND s.is_review = FALSE AND s.is_video = FALSE"

    order_by = "n DESC, latest DESC" if view == "covered" else "latest DESC"

    # Coverage filter is Main-tab only - see MIN_SOURCES_DEFAULT above for
    # the reasoning. Reviews/Video are never filtered regardless of the
    # show_all flag's value.
    coverage_having = ""
    if tab == "main" and not show_all:
        coverage_having = f"AND count(*) >= {MIN_SOURCES_DEFAULT}"

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
            s.liked_at,
            count(*) AS n,
            count(*) FILTER (WHERE a.source_tier = 'trusted') AS trusted_n,
            count(*) FILTER (WHERE a.source_tier = 'niche') AS niche_n,
            count(*) FILTER (WHERE a.source_tier = 'community') AS community_n,
            max(COALESCE(a.published_at, a.fetched_at)) AS latest
        FROM stories s
        JOIN articles a ON a.story_id = s.id
        WHERE 1=1 {tab_where}
        AND s.dismissed_at IS NULL
        GROUP BY s.id, s.title, s.opencritic_score, s.opencritic_tier, s.read_at, s.liked_at
        HAVING max(COALESCE(a.published_at, a.fetched_at)) > now() - interval '{FEED_WINDOW_DAYS} days'
        {coverage_having}
        ORDER BY (s.read_at IS NOT NULL), {order_by}
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

        cur.execute(
            f"""
            SELECT image_url FROM articles
            WHERE story_id = %s AND image_url IS NOT NULL
            ORDER BY {TIER_RANK_SQL}
            LIMIT 1
            """,
            (row["id"],),
        )
        image_row = cur.fetchone()
        image_url = image_row["image_url"] if image_row else None

        delta = (now - row["latest"]).total_seconds() if row["latest"] else 0
        stories.append({
            "id": row["id"],
            "title": row["title"],
            "n": row["n"],
            "trusted_n": row["trusted_n"],
            "niche_n": row["niche_n"],
            "community_n": row["community_n"],
            "sources": sources,
            "image_url": image_url,
            "time_ago": humanize(delta),
            "opencritic_score": row["opencritic_score"],
            "opencritic_tier": row["opencritic_tier"],
            "is_read": row["read_at"] is not None,
            "is_liked": row["liked_at"] is not None,
        })

    hidden_count = 0
    if tab == "main" and not show_all:
        cur.execute(
            f"""
            SELECT count(*) AS n FROM (
                SELECT s.id
                FROM stories s
                JOIN articles a ON a.story_id = s.id
                WHERE s.is_review = FALSE AND s.is_video = FALSE AND s.dismissed_at IS NULL
                GROUP BY s.id
                HAVING max(COALESCE(a.published_at, a.fetched_at)) > now() - interval '{FEED_WINDOW_DAYS} days'
                AND count(*) < {MIN_SOURCES_DEFAULT}
            ) hidden
            """
        )
        hidden_count = cur.fetchone()["n"]

    cur.execute("SELECT count(DISTINCT source) FROM articles")
    source_count = cur.fetchone()["count"]

    cur.close()
    conn.close()
    return stories, source_count, hidden_count


@app.route("/")
def index():
    view = valid_view()
    show_all = valid_show_all()
    stories, source_count, hidden_count = fetch_stories(tab="main", view=view, show_all=show_all)

    show_rails = (view == "recent")
    if show_rails:
        trending = fetch_rail("trending")
        review_rail = fetch_rail("reviews")
        video_rail = fetch_rail("video")
    else:
        trending = None
        review_rail = None
        video_rail = None

    return render_template_string(
        FEED_TEMPLATE, stories=stories, source_count=source_count,
        active_tab="main", view=view, show_all=show_all, hidden_count=hidden_count,
        recent_url=build_url("/", view="recent", show_all=show_all),
        covered_url=build_url("/", view="covered", show_all=show_all),
        toggle_url=build_url("/", view=view, show_all=not show_all),
        show_filter_toggle=True,
        show_rails=show_rails, trending=trending, review_rail=review_rail, video_rail=video_rail,
    )


@app.route("/reviews")
def reviews():
    view = valid_view()
    stories, source_count, _ = fetch_stories(tab="reviews", view=view)
    return render_template_string(
        FEED_TEMPLATE, stories=stories, source_count=source_count,
        active_tab="reviews", view=view, show_all=True, hidden_count=0,
        recent_url=build_url("/reviews", view="recent"),
        covered_url=build_url("/reviews", view="covered"),
        toggle_url=None,
        show_filter_toggle=False,
        show_rails=False, trending=None, review_rail=None, video_rail=None,
    )


@app.route("/video")
def video():
    view = valid_view()
    stories, source_count, _ = fetch_stories(tab="video", view=view)
    return render_template_string(
        FEED_TEMPLATE, stories=stories, source_count=source_count,
        active_tab="video", view=view, show_all=True, hidden_count=0,
        recent_url=build_url("/video", view="recent"),
        covered_url=build_url("/video", view="covered"),
        toggle_url=None,
        show_filter_toggle=False,
        show_rails=False, trending=None, review_rail=None, video_rail=None,
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


@app.route("/story/<int:story_id>/undiscard", methods=["POST"])
def undiscard_story(story_id):
    # Backs the Undo toast shown right after a discard - only meaningful
    # within the short client-side grace window before the card actually
    # leaves the DOM (see UNDO_WINDOW_MS and CARD_INTERACTIONS_JS).
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("UPDATE stories SET dismissed_at = NULL WHERE id = %s", (story_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify(ok=True)


@app.route("/story/<int:story_id>/like", methods=["POST"])
def like_story(story_id):
    # A toggle, not a one-way action - tapping again un-likes. Kept as its
    # own explicit signal (liked_at) separate from read_at, since "opened
    # this" and "actually liked this" are different strengths of signal
    # for the Themes page's future interest-profile idea.
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT liked_at FROM stories WHERE id = %s", (story_id,))
    row = cur.fetchone()
    if row is None:
        cur.close()
        conn.close()
        return jsonify(ok=False), 404
    liked = row["liked_at"] is None
    cur.execute(
        "UPDATE stories SET liked_at = %s WHERE id = %s",
        (datetime.datetime.now(datetime.timezone.utc) if liked else None, story_id),
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify(ok=True, liked=liked)


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
        SELECT source, source_tier, title, url, summary, image_url,
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

    hero_image = None
    for a in sorted(articles, key=lambda a: tier_rank.get(a["source_tier"], 3)):
        if a["image_url"]:
            hero_image = a["image_url"]
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
        hero_image=hero_image,
        n=len(articles),
        trusted_n=trusted_n,
        niche_n=niche_n,
        community_n=community_n,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
