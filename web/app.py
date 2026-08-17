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
RAIL_LIMIT = 8
MIN_VOTES_FOR_SENTIMENT = 5

MIN_SOURCES_DEFAULT = "1"
VALID_MIN_SOURCES = ("1", "2", "3")

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

PLATFORM_SHORT_NAMES = {
    "PC (Microsoft Windows)": "PC",
    "Mac": "Mac",
    "Linux": "Linux",
    "PlayStation 5": "PS5",
    "PlayStation 4": "PS4",
    "Xbox Series X|S": "Xbox Series X|S",
    "Xbox One": "Xbox One",
    "Nintendo Switch": "Switch",
    "Nintendo Switch 2": "Switch 2",
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
padding-top: 40px;
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
.source-filter {
display: flex;
gap: 8px;
padding: 0 16px 14px;
max-width: 640px;
margin: 0 auto;
}
.source-filter-option {
flex: 1;
text-align: center;
font-size: 13px;
font-weight: 600;
padding: 8px 0;
border-radius: 8px;
background: var(--border);
color: var(--text-secondary);
}
.source-filter-option.active {
background: var(--text);
color: var(--bg);
}
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
width: 64px;
height: 85px;
border-radius: 8px;
object-fit: cover;
background: var(--border);
flex-shrink: 0;
}
.calendar-cover-placeholder {
width: 64px;
height: 85px;
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
.calendar-platforms {
display: flex;
flex-wrap: wrap;
gap: 5px;
margin: 4px 0 6px;
}
.platform-chip {
font-size: 11px;
font-weight: 600;
padding: 2px 8px;
border-radius: 20px;
background: var(--border);
color: var(--text-secondary);
}
.calendar-summary {
font-size: 12.5px;
color: var(--text-secondary);
line-height: 1.4;
margin: 4px 0 6px;
}
.calendar-igdb-link {
font-size: 12px;
font-weight: 600;
text-decoration: underline;
color: var(--text-secondary);
}
.calendar-date-inline {
font-size: 12px;
font-weight: 600;
color: var(--text-secondary);
margin: 0 0 6px 2px;
}
.feed-sidebar {
display: none;
}
.sidebar-section {
margin-bottom: 26px;
}
.sidebar-section-header {
display: flex;
justify-content: space-between;
align-items: baseline;
margin-bottom: 10px;
}
.sidebar-item {
display: flex;
gap: 10px;
padding: 8px 0;
border-bottom: 1px solid var(--border);
}
.sidebar-item:last-child {
border-bottom: none;
}
.sidebar-item-image {
width: 64px;
height: 64px;
border-radius: 8px;
object-fit: cover;
background: var(--border);
flex-shrink: 0;
}
.sidebar-item-body {
min-width: 0;
}
.sidebar-item-title {
font-size: 13px;
font-weight: 600;
line-height: 1.35;
margin: 0 0 4px;
display: -webkit-box;
-webkit-line-clamp: 2;
-webkit-box-orient: vertical;
overflow: hidden;
}
.sidebar-item-meta {
font-size: 11.5px;
color: var(--text-secondary);
}
.sidebar-score-chip {
font-size: 11px;
font-weight: 700;
padding: 1px 7px;
border-radius: 20px;
display: inline-block;
margin-right: 6px;
}
@media (min-width: 1040px) {
header, .tabs, .segmented, .source-filter, .legend, main {
max-width: 1000px;
}
.feed-layout {
display: grid;
grid-template-columns: minmax(0, 1fr) 320px;
gap: 36px;
align-items: start;
}
.feed-sidebar {
display: block;
position: sticky;
top: 24px;
}
.mobile-rail {
display: none;
}
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
<div class="rail-section mobile-rail">
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
<div class="rail-section mobile-rail">
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
<div class="rail-section mobile-rail">
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

# Desktop sidebar (added 17 Aug 2026): reuses the exact same trending /
# video_rail / review_rail data as the mobile rails above - no new
# queries - just a vertical, persistent (sticky) layout instead of a
# horizontal scroll strip that only appears once between cards. Hidden
# by default (feed-sidebar has display:none), shown only past the
# 1040px breakpoint where the mobile-rail versions above get hidden
# instead. Topics deliberately stays out of this sidebar and remains a
# horizontal strip at the top on all screen sizes, per the "start
# safer" scope agreed with the user - the fuller 3-column Ground
# News-style layout (Topics as a left rail too) is a possible later
# step, not part of this pass.
SIDEBAR_RAIL_HTML = """
<aside class="feed-sidebar">
{% if trending %}
<div class="sidebar-section">
<div class="sidebar-section-header"><span class="rail-title">Trending</span></div>
{% for item in trending %}
<a class="sidebar-item" href="/story/{{ item.id }}">
{% if item.image_url %}<img class="sidebar-item-image" src="{{ item.image_url }}" loading="lazy" alt="">{% endif %}
<div class="sidebar-item-body">
<p class="sidebar-item-title">{{ item.title }}</p>
<p class="sidebar-item-meta">{{ item.n }} source{{ 's' if item.n != 1 else '' }} &middot; {{ item.time_ago }}</p>
</div>
</a>
{% endfor %}
</div>
{% endif %}
{% if video_rail %}
<div class="sidebar-section">
<div class="sidebar-section-header"><span class="rail-title">New video</span><a class="rail-see-all" href="/video">See all &rarr;</a></div>
{% for item in video_rail %}
<a class="sidebar-item" href="/story/{{ item.id }}">
{% if item.image_url %}<img class="sidebar-item-image" src="{{ item.image_url }}" loading="lazy" alt="">{% endif %}
<div class="sidebar-item-body">
<p class="sidebar-item-title">{{ item.title }}</p>
<p class="sidebar-item-meta">{{ item.time_ago }}</p>
</div>
</a>
{% endfor %}
</div>
{% endif %}
{% if review_rail %}
<div class="sidebar-section">
<div class="sidebar-section-header"><span class="rail-title">Latest reviews</span><a class="rail-see-all" href="/reviews">See all &rarr;</a></div>
{% for item in review_rail %}
<a class="sidebar-item" href="/story/{{ item.id }}">
{% if item.image_url %}<img class="sidebar-item-image" src="{{ item.image_url }}" loading="lazy" alt="">{% endif %}
<div class="sidebar-item-body">
{% if item.opencritic_score and item.opencritic_score > 0 %}<span class="sidebar-score-chip" style="background:var(--{{ (item.opencritic_tier or 'strong')|lower }}-bg); color:var(--{{ (item.opencritic_tier or 'strong')|lower }}-fg);">{{ item.opencritic_score|round|int }}</span>{% endif %}
<p class="sidebar-item-title">{{ item.title }}</p>
<p class="sidebar-item-meta">{{ item.time_ago }}</p>
</div>
</a>
{% endfor %}
</div>
{% endif %}
</aside>
"""

CARD_HTML = """
<div class="card">
<button class="discard-btn" data-action="/story/{{ story.id }}/discard" data-id="{{ story.id }}" aria-label="Discard">""" + ICON_X + """</button>
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

SOURCE_FILTER_HTML = """
<div class="source-filter">
<a href="{{ min1_url }}" class="source-filter-option {{ 'active' if min_sources == '1' else '' }}">1 source</a>
<a href="{{ min2_url }}" class="source-filter-option {{ 'active' if min_sources == '2' else '' }}">2 sources</a>
<a href="{{ min3_url }}" class="source-filter-option {{ 'active' if min_sources == '3' else '' }}">3+ sources</a>
</div>
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
""" + SOURCE_FILTER_HTML + """
</div>
<div class="legend">
<span><span class="dot" style="background:var(--trust)"></span>Trusted</span>
<span><span class="dot" style="background:var(--niche)"></span>Niche</span>
<span><span class="dot" style="background:var(--comm)"></span>Community</span>
</div>
<main>
<div class="feed-layout">
<div class="feed-main">
""" + TOPICS_RAIL_HTML + VIDEO_RAIL_HTML + """
{% for story in stories_part1 %}""" + CARD_HTML + """{% endfor %}
""" + TRENDING_RAIL_HTML + """
{% for story in stories_part2 %}""" + CARD_HTML + """{% endfor %}
""" + REVIEW_RAIL_HTML + """
{% for story in stories_part3 %}""" + CARD_HTML + """{% endfor %}
{% if not stories %}
<p class="meta">Nothing here yet.</p>
{% endif %}
</div>
""" + SIDEBAR_RAIL_HTML + """
</div>
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

CALENDAR_ENTRY_HTML = """
<div class="calendar-entry">
{% if item.cover_url %}
<img class="calendar-cover" src="{{ item.cover_url }}" loading="lazy" alt="">
{% else %}
<div class="calendar-cover-placeholder"></div>
{% endif %}
<div class="calendar-entry-body">
<h3>{{ item.game_name }}</h3>
<div class="calendar-platforms">
{% for p in item.platforms %}
<span class="platform-chip">{{ p }}</span>
{% endfor %}
{% if item.opencritic_score %}
<span class="score-chip" style="background:var(--{{ (item.opencritic_tier or 'strong')|lower }}-bg); color:var(--{{ (item.opencritic_tier or 'strong')|lower }}-fg); margin-bottom:0;">{{ item.opencritic_score|round|int }}</span>
{% endif %}
</div>
{% if item.summary %}
<p class="calendar-summary">{{ item.summary|truncate(140) }}</p>
{% endif %}
{% if item.game_slug %}
<a class="calendar-igdb-link" href="https://www.igdb.com/games/{{ item.game_slug }}" target="_blank" rel="noopener">View on IGDB &#8599;</a>
{% endif %}
</div>
</div>
"""

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
<div class="segmented">
<a href="{{ chrono_url }}" class="segmented-option {{ 'active' if view == 'chronological' else '' }}">Chronological</a>
<a href="{{ hyped_url }}" class="segmented-option {{ 'active' if view == 'hyped' else '' }}">Most anticipated</a>
</div>
</div>
<main style="padding-top:16px;">
{% if view == 'chronological' %}
{% if not groups %}
<p class="meta">No release data yet - check back soon.</p>
{% endif %}
{% for group in groups %}
<div class="calendar-group">
<p class="section-label">{{ group.label }}</p>
{% for item in group.entries %}
""" + CALENDAR_ENTRY_HTML + """
{% endfor %}
</div>
{% endfor %}
{% else %}
{% if not flat_entries %}
<p class="meta">No release data yet - check back soon.</p>
{% endif %}
{% for item in flat_entries %}
<p class="calendar-date-inline">{{ item.release_date_label }}</p>
""" + CALENDAR_ENTRY_HTML + """
{% endfor %}
{% endif %}
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


def valid_min_sources():
    v = request.args.get("min_sources", MIN_SOURCES_DEFAULT)
    return v if v in VALID_MIN_SOURCES else MIN_SOURCES_DEFAULT


def build_url(base_path, view="recent", min_sources=MIN_SOURCES_DEFAULT):
    params = []
    if view == "covered":
        params.append("view=covered")
    if min_sources != MIN_SOURCES_DEFAULT:
        params.append(f"min_sources={min_sources}")
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


def fetch_stories(tab, view, min_sources=MIN_SOURCES_DEFAULT):
    if tab == "reviews":
        tab_where = "AND s.is_review = TRUE"
    elif tab == "video":
        tab_where = "AND s.is_video = TRUE"
    else:
        tab_where = "AND s.is_review = FALSE AND s.is_video = FALSE"

    order_by = "n DESC, latest DESC" if view == "covered" else "latest DESC"

    coverage_having = ""
    if tab == "main" and min_sources in ("2", "3"):
        coverage_having = f"AND count(*) >= {min_sources}"

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

    cur.execute("SELECT count(DISTINCT source) FROM articles")
    source_count = cur.fetchone()["count"]

    cur.close()
    conn.close()
    return stories, source_count


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


def fetch_calendar_entries(view="chronological"):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    order_sql = "hype_val DESC NULLS LAST, gr.release_date ASC" if view == "hyped" else "gr.release_date ASC, gr.game_name ASC"
    cur.execute(
        f"""
        SELECT gr.game_name, gr.release_date,
               array_agg(DISTINCT gr.platform) FILTER (WHERE gr.platform IS NOT NULL) AS platforms,
               (array_agg(gr.cover_url) FILTER (WHERE gr.cover_url IS NOT NULL))[1] AS cover_url,
               (array_agg(gr.game_slug) FILTER (WHERE gr.game_slug IS NOT NULL))[1] AS game_slug,
               (array_agg(gr.summary) FILTER (WHERE gr.summary IS NOT NULL))[1] AS summary,
               max(gr.hype) AS hype_val,
               s.opencritic_score, s.opencritic_tier
        FROM game_releases gr
        LEFT JOIN stories s ON s.opencritic_game_name ILIKE gr.game_name
        WHERE gr.release_date >= CURRENT_DATE
        GROUP BY gr.game_name, gr.release_date, s.opencritic_score, s.opencritic_tier
        ORDER BY {order_sql}
        """
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    for row in rows:
        row["platforms"] = [PLATFORM_SHORT_NAMES.get(p, p) for p in (row["platforms"] or [])]
        row["release_date_label"] = row["release_date"].strftime("%b %-d")

    if view == "hyped":
        return {"flat": rows, "grouped": None}

    grouped = []
    current_key = None
    current_group = None
    for row in rows:
        key = row["release_date"]
        if current_group is None or key != current_key:
            label = key.strftime("%A, %B %-d")
            current_group = {"label": label, "entries": []}
            grouped.append(current_group)
            current_key = key
        current_group["entries"].append(row)
    return {"flat": None, "grouped": grouped}


@app.route("/")
def index():
    view = valid_view()
    min_sources = valid_min_sources()
    stories, source_count = fetch_stories(tab="main", view=view, min_sources=min_sources)

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
        active_tab="main", view=view, min_sources=min_sources,
        recent_url=build_url("/", view="recent", min_sources=min_sources),
        covered_url=build_url("/", view="covered", min_sources=min_sources),
        min1_url=build_url("/", view=view, min_sources="1"),
        min2_url=build_url("/", view=view, min_sources="2"),
        min3_url=build_url("/", view=view, min_sources="3"),
        show_rails=show_rails, trending=trending, review_rail=review_rail, video_rail=video_rail,
        topic_tiles=all_topic_tiles(), active_topic=None,
    )


@app.route("/reviews")
def reviews():
    view = valid_view()
    stories, source_count = fetch_stories(tab="reviews", view=view)
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
    stories, source_count = fetch_stories(tab="video", view=view)
    return render_template_string(
        FEED_TEMPLATE, stories=stories, source_count=source_count,
        active_tab="video", view=view,
        recent_url=build_url("/video", view="recent"),
        covered_url=build_url("/video", view="covered"),
        topic_tiles=all_topic_tiles(), active_topic=None, topic_label=None,
    )


@app.route("/calendar")
def calendar():
    view = request.args.get("view", "chronological")
    view = view if view in ("chronological", "hyped") else "chronological"
    result = fetch_calendar_entries(view)
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT count(DISTINCT source) FROM articles")
    source_count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return render_template_string(
        CALENDAR_TEMPLATE,
        groups=result["grouped"], flat_entries=result["flat"],
        view=view, source_count=source_count, active_tab="calendar",
        chrono_url="/calendar?view=chronological", hyped_url="/calendar?view=hyped",
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
