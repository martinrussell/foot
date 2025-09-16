import requests
import time
from flask import Flask, render_template, jsonify
from config import HEADERS
from requests.exceptions import JSONDecodeError
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import os
from logging.handlers import RotatingFileHandler
import random

# Establish a database connection
conn = sqlite3.connect("database.sqlite")


# Create table if it doesn't exist
def create_table():
    conn = sqlite3.connect("database.sqlite")
    try:
        cur = conn.cursor()
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS player_match_statistics (
            match_id INT,
            player_id INT,
            wasFouled INT,
            fouls INT,
            shotOffTarget INT,
            shotOnTarget INT,
            yellowCardsCount INT,
            redCard BOOLEAN,
            avg_minutes_played FLOAT,
            PRIMARY KEY (match_id, player_id)
        );
        """
        cur.execute(create_table_sql)
        conn.commit()
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        cur.close()
        conn.close()


# Call create_table function to ensure table exists
create_table()

# Configure rotating file logger for player stats
LOG_PATH = os.path.join(os.path.dirname(__file__), "player_stats.log")
player_logger = logging.getLogger("player_stats")
player_logger.setLevel(logging.INFO)
if not player_logger.handlers:
    _handler = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=3)
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    player_logger.addHandler(_handler)
    player_logger.propagate = False


def _parse_retry_after(headers):
    try:
        val = headers.get("Retry-After") or headers.get("retry-after")
        if not val:
            return None
        return float(val)
    except Exception:
        return None


def http_get_with_retry(url, headers, max_attempts=8, backoff_base=0.75, backoff_cap=10.0):
    attempts = 0
    delays = []
    last_resp = None
    while attempts < max_attempts:
        attempts += 1
        resp = requests.get(url, headers=headers)
        status = resp.status_code
        if status == 200:
            return resp, attempts, delays
        # Retry on rate limits and transient errors (do NOT retry 204)
        if status in (420, 429, 408, 500, 502, 503, 504):
            retry_after = _parse_retry_after(resp.headers)
            wait = retry_after if retry_after is not None else min(
                backoff_cap, backoff_base * (2 ** (attempts - 1)) + random.random() * 0.25
            )
            try:
                print(f"Retry {attempts} ({status}) for {url} — waiting {wait:.2f}s")
            except Exception:
                pass
            try:
                time.sleep(wait)
            except Exception:
                pass
            delays.append(wait)
            last_resp = resp
            continue
        # Non-retriable
        return resp, attempts, delays
    return (last_resp or resp), attempts, delays


def get_new_connection():
    return sqlite3.connect("database.sqlite")


def fetch_statistics_if_exists(match_id, player_id):
    """Fetch player statistics if they exist for a given match_id and player_id."""
    conn = get_new_connection()  # get a database connection
    cur = conn.cursor()

    query = """
        SELECT 
            wasFouled, fouls, shotOffTarget, shotOnTarget, 
            yellowCardsCount, redCard, avg_minutes_played
        FROM player_match_statistics 
        WHERE match_id = ? AND player_id = ? LIMIT 1
    """
    cur.execute(query, (match_id, player_id))
    result = cur.fetchone()
    conn.close()

    if result:
        return True, result  # Record exists, return True and the fetched values
    else:
        return False, None  # Record does not exist, return False and None


def insert_data(match_id, player_id, fouls_data, cards_data, avg_minutes_played_dict, api_context=None, source="api"):
    fouls_entry = fouls_data[player_id].get(match_id, {})
    cards_entry = cards_data[player_id].get(match_id, {})

    # Store per-match minutesPlayed in the DB (column name kept for compatibility)
    if isinstance(fouls_entry, dict):
        avg_minutes_played = fouls_entry.get("minutesPlayed", 0)
    else:
        avg_minutes_played = 0

    was_fouled = fouls_entry.get("wasFouled", 0)
    fouls = fouls_entry.get("fouls", 0)
    shot_off_target = fouls_entry.get("shotOffTarget", 0)
    shot_on_target = fouls_entry.get("shotOnTarget", 0)
    yellow_cards_count = cards_entry.get("yellowCardsCount", 0)
    red_card = cards_entry.get("redCard", False)

    sql = (
        "INSERT INTO player_match_statistics(\n"
        "  match_id, player_id, wasFouled, fouls, shotOffTarget, shotOnTarget, yellowCardsCount, redCard, avg_minutes_played\n"
        ") VALUES(?,?,?,?,?,?,?,?,?)\n"
        "ON CONFLICT(match_id, player_id) DO UPDATE SET\n"
        "  wasFouled=excluded.wasFouled,\n"
        "  fouls=excluded.fouls,\n"
        "  shotOffTarget=excluded.shotOffTarget,\n"
        "  shotOnTarget=excluded.shotOnTarget,\n"
        "  yellowCardsCount=excluded.yellowCardsCount,\n"
        "  redCard=excluded.redCard,\n"
        "  avg_minutes_played=excluded.avg_minutes_played;"
    )

    conn_local = get_new_connection()
    db_success = False
    db_error = None
    try:
        cur = conn_local.cursor()
        cur.execute(
            sql,
            (
                match_id,
                player_id,
                was_fouled,
                fouls,
                shot_off_target,
                shot_on_target,
                yellow_cards_count,
                red_card,
                avg_minutes_played,
            ),
        )
        conn_local.commit()
        db_success = True
    except Exception as e:
        print(f"An error occurred: {e}")
        db_error = str(e)
    finally:
        cur.close()
        conn_local.close()

    # Print a confirmation message
    print(f"Data for player ID {player_id} in match ID {match_id} successfully added.")
    # Log full stats for debugging
    try:
        player_logger.info(
            json.dumps(
                {
                    "action": "insert_player_match_statistics",
                    "match_id": match_id,
                    "player_id": player_id,
                    "wasFouled": was_fouled,
                    "fouls": fouls,
                    "shotOffTarget": shot_off_target,
                    "shotOnTarget": shot_on_target,
                    "yellowCardsCount": yellow_cards_count,
                    "redCard": bool(red_card),
                    "minutesPlayed": avg_minutes_played,
                    "source": source,
                    "db": {"success": db_success, "error": db_error},
                    "api": api_context or {},
                }
            )
        )
    except Exception as log_err:
        print(f"Logging failed for player {player_id}, match {match_id}: {log_err}")


def fetch_player_matches_concurrently(player_id, finished_matches):
    """Fetch a player's last N finished matches concurrently and return aggregates.

    Returns a tuple: (player_fouls_dict, player_cards_dict, avg_minutes)
    """
    player_fouls = {}
    player_cards = {}
    minutes_values = []

    match_ids = [m.get("id") for m in finished_matches if m and m.get("id") is not None]
    player_start_time = time.time()
    try:
        print(f"Player {player_id}: starting fetch for {len(match_ids)} matches")
    except Exception:
        pass

    # First, check DB for existing rows (sequential to avoid sqlite locking)
    missing_ids = []
    api_ctx_by_mid = {}
    for match_id in match_ids:
        exists, stats = fetch_statistics_if_exists(match_id, player_id)
        if exists and stats:
            (
                was_fouled,
                fouls,
                shot_off_target,
                shot_on_target,
                yellow_cards_count,
                red_card,
                avg_minutes,
            ) = stats
            existing_is_valid = False
            try:
                existing_is_valid = (
                    (isinstance(avg_minutes, (int, float)) and avg_minutes > 0)
                    or any([
                        was_fouled, fouls, shot_off_target, shot_on_target,
                        yellow_cards_count, 1 if red_card else 0
                    ])
                )
            except Exception:
                existing_is_valid = False

            if existing_is_valid:
                player_fouls[match_id] = {
                    "wasFouled": was_fouled or 0,
                    "fouls": fouls or 0,
                    "shotOffTarget": shot_off_target or 0,
                    "shotOnTarget": shot_on_target or 0,
                    "minutesPlayed": avg_minutes or 0,
                }
                player_cards[match_id] = {
                    "yellowCardsCount": yellow_cards_count or 0,
                    "redCard": bool(red_card),
                }
                if isinstance(avg_minutes, (int, float)):
                    minutes_values.append(avg_minutes)
            else:
                # Stale/empty row; refetch to correct it
                missing_ids.append(match_id)
        else:
            missing_ids.append(match_id)

    def fetch_for_match(mid):
        statistics_url = f"https://footapi7.p.rapidapi.com/api/match/{mid}/player/{player_id}/statistics"
        incidents_url = f"https://footapi7.p.rapidapi.com/api/match/{mid}/incidents"

        statistics = {}
        yellow_cards_count = 0
        red_card = False
        statistics_status = None
        incidents_status = None
        incidents_len = 0
        # Extra diagnostics for non-200s (e.g., 420/429)
        statistics_headers = {}
        incidents_headers = {}
        statistics_body = None
        incidents_body = None

        stats_attempts = 0
        stats_delays = []
        try:
            r, stats_attempts, stats_delays = http_get_with_retry(
                statistics_url, HEADERS, max_attempts=10
            )
            statistics_status = r.status_code
            if statistics_status == 200:
                try:
                    statistics = r.json().get("statistics", {})
                except JSONDecodeError:
                    statistics = {}
            else:
                try:
                    statistics_body = r.text[:500]
                except Exception:
                    statistics_body = None
                try:
                    # Pull a few relevant headers for rate limit context
                    statistics_headers = {
                        k: r.headers.get(k)
                        for k in [
                            "retry-after",
                            "x-ratelimit-remaining",
                            "x-ratelimit-reset",
                            "x-ratelimit-limit",
                        ]
                    }
                except Exception:
                    statistics_headers = {}
        except Exception as e:
            print(f"Error fetching statistics for match {mid}, player {player_id}: {e}")

        inc_attempts = 0
        inc_delays = []
        try:
            r2, inc_attempts, inc_delays = http_get_with_retry(
                incidents_url, HEADERS, max_attempts=10
            )
            incidents_status = r2.status_code
            if incidents_status == 200:
                try:
                    incidents = r2.json().get("incidents", [])
                    incidents_len = len(incidents)
                    yellow_cards_count = sum(
                        1
                        for incident in incidents
                        if incident.get("incidentClass") in ["yellow", "yellowRed"]
                        and incident.get("player", {}).get("id") == player_id
                    )

                    red_card = any(
                        incident
                        for incident in incidents
                        if incident.get("incidentClass") in ["red", "yellowRed"]
                        and incident.get("player", {}).get("id") == player_id
                    )
                except json.JSONDecodeError:
                    incidents = []
            else:
                incidents = []
                try:
                    incidents_body = r2.text[:500]
                except Exception:
                    incidents_body = None
                try:
                    incidents_headers = {
                        k: r2.headers.get(k)
                        for k in [
                            "retry-after",
                            "x-ratelimit-remaining",
                            "x-ratelimit-reset",
                            "x-ratelimit-limit",
                        ]
                    }
                except Exception:
                    incidents_headers = {}
        except Exception as e:
            print(f"Error fetching incidents for match {mid}, player {player_id}: {e}")

        fouls_entry = {
            "wasFouled": statistics.get("wasFouled", 0),
            "fouls": statistics.get("fouls", 0),
            "shotOffTarget": statistics.get("shotOffTarget", 0),
            "shotOnTarget": statistics.get("onTargetScoringAttempt", 0),
            "minutesPlayed": statistics.get("minutesPlayed", 0),
        }
        cards_entry = {"yellowCardsCount": yellow_cards_count, "redCard": red_card}
        api_ctx = {
            "statistics": {
                "url": statistics_url,
                "status_code": statistics_status,
                "ok": statistics_status == 200,
                "response": statistics,
                "status_explanation": (
                    "Enhance Your Calm / Rate limited" if statistics_status in (420, 429) else None
                ),
                "headers": statistics_headers,
                "body": statistics_body,
                "attempts": stats_attempts,
                "delays_s": stats_delays,
            },
            "incidents": {
                "url": incidents_url,
                "status_code": incidents_status,
                "ok": incidents_status == 200,
                "response_count": incidents_len,
                "status_explanation": (
                    "Enhance Your Calm / Rate limited" if incidents_status in (420, 429) else None
                ),
                "headers": incidents_headers,
                "body": incidents_body,
                "attempts": inc_attempts,
                "delays_s": inc_delays,
            },
        }
        return mid, fouls_entry, cards_entry, api_ctx

    if missing_ids:
        max_workers = min(3, len(missing_ids))
        total_jobs = len(missing_ids)
        completed_jobs = 0
        last_percent = -1
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(fetch_for_match, mid) for mid in missing_ids]
            for fut in as_completed(futures):
                mid, fouls_entry, cards_entry, api_ctx = fut.result()
                player_fouls[mid] = fouls_entry
                player_cards[mid] = cards_entry
                api_ctx_by_mid[mid] = api_ctx
                minutes = fouls_entry.get("minutesPlayed", 0)
                if isinstance(minutes, (int, float)):
                    minutes_values.append(minutes)
                completed_jobs += 1
                if total_jobs > 0:
                    percent = int((completed_jobs * 100) / total_jobs)
                    if percent != last_percent:
                        elapsed = time.time() - player_start_time
                        print(f"Player {player_id}: fetched {completed_jobs}/{total_jobs} matches ({percent}%) — {elapsed:.1f}s elapsed")
                        last_percent = percent
    try:
        total_elapsed = time.time() - player_start_time
        print(f"Player {player_id}: completed in {total_elapsed:.2f}s")
    except Exception:
        pass

    avg_minutes = (sum(minutes_values) / len(minutes_values)) if minutes_values else 0.0

    # Insert newly fetched matches into DB with the computed average
    if missing_ids:
        avg_map = {player_id: avg_minutes}
        for mid in missing_ids:
            insert_data(
                mid,
                player_id,
                {player_id: player_fouls},
                {player_id: player_cards},
                avg_map,
                api_context=api_ctx_by_mid.get(mid),
                source="api",
            )

    return player_fouls, player_cards, avg_minutes


def team_detail(team_id):
    start_time = time.time()
    # Fetch team details
    team_url = f"https://footapi7.p.rapidapi.com/api/team/{team_id}"
    team_response = requests.get(team_url, headers=HEADERS)
    team = team_response.json().get("team", {})

    # Fetch players for the team
    players_url = f"https://footapi7.p.rapidapi.com/api/team/{team_id}/players"
    players_response = requests.get(players_url, headers=HEADERS)
    players = players_response.json().get("players", [])

    # Fetch the last 5 matches for the team
    matches_url = (
        f"https://footapi7.p.rapidapi.com/api/team/{team_id}/matches/previous/0"
    )
    next_matches_response = requests.get(matches_url, headers=HEADERS)
    all_matches = next_matches_response.json().get("events", [])
    print(all_matches[0]["status"])

    # Fetch the next match for the team
    next_matches_url = (
        f"https://footapi7.p.rapidapi.com/api/team/{team_id}/matches/next/0"
    )
    next_matches_response = requests.get(next_matches_url, headers=HEADERS)
    next_matches = next_matches_response.json().get("events", [])
    next_match_id = next_matches[0]["id"]

    near_matches_url = (
        next_matches_url
    ) = f"https://footapi7.p.rapidapi.com/api/team/{team_id}/matches/near"
    near_matches_response = requests.get(near_matches_url, headers=HEADERS)
    near_matches = near_matches_response.json().get("previousEvent", [])
    previous_event = near_matches["status"]
    print(previous_event)
    previous_match_id = near_matches["id"]

    near_matches_response = requests.get(near_matches_url, headers=HEADERS)
    near_matches = near_matches_response.json().get("nextEvent", [])
    next_match = near_matches["status"]
    next_match_id = near_matches["id"]
    if previous_event["type"] == "inprogress":
        print("game in progress")
        live_match_id = previous_match_id
    if previous_event["type"] != "inprogress":
        print("game coming up")
        live_match_id = next_match_id

    # Fetch lineups for the match
    lineup_url = f"https://footapi7.p.rapidapi.com/api/match/{live_match_id}/lineups"
    lineup_response = requests.get(lineup_url, headers=HEADERS)

    # Check if the lineup request was successful
    if lineup_response.status_code == 200:
        try:
            lineups = lineup_response.json()

        except JSONDecodeError:
            print("Failed to decode JSON for lineups data")
            lineups = {"home": {}, "away": {}}  # Provide a default value
    else:
        print(f"Failed to fetch lineups. Status code: {lineup_response.status_code}")
        lineups = {
            "home": {},
            "away": {},
        }  # Provide a default value in case of failure

    try:
        lineups = lineup_response.json()
        # Fetch and save player images for home players
        for player in lineups["home"]["players"]:
            player_id = player["player"]["id"]
        # Fetch and save player images for away players
        for player in lineups["away"]["players"]:
            player_id = player["player"]["id"]
    except ValueError:
        print(
            f"Error decoding JSON for lineups of match {live_match_id}. Response content: {lineup_response.content}"
        )
        lineups = {
            "home": {},
            "away": {},
        }  # Ensuring structure with home and away keys

    # Check to see if they currently have a match

    last_5_matches = all_matches[::-1][:10]
    last_5_finished_matches = [
        match
        for match in all_matches[::-1]
        if match.get("status", {}).get("type") == "finished"
    ][:10]

    fouls_data = {}
    cards_data = {}
    avg_minutes_played = {}

    total_players = len(players)
    current_player_index = 0
    players_start_time = time.time()
    for player_data in players:
        player_id = player_data["player"]["id"]

        player_fouls, player_cards, player_avg = fetch_player_matches_concurrently(
            player_id, last_5_finished_matches
        )

        fouls_data[player_id] = player_fouls
        cards_data[player_id] = player_cards
        avg_minutes_played[player_id] = player_avg
        current_player_index += 1
        if total_players > 0:
            pcent = int((current_player_index * 100) / total_players)
            elapsed_players = time.time() - players_start_time
            print(f"Players processed: {current_player_index}/{total_players} ({pcent}%) — {elapsed_players:.1f}s elapsed")

    try:
        total_elapsed_players = time.time() - players_start_time
        print(f"All players processed in {total_elapsed_players:.2f}s")
    except Exception:
        pass

    return render_template(
        "team_detail.html",
        team=team,
        team_id=team_id,
        players=players,
        matches=last_5_finished_matches,
        fouls_data=fouls_data,
        cards_data=cards_data,
        lineups=lineups,
        avg_minutes_played=avg_minutes_played,
    )
