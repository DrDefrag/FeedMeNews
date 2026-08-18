# FeedMeNews

A self-hosted, mobile-first gaming news aggregator, built the way
[Ground News](https://ground.news) approaches general news: pull the same
story from multiple outlets, group it into one card, and show *who* is
covering it and how much - rather than just another chronological feed.

Live at: https://feedforge.gg

## What it actually does

- Pulls articles from 25 sources every 15 minutes across three content
types - press RSS, Reddit, and YouTube (see table below)
- **Clusters** articles about the same real-world story together (TF-IDF +
cosine similarity), so a story covered by 4 outlets shows as one card
with a "4 sources" coverage bar, not 4 separate entries
- Shows a real **image** on every story card and detail page - hotlinked
to the outlet's own URL, never downloaded or re-hosted. Verified live
across all 25 sources before building: 14/14 press RSS and 7/7 YouTube
channels carry a real image; Reddit's `.rss` format has none at all.
On a multi-source story, the image comes from whichever source ranks
highest by trust tier - same rule already used for picking the synopsis
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
- A **release calendar** (added 16-17 Aug 2026), backed by IGDB - a
date-grouped chronological list (not a month grid; checked how Steam/
IGN/Metacritic present this kind of data before building, a grid isn't
the convention and wouldn't suit mobile) of upcoming and just-released
games, each showing real cover art, platform chips (a game on multiple
platforms merges into one entry, not one per platform), a short
description and a link to the game's real IGDB page, and - at zero
extra API cost - an OpenCritic score if we've already reviewed it
ourselves. Two views: **Chronological** and **Most Anticipated** (sorted
by IGDB's own hype/follower signal, added 17 Aug 2026)
- Five tabs: **Main** / **Reviews** / **Video** / **Calendar** / **Themes**
(Read tab tried and removed - see below). Themes is a descriptive stats
page over your read/discard history (tier, content-type, and outlet
breakdown, plus a lightweight recurring-words stat), *not* a
recommender - it shows patterns, it doesn't yet act on them. Tabs are
filters over the same data, not silos - a video review shows up in both
Reviews and Video
- Main's coverage filter is three explicit buttons - **1 source / 2
sources / 3+ sources** (rebuilt 17 Aug 2026 from an earlier binary
"2+ default, toggle to show all"). Default is 1 source, changed from an
earlier default of 2+ based on real usage - genuinely interesting
single-source stories were being hidden by default more often than the
noise the filter was meant to catch
- Stories age out of the feed entirely after 2 days (`FEED_WINDOW_DAYS`
in `web/app.py`), regardless of read state - rows are never deleted,
just filtered out of view, so the Themes page above still has the full
history to work with
- Read stories **dim in place** (opacity, not moved to a separate view) so
you can see what you've already seen without losing your scroll
position or needing a dedicated destination for it
- **Discard** button on every card (top-left, 44×44pt tap target) to hide
something immediately, permanently, regardless of age
- Reader **up/down voting** on the story detail page (added 14 Aug 2026,
replacing an earlier single Like button) - shows "N% liked this" once a
story has 5+ votes. Removed from feed cards on 18 Aug 2026 after direct
feedback that they cluttered the card view; kept on the detail page only
- **Desktop layout** (added 18 Aug 2026): on screens ≥1040px wide, the
Main feed widens and centers, and the three horizontal-scroll rails
(New video, Trending, Latest reviews) become a persistent sticky right
sidebar instead - inspired directly by Ground News's own desktop layout
(checked live before building), deliberately the narrower "safer" half
of that redesign discussion. Topics stayed a horizontal strip rather
than also becoming a sidebar. Mobile is completely unchanged - same
markup, same CSS, the desktop treatment is purely additive
- No login, no accounts - this is a personal single-user tool. Read/
discard/vote state lives in the database (not the browser, aside from a
small localStorage check to stop double-voting), so it's consistent
across devices, but it's one shared state, not per-visitor - the Themes
page says this plainly on the page itself

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
| Game Developer | Trusted | RSS |
| GamesIndustry.biz | Trusted | RSS |
| VGC | Trusted | YouTube |
| Digital Foundry | Trusted | YouTube |
| DF Clips | Trusted | YouTube |
| Game Informer | Trusted | YouTube |
| Rock Paper Shotgun | Niche | RSS |
| NintendoLife | Niche | RSS |
| VG247 | Niche | RSS |
| Push Square | Niche | RSS |
| Pure Xbox | Niche | RSS |
| PCGamesN | Niche | RSS |
| The Indie Informer | Niche | RSS |
| Indie Game Reviewer | Niche | RSS |
| Kinda Funny Games | Niche | YouTube |
| Fextralife | Niche | YouTube |
| Bellular News | Niche | YouTube |
| r/Games | Community | Reddit (.rss) |
| r/pcgaming | Community | Reddit (.rss) |
| r/NintendoSwitch | Community | Reddit (.rss) |
| r/PS5 | Community | Reddit (.rss) |

29 distinct source names, 32 total feeds (IGN, GameSpot, and Polygon each
appear twice - once per content type).

**Ownership transparency, in the same spirit as what Ground News does for
general news:** Rock Paper Shotgun, VG247, GamesIndustry.biz, and Eurogamer
are all owned by Ziff Davis; PC Gamer and GamesRadar are both owned by
Future plc; Polygon and TheGamer are both owned by Valnet; NintendoLife,
Push Square, and Pure Xbox are all owned by Hookshot Media. Surfaced
directly in the UI as a small note under any story where 2+ sources share
a parent - deliberately added even for outlets already covered elsewhere
(GamesIndustry.biz shares ownership with IGN/Eurogamer/RPS/VG247), since
the point of the feature is surfacing the connection, not avoiding sources
that reveal it.

**Deliberately excluded** (checked live, didn't work or didn't fit):
Destructoid and Siliconera both return 403 Forbidden on their feeds.
r/gaming works technically but its "Hot" listing surfaces community
meta-threads (e.g. "Making Friends Monday") rather than news, so it was
left out in favour of the narrower, more on-topic subreddits above.
r/IndieDev and YouTube curator Jupiter Hadley were both checked and left
out too - the former is almost entirely self-promotional WIP showcases,
the latter's current uploads are entirely serial "Part N" playthroughs
that would never actually surface given the walkthrough exclusion below.

## Architecture

Two Coolify Application resources sharing one Postgres database, all on a
single OVHcloud VPS. **Deploying a change to either file requires
redeploying its own resource separately** - they're two different
Application resources with different Dockerfiles, even though both files
live in the same repo/commit history.

- **`ingest.py`** - long-running worker. Every 15 minutes: fetches all
sources (RSS, YouTube, Reddit), extracts an image URL where available,
clusters recent articles into stories, flags review and video titles,
and (on its own slower hourly cadence, budget-capped) looks up
OpenCritic scores for reviews. On a separate once-a-day cadence, also
fetches upcoming game release dates from IGDB for the Calendar tab.
- **`web/app.py`** - Flask app, server-rendered HTML (no frontend
framework), reads the same database. Routes: `/`, `/reviews`,
`/video`, `/calendar`, `/themes`, `/search`, `/topic/<key>`, plus
`/story/<id>`.

No separate job queue, no cache layer - deliberately kept simple for a
personal-scale project. Postgres is the only shared state.

### Database

Three tables: `articles` (raw ingested items, with `is_video`,
`is_walkthrough`, and `image_url` known unconditionally or extracted at
ingestion), `stories` (clusters, with review-score, video, read/dismissed,
and like/dislike-count columns), and `game_releases` (added 16 Aug 2026 -
backs the Calendar tab; one row per IGDB `release_dates` entry, i.e. one
game+platform+date combination, deduped on IGDB's own row id
`igdb_release_id`; the web app merges multi-platform rows for the same
game+date back into one display card at query time via `array_agg`, it's
not deduped at ingestion). Schema is created/migrated by `ensure_schema()`
in `ingest.py` on every startup (idempotent `CREATE TABLE IF NOT EXISTS`
/ `ALTER TABLE ADD COLUMN IF NOT EXISTS`) - there's no separate migration
tool.

**Read/discard/vote state lives on `stories`**: `read_at` and
`dismissed_at` are timestamp columns (`read_at` only affects dimming in
the feed view, `dismissed_at` hides a story immediately regardless of
age); `like_count`/`dislike_count` are plain incrementing integers with
no per-voter table, so a determined person could vote more than once -
mitigated client-side via a `localStorage` check, same category of
limitation as everywhere else until real accounts exist. Neither read nor
discard ever deletes the underlying row - the feed query filters by
recency and dismissal state, the data itself persists for the Themes
page. (An earlier `archived_at` column, added to support a since-removed
separate Read tab, still exists in the schema but is no longer used by
the app - harmless, not worth a migration to remove. A `community_sentiment`
column stub from an earlier abandoned attempt at reader sentiment *was*
removed via a real migration on 14 Aug 2026, since it was genuinely dead
code, not just superseded.)

**`image_url` is hotlinked, never downloaded or re-hosted** - the same
approach already used for article links and game cover art.

### External APIs

- **OpenCritic**, via RapidAPI's free tier (25 searches/day, 200
requests/day, non-commercial use only). Key lives in Coolify as
`OPENCRITIC_API_KEY`, never committed to the repo. Our own daily budget
(`MAX_OPENCRITIC_LOOKUPS_PER_DAY`) is set well under the real limit for
headroom - lowered from 20 to 10 after usage crept up with more sources.
- **IGDB** (added 16 Aug 2026), via a Twitch Developer app - free for
non-commercial use under the Twitch Developer Services Agreement, 4
req/sec rate limit. Auth is a standard OAuth2 client-credentials grant
(app-only, no interactive login at runtime). Credentials live in
Coolify as `IGDB_CLIENT_ID` / `IGDB_CLIENT_SECRET`, never committed to
the repo. The release-dates query filters to `game.category = 0` (main
games only, excluding DLC/bundles) and `game.hypes != null` - the
latter fixed a real bug where IGDB's own null-hype entries were sorting
*ahead of* genuinely anticipated titles in a descending sort, silently
excluding real games from the fetched window (see project log for the
full story).
- **Reddit's `.rss` endpoints** - not the official JSON API. Reddit blocks
anonymous `.json` requests from most datacenter IP ranges, but the
older Atom `.rss` feeds aren't subject to the same block, just normal
rate limits (15s delay between Reddit requests specifically, longer than
the 5s used for press/YouTube feeds, since Reddit proved more
rate-limit-sensitive as more subreddits were added). Carries no image
data at all - checked the full raw feed across two subreddits, not a
single missing entry, genuinely absent from the format.
- **YouTube's channel RSS feeds** (`youtube.com/feeds/videos.xml?
channel_id=...`) - no API key, no OAuth, no quota. The channel ID isn't
the same as the `@handle` - find it via the `<link rel="alternate"
type="application/rss+xml">` tag on the channel's page. Every entry
reliably includes a `media:thumbnail`.

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
- **No accounts** - read/discard/vote state is one shared record per
story, not per-visitor. The Themes page is currently one shared profile
for the same reason. Fine for a personal tool; adding real accounts
(Google OAuth is the likely direction) would need a proper migration -
read state moving from columns on `stories` to a `user_id`+`story_id`
join table, since "read" becomes a property of a person-and-story pair,
not the story alone.
- **Themes is descriptive, not predictive** - it shows what you've read,
it doesn't (yet) change what the feed shows you based on it. Deliberate
scope choice: validate the signal is meaningful before building
anything that acts on it.
- **Not every article has an image**, even from sources that generally
carry them - some individual RSS entries genuinely lack a thumbnail in
the source feed itself. Cards and detail pages simply show no image
slot in that case rather than a broken one.
- **Calendar has no platform filter or search yet** - ranked lower than
sort-by-anticipation in a direct feedback round on 17 Aug 2026 and not
yet built. A game on multiple platforms shows as one merged card with
platform chips (fixed 17 Aug 2026), but there's no way yet to filter
the list down to just one platform, or search by name.
- **Desktop layout only covers the Main feed's sidebar** - Reviews/Video/
Calendar/Search/Story pages get a wider centered column at desktop
width for visual consistency, but only Main has rail content to show in
a sidebar. The story detail page's "Covered by" list is still a single
long column on every screen size.

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

Check image coverage within the live feed window:
```sql
SELECT count(*) AS total, count(image_url) AS with_image FROM articles
WHERE COALESCE(published_at, fetched_at) > now() - interval '2 days';
```

Check the release calendar's data health:
```sql
SELECT count(*), count(hype), min(release_date), max(release_date) FROM game_releases;
```
`count(hype)` should be close to `count(*)` (a large gap means the
null-hype exclusion filter has regressed); `min(release_date)` should
never be earlier than today.

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

If a newly-deployed field looks wrong on a sample of "recent" rows,
double-check the actual timestamp cutoff before assuming a code bug -
`ON CONFLICT (url) DO NOTHING` means pre-deploy rows can look like
false negatives forever. Verify the underlying function directly against
live data before concluding something's broken.

If an unfamiliar, independently-written version of something you just
built turns up in the repo, don't assume malice or a stray process before
considering the mundane explanation first: a dropped session mid-work
(especially if tool connectivity has been visibly unstable) can mean an
earlier attempt made real progress and a real commit, then lost
continuity before that work could be remembered - the next attempt
simply redoes the same feature from scratch with different naming
choices. Reconcile onto whichever version is actually live rather than
assuming either one is wrong.
