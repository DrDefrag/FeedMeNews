import os
import re
import datetime
import psycopg2
import psycopg2.extras
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)
DB_URL = os.environ["DATABASE_URL"]

FEED_WINDOW_DAYS = 2
UNDO_WINDOW_MS = 5000
MIN_SOURCES_DEFAULT = 2
RAIL_LIMIT = 8
MIN_VOTES_FOR_SENTIMENT = 5

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

TIER_RANK_SQL = "CASE source_tier WHEN 'trusted' THEN 0 WHEN 'niche' THEN 1 ELSE 2 END"

SOURCE_OWNERSHIP = {
    "IGN": "Ziff Davis",
    "Eurogamer": "Ziff Davis",
    "Rock Paper Shotgun": "Ziff Davis",
    "VG247": "Ziff Davis",
    "GamesIndustry.biz": "Ziff Davis",
    "PC Gamer": "Future plc",
    "GamesRadar": "Future plc",
    "Polygon": "Valnet",
    "TheGamer": "Valnet",
    "NintendoLife": "Hookshot Media",
    "Push Square": "Hookshot Media",
    "Pure Xbox": "Hookshot Media",
    "GameSpot": "Fandom, Inc.",
    "Kotaku": "Keleops",
    "PCGamesN": "NetworkN",
}

TOPICS = {
    "playstation": {
        "label": "PlayStation",
        "sources": ["Push Square", "r/PS5"],
        "keywords": "playstation | ps5 | ps4",
    },
    "xbox": {
        "label": "Xbox",
        "sources": ["Pure Xbox"],
        "keywords": "xbox",
    },
    "switch": {
        "label": "Nintendo Switch",
        "sources": ["NintendoLife", "r/NintendoSwitch"],
        "keywords": "nintendo | switch",
    },
    "pc": {
        "label": "PC",
        "sources": ["PC Gamer", "PCGamesN", "r/pcgaming"],
        "keywords": "steam",
    },
    "indie": {
        "label": "Indie",
        "sources": ["The Indie Informer", "Indie Game Reviewer"],
        "keywords": None,
    },
    "industry": {
        "label": "Industry",
        "sources": ["Game Developer", "GamesIndustry.biz"],
        "keywords": None,
    },
}

ICON_MAIN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"></rect><line x1="7" y1="9" x2="17" y2="9"></line><line x1="7" y1="13" x2="17" y2="13"></line><line x1="7" y1="17" x2="13" y2="17"></line></svg>'
ICON_REVIEWS = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15 9 22 9.5 17 14.5 18.5 22 12 18 5.5 22 7 14.5 2 9.5 9 9"></polygon></svg>'
ICON_VIDEO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"></circle><polygon points="10 8 16 12 10 16" fill="currentColor" stroke="none"></polygon></svg>'
ICON_CALENDAR = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>'
ICON_THEMES = '<svg viewBox="0 0 24 24" fill="currentColor" stroke="none"><path d="M12 2l1.8 6.2L20 10l-6.2 1.8L12 18l-1.8-6.2L4 10l6.2-1.8z"></path></svg>'
ICON_X = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="6" y1="6" x2="18" y2="18"></line><line x1="18" y1="6" x2="6" y2="18"></line></svg>'
ICON_UP = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="19" x2="12" y2="5"></line><polyline points="6 11 12 5 18 11"></polyline></svg>'
ICON_SEARCH = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>'
ICON_REFRESH = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="1 4 1 10 7 10"></polyline><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"></path></svg>'
ICON_THUMBS_UP = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"></path></svg>'
ICON_THUMBS_DOWN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3" transform="rotate(180 12 12)"></path></svg>'

LOGO_ICON = """<svg viewBox="0 0 200 220" xmlns="http://www.w3.org/2000/svg">
<path d="M 15 168 A 85 85 0 0 1 185 168" fill="none" stroke="#1a1a18" stroke-width="13" stroke-linecap="round"/>
<path d="M 35 168 A 65 65 0 0 1 165 168" fill="none" stroke="#1a1a18" stroke-width="13" stroke-linecap="round"/>
<path d="M 55 168 A 45 45 0 0 1 145 168" fill="none" stroke="#1a1a18" stroke-width="13" stroke-linecap="round"/>
<rect x="65" y="168" width="70" height="25" fill="#1a1a18"/>
<rect x="15" y="193" width="170" height="23" fill="#1a1a18"/>
<path d="M 100 122 C 112 138, 120 152, 116 164 C 113 174, 104 180, 100 180 C 96 180, 87 174, 84 164 C 80 152, 88 138, 100 122 Z" fill="#D85A30"/>
</svg>"""

