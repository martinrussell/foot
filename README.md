# Football App: Player Stats Data Flow and Architecture

## Overview
This Flask app fetches football data from the `footapi7` RapidAPI, persists per-player match statistics into a local SQLite database, and renders pages for fixtures, matches, and teams. Styling is handled with Tailwind via a base Jinja layout.

Key modules:
- `app.py`: Routes for fixtures, match and team pages
- `team_detail.py`: Fetches team info, collects player stats, persists to SQLite, renders `team_detail.html`
- `run.py`: Batch process to pre-populate the SQLite table for all fixtures of the day
- `match_detail.py`: Fetches a single match with lineups and incidents, renders `match_detail.html`
- `templates/team_detail.html`: Displays players with per-match metrics from API/DB
- `database.sqlite`: Local persistent store for per-player per-match statistics

## Data model
SQLite table: `player_match_statistics`
- `match_id` (INT)
- `player_id` (INT)
- `wasFouled` (INT)
- `fouls` (INT)
- `shotOffTarget` (INT)
- `shotOnTarget` (INT)
- `yellowCardsCount` (INT)
- `redCard` (BOOLEAN)
- `avg_minutes_played` (FLOAT)
- Primary key: `(match_id, player_id)`

This schema stores API-derived stats per player per match, plus an average minutes figure per player across the last finished matches considered in the job/request.

## How stats are gathered and saved
There are two paths that populate the DB and in-memory data structures.

1) On-demand via `team_detail.py`
- Route: `/team/<team_id>` calls `team_detail(team_id)`
- Fetches team, players, and last finished matches
- For each player and each of the last finished matches:
  - Checks DB for existing record with `fetch_statistics_if_exists(match_id, player_id)`
  - If not found, calls two APIs:
    - Player statistics: `GET /api/match/{match_id}/player/{player_id}/statistics`
    - Match incidents: `GET /api/match/{match_id}/incidents` to derive `yellowCardsCount` and `redCard`
  - Builds `fouls_data[player_id][match_id]` and `cards_data[player_id][match_id]`
  - Tracks `minutesPlayed` to compute `avg_minutes_played[player_id]`
  - Persists with `insert_data(...)` into SQLite
- Returns `render_template('team_detail.html', ...)` with:
  - `players`, `matches` (last finished), `fouls_data`, `cards_data`, `lineups`, `avg_minutes_played`

2) Batch pre-population via `run.py`
- `get_fixtures()` fetches today’s top matches, then for each event runs `team_detail(home_team_id)` and `team_detail(away_team_id)` in a thread pool to warm the DB
- The same logic in `team_detail(team_id)` writes into SQLite via `insert_data(...)`

Note: `update.py` contains exploratory/async code for gathering player stats but is not wired into the main flow; the authoritative batch path is `run.py`.

## How stats are shown on team_detail.html
`templates/team_detail.html` renders a DataTable of players vs. matches:
- The template receives `players`, `matches`, `fouls_data`, `cards_data`
- For each player row and each match column, it displays:
  - Was Fouled, Fouls, Shots Off/On Target from `fouls_data[player_id][match_id]`
  - Yellow/Red from `cards_data[player_id][match_id]`
  - Minutes Played from the same `fouls_data` entry (or derived average)
- Client-side buttons toggle highlighting for specific metrics
- Lineup info is also shown if `lineups` are provided

Because `team_detail(team_id)` also reads from SQLite if data exists, repeated views can avoid re-hitting the external APIs for already-cached records.

## Execution paths
- Dev server: `python app.py` and browse `/team/<team_id>` to on-demand populate and view
- Batch warm: `python run.py` to pre-populate today’s teams’ players' stats into SQLite

## Architecture review and recommendations
Current state:
- App mixes data fetching, processing, and persistence inside request handlers
- Batch pre-population uses Flask code paths directly (thread pool) and SQLite per-thread connections
- Persistence is raw SQL; no migrations
- API keys live in code files

Recommendations:
1) Separate concerns into layers
- Create a `services/` module for API clients: `footapi.py` with typed functions (requests, retries)
- Create a `repositories/` module for DB operations (using SQLAlchemy or at least a thin DAL) with connection management, schema, and migrations (alembic)
- Create a `use_cases/` module: orchestrate “collect player stats for team” separate from Flask handlers

2) Move batch jobs out of web request context
- Extract the warmup logic into a CLI (e.g., `cli.py`) or a Celery/RQ worker
- Schedule with cron or APScheduler
- Share code with web layer via the use case modules

3) Improve data model
- Normalize tables: `matches`, `players`, `teams`, `player_match_stats`
- Add FKs and indexes for `player_id`, `match_id`
- Track `tournament_id`, `status`, timestamps
- Store raw JSON snapshots per API call for auditability and reprocessing

4) Caching and rate limiting
- Add a short TTL cache (Redis) for API responses to reduce external calls
- Implement polite rate limiting/backoff with tenacity; batch calls with concurrency limits (async httpx + asyncio)

5) Config and secrets
- Move `HEADERS` and API keys to environment variables; use `python-dotenv` locally
- Parameterize DB path

6) Resilience and observability
- Centralize logging; add structured logs with context (team_id, match_id, player_id)
- Catch and classify API errors; retry transient ones; mark failures in DB

7) Frontend consistency
- Remove in-template heavy CSS and external frameworks (Bootstrap + Tailwind + jQuery) conflicts
- Standardize Tailwind via `base.html` and component partials; migrate DataTables usage to a lightweight JS table or server-side rendering

8) Performance
- When computing averages, compute once per player after loop rather than per match insertion
- Use set-based inserts or transaction batching when writing many rows

9) Testing
- Add unit tests for repository and service layers with mocked API responses
- Add an integration test that exercises the end-to-end flow on a small fixture

## Quick start
- Set `RAPIDAPI_KEY` in environment and expose via `config.py`
- Create venv, install Flask and deps
- Run app: `python app.py`
- Visit `/team/<team_id>` to populate and view stats
- Optional: `python run.py` to pre-warm DB for today’s fixtures

## Future options
- Move to Postgres; use SQLAlchemy models and Alembic migrations
- Add a small worker (Celery/RQ) for background ingestion and scheduled refresh
- Expose a JSON API for stats; consider a React + Chakra UI frontend consuming these endpoints

## Speeding up database population (implemented in run.py)
Prioritized strategies now in place:
- Reuse a single `requests.Session` for connection pooling
- Fetch incidents once per match and reuse per-player (no duplicate calls)
- Batch DB writes in a single transaction with SQLite PRAGMAs for faster I/O (`WAL`, `synchronous=NORMAL`, `temp_store=MEMORY`)
- Use bulk upserts (`ON CONFLICT(match_id, player_id) DO UPDATE`) instead of pre-check SELECTs

Key code areas:
- Session reuse: `SESSION = requests.Session(); SESSION.headers.update(HEADERS)`
- Incidents map per match: build `incidents_by_match[match_id] = {player_id: (yellow_count, red_bool)}` once
- Bulk upsert: `upsert_rows(conn, rows_to_write)` inside a single `BEGIN`/`COMMIT`

Tunable knobs:
- Thread pool `max_workers` in `get_fixtures()`; increase cautiously to respect API limits
- Consider `asyncio + httpx` for higher throughput if needed
- Add short TTL caching (Redis) to avoid repeated stats calls across runs
