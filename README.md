# FeedMeNews

A self-hosted, mobile-first gaming news aggregator, built the way
[Ground News](https://ground.news) approaches general news: pull the same
story from multiple outlets, group it into one card, and show *who* is
covering it and how much - rather than just another chronological feed.

Live at: http://bj5bgvbwfrf4z0xkuwjeph24.51.38.82.48.sslip.io/

## What it actually does

- Pulls articles from 25 sources every 15 minutes across three content
  types - press RSS, Reddit, and YouTube (see table below)
- **Clusters** articles about the same real-world story together (TF-IDF +
  cosine similarity), so a story covered by 4 outlets shows as one card
  with a "4 sources" coverage bar, not 4 separate entries
- Colour-codes each source by **trust tier** - Trusted / Niche / Community
  - on every story card, so at a glance you can see whether something is
  backed by mainstream press or is a single Reddit post
- Detects **review** stories (text or video - the check is on the title,
  source-agnostic) and looks up a real critic score from OpenCritic, shown
  as a coloured badge (Mighty/Strong/Fair/Weak)
- Detects **video** stories and excludes **walkthroughs/playthroughs**
  from clustering entirely (they're serial, not episodic, and would either
  flood the feed or merge into nonsense "stories" otherwise) - the raw
  rows are kept, just never linked to a story, so nothing is thrown away
- Three tabs (**Main** / **Reviews** / **Video**), each with three views:
  **Most recent** (default), **Most covered**, and **Read** (things
  you've opened or discarded, kept as a permanent record rather than just
  hidden). Tabs are filters, not silos - a video review shows up in both
  Reviews and Video
- **Discard** button on every card (top-left, 44×44pt tap target) to
  clear something from view instantly, without a page reload - including
  from within the Read tab itself, which permanently removes it via a
  separate "archived" state layered on top
- No login, no accounts - this is a personal single-user tool. Read/
  discard/archive state lives in the database (not the browser), so it's
  consistent across devices, but it's one shared state, not per-visitor

## Sources

| Source | Tier | Type |
|---|---|---|
| IGN | Trusted | RSS + YouTube |
| Polygon | Trusted | RSS + YouTube |
| PC Gamer | Trusted | RSS |
| Eurogamer | Trusted | RSS |
| GameSpot | Trusted | RSS + YouTube |
| GamesRadar | Trusted | RSS |
| Kotaku | Trusted | RSS |
| TheGamer | Trusted | RSS |
| VGC | Trusted | YouTube |
| Digital Foundry | Trusted | YouTube |
| Game Informer | Trusted | YouTube |
| Rock Paper Shotgun | Niche | RSS |
| NintendoLife | Niche | RSS |
| VG247 | Niche | RSS |
| Push Square | Niche | RSS |
| Pure Xbox | Niche | RSS |
| PCGamesN | Niche | RSS |
| Kinda Funny Games | Niche | YouTube |
| r/Games | Community | Reddit (.rss) |
| r/pcgaming | Community | Reddit (.rss) |
| r/NintendoSwitch | Community | Reddit (.rss) |
| r/PS5 | Community | Reddit (.rss) |

22 distinct source names, 25 total feeds (IGN, GameSpot, and Polygon each
appear twice - once per content type).

**Ownership transparency, in the same spirit as what Ground News does for
general news:** Rock Paper Shotgun is owned by IGN Entertainment; PC Gamer
and GamesRadar are both owned by Future plc. Not yet surfaced in the UI,
but the data's worth knowing.

**Deliberately excluded** (checked live, didn't work or didn't fit):
Destructoid and Siliconera both return 403 Forbidden on their feeds.
r/gaming works technically but its "Hot" listing surfaces community
meta-threads (e.g. "Making Friends Monday") rather than news, so it was
left out in favour of the narrower, more on-topic subreddits above.

## Architecture

Two Coolify Application resources sharing one Postgres database, all on a
single OVHcloud VPS. **Deploying a change to either file requires
redeploying its own resource separately** - they're two different
Application resources with different Dockerfiles, even though both files
live in the same repo/commit history.

- **`ingest.py`** - long-running worker. Every 15 minutes: fetches all
  sources (RSS, YouTube, Reddit), clusters recent articles into stories,
  flags review and video titles, and (on its own slower hourly cadence,
  budget-capped) looks up OpenCritic scores for reviews.
- **`web/app.py`** - Flask app, server-rendered HTML (no frontend
  framework), reads the same database. Routes: `/`, `/reviews`,
  `/video`, plus `/story/<id>`.

No separate job queue, no cache layer - deliberately kept simple for a
personal-scale project. Postgres is the only shared state.

### Database

Two tables: `articles` (raw ingested items, with `is_video` and
`is_walkthrough` flags known unconditionally at ingestion) and `stories`
(clusters, with review-score, video, and read/dismissed/archived columns).
Schema is created/migrated by `ensure_schema()` in `ingest.py` on every
startup (idempotent `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE ADD
COLUMN IF NOT EXISTS`) - there's no separate migration tool.

**Read/discard/archive state is three separate timestamp columns on
`stories`** (`read_at`, `dismissed_at`, `archived_at`), layered rather
than replacing each other - nothing is ever deleted, each new need has
just added another filter on top. `read_at`/`dismissed_at` together
define the Read tab; `archived_at` permanently removes something from
Read itself once there.

### External APIs

- **OpenCritic**, via RapidAPI's free tier (25 searches/day, 200
  requests/day, non-commercial use only). Key lives in Coolify as
  `OPENCRITIC_API_KEY`, never committed to the repo. Our own daily budget
  (`MAX_OPENCRITIC_LOOKUPS_PER_DAY`) is set well under the real limit for
  headroom - lowered from 20 to 10 after usage crept up with more sources.