FAVICON_LINK = '<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,PHN2ZyB2aWV3Qm94PSIwIDAgMjAwIDIyMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KICA8cGF0aCBkPSJNIDE1IDE2OCBBIDg1IDg1IDAgMCAxIDE4NSAxNjgiIGZpbGw9Im5vbmUiIHN0cm9rZT0iIzFhMWExOCIgc3Ryb2tlLXdpZHRoPSIxMyIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIi8+CiAgPHBhdGggZD0iTSAzNSAxNjggQSA2NSA2NSAwIDAgMSAxNjUgMTY4IiBmaWxsPSJub25lIiBzdHJva2U9IiMxYTFhMTgiIHN0cm9rZS13aWR0aD0iMTMiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPgogIDxwYXRoIGQ9Ik0gNTUgMTY4IEEgNDUgNDUgMCAwIDEgMTQ1IDE2OCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjMWExYTE4IiBzdHJva2Utd2lkdGg9IjEzIiBzdHJva2UtbGluZWNhcD0icm91bmQiLz4KICA8cmVjdCB4PSI2NSIgeT0iMTY4IiB3aWR0aD0iNzAiIGhlaWdodD0iMjUiIGZpbGw9IiMxYTFhMTgiLz4KICA8cmVjdCB4PSIxNSIgeT0iMTkzIiB3aWR0aD0iMTcwIiBoZWlnaHQ9IjIzIiBmaWxsPSIjMWExYTE4Ii8+CiAgPHBhdGggZD0iTSAxMDAgMTIyCiAgICAgICAgICAgQyAxMTIgMTM4LCAxMjAgMTUyLCAxMTYgMTY0CiAgICAgICAgICAgQyAxMTMgMTc0LCAxMDQgMTgwLCAxMDAgMTgwCiAgICAgICAgICAgQyA5NiAxODAsIDg3IDE3NCwgODQgMTY0CiAgICAgICAgICAgQyA4MCAxNTIsIDg4IDEzOCwgMTAwIDEyMgogICAgICAgICAgIFoiCiAgICAgICAgZmlsbD0iI0Q4NUEzMCIvPgo8L3N2Zz4K">'


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
display: flex;
justify-content: space-between;
align-items: flex-start;
gap: 12px;
}
.header-brand {
display: flex;
align-items: center;
gap: 10px;
}
.logo-icon {
width: 32px;
height: 35px;
flex-shrink: 0;
}
.logo-icon svg {
width: 100%;
height: 100%;
display: block;
}
header h1 {
font-size: 21px;
font-weight: 800;
letter-spacing: -0.02em;
margin: 0 0 2px;
}
.tagline {
font-size: 12px;
font-weight: 700;
font-style: italic;
color: var(--comm);
margin: 0 0 3px;
}
header p {
font-size: 13px;
color: var(--text-secondary);
margin: 0;
}
.search-icon-btn {
width: 36px;
height: 36px;
border-radius: 50%;
background: var(--border);
color: var(--text-secondary);
display: flex;
align-items: center;
justify-content: center;
flex-shrink: 0;
margin-top: 2px;
}
.search-icon-btn svg { width: 17px; height: 17px; }
.search-form {
padding: 8px 16px 12px;
max-width: 640px;
margin: 0 auto;
}
.search-input {
width: 100%;
padding: 11px 14px;
border-radius: 10px;
border: 1px solid var(--border);
background: var(--card);
color: var(--text);
font-size: 15px;
}
.search-input:focus {
outline: none;
border-color: var(--text-secondary);
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
.topic-heading {
font-size: 18px;
font-weight: 700;
padding: 4px 0 14px;
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
.topic-tile {
flex: 0 0 auto;
scroll-snap-align: start;
display: flex;
align-items: center;
padding: 13px 20px;
background: var(--card);
border: 1px solid var(--border);
border-radius: 12px;
font-size: 14px;
font-weight: 600;
color: var(--text);
white-space: nowrap;
}
.topic-tile.active {
background: var(--text);
color: var(--bg);
border-color: var(--text);
}
.card {
position: relative;
display: block;
background: var(--card);
border: 1px solid var(--border);
border-radius: 14px;
padding: 16px;
margin-bottom: 14px;
transition: opacity 0.15s ease, transform 0.15s ease, max-height 0.22s ease, margin-bottom 0.22s ease, padding 0.22s ease;
overflow: hidden;
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
.discard-btn {
position: absolute;
top: 8px;
left: 8px;
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
.discard-btn:active { transform: scale(0.88); }
.discard-btn svg { width: 17px; height: 17px; }
.vote-controls {
position: absolute;
top: 8px;
right: 8px;
display: flex;
flex-direction: column;
gap: 6px;
z-index: 2;
}
.vote-controls.inline {
position: static;
flex-direction: row;
gap: 10px;
}
.vote-btn {
width: 36px;
height: 36px;
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
padding: 0;
box-shadow: 0 1px 4px rgba(0,0,0,0.25);
transition: transform 0.15s ease;
}
.vote-btn:active { transform: scale(0.88); }
.vote-btn svg { width: 16px; height: 16px; }
.vote-btn.voted-up { background: rgba(0,0,0,0.55); color: var(--strong-fg); }
.vote-btn.voted-down { background: rgba(0,0,0,0.55); color: var(--weak-fg); }
.vote-btn:disabled { cursor: default; }
.vote-controls.inline .vote-btn {
width: 40px;
height: 40px;
background: var(--border);
color: var(--text-secondary);
backdrop-filter: none;
-webkit-backdrop-filter: none;
box-shadow: none;
}
.vote-controls.inline .vote-btn.voted-up { background: var(--strong-bg); color: var(--strong-fg); }
.vote-controls.inline .vote-btn.voted-down { background: var(--weak-bg); color: var(--weak-fg); }
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
.blindspot-chip {
font-size: 12px;
font-weight: 700;
padding: 4px 10px;
border-radius: 20px;
display: inline-block;
margin-bottom: 10px;
background: var(--fair-bg);
color: var(--fair-fg);
}
.ownership-note {
font-size: 11.5px;
color: var(--text-secondary);
font-style: italic;
margin: 8px 0 0;
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
.score-block, .sentiment-block {
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
.sentiment-summary {
font-size: 14px;
color: var(--text-secondary);
margin: 0;
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
.timeline-badge {
font-size: 11px;
font-weight: 600;
color: var(--text-secondary);
margin-left: 6px;
}
.timeline-badge.timeline-first {
color: var(--niche);
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
.pull-indicator {
position: fixed;
top: -50px;
left: 50%;
transform: translateX(-50%) rotate(0deg);
width: 38px;
height: 38px;
border-radius: 50%;
background: var(--text);
color: var(--bg);
display: flex;
align-items: center;
justify-content: center;
z-index: 25;
opacity: 0;
box-shadow: 0 2px 8px rgba(0,0,0,0.25);
}
.pull-indicator svg { width: 18px; height: 18px; }
.calendar-group {
margin-bottom: 20px;
}
.calendar-entry {
display: flex;
gap: 12px;
background: var(--card);
border: 1px solid var(--border);
border-radius: 14px;
padding: 12px;
margin-bottom: 10px;
}
.calendar-cover {
width: 56px;
height: 74px;
border-radius: 8px;
object-fit: cover;
background: var(--border);
flex-shrink: 0;
}
.calendar-cover-placeholder {
width: 56px;
height: 74px;
border-radius: 8px;
background: var(--border);
flex-shrink: 0;
}
.calendar-entry-body h3 {
font-size: 15px;
font-weight: 600;
margin: 0 0 4px;
line-height: 1.35;
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

  function collapseCard(card) {
    var height = card.offsetHeight;
    card.style.maxHeight = height + "px";
    card.offsetHeight;
    card.style.opacity = "0";
    card.style.transform = "scale(0.96)";
    card.style.maxHeight = "0px";
    card.style.marginBottom = "0px";
    card.style.paddingTop = "0px";
    card.style.paddingBottom = "0px";
    card.style.pointerEvents = "none";
  }

  function restoreCard(card) {
    card.style.pointerEvents = "";
    card.style.maxHeight = "";
    card.style.opacity = "";
    card.style.transform = "";
    card.style.marginBottom = "";
    card.style.paddingTop = "";
    card.style.paddingBottom = "";
  }

  document.addEventListener("click", function (e) {
    var discardBtn = e.target.closest(".discard-btn");
    if (!discardBtn) return;
    e.preventDefault();
    e.stopPropagation();
    var url = discardBtn.getAttribute("data-action");
    var card = discardBtn.closest(".card");
    var storyId = discardBtn.getAttribute("data-id");
    fetch(url, { method: "POST" }).then(function (r) {
      if (!r.ok) return;
      collapseCard(card);
      var removeTimeout = setTimeout(function () {
        card.remove();
      }, """ + str(UNDO_WINDOW_MS) + """);
      showToast("Story discarded", function () {
        clearTimeout(removeTimeout);
        restoreCard(card);
        fetch("/story/" + storyId + "/undiscard", { method: "POST" });
      });
    });
  });
})();
</script>
"""

VOTE_INTERACTIONS_JS = """
<script>
(function () {
  function getVoted() {
    try {
      return JSON.parse(localStorage.getItem("votedStories") || "{}");
    } catch (e) {
      return {};
    }
  }

  function setVoted(storyId, direction) {
    var voted = getVoted();
    voted[storyId] = direction;
    try {
      localStorage.setItem("votedStories", JSON.stringify(voted));
    } catch (e) {}
  }

  function disableGroup(group, direction) {
    var buttons = group.querySelectorAll(".vote-btn");
    buttons.forEach(function (b) {
      b.disabled = true;
      if (b.getAttribute("data-direction") === direction) {
        b.classList.add(direction === "up" ? "voted-up" : "voted-down");
      }
    });
  }

  function applyVotedState() {
    var voted = getVoted();
    document.querySelectorAll(".vote-controls[data-story-id]").forEach(function (group) {
      var storyId = group.getAttribute("data-story-id");
      var direction = voted[storyId];
      if (direction) disableGroup(group, direction);
    });
  }

  applyVotedState();

  document.addEventListener("click", function (e) {
    var btn = e.target.closest(".vote-btn");
    if (!btn || btn.disabled) return;
    e.preventDefault();
    e.stopPropagation();
    var group = btn.closest(".vote-controls");
    var storyId = group.getAttribute("data-story-id");
    var direction = btn.getAttribute("data-direction");
    if (getVoted()[storyId]) return;

    fetch("/story/" + storyId + "/vote/" + direction, { method: "POST" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.ok) return;
        setVoted(storyId, direction);
        disableGroup(group, direction);
        var summaryEl = group.parentElement.querySelector(".sentiment-summary");
        if (summaryEl) {
          var total = data.like_count + data.dislike_count;
          if (total >= """ + str(MIN_VOTES_FOR_SENTIMENT) + """) {
            var pct = Math.round((data.like_count / total) * 100);
            summaryEl.textContent = pct + "% liked this (" + total + " vote" + (total !== 1 ? "s" : "") + ")";
          } else {
            summaryEl.textContent = "Not enough votes yet";
          }
        }
      });
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

PULL_TO_REFRESH_HTML = """
<div class="pull-indicator" id="pullIndicator">""" + ICON_REFRESH + """</div>
<script>
(function () {
  var indicator = document.getElementById("pullIndicator");
  if (!indicator) return;
  var startY = null;
  var threshold = 70;
  var maxPull = 110;
  var ready = false;

  document.addEventListener("touchstart", function (e) {
    if (window.scrollY === 0) {
      startY = e.touches[0].clientY;
      ready = false;
    } else {
      startY = null;
    }
  }, { passive: true });

  document.addEventListener("touchmove", function (e) {
    if (startY === null) return;
    var delta = e.touches[0].clientY - startY;
    if (delta <= 0) {
      indicator.style.opacity = "0";
      indicator.style.top = "-50px";
      ready = false;
      return;
    }
    var pull = Math.min(delta, maxPull);
    var progress = pull / threshold;
    indicator.style.opacity = Math.min(progress, 1);
    indicator.style.top = (pull - 50) + "px";
    indicator.style.transform = "translateX(-50%) rotate(" + (progress * 360) + "deg)";
    ready = pull >= threshold;
  }, { passive: true });

  document.addEventListener("touchend", function () {
    if (ready) {
      indicator.style.top = "20px";
      indicator.style.opacity = "1";
      window.location.reload();
    } else {
      indicator.style.opacity = "0";
      indicator.style.top = "-50px";
    }
    startY = null;
    ready = false;
  });
})();
</script>
"""

HEADER_HTML = """
<header>
<div class="header-brand">
<div class="logo-icon">""" + LOGO_ICON + """</div>
<div>
<h1>FeedForge</h1>
<p class="tagline">Curation Done Correctly</p>
<p>Gaming coverage across {{ source_count }} sources, grouped by story</p>
</div>
</div>
<a href="/search" class="search-icon-btn" aria-label="Search">""" + ICON_SEARCH + """</a>
</header>
"""

TABS_HTML = """
<div class="tabs">
<a href="/" class="tab {{ 'active' if active_tab == 'main' else '' }}">""" + ICON_MAIN + """ Main</a>
<a href="/reviews" class="tab {{ 'active' if active_tab == 'reviews' else '' }}">""" + ICON_REVIEWS + """ Reviews</a>
<a href="/video" class="tab {{ 'active' if active_tab == 'video' else '' }}">""" + ICON_VIDEO + """ Video</a>
<a href="/calendar" class="tab {{ 'active' if active_tab == 'calendar' else '' }}">""" + ICON_CALENDAR + """ Calendar</a>
<a href="/themes" class="tab {{ 'active' if active_tab == 'themes' else '' }}">""" + ICON_THEMES + """ Themes</a>
</div>
"""

TOPICS_RAIL_HTML = """
<div class="rail-section">
<div class="rail-header"><span class="rail-title">Topics</span></div>
<div class="rail-scroll">
{% for key, label in topic_tiles %}
<a class="topic-tile {{ 'active' if key == active_topic else '' }}" href="/topic/{{ key }}">{{ label }}</a>
{% endfor %}
</div>
</div>
"""

VIDEO_RAIL_HTML = """
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
"""

TRENDING_RAIL_HTML = """
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
"""

REVIEW_RAIL_HTML = """
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
"""

CARD_HTML = """
<div class="card">
<button class="discard-btn" data-action="/story/{{ story.id }}/discard" data-id="{{ story.id }}" aria-label="Discard">""" + ICON_X + """</button>
<div class="vote-controls" data-story-id="{{ story.id }}">
<button class="vote-btn" data-direction="up" aria-label="Vote up">""" + ICON_THUMBS_UP + """</button>
<button class="vote-btn" data-direction="down" aria-label="Vote down">""" + ICON_THUMBS_DOWN + """</button>
</div>
<a class="card-link with-buttons" href="/story/{{ story.id }}">
{% if story.image_url %}
<img class="card-image" src="{{ story.image_url }}" loading="lazy" alt="">
{% endif %}
{% if story.is_blindspot %}
<span class="blindspot-chip">Not yet in mainstream coverage</span><br>
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
{% if story.ownership_note %}
<p class="ownership-note">{{ story.ownership_note }}</p>
{% endif %}
</a>
</div>
"""

STORY_CARD_LOOP_HTML = """
{% for story in stories %}
""" + CARD_HTML + """
{% endfor %}
{% if not stories %}
<p class="meta">Nothing here yet.</p>
{% endif %}
"""

MAIN_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FeedForge</title>
""" + FAVICON_LINK + """
<style>""" + CSS + """</style>
</head>
<body>
""" + HEADER_HTML + """
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
""" + TOPICS_RAIL_HTML + VIDEO_RAIL_HTML + """
{% for story in stories_part1 %}""" + CARD_HTML + """{% endfor %}
""" + TRENDING_RAIL_HTML + """
{% for story in stories_part2 %}""" + CARD_HTML + """{% endfor %}
""" + REVIEW_RAIL_HTML + """
{% for story in stories_part3 %}""" + CARD_HTML + """{% endfor %}
{% if not stories %}
<p class="meta">Nothing here yet.</p>
{% endif %}
</main>
""" + CARD_INTERACTIONS_JS + VOTE_INTERACTIONS_JS + BACK_TO_TOP_HTML + PULL_TO_REFRESH_HTML + """
</body>
</html>"""

FEED_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FeedForge</title>
""" + FAVICON_LINK + """
<style>""" + CSS + """</style>
</head>
<body>
""" + HEADER_HTML + """
<div class="sticky-nav">
""" + TABS_HTML + """
<div class="segmented">
<a href="{{ recent_url }}" class="segmented-option {{ 'active' if view == 'recent' else '' }}">Most recent</a>
<a href="{{ covered_url }}" class="segmented-option {{ 'active' if view == 'covered' else '' }}">Most covered</a>
</div>
</div>
<div class="legend">
<span><span class="dot" style="background:var(--trust)"></span>Trusted</span>
<span><span class="dot" style="background:var(--niche)"></span>Niche</span>
<span><span class="dot" style="background:var(--comm)"></span>Community</span>
</div>
<div style="max-width:640px;margin:0 auto;padding:0 16px;">
""" + TOPICS_RAIL_HTML + """
</div>
{% if topic_label %}
<p class="topic-heading" style="max-width:640px;margin:0 auto;padding-left:16px;padding-right:16px;">{{ topic_label }}</p>
{% endif %}
<main>
""" + STORY_CARD_LOOP_HTML + """
</main>
""" + CARD_INTERACTIONS_JS + VOTE_INTERACTIONS_JS + BACK_TO_TOP_HTML + PULL_TO_REFRESH_HTML + """
</body>
</html>"""

CALENDAR_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Calendar - FeedForge</title>
""" + FAVICON_LINK + """
<style>""" + CSS + """</style>
</head>
<body>
""" + HEADER_HTML + """
<div class="sticky-nav">
""" + TABS_HTML + """
</div>
<main style="padding-top:16px;">
{% if not groups %}
<p class="meta">No release data yet - check back soon.</p>
{% endif %}
{% for group in groups %}
<div class="calendar-group">
<p class="section-label">{{ group.label }}</p>
{% for item in group.items %}
<div class="calendar-entry">
{% if item.cover_url %}
<img class="calendar-cover" src="{{ item.cover_url }}" loading="lazy" alt="">
{% else %}
<div class="calendar-cover-placeholder"></div>
{% endif %}
<div class="calendar-entry-body">
<h3>{{ item.game_name }}</h3>
<p class="meta">{{ item.platform or "Platform TBD" }}{% if item.opencritic_score %} &middot; <span class="score-chip" style="background:var(--{{ (item.opencritic_tier or 'strong')|lower }}-bg); color:var(--{{ (item.opencritic_tier or 'strong')|lower }}-fg); margin-bottom:0;">{{ item.opencritic_score|round|int }}</span>{% endif %}</p>
</div>
</div>
{% endfor %}
</div>
{% endfor %}
</main>
""" + BACK_TO_TOP_HTML + PULL_TO_REFRESH_HTML + """
</body>
</html>"""

THEMES_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Themes - FeedForge</title>
""" + FAVICON_LINK + """
<style>""" + CSS + """</style>
</head>
<body>
""" + HEADER_HTML + """
<div class="sticky-nav">
""" + TABS_HTML + """
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
""" + BACK_TO_TOP_HTML + PULL_TO_REFRESH_HTML + """
</body>
</html>"""

SEARCH_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Search - FeedForge</title>
""" + FAVICON_LINK + """
<style>""" + CSS + """</style>
</head>
<body>
""" + HEADER_HTML + """
<div class="sticky-nav">
""" + TABS_HTML + """
<form class="search-form" action="/search" method="get">
<input type="text" name="q" value="{{ query }}" placeholder="Search all stories, ever posted..." class="search-input" autofocus>
</form>
</div>
<main style="padding-top:16px;">
{% if query %}
<p class="meta">{{ stories|length }} result{{ 's' if stories|length != 1 else '' }} for "{{ query }}"</p>
{% endif %}
""" + STORY_CARD_LOOP_HTML + """
</main>
""" + CARD_INTERACTIONS_JS + VOTE_INTERACTIONS_JS + BACK_TO_TOP_HTML + PULL_TO_REFRESH_HTML + """
</body>
</html>"""

STORY_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ story.title }} - FeedForge</title>
""" + FAVICON_LINK + """
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
{% if is_blindspot %}
<span class="blindspot-chip">Not yet in mainstream coverage</span>
{% endif %}
{% if ownership_note %}
<p class="ownership-note">{{ ownership_note }}</p>
{% endif %}
{% if story.opencritic_score and story.opencritic_score > 0 %}
<div class="score-block">
<div class="score-circle" style="background:var(--{{ (story.opencritic_tier or 'strong')|lower }}-bg); color:var(--{{ (story.opencritic_tier or 'strong')|lower }}-fg);">{{ story.opencritic_score|round|int }}</div>
<div>
{% if story.opencritic_tier %}<p class="score-tier">{{ story.opencritic_tier }}</p>{% endif %}
<a class="score-link" href="{{ story.opencritic_url }}" target="_blank" rel="noopener">View on OpenCritic &#8599;</a>
</div>
</div>
{% endif %}
<div class="sentiment-block">
<div class="vote-controls inline" data-story-id="{{ story.id }}">
<button class="vote-btn" data-direction="up" aria-label="Vote up">""" + ICON_THUMBS_UP + """</button>
<button class="vote-btn" data-direction="down" aria-label="Vote down">""" + ICON_THUMBS_DOWN + """</button>
</div>
<p class="sentiment-summary">{{ sentiment_summary or "Not enough votes yet" }}</p>
</div>
{% if synopsis %}
<p class="synopsis">{{ synopsis }}</p>
{% endif %}
<p class="section-label">Covered by</p>
{% for a in articles %}
<a class="source-row" href="{{ a.url }}" target="_blank" rel="noopener">
<span class="src-name" style="background:var(--{{ a.source_tier }}-bg); color:var(--{{ a.source_tier }}-fg);">{{ a.source }}</span>
{% if a.timeline_label %}<span class="timeline-badge {{ 'timeline-first' if loop.first else '' }}">{{ a.timeline_label }}</span>{% endif %}
<p class="src-title">{{ a.title }}</p>
<p class="src-meta">{{ a.time_ago }} &middot; <span style="text-decoration:underline;">Read on {{ a.source }} &#8599;</span></p>
</a>
{% endfor %}
</main>
""" + VOTE_INTERACTIONS_JS + BACK_TO_TOP_HTML + PULL_TO_REFRESH_HTML + """
</body>
</html>"""


def humanize(delta_seconds):
    if delta_seconds < 3600:
        return f"{max(1, int(delta_seconds // 60))}m ago"
    if delta_seconds < 86400:
        return f"{int(delta_seconds // 3600)}h ago"
    return f"{int(delta_seconds // 86400)}d ago"


def humanize_delay(delta_seconds):
    if delta_seconds < 60:
        return "under a minute"
    if delta_seconds < 3600:
        return f"{int(delta_seconds // 60)}m"
    if delta_seconds < 86400:
        return f"{int(delta_seconds // 3600)}h"
    return f"{int(delta_seconds // 86400)}d"


def compute_ownership_note(sources):
    groups = {}
    for name, _tier in sources:
        parent = SOURCE_OWNERSHIP.get(name)
        if parent:
            groups.setdefault(parent, []).append(name)
    for parent, names in groups.items():
        if len(names) < 2:
            continue
        if len(names) == 2:
            return f"{names[0]} and {names[1]} are both owned by {parent}"
        return f"{', '.join(names[:-1])}, and {names[-1]} are all owned by {parent}"
    return None


def compute_sentiment_summary(like_count, dislike_count):
    total = (like_count or 0) + (dislike_count or 0)
    if total < MIN_VOTES_FOR_SENTIMENT:
        return None
    pct = round((like_count or 0) / total * 100)
    return f"{pct}% liked this ({total} vote{'s' if total != 1 else ''})"


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


def all_topic_tiles():
    return [(key, t["label"]) for key, t in TOPICS.items()]


def fetch_rail(kind):
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
            s.like_count,
            s.dislike_count,
            count(*) AS n,
            count(*) FILTER (WHERE a.source_tier = 'trusted') AS trusted_n,
            count(*) FILTER (WHERE a.source_tier = 'niche') AS niche_n,
            count(*) FILTER (WHERE a.source_tier = 'community') AS community_n,
            max(COALESCE(a.published_at, a.fetched_at)) AS latest
        FROM stories s
        JOIN articles a ON a.story_id = s.id
        WHERE 1=1 {tab_where}
        AND s.dismissed_at IS NULL
        GROUP BY s.id, s.title, s.opencritic_score, s.opencritic_tier, s.read_at, s.like_count, s.dislike_count
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
            "is_blindspot": row["trusted_n"] == 0 and row["n"] >= 2,
            "ownership_note": compute_ownership_note(sources),
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


def fetch_search_results(query):
    query = (query or "").strip()

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    stories = []
    if query:
        cur.execute(
            """
            SELECT
                s.id,
                s.title,
                s.opencritic_score,
                s.opencritic_tier,
                s.read_at,
                s.like_count,
                s.dislike_count,
                count(*) AS n,
                count(*) FILTER (WHERE a.source_tier = 'trusted') AS trusted_n,
                count(*) FILTER (WHERE a.source_tier = 'niche') AS niche_n,
                count(*) FILTER (WHERE a.source_tier = 'community') AS community_n,
                max(COALESCE(a.published_at, a.fetched_at)) AS latest,
                ts_rank(to_tsvector('english', s.title), plainto_tsquery('english', %s)) AS rank
            FROM stories s
            JOIN articles a ON a.story_id = s.id
            WHERE s.dismissed_at IS NULL
            AND to_tsvector('english', s.title) @@ plainto_tsquery('english', %s)
            GROUP BY s.id, s.title, s.opencritic_score, s.opencritic_tier, s.read_at, s.like_count, s.dislike_count
            ORDER BY (s.read_at IS NOT NULL), rank DESC, latest DESC
            LIMIT 40
            """,
            (query, query),
        )
        story_rows = cur.fetchall()

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
                "is_blindspot": row["trusted_n"] == 0 and row["n"] >= 2,
                "ownership_note": compute_ownership_note(sources),
            })

    cur.execute("SELECT count(DISTINCT source) FROM articles")
    source_count = cur.fetchone()["count"]

    cur.close()
    conn.close()
    return stories, source_count


def fetch_topic_stories(topic_key, view="recent"):
    topic = TOPICS.get(topic_key)
    if not topic:
        return [], 0

    order_by = "n DESC, latest DESC" if view == "covered" else "latest DESC"

    conditions = []
    params = []
    if topic.get("sources"):
        conditions.append("EXISTS (SELECT 1 FROM articles a2 WHERE a2.story_id = s.id AND a2.source = ANY(%s))")
        params.append(topic["sources"])
    if topic.get("keywords"):
        conditions.append("to_tsvector('english', s.title) @@ to_tsquery('english', %s)")
        params.append(topic["keywords"])
    topic_where = "AND (" + " OR ".join(conditions) + ")"

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        f"""
        SELECT
            s.id, s.title, s.opencritic_score, s.opencritic_tier, s.read_at,
            s.like_count, s.dislike_count,
            count(*) AS n,
            count(*) FILTER (WHERE a.source_tier = 'trusted') AS trusted_n,
            count(*) FILTER (WHERE a.source_tier = 'niche') AS niche_n,
            count(*) FILTER (WHERE a.source_tier = 'community') AS community_n,
            max(COALESCE(a.published_at, a.fetched_at)) AS latest
        FROM stories s
        JOIN articles a ON a.story_id = s.id
        WHERE s.dismissed_at IS NULL
        {topic_where}
        GROUP BY s.id, s.title, s.opencritic_score, s.opencritic_tier, s.read_at, s.like_count, s.dislike_count
        HAVING max(COALESCE(a.published_at, a.fetched_at)) > now() - interval '{FEED_WINDOW_DAYS} days'
        ORDER BY (s.read_at IS NOT NULL), {order_by}
        LIMIT 30
        """,
        params,
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
            "is_blindspot": row["trusted_n"] == 0 and row["n"] >= 2,
            "ownership_note": compute_ownership_note(sources),
        })

    cur.execute("SELECT count(DISTINCT source) FROM articles")
    source_count = cur.fetchone()["count"]

    cur.close()
    conn.close()
    return stories, source_count


def fetch_calendar_entries():
    """Backs the Calendar tab (added 16 Aug 2026). Groups game_releases
    rows by date into a chronological list - see CALENDAR_TEMPLATE's
    comment for why a plain grouped list rather than a month grid.
    release_date is NOT NULL in the actual schema (every IGDB
    release_dates row we store has a real date), so no "TBD" fallback
    is needed here. The OpenCritic cross-reference costs zero extra API
    calls - a simple case-insensitive match against stories we've
    already scored via the existing review-score pipeline. A game
    releasing on multiple platforms produces multiple separate rows
    here, matching how IGDB itself models a release_dates record - a
    known v1 simplification, not merged into one display row.
    """
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """
        SELECT gr.game_name, gr.platform, gr.release_date, gr.cover_url,
               s.opencritic_score, s.opencritic_tier
        FROM game_releases gr
        LEFT JOIN stories s ON s.opencritic_game_name ILIKE gr.game_name
        ORDER BY gr.release_date ASC, gr.game_name ASC
        """
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    grouped = []
    current_key = None
    current_group = None
    for row in rows:
        key = row["release_date"]
        if current_group is None or key != current_key:
            label = key.strftime("%A, %B %-d")
            current_group = {"label": label, "items": []}
            grouped.append(current_group)
            current_key = key
        current_group["items"].append(row)
    return grouped


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
        stories_part1 = stories[:10]
        stories_part2 = stories[10:20]
        stories_part3 = stories[20:]
    else:
        trending = None
        review_rail = None
        video_rail = None
        stories_part1 = stories
        stories_part2 = []
        stories_part3 = []

    return render_template_string(
        MAIN_TEMPLATE, stories=stories, source_count=source_count,
        stories_part1=stories_part1, stories_part2=stories_part2, stories_part3=stories_part3,
        active_tab="main", view=view, show_all=show_all, hidden_count=hidden_count,
        recent_url=build_url("/", view="recent", show_all=show_all),
        covered_url=build_url("/", view="covered", show_all=show_all),
        toggle_url=build_url("/", view=view, show_all=not show_all),
        show_filter_toggle=True,
        show_rails=show_rails, trending=trending, review_rail=review_rail, video_rail=video_rail,
        topic_tiles=all_topic_tiles(), active_topic=None,
    )


@app.route("/reviews")
def reviews():
    view = valid_view()
    stories, source_count, _ = fetch_stories(tab="reviews", view=view)
    return render_template_string(
        FEED_TEMPLATE, stories=stories, source_count=source_count,
        active_tab="reviews", view=view,
        recent_url=build_url("/reviews", view="recent"),
        covered_url=build_url("/reviews", view="covered"),
        topic_tiles=all_topic_tiles(), active_topic=None, topic_label=None,
    )


@app.route("/video")
def video():
    view = valid_view()
    stories, source_count, _ = fetch_stories(tab="video", view=view)
    return render_template_string(
        FEED_TEMPLATE, stories=stories, source_count=source_count,
        active_tab="video", view=view,
        recent_url=build_url("/video", view="recent"),
        covered_url=build_url("/video", view="covered"),
        topic_tiles=all_topic_tiles(), active_topic=None, topic_label=None,
    )


@app.route("/calendar")
def calendar():
    groups = fetch_calendar_entries()
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT count(DISTINCT source) FROM articles")
    source_count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return render_template_string(
        CALENDAR_TEMPLATE, groups=groups, source_count=source_count, active_tab="calendar",
    )


@app.route("/topic/<key>")
def topic(key):
    topic_def = TOPICS.get(key)
    if not topic_def:
        return "Topic not found", 404
    view = valid_view()
    stories, source_count = fetch_topic_stories(key, view=view)
    return render_template_string(
        FEED_TEMPLATE, stories=stories, source_count=source_count,
        active_tab=None, view=view,
        recent_url=build_url(f"/topic/{key}", view="recent"),
        covered_url=build_url(f"/topic/{key}", view="covered"),
        topic_label=topic_def["label"],
        topic_tiles=all_topic_tiles(), active_topic=key,
    )


@app.route("/search")
def search():
    query = request.args.get("q", "")
    stories, source_count = fetch_search_results(query)
    return render_template_string(
        SEARCH_TEMPLATE,
        stories=stories, source_count=source_count, query=query.strip(),
        active_tab=None,
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
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("UPDATE stories SET dismissed_at = NULL WHERE id = %s", (story_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify(ok=True)


@app.route("/story/<int:story_id>/vote/<direction>", methods=["POST"])
def vote_story(story_id, direction):
    if direction not in ("up", "down"):
        return jsonify(ok=False, error="invalid direction"), 400
    column = "like_count" if direction == "up" else "dislike_count"
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        f"UPDATE stories SET {column} = {column} + 1 WHERE id = %s RETURNING like_count, dislike_count",
        (story_id,),
    )
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    if row is None:
        return jsonify(ok=False), 404
    return jsonify(ok=True, like_count=row["like_count"], dislike_count=row["dislike_count"])


@app.route("/story/<int:story_id>")
def story_detail(story_id):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """
        SELECT id, title, is_review, is_video, opencritic_score, opencritic_tier, opencritic_url,
               like_count, dislike_count
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
    is_blindspot = trusted_n == 0 and len(articles) >= 2
    ownership_note = compute_ownership_note([(a["source"], a["source_tier"]) for a in articles])
    sentiment_summary = compute_sentiment_summary(story["like_count"], story["dislike_count"])

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

    first_published = articles[0]["published_at"] if articles else None
    show_timeline = len(articles) > 1
    for i, a in enumerate(articles):
        if not show_timeline:
            a["timeline_label"] = None
        elif i == 0:
            a["timeline_label"] = "First to cover this"
        elif a["published_at"] and first_published:
            delay = (a["published_at"] - first_published).total_seconds()
            a["timeline_label"] = f"+{humanize_delay(delay)} after first"
        else:
            a["timeline_label"] = None

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
        is_blindspot=is_blindspot,
        ownership_note=ownership_note,
        sentiment_summary=sentiment_summary,
        n=len(articles),
        trusted_n=trusted_n,
        niche_n=niche_n,
        community_n=community_n,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
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
# affects sort order (is_read below), not whether something's in the
# window at all - a read story ages out exactly the same way an unread
# one does. Search (below) deliberately ignores this window entirely -
# see fetch_search_results for why. Topic pages (also below) use the
# same window as the main feed - unlike search, a topic page is meant to
# feel like a live, current slice of the feed, not a historical archive.
FEED_WINDOW_DAYS = 2

# Milliseconds the Undo option stays available after a discard - see
# CARD_INTERACTIONS_JS below. This used to also control how long the
# card visually sat there dimmed before collapsing, which made every
# discard feel like it took several seconds even though the actual
# server round-trip was instant. Restructured 12 Aug 2026 so the card
# collapses immediately on server confirmation instead - this constant
# now purely controls the Undo safety-net window, with no effect on how
# quickly a discard feels.
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
# Not applied to search or topics either, for the same reason.
MIN_SOURCES_DEFAULT = 2

# How many items each horizontal rail shows (added 11 Aug 2026, inspired
# by Ground News's homepage rails). Rails are a preview/teaser, not a
# replacement for the full Reviews/Video tabs - deliberately kept short
# with a "See all" link through to the real thing, rather than trying to
# cram full browsability into a scroll strip.
RAIL_LIMIT = 8

# Minimum combined votes (like_count + dislike_count) before showing a
# percentage-based sentiment summary (added 14 Aug 2026). Below this,
# a "73% liked this" style readout from a tiny handful of votes would be
# real numbers dressed up as a statistic - misleadingly precise for a
# sample that small. Below the threshold we just say there aren't
# enough votes yet, rather than show a percentage that happens to be
# mathematically correct but not actually meaningful.
MIN_VOTES_FOR_SENTIMENT = 5

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

# Ultimate parent company per outlet - verified live against Wikipedia on
# 12 Aug 2026, deliberately not written from memory. Two real, current
# changes memory alone would have gotten wrong: Polygon was sold from Vox
# Media to Valnet in 2025, and Kotaku was sold from G/O Media to the
# Swiss firm Keleops, also in 2025. The single biggest finding: Gamer
# Network (Eurogamer, Rock Paper Shotgun, VG247) was bought by IGN
# Entertainment in 2024 - meaning IGN itself and three of our "niche"
# sources now share the same ultimate owner, which is exactly the kind
# of thing this feature exists to surface. Intermediate holding
# companies are collapsed to the ultimate parent (e.g. Eurogamer's
# immediate parent is Gamer Network, but Gamer Network's own parent is
# IGN Entertainment/Ziff Davis, so Eurogamer is recorded under "Ziff
# Davis" directly - what matters for "do these share an owner" is the
# ultimate parent, not the intermediate chain). Only sources we actually
# have verified data for appear here; anything absent is simply not
# flagged, not assumed independent. GamesIndustry.biz added 12 Aug 2026
# deliberately BECAUSE of its overlap with the IGN Entertainment/Ziff
# Davis group already represented here - the user's own reasoning:
# seeing that connection flagged live is the point of this feature, not
# a reason to avoid a source.
SOURCE_OWNERSHIP = {
    "IGN": "Ziff Davis",
    "Eurogamer": "Ziff Davis",
    "Rock Paper Shotgun": "Ziff Davis",
    "VG247": "Ziff Davis",
    "GamesIndustry.biz": "Ziff Davis",
    "PC Gamer": "Future plc",
    "GamesRadar": "Future plc",
    "Polygon": "Valnet",
    "TheGamer": "Valnet",
    "NintendoLife": "Hookshot Media",
    "Push Square": "Hookshot Media",
    "Pure Xbox": "Hookshot Media",
    "GameSpot": "Fandom, Inc.",
    "Kotaku": "Keleops",
    "PCGamesN": "NetworkN",
}

# Topic tiles (added 12 Aug 2026) - the first slice of topic browsing,
# deliberately source-identity-based rather than full content/entity
# extraction, which would be a much bigger, more fragile build. A story
# qualifies for a topic if EITHER at least one of its sources is a
# dedicated outlet for that topic (regardless of title wording), OR its
# title matches a simple keyword OR-query - the same tsquery machinery
# already proven in fetch_search_results, just aimed at a fixed set of
# terms instead of a user-typed one. "sources" is the primary signal
# (high precision - Push Square covering something really does mean
# it's a PlayStation story); "keywords" adds recall for stories from
# non-platform-specific outlets that are still clearly on-topic. Indie
# and Industry have no natural keyword equivalent, so they rely on
# source identity alone - that's fine, both have genuinely dedicated
# sources now (Indie Informer/Indie Game Reviewer; Game Developer/
# GamesIndustry.biz). Order here is the display order of the tiles on
# Main. Xbox has no dedicated subreddit in REDDIT_SOURCES (only r/PS5
# and r/NintendoSwitch are platform-specific there) - a real, known gap
# versus PlayStation/Switch's stronger source coverage, not an oversight.
TOPICS = {
    "playstation": {
        "label": "PlayStation",
        "sources": ["Push Square", "r/PS5"],
        "keywords": "playstation | ps5 | ps4",
    },
    "xbox": {
        "label": "Xbox",
        "sources": ["Pure Xbox"],
        "keywords": "xbox",
    },
    "switch": {
        "label": "Nintendo Switch",
        "sources": ["NintendoLife", "r/NintendoSwitch"],
        "keywords": "nintendo | switch",
    },
    "pc": {
        "label": "PC",
        "sources": ["PC Gamer", "PCGamesN", "r/pcgaming"],
        "keywords": "steam",
    },
    "indie": {
        "label": "Indie",
        "sources": ["The Indie Informer", "Indie Game Reviewer"],
        "keywords": None,
    },
    "industry": {
        "label": "Industry",
        "sources": ["Game Developer", "GamesIndustry.biz"],
        "keywords": None,
    },
}

ICON_MAIN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"></rect><line x1="7" y1="9" x2="17" y2="9"></line><line x1="7" y1="13" x2="17" y2="13"></line><line x1="7" y1="17" x2="13" y2="17"></line></svg>'
ICON_REVIEWS = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15 9 22 9.5 17 14.5 18.5 22 12 18 5.5 22 7 14.5 2 9.5 9 9"></polygon></svg>'
ICON_VIDEO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"></circle><polygon points="10 8 16 12 10 16" fill="currentColor" stroke="none"></polygon></svg>'
ICON_THEMES = '<svg viewBox="0 0 24 24" fill="currentColor" stroke="none"><path d="M12 2l1.8 6.2L20 10l-6.2 1.8L12 18l-1.8-6.2L4 10l6.2-1.8z"></path></svg>'
ICON_X = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="6" y1="6" x2="18" y2="18"></line><line x1="18" y1="6" x2="6" y2="18"></line></svg>'
ICON_UP = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="19" x2="12" y2="5"></line><polyline points="6 11 12 5 18 11"></polyline></svg>'
ICON_SEARCH = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>'
ICON_REFRESH = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="1 4 1 10 7 10"></polyline><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"></path></svg>'

# Thumbs up/down (added 14 Aug 2026), replacing the old single heart
# "like" button entirely per the user's explicit call - one unified
# up/down action rather than a personal-interest heart plus a separate
# public-sentiment control. Down is the same path as up, just rotated
# 180 degrees around the icon's own center, rather than a second
# hand-authored path - guarantees the two stay visually consistent.
ICON_THUMBS_UP = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"></path></svg>'
ICON_THUMBS_DOWN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3" transform="rotate(180 12 12)"></path></svg>'

# FeedForge logo mark (added 13 Aug 2026) - the anvil/forge shape reduced
# to two stacked solid blocks (a narrow "body" sitting on a wide "foot")
# rather than a literal anvil illustration, topped by concentric signal
# arcs and a single warm-orange flame accent. Designed through several
# rounds with the user: started as a full 3D-rendered anvil under a
# rainbow-colored signal, then reduced to flat black geometry specifically
# because a plain silhouette reads more clearly as "signal" than a
# multi-color arc does (which risks being misread as a literal rainbow),
# and flat shapes hold up far better at small sizes than gradients/bevels
# do. The two-block base was the user's own refinement - it gestures at a
# real anvil's silhouette (narrow body, flared foot) through pure
# geometry, without needing literal anvil detail. Reused directly (no
# separate favicon asset) as both the header icon and the favicon via a
# base64 data URI, consistent with this app's existing pattern of keeping
# every icon as an inline SVG string in app.py rather than separate static
# files.
LOGO_ICON = """<svg viewBox="0 0 200 220" xmlns="http://www.w3.org/2000/svg">
<path d="M 15 168 A 85 85 0 0 1 185 168" fill="none" stroke="#1a1a18" stroke-width="13" stroke-linecap="round"/>
<path d="M 35 168 A 65 65 0 0 1 165 168" fill="none" stroke="#1a1a18" stroke-width="13" stroke-linecap="round"/>
<path d="M 55 168 A 45 45 0 0 1 145 168" fill="none" stroke="#1a1a18" stroke-width="13" stroke-linecap="round"/>
<rect x="65" y="168" width="70" height="25" fill="#1a1a18"/>
<rect x="15" y="193" width="170" height="23" fill="#1a1a18"/>
<path d="M 100 122 C 112 138, 120 152, 116 164 C 113 174, 104 180, 100 180 C 96 180, 87 174, 84 164 C 80 152, 88 138, 100 122 Z" fill="#D85A30"/>
</svg>"""

FAVICON_LINK = '<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,PHN2ZyB2aWV3Qm94PSIwIDAgMjAwIDIyMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KICA8cGF0aCBkPSJNIDE1IDE2OCBBIDg1IDg1IDAgMCAxIDE4NSAxNjgiIGZpbGw9Im5vbmUiIHN0cm9rZT0iIzFhMWExOCIgc3Ryb2tlLXdpZHRoPSIxMyIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIi8+CiAgPHBhdGggZD0iTSAzNSAxNjggQSA2NSA2NSAwIDAgMSAxNjUgMTY4IiBmaWxsPSJub25lIiBzdHJva2U9IiMxYTFhMTgiIHN0cm9rZS13aWR0aD0iMTMiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPgogIDxwYXRoIGQ9Ik0gNTUgMTY4IEEgNDUgNDUgMCAwIDEgMTQ1IDE2OCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjMWExYTE4IiBzdHJva2Utd2lkdGg9IjEzIiBzdHJva2UtbGluZWNhcD0icm91bmQiLz4KICA8cmVjdCB4PSI2NSIgeT0iMTY4IiB3aWR0aD0iNzAiIGhlaWdodD0iMjUiIGZpbGw9IiMxYTFhMTgiLz4KICA8cmVjdCB4PSIxNSIgeT0iMTkzIiB3aWR0aD0iMTcwIiBoZWlnaHQ9IjIzIiBmaWxsPSIjMWExYTE4Ii8+CiAgPHBhdGggZD0iTSAxMDAgMTIyCiAgICAgICAgICAgQyAxMTIgMTM4LCAxMjAgMTUyLCAxMTYgMTY0CiAgICAgICAgICAgQyAxMTMgMTc0LCAxMDQgMTgwLCAxMDAgMTgwCiAgICAgICAgICAgQyA5NiAxODAsIDg3IDE3NCwgODQgMTY0CiAgICAgICAgICAgQyA4MCAxNTIsIDg4IDEzOCwgMTAwIDEyMgogICAgICAgICAgIFoiCiAgICAgICAgZmlsbD0iI0Q4NUEzMCIvPgo8L3N2Zz4K">'


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
display: flex;
justify-content: space-between;
align-items: flex-start;
gap: 12px;
}
.header-brand {
display: flex;
align-items: center;
gap: 10px;
}
.logo-icon {
width: 32px;
height: 35px;
flex-shrink: 0;
}
.logo-icon svg {
width: 100%;
height: 100%;
display: block;
}
header h1 {
font-size: 21px;
font-weight: 800;
letter-spacing: -0.02em;
margin: 0 0 2px;
}
.tagline {
font-size: 12px;
font-weight: 700;
font-style: italic;
color: var(--comm);
margin: 0 0 3px;
}
header p {
font-size: 13px;
color: var(--text-secondary);
margin: 0;
}
.search-icon-btn {
width: 36px;
height: 36px;
border-radius: 50%;
background: var(--border);
color: var(--text-secondary);
display: flex;
align-items: center;
justify-content: center;
flex-shrink: 0;
margin-top: 2px;
}
.search-icon-btn svg { width: 17px; height: 17px; }
.search-form {
padding: 8px 16px 12px;
max-width: 640px;
margin: 0 auto;
}
.search-input {
width: 100%;
padding: 11px 14px;
border-radius: 10px;
border: 1px solid var(--border);
background: var(--card);
color: var(--text);
font-size: 15px;
}
.search-input:focus {
outline: none;
border-color: var(--text-secondary);
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
.topic-heading {
font-size: 18px;
font-weight: 700;
padding: 4px 0 14px;
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
.topic-tile {
flex: 0 0 auto;
scroll-snap-align: start;
display: flex;
align-items: center;
padding: 13px 20px;
background: var(--card);
border: 1px solid var(--border);
border-radius: 12px;
font-size: 14px;
font-weight: 600;
color: var(--text);
white-space: nowrap;
}
.topic-tile.active {
background: var(--text);
color: var(--bg);
border-color: var(--text);
}
.card {
position: relative;
display: block;
background: var(--card);
border: 1px solid var(--border);
border-radius: 14px;
padding: 16px;
margin-bottom: 14px;
transition: opacity 0.15s ease, transform 0.15s ease, max-height 0.22s ease, margin-bottom 0.22s ease, padding 0.22s ease;
overflow: hidden;
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
.discard-btn {
position: absolute;
top: 8px;
left: 8px;
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
.discard-btn:active { transform: scale(0.88); }
.discard-btn svg { width: 17px; height: 17px; }
/* Vote controls: default styling is tuned for sitting on top of a card
   image (semi-transparent dark + blur, since the background varies per
   story) - added 14 Aug 2026, replacing the old single like-btn heart
   entirely. The .inline modifier (used on the story detail page, which
   never had a like control before this) restyles the same buttons for
   sitting on a plain card/page background instead. */
.vote-controls {
position: absolute;
top: 8px;
right: 8px;
display: flex;
flex-direction: column;
gap: 6px;
z-index: 2;
}
.vote-controls.inline {
position: static;
flex-direction: row;
gap: 10px;
}
.vote-btn {
width: 36px;
height: 36px;
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
padding: 0;
box-shadow: 0 1px 4px rgba(0,0,0,0.25);
transition: transform 0.15s ease;
}
.vote-btn:active { transform: scale(0.88); }
.vote-btn svg { width: 16px; height: 16px; }
.vote-btn.voted-up { background: rgba(0,0,0,0.55); color: var(--strong-fg); }
.vote-btn.voted-down { background: rgba(0,0,0,0.55); color: var(--weak-fg); }
.vote-btn:disabled { cursor: default; }
.vote-controls.inline .vote-btn {
width: 40px;
height: 40px;
background: var(--border);
color: var(--text-secondary);
backdrop-filter: none;
-webkit-backdrop-filter: none;
box-shadow: none;
}
.vote-controls.inline .vote-btn.voted-up { background: var(--strong-bg); color: var(--strong-fg); }
.vote-controls.inline .vote-btn.voted-down { background: var(--weak-bg); color: var(--weak-fg); }
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
.blindspot-chip {
font-size: 12px;
font-weight: 700;
padding: 4px 10px;
border-radius: 20px;
display: inline-block;
margin-bottom: 10px;
background: var(--fair-bg);
color: var(--fair-fg);
}
.ownership-note {
font-size: 11.5px;
color: var(--text-secondary);
font-style: italic;
margin: 8px 0 0;
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
.score-block, .sentiment-block {
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
.sentiment-summary {
font-size: 14px;
color: var(--text-secondary);
margin: 0;
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
.timeline-badge {
font-size: 11px;
font-weight: 600;
color: var(--text-secondary);
margin-left: 6px;
}
.timeline-badge.timeline-first {
color: var(--niche);
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
.pull-indicator {
position: fixed;
top: -50px;
left: 50%;
transform: translateX(-50%) rotate(0deg);
width: 38px;
height: 38px;
border-radius: 50%;
background: var(--text);
color: var(--bg);
display: flex;
align-items: center;
justify-content: center;
z-index: 25;
opacity: 0;
box-shadow: 0 2px 8px rgba(0,0,0,0.25);
}
.pull-indicator svg { width: 18px; height: 18px; }
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

  function collapseCard(card) {
    // Collapses the card immediately on server confirmation of the
    // discard - previously the card just sat there dimmed for the full
    // UNDO_WINDOW_MS before this ran, making every discard feel like it
    // took several seconds. pointerEvents is disabled so a collapsed
    // (but not-yet-removed) card can't accidentally catch a tap.
    var height = card.offsetHeight;
    card.style.maxHeight = height + "px";
    card.offsetHeight; // force a reflow so the browser registers the starting height
    card.style.opacity = "0";
    card.style.transform = "scale(0.96)";
    card.style.maxHeight = "0px";
    card.style.marginBottom = "0px";
    card.style.paddingTop = "0px";
    card.style.paddingBottom = "0px";
    card.style.pointerEvents = "none";
  }

  function restoreCard(card) {
    // Undo just clears the inline styles collapseCard set - the card
    // never actually left the DOM, so this restores it exactly in place
    // with no need to track or reinsert anything.
    card.style.pointerEvents = "";
    card.style.maxHeight = "";
    card.style.opacity = "";
    card.style.transform = "";
    card.style.marginBottom = "";
    card.style.paddingTop = "";
    card.style.paddingBottom = "";
  }

  document.addEventListener("click", function (e) {
    var discardBtn = e.target.closest(".discard-btn");
    if (!discardBtn) return;
    e.preventDefault();
    e.stopPropagation();
    var url = discardBtn.getAttribute("data-action");
    var card = discardBtn.closest(".card");
    var storyId = discardBtn.getAttribute("data-id");
    fetch(url, { method: "POST" }).then(function (r) {
      if (!r.ok) return;
      collapseCard(card);
      var removeTimeout = setTimeout(function () {
        card.remove();
      }, """ + str(UNDO_WINDOW_MS) + """);
      showToast("Story discarded", function () {
        clearTimeout(removeTimeout);
        restoreCard(card);
        fetch("/story/" + storyId + "/undiscard", { method: "POST" });
      });
    });
  });
})();
</script>
"""

# Vote controls JS (added 14 Aug 2026): shared by every template that can
# render a .vote-controls block - feed cards (Main/Reviews/Video/Search/
# Topic) and the story detail page alike. No accounts exist yet, so vote
# state is tracked client-side in localStorage rather than server-side
# per visitor - a determined person could clear it and vote again, same
# category of limitation as the shared read/like state elsewhere until
# real accounts exist. Once a story has been voted on in this browser,
# both buttons for that story are disabled and the chosen direction is
# highlighted - no changing your mind, no un-voting, deliberately the
# simplest possible v1 rather than also handling switched votes
# server-side.
VOTE_INTERACTIONS_JS = """
<script>
(function () {
  function getVoted() {
    try {
      return JSON.parse(localStorage.getItem("votedStories") || "{}");
    } catch (e) {
      return {};
    }
  }

  function setVoted(storyId, direction) {
    var voted = getVoted();
    voted[storyId] = direction;
    try {
      localStorage.setItem("votedStories", JSON.stringify(voted));
    } catch (e) {}
  }

  function disableGroup(group, direction) {
    var buttons = group.querySelectorAll(".vote-btn");
    buttons.forEach(function (b) {
      b.disabled = true;
      if (b.getAttribute("data-direction") === direction) {
        b.classList.add(direction === "up" ? "voted-up" : "voted-down");
      }
    });
  }

  function applyVotedState() {
    var voted = getVoted();
    document.querySelectorAll(".vote-controls[data-story-id]").forEach(function (group) {
      var storyId = group.getAttribute("data-story-id");
      var direction = voted[storyId];
      if (direction) disableGroup(group, direction);
    });
  }

  applyVotedState();

  document.addEventListener("click", function (e) {
    var btn = e.target.closest(".vote-btn");
    if (!btn || btn.disabled) return;
    e.preventDefault();
    e.stopPropagation();
    var group = btn.closest(".vote-controls");
    var storyId = group.getAttribute("data-story-id");
    var direction = btn.getAttribute("data-direction");
    if (getVoted()[storyId]) return;

    fetch("/story/" + storyId + "/vote/" + direction, { method: "POST" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.ok) return;
        setVoted(storyId, direction);
        disableGroup(group, direction);
        var summaryEl = group.parentElement.querySelector(".sentiment-summary");
        if (summaryEl) {
          var total = data.like_count + data.dislike_count;
          if (total >= """ + str(MIN_VOTES_FOR_SENTIMENT) + """) {
            var pct = Math.round((data.like_count / total) * 100);
            summaryEl.textContent = pct + "% liked this (" + total + " vote" + (total !== 1 ? "s" : "") + ")";
          } else {
            summaryEl.textContent = "Not enough votes yet";
          }
        }
      });
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

# Pull-to-refresh (added 12 Aug 2026): the site is entirely server-rendered
# per request with no client-side polling anywhere, so nothing updates
# on its own if a tab is left open - a manual reload is the only way to
# see anything new. This adds the standard mobile gesture rather than
# relying on the browser's own (inconsistent across browsers) overscroll
# behavior: track touchstart only when already at scrollY 0 (so it can't
# trigger mid-scroll), grow/rotate a small indicator proportionally to
# pull distance past a threshold, then a real window.location.reload()
# on release if the pull cleared that threshold - a full reload rather
# than an AJAX partial refresh, since there's no client-only state worth
# preserving across it (everything meaningful already lives server-side
# in the database). Included everywhere BACK_TO_TOP_HTML already is.
# Genuinely can't be verified through browser automation, which has no
# way to simulate a real touch swipe - verified the code is correct and
# deployed, not that the gesture itself feels right on an actual phone.
PULL_TO_REFRESH_HTML = """
<div class="pull-indicator" id="pullIndicator">""" + ICON_REFRESH + """</div>
<script>
(function () {
  var indicator = document.getElementById("pullIndicator");
  if (!indicator) return;
  var startY = null;
  var threshold = 70;
  var maxPull = 110;
  var ready = false;

  document.addEventListener("touchstart", function (e) {
    if (window.scrollY === 0) {
      startY = e.touches[0].clientY;
      ready = false;
    } else {
      startY = null;
    }
  }, { passive: true });

  document.addEventListener("touchmove", function (e) {
    if (startY === null) return;
    var delta = e.touches[0].clientY - startY;
    if (delta <= 0) {
      indicator.style.opacity = "0";
      indicator.style.top = "-50px";
      ready = false;
      return;
    }
    var pull = Math.min(delta, maxPull);
    var progress = pull / threshold;
    indicator.style.opacity = Math.min(progress, 1);
    indicator.style.top = (pull - 50) + "px";
    indicator.style.transform = "translateX(-50%) rotate(" + (progress * 360) + "deg)";
    ready = pull >= threshold;
  }, { passive: true });

  document.addEventListener("touchend", function () {
    if (ready) {
      indicator.style.top = "20px";
      indicator.style.opacity = "1";
      window.location.reload();
    } else {
      indicator.style.opacity = "0";
      indicator.style.top = "-50px";
    }
    startY = null;
    ready = false;
  });
})();
</script>
"""

# Tagline added 14 Aug 2026, sitting between the FeedForge wordmark and
# the plain factual source-count line - a short, deliberate statement of
# what this whole project is actually for, styled in the same orange
# accent as the logo's flame for a small tie-back to the mark itself.
HEADER_HTML = """
<header>
<div class="header-brand">
<div class="logo-icon">""" + LOGO_ICON + """</div>
<div>
<h1>FeedForge</h1>
<p class="tagline">Curation Done Correctly</p>
<p>Gaming coverage across {{ source_count }} sources, grouped by story</p>
</div>
</div>
<a href="/search" class="search-icon-btn" aria-label="Search">""" + ICON_SEARCH + """</a>
</header>
"""

TABS_HTML = """
<div class="tabs">
<a href="/" class="tab {{ 'active' if active_tab == 'main' else '' }}">""" + ICON_MAIN + """ Main</a>
<a href="/reviews" class="tab {{ 'active' if active_tab == 'reviews' else '' }}">""" + ICON_REVIEWS + """ Reviews</a>
<a href="/video" class="tab {{ 'active' if active_tab == 'video' else '' }}">""" + ICON_VIDEO + """ Video</a>
<a href="/themes" class="tab {{ 'active' if active_tab == 'themes' else '' }}">""" + ICON_THEMES + """ Themes</a>
</div>
"""

# Topics rail (added 12 Aug 2026, fixed same day): unlike the
# Video/Trending/Reviews rails below, this is pure navigation, not a
# content preview - it doesn't make any claim about freshness, so it
# isn't gated by show_rails/hidden during "Most covered" the way those
# three are. Originally only included in MAIN_TEMPLATE; the user
# immediately caught the real problem with that - clicking into a topic
# page (which shares FEED_TEMPLATE with Reviews/Video) meant the rail,
# and with it any way to jump to a *different* topic, vanished entirely.
# Fixed by including this in FEED_TEMPLATE too, so it's now present on
# Reviews/Video/every topic page - not just where a topic was first
# clicked from. active_topic (the current page's topic key, None
# everywhere except topic pages themselves) highlights whichever tile
# you're currently on, same idea as TABS_HTML's active state.
TOPICS_RAIL_HTML = """
<div class="rail-section">
<div class="rail-header"><span class="rail-title">Topics</span></div>
<div class="rail-scroll">
{% for key, label in topic_tiles %}
<a class="topic-tile {{ 'active' if key == active_topic else '' }}" href="/topic/{{ key }}">{{ label }}</a>
{% endfor %}
</div>
</div>
"""

# Three separate rail blocks (added 11 Aug 2026, split out of a single
# combined RAILS_HTML) so index() below can place each one independently
# at a different point in the page, rather than all three stacked back
# to back at the very top. Reasoning: Trending and Latest reviews update
# far less often than the feed itself does (a story needs many outlets
# to converge, or a new review to actually publish), so stacking all
# three rails up front meant a returning user's first impression was
# three mostly-unchanged sections before reaching any real movement.
# Video updates the most (10 channels posting regularly) and gets
# promoted to the very top for exactly that reason; the slower two are
# spread further down to break up the vertical scroll instead of
# front-loading it.
VIDEO_RAIL_HTML = """
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
"""

TRENDING_RAIL_HTML = """
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
"""

REVIEW_RAIL_HTML = """
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
"""

# Vote controls block (added 14 Aug 2026), reused on both feed cards and
# the story detail page via {% include %}-style string concatenation -
# on cards it's absolutely positioned over the image (top-right, where
# the old like heart used to sit); on the detail page it's rendered with
# the "inline" class instead (see .vote-controls.inline in CSS), sitting
# statically in its own row/block rather than overlaying anything.
VOTE_CONTROLS_HTML = """
<div class="vote-controls {{ vote_extra_class|default('') }}" data-story-id="{{ vote_story_id }}">
<button class="vote-btn" data-direction="up" aria-label="Vote up">""" + ICON_THUMBS_UP + """</button>
<button class="vote-btn" data-direction="down" aria-label="Vote down">""" + ICON_THUMBS_DOWN + """</button>
</div>
"""

# Single-story card markup, kept as its own reusable block so it can be
# looped over multiple times with different list variables (Main's
# split-into-parts layout below) or once with a single flat list
# (Reviews/Video/Search/Topic) without duplicating the actual HTML.
#
# Vote controls replace the old single heart "like" button entirely as
# of 14 Aug 2026, per the user's explicit call - one unified up/down
# action rather than a personal-interest heart plus a separate public-
# sentiment control living side by side.
#
# blindspot-chip added 12 Aug 2026: flags a story with real multi-source
# coverage (2+ sources) but zero "trusted"-tier sources - i.e. niche
# and/or community outlets are covering something that hasn't (yet)
# reached mainstream press. Deliberately worded "not yet in mainstream
# coverage" rather than "no press coverage" - niche outlets are real
# journalism too, just a different tier in our system; the chip flags
# an absence of the *trusted* tier specifically, not press in general.
#
# ownership-note added 12 Aug 2026: when 2+ of a story's sources share a
# known ultimate parent company (see SOURCE_OWNERSHIP above), a small
# italic line names them - deliberately lighter-weight than the chips
# above (plain text, not another colored badge) since most stories won't
# trigger it and it shouldn't compete visually with score/blindspot.
CARD_HTML = """
<div class="card">
<button class="discard-btn" data-action="/story/{{ story.id }}/discard" data-id="{{ story.id }}" aria-label="Discard">""" + ICON_X + """</button>
<div class="vote-controls" data-story-id="{{ story.id }}">
<button class="vote-btn" data-direction="up" aria-label="Vote up">""" + ICON_THUMBS_UP + """</button>
<button class="vote-btn" data-direction="down" aria-label="Vote down">""" + ICON_THUMBS_DOWN + """</button>
</div>
<a class="card-link with-buttons" href="/story/{{ story.id }}">
{% if story.image_url %}
<img class="card-image" src="{{ story.image_url }}" loading="lazy" alt="">
{% endif %}
{% if story.is_blindspot %}
<span class="blindspot-chip">Not yet in mainstream coverage</span><br>
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
{% if story.ownership_note %}
<p class="ownership-note">{{ story.ownership_note }}</p>
{% endif %}
</a>
</div>
"""

STORY_CARD_LOOP_HTML = """
{% for story in stories %}
""" + CARD_HTML + """
{% endfor %}
{% if not stories %}
<p class="meta">Nothing here yet.</p>
{% endif %}
"""

MAIN_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FeedForge</title>
""" + FAVICON_LINK + """
<style>""" + CSS + """</style>
</head>
<body>
""" + HEADER_HTML + """
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
""" + TOPICS_RAIL_HTML + VIDEO_RAIL_HTML + """
{% for story in stories_part1 %}""" + CARD_HTML + """{% endfor %}
""" + TRENDING_RAIL_HTML + """
{% for story in stories_part2 %}""" + CARD_HTML + """{% endfor %}
""" + REVIEW_RAIL_HTML + """
{% for story in stories_part3 %}""" + CARD_HTML + """{% endfor %}
{% if not stories %}
<p class="meta">Nothing here yet.</p>
{% endif %}
</main>
""" + CARD_INTERACTIONS_JS + VOTE_INTERACTIONS_JS + BACK_TO_TOP_HTML + PULL_TO_REFRESH_HTML + """
</body>
</html>"""

FEED_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FeedForge</title>
""" + FAVICON_LINK + """
<style>""" + CSS + """</style>
</head>
<body>
""" + HEADER_HTML + """
<div class="sticky-nav">
""" + TABS_HTML + """
<div class="segmented">
<a href="{{ recent_url }}" class="segmented-option {{ 'active' if view == 'recent' else '' }}">Most recent</a>
<a href="{{ covered_url }}" class="segmented-option {{ 'active' if view == 'covered' else '' }}">Most covered</a>
</div>
</div>
<div class="legend">
<span><span class="dot" style="background:var(--trust)"></span>Trusted</span>
<span><span class="dot" style="background:var(--niche)"></span>Niche</span>
<span><span class="dot" style="background:var(--comm)"></span>Community</span>
</div>
<div style="max-width:640px;margin:0 auto;padding:0 16px;">
""" + TOPICS_RAIL_HTML + """
</div>
{% if topic_label %}
<p class="topic-heading" style="max-width:640px;margin:0 auto;padding-left:16px;padding-right:16px;">{{ topic_label }}</p>
{% endif %}
<main>
""" + STORY_CARD_LOOP_HTML + """
</main>
""" + CARD_INTERACTIONS_JS + VOTE_INTERACTIONS_JS + BACK_TO_TOP_HTML + PULL_TO_REFRESH_HTML + """
</body>
</html>"""

THEMES_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Themes - FeedForge</title>
""" + FAVICON_LINK + """
<style>""" + CSS + """</style>
</head>
<body>
""" + HEADER_HTML + """
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
""" + BACK_TO_TOP_HTML + PULL_TO_REFRESH_HTML + """
</body>
</html>"""

SEARCH_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Search - FeedForge</title>
""" + FAVICON_LINK + """
<style>""" + CSS + """</style>
</head>
<body>
""" + HEADER_HTML + """
<div class="sticky-nav">
""" + TABS_HTML + """
<form class="search-form" action="/search" method="get">
<input type="text" name="q" value="{{ query }}" placeholder="Search all stories, ever posted..." class="search-input" autofocus>
</form>
</div>
<main style="padding-top:16px;">
{% if query %}
<p class="meta">{{ stories|length }} result{{ 's' if stories|length != 1 else '' }} for "{{ query }}"</p>
{% endif %}
""" + STORY_CARD_LOOP_HTML + """
</main>
""" + CARD_INTERACTIONS_JS + VOTE_INTERACTIONS_JS + BACK_TO_TOP_HTML + PULL_TO_REFRESH_HTML + """
</body>
</html>"""

STORY_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ story.title }} - FeedForge</title>
""" + FAVICON_LINK + """
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
{% if is_blindspot %}
<span class="blindspot-chip">Not yet in mainstream coverage</span>
{% endif %}
{% if ownership_note %}
<p class="ownership-note">{{ ownership_note }}</p>
{% endif %}
{% if story.opencritic_score and story.opencritic_score > 0 %}
<div class="score-block">
<div class="score-circle" style="background:var(--{{ (story.opencritic_tier or 'strong')|lower }}-bg); color:var(--{{ (story.opencritic_tier or 'strong')|lower }}-fg);">{{ story.opencritic_score|round|int }}</div>
<div>
{% if story.opencritic_tier %}<p class="score-tier">{{ story.opencritic_tier }}</p>{% endif %}
<a class="score-link" href="{{ story.opencritic_url }}" target="_blank" rel="noopener">View on OpenCritic &#8599;</a>
</div>
</div>
{% endif %}
<div class="sentiment-block">
<div class="vote-controls inline" data-story-id="{{ story.id }}">
<button class="vote-btn" data-direction="up" aria-label="Vote up">""" + ICON_THUMBS_UP + """</button>
<button class="vote-btn" data-direction="down" aria-label="Vote down">""" + ICON_THUMBS_DOWN + """</button>
</div>
<p class="sentiment-summary">{{ sentiment_summary or "Not enough votes yet" }}</p>
</div>
{% if synopsis %}
<p class="synopsis">{{ synopsis }}</p>
{% endif %}
<p class="section-label">Covered by</p>
{% for a in articles %}
<a class="source-row" href="{{ a.url }}" target="_blank" rel="noopener">
<span class="src-name" style="background:var(--{{ a.source_tier }}-bg); color:var(--{{ a.source_tier }}-fg);">{{ a.source }}</span>
{% if a.timeline_label %}<span class="timeline-badge {{ 'timeline-first' if loop.first else '' }}">{{ a.timeline_label }}</span>{% endif %}
<p class="src-title">{{ a.title }}</p>
<p class="src-meta">{{ a.time_ago }} &middot; <span style="text-decoration:underline;">Read on {{ a.source }} &#8599;</span></p>
</a>
{% endfor %}
</main>
""" + VOTE_INTERACTIONS_JS + BACK_TO_TOP_HTML + PULL_TO_REFRESH_HTML + """
</body>
</html>"""


def humanize(delta_seconds):
    if delta_seconds < 3600:
        return f"{max(1, int(delta_seconds // 60))}m ago"
    if delta_seconds < 86400:
        return f"{int(delta_seconds // 3600)}h ago"
    return f"{int(delta_seconds // 86400)}d ago"


def humanize_delay(delta_seconds):
    """Format a gap between two timestamps for the coverage-timeline
    badges on the story detail page - e.g. "+47m", "+3h", "+2d". Distinct
    from humanize() above, which formats "how long ago from now" - this
    formats "how long after some other event," a different question.
    """
    if delta_seconds < 60:
        return "under a minute"
    if delta_seconds < 3600:
        return f"{int(delta_seconds // 60)}m"
    if delta_seconds < 86400:
        return f"{int(delta_seconds // 3600)}h"
    return f"{int(delta_seconds // 86400)}d"


def compute_ownership_note(sources):
    """Given a list of (source, tier) tuples for a story, check whether
    2+ of them share a known ultimate parent company (SOURCE_OWNERSHIP
    above). Returns a short human sentence, or None if nothing to flag -
    most stories won't trigger this, and that's fine; only sources we
    have verified data for are ever considered, so an unmapped outlet is
    simply silent rather than assumed independent.
    """
    groups = {}
    for name, _tier in sources:
        parent = SOURCE_OWNERSHIP.get(name)
        if parent:
            groups.setdefault(parent, []).append(name)
    for parent, names in groups.items():
        if len(names) < 2:
            continue
        if len(names) == 2:
            return f"{names[0]} and {names[1]} are both owned by {parent}"
        return f"{', '.join(names[:-1])}, and {names[-1]} are all owned by {parent}"
    return None


def compute_sentiment_summary(like_count, dislike_count):
    """Reader-driven sentiment (added 14 Aug 2026): real explicit up/down
    votes rather than anything inferred from text. Returns None below
    MIN_VOTES_FOR_SENTIMENT rather than a percentage that would be
    mathematically correct but misleadingly precise for a tiny sample -
    callers render "Not enough votes yet" in that case instead.
    """
    total = (like_count or 0) + (dislike_count or 0)
    if total < MIN_VOTES_FOR_SENTIMENT:
        return None
    pct = round((like_count or 0) / total * 100)
    return f"{pct}% liked this ({total} vote{'s' if total != 1 else ''})"


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


def all_topic_tiles():
    return [(key, t["label"]) for key, t in TOPICS.items()]


def fetch_rail(kind):
    """A short, glanceable preview strip - inspired by Ground News's
    homepage rails. Deliberately not a replacement for the full
    Reviews/Video tabs: short (RAIL_LIMIT items), no discard/vote
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
            s.like_count,
            s.dislike_count,
            count(*) AS n,
            count(*) FILTER (WHERE a.source_tier = 'trusted') AS trusted_n,
            count(*) FILTER (WHERE a.source_tier = 'niche') AS niche_n,
            count(*) FILTER (WHERE a.source_tier = 'community') AS community_n,
            max(COALESCE(a.published_at, a.fetched_at)) AS latest
        FROM stories s
        JOIN articles a ON a.story_id = s.id
        WHERE 1=1 {tab_where}
        AND s.dismissed_at IS NULL
        GROUP BY s.id, s.title, s.opencritic_score, s.opencritic_tier, s.read_at, s.like_count, s.dislike_count
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
            "is_blindspot": row["trusted_n"] == 0 and row["n"] >= 2,
            "ownership_note": compute_ownership_note(sources),
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


def fetch_search_results(query):
    """Full-text search over story titles, spanning all history - no
    FEED_WINDOW_DAYS limit and no MIN_SOURCES_DEFAULT filter, deliberately.
    Search is a different use case from the feed: the feed answers "what's
    fresh right now," search answers "I remember seeing something about
    this, where did it go" - filtering search results by recency or
    coverage count would work against exactly what it's for. Dismissed
    stories are still excluded (an explicit "not interested" shouldn't be
    resurrected by search), but read stories are included (sorted after
    unread ones, same as everywhere else) since a read story is exactly
    the kind of thing you'd search for.

    Uses Postgres's built-in full-text search (to_tsvector/plainto_tsquery)
    rather than a plain ILIKE substring match - real relevance ranking and
    basic stemming ("review" matches "reviewed") for zero new
    infrastructure. tsvector is computed on the fly rather than stored in
    a column - at our current scale (low thousands of rows) a sequential
    scan is fast enough that a persisted/indexed column isn't needed yet;
    worth revisiting only if search ever feels slow in practice.

    v1 scope is story titles only, not article titles/summaries - a
    deliberate choice to ship a smaller, simpler thing first and expand
    recall later if it feels too narrow.
    """
    query = (query or "").strip()

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    stories = []
    if query:
        cur.execute(
            """
            SELECT
                s.id,
                s.title,
                s.opencritic_score,
                s.opencritic_tier,
                s.read_at,
                s.like_count,
                s.dislike_count,
                count(*) AS n,
                count(*) FILTER (WHERE a.source_tier = 'trusted') AS trusted_n,
                count(*) FILTER (WHERE a.source_tier = 'niche') AS niche_n,
                count(*) FILTER (WHERE a.source_tier = 'community') AS community_n,
                max(COALESCE(a.published_at, a.fetched_at)) AS latest,
                ts_rank(to_tsvector('english', s.title), plainto_tsquery('english', %s)) AS rank
            FROM stories s
            JOIN articles a ON a.story_id = s.id
            WHERE s.dismissed_at IS NULL
            AND to_tsvector('english', s.title) @@ plainto_tsquery('english', %s)
            GROUP BY s.id, s.title, s.opencritic_score, s.opencritic_tier, s.read_at, s.like_count, s.dislike_count
            ORDER BY (s.read_at IS NOT NULL), rank DESC, latest DESC
            LIMIT 40
            """,
            (query, query),
        )
        story_rows = cur.fetchall()

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
                "is_blindspot": row["trusted_n"] == 0 and row["n"] >= 2,
                "ownership_note": compute_ownership_note(sources),
            })

    cur.execute("SELECT count(DISTINCT source) FROM articles")
    source_count = cur.fetchone()["count"]

    cur.close()
    conn.close()
    return stories, source_count


def fetch_topic_stories(topic_key, view="recent"):
    """Topic pages (added 12 Aug 2026): a story qualifies if EITHER at
    least one of its sources is a dedicated outlet for the topic
    (TOPICS[key]["sources"]), OR its title matches a fixed keyword
    OR-query (TOPICS[key]["keywords"], using real tsquery '|' OR syntax,
    not plainto_tsquery's implicit AND) - source identity is the primary,
    high-precision signal; keywords add recall for stories from
    non-platform-specific outlets that are still clearly on-topic. Uses
    the same FEED_WINDOW_DAYS/no-MIN_SOURCES_DEFAULT posture as the main
    feed (a topic page should feel like a live current slice, not an
    archive) - unlike fetch_search_results, which deliberately ignores
    both.
    """
    topic = TOPICS.get(topic_key)
    if not topic:
        return [], 0

    order_by = "n DESC, latest DESC" if view == "covered" else "latest DESC"

    conditions = []
    params = []
    if topic.get("sources"):
        conditions.append("EXISTS (SELECT 1 FROM articles a2 WHERE a2.story_id = s.id AND a2.source = ANY(%s))")
        params.append(topic["sources"])
    if topic.get("keywords"):
        conditions.append("to_tsvector('english', s.title) @@ to_tsquery('english', %s)")
        params.append(topic["keywords"])
    topic_where = "AND (" + " OR ".join(conditions) + ")"

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        f"""
        SELECT
            s.id, s.title, s.opencritic_score, s.opencritic_tier, s.read_at,
            s.like_count, s.dislike_count,
            count(*) AS n,
            count(*) FILTER (WHERE a.source_tier = 'trusted') AS trusted_n,
            count(*) FILTER (WHERE a.source_tier = 'niche') AS niche_n,
            count(*) FILTER (WHERE a.source_tier = 'community') AS community_n,
            max(COALESCE(a.published_at, a.fetched_at)) AS latest
        FROM stories s
        JOIN articles a ON a.story_id = s.id
        WHERE s.dismissed_at IS NULL
        {topic_where}
        GROUP BY s.id, s.title, s.opencritic_score, s.opencritic_tier, s.read_at, s.like_count, s.dislike_count
        HAVING max(COALESCE(a.published_at, a.fetched_at)) > now() - interval '{FEED_WINDOW_DAYS} days'
        ORDER BY (s.read_at IS NOT NULL), {order_by}
        LIMIT 30
        """,
        params,
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
            "is_blindspot": row["trusted_n"] == 0 and row["n"] >= 2,
            "ownership_note": compute_ownership_note(sources),
        })

    cur.execute("SELECT count(DISTINCT source) FROM articles")
    source_count = cur.fetchone()["count"]

    cur.close()
    conn.close()
    return stories, source_count


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
        # Split into three chunks so the rails above can be interspersed
        # through the list (video rail, then part1, trending rail, then
        # part2, reviews rail, then part3) instead of all three rails
        # sitting stacked before any real story content - see
        # VIDEO_RAIL_HTML's comment for the reasoning.
        stories_part1 = stories[:10]
        stories_part2 = stories[10:20]
        stories_part3 = stories[20:]
    else:
        trending = None
        review_rail = None
        video_rail = None
        stories_part1 = stories
        stories_part2 = []
        stories_part3 = []

    return render_template_string(
        MAIN_TEMPLATE, stories=stories, source_count=source_count,
        stories_part1=stories_part1, stories_part2=stories_part2, stories_part3=stories_part3,
        active_tab="main", view=view, show_all=show_all, hidden_count=hidden_count,
        recent_url=build_url("/", view="recent", show_all=show_all),
        covered_url=build_url("/", view="covered", show_all=show_all),
        toggle_url=build_url("/", view=view, show_all=not show_all),
        show_filter_toggle=True,
        show_rails=show_rails, trending=trending, review_rail=review_rail, video_rail=video_rail,
        topic_tiles=all_topic_tiles(), active_topic=None,
    )


@app.route("/reviews")
def reviews():
    view = valid_view()
    stories, source_count, _ = fetch_stories(tab="reviews", view=view)
    return render_template_string(
        FEED_TEMPLATE, stories=stories, source_count=source_count,
        active_tab="reviews", view=view,
        recent_url=build_url("/reviews", view="recent"),
        covered_url=build_url("/reviews", view="covered"),
        topic_tiles=all_topic_tiles(), active_topic=None, topic_label=None,
    )


@app.route("/video")
def video():
    view = valid_view()
    stories, source_count, _ = fetch_stories(tab="video", view=view)
    return render_template_string(
        FEED_TEMPLATE, stories=stories, source_count=source_count,
        active_tab="video", view=view,
        recent_url=build_url("/video", view="recent"),
        covered_url=build_url("/video", view="covered"),
        topic_tiles=all_topic_tiles(), active_topic=None, topic_label=None,
    )


@app.route("/topic/<key>")
def topic(key):
    topic_def = TOPICS.get(key)
    if not topic_def:
        return "Topic not found", 404
    view = valid_view()
    stories, source_count = fetch_topic_stories(key, view=view)
    return render_template_string(
        FEED_TEMPLATE, stories=stories, source_count=source_count,
        active_tab=None, view=view,
        recent_url=build_url(f"/topic/{key}", view="recent"),
        covered_url=build_url(f"/topic/{key}", view="covered"),
        topic_label=topic_def["label"],
        topic_tiles=all_topic_tiles(), active_topic=key,
    )


@app.route("/search")
def search():
    query = request.args.get("q", "")
    stories, source_count = fetch_search_results(query)
    return render_template_string(
        SEARCH_TEMPLATE,
        stories=stories, source_count=source_count, query=query.strip(),
        active_tab=None,
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


@app.route("/story/<int:story_id>/vote/<direction>", methods=["POST"])
def vote_story(story_id, direction):
    # Reader-driven sentiment (added 14 Aug 2026), replacing the old
    # single-toggle /like route entirely. Simple incrementing counters,
    # no per-voter table - see the schema comment in ingest.py for why
    # (no accounts yet to key a real per-voter record on). direction is
    # validated against a fixed set before touching the column name, so
    # the f-string below is never fed anything from user input directly.
    if direction not in ("up", "down"):
        return jsonify(ok=False, error="invalid direction"), 400
    column = "like_count" if direction == "up" else "dislike_count"
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        f"UPDATE stories SET {column} = {column} + 1 WHERE id = %s RETURNING like_count, dislike_count",
        (story_id,),
    )
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    if row is None:
        return jsonify(ok=False), 404
    return jsonify(ok=True, like_count=row["like_count"], dislike_count=row["dislike_count"])


@app.route("/story/<int:story_id>")
def story_detail(story_id):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """
        SELECT id, title, is_review, is_video, opencritic_score, opencritic_tier, opencritic_url,
               like_count, dislike_count
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
    is_blindspot = trusted_n == 0 and len(articles) >= 2
    ownership_note = compute_ownership_note([(a["source"], a["source_tier"]) for a in articles])
    sentiment_summary = compute_sentiment_summary(story["like_count"], story["dislike_count"])

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

    # Coverage timeline (added 12 Aug 2026): articles is already ordered
    # ASC by published_at from the query above, so articles[0] is
    # genuinely the earliest. Reuses that same ordering rather than
    # building a separate visualization - the existing "Covered by" list
    # order already IS the timeline; these badges just make the
    # relationship explicit instead of implicit.
    first_published = articles[0]["published_at"] if articles else None
    show_timeline = len(articles) > 1
    for i, a in enumerate(articles):
        if not show_timeline:
            a["timeline_label"] = None
        elif i == 0:
            a["timeline_label"] = "First to cover this"
        elif a["published_at"] and first_published:
            delay = (a["published_at"] - first_published).total_seconds()
            a["timeline_label"] = f"+{humanize_delay(delay)} after first"
        else:
            a["timeline_label"] = None

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
        is_blindspot=is_blindspot,
        ownership_note=ownership_note,
        sentiment_summary=sentiment_summary,
        n=len(articles),
        trusted_n=trusted_n,
        niche_n=niche_n,
        community_n=community_n,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