- **Reddit's `.rss` endpoints** - not the official JSON API. Reddit blocks
  anonymous `.json` requests from most datacenter IP ranges, but the
  older Atom `.rss` feeds aren't subject to the same block, just normal
  rate limits (15s delay between Reddit requests specifically, longer than
  the 5s used for press/YouTube feeds, since Reddit proved more
  rate-limit-sensitive as more subreddits were added).
- **YouTube's channel RSS feeds** (`youtube.com/feeds/videos.xml?
  channel_id=...`) - no API key, no OAuth, no quota. The channel ID isn't
  the same as the `@handle` - find it via the `<link rel="alternate"
  type="application/rss+xml">` tag on the channel's page.

## Known limitations (accepted tradeoffs, not bugs)

- **Story clustering** is TF-IDF similarity on titles, not real language
  understanding. Two known failure classes, both found via real data:
  boilerplate marketing phrases (fixed via an extended stopword list) and
  **multi-game showcase events** (not yet fixed - when one event announces
  several different games, outlets often put the event name in every
  game's individual trailer title, which can falsely cluster genuinely
  different games together; deferred since the fix isn't a simple
  stopword add without risking legitimate same-event clusters). Recomputes
  from scratch every run, so a clustering logic change needs a manual
  reset (see below) - splitting stories apart isn't automatic.
- **Review score matching** rejects a search result if it shares no real
  word with the query, which fixes most wrong matches but can still let
  through two different games that happen to share one generic word.
- **No pros/cons summary** for reviews - deliberately out of scope for
  now, since doing it well would need an LLM step, which is a genuinely
  bigger piece of infrastructure than anything else here.
- **No accounts** - read/discard/archive state is one shared record per
  story, not per-visitor. Fine for a personal tool, would need real auth
  to support multiple people.

## Local operational notes

Reset story clustering after a logic change (forces a full rebuild on the
next run):
```sql
UPDATE articles SET story_id = NULL;
DELETE FROM stories;
```

Reset review-score matching after a logic change:
```sql
UPDATE stories SET opencritic_checked_at = NULL, opencritic_score = NULL,
  opencritic_tier = NULL, opencritic_url = NULL, opencritic_review_count = NULL,
  opencritic_game_name = NULL WHERE is_review = TRUE;
```

Check source health:
```sql
SELECT source, count(*) FROM articles GROUP BY source ORDER BY source;
```

Note: `docker logs` / Coolify's log viewer can show "No logs yet" even
when the ingestion script is actively running - Python's `print()` is
buffered when stdout isn't a real terminal, and `PYTHONUNBUFFERED=1` is
set specifically to avoid this. If logs ever seem stuck again, check the
database directly rather than trusting an empty log panel.

Don't repeatedly restart the ingestion container to "check if a rate
limit cleared up" - each restart triggers a fresh run that hits the same
rate-limited source again, adding to the exact problem being diagnosed.
Fix the code once, ship it, and let the next natural 15-minute cycle
confirm it.
