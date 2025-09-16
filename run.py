from flask import Flask, render_template, jsonify
import requests
from datetime import datetime
from requests.exceptions import JSONDecodeError
from flask_caching import Cache
import time
import os
from flask import current_app
from collections import defaultdict
import json
import sqlite3
from config import HEADERS
from tqdm import tqdm
import concurrent.futures  # Add this import


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


# HTTP session (connection reuse for speed)
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def get_db_connection():
    """Return a SQLite connection tuned for faster bulk writes."""
    conn = sqlite3.connect("database.sqlite", check_same_thread=False)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA temp_store=MEMORY;")
    except Exception:
        # Pragmas are best-effort; continue if unsupported
        pass
    return conn


# Call create_table function to ensure table exists
create_table()


def get_fixtures():
    today = datetime.now().strftime("%d/%m/%Y")
    day, month, year = today.split("/")
    url = f"https://footapi7.p.rapidapi.com/api/matches/top/{day}/{month}/{year}"
    response = SESSION.get(url)
    data = response.json()
    events = data.get("events", [])

    # Use tqdm to create a progress bar
    for event in tqdm(events, desc="Processing fixtures"):
        current_date = datetime.now().strftime("%d/%m/%Y")
        formatted_start_date = datetime.fromtimestamp(event["startTimestamp"]).strftime(
            "%d/%m/%Y"
        )
        if formatted_start_date == current_date:
            home_team_name = event["homeTeam"]["name"]
            away_team_name = event["awayTeam"]["name"]
            home_team_id = event["homeTeam"]["id"]
            away_team_id = event["awayTeam"]["id"]
            print("Event : ", home_team_name, " v ", away_team_name)

            # Record the start time before making the next event request
            start_time = time.time()

            # Use concurrent.futures to fetch team details and player statistics concurrently
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = [
                    executor.submit(team_detail, home_team_id),
                    executor.submit(team_detail, away_team_id),
                ]

                # Wait for both tasks to complete before moving on to the next event
                concurrent.futures.wait(futures)

            # Calculate the time it took to get to the next event
            elapsed_time = time.time() - start_time
            print(f"Time to next event: {elapsed_time:.2f} seconds")


def get_new_connection():
    return get_db_connection()


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


def upsert_rows(conn, rows):
    """Bulk upsert rows into player_match_statistics.

    rows: iterable of tuples (match_id, player_id, wasFouled, fouls, shotOffTarget, shotOnTarget, yellowCardsCount, redCard, avg_minutes_played)
    """
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
    cur = conn.cursor()
    cur.executemany(sql, rows)
    cur.close()


def team_detail(team_id):
    start_time = time.time()
    # Fetch team details
    team_url = f"https://footapi7.p.rapidapi.com/api/team/{team_id}"
    team_response = SESSION.get(team_url)
    team = team_response.json().get("team", {})

    # Fetch players for the team
    players_url = f"https://footapi7.p.rapidapi.com/api/team/{team_id}/players"
    players_response = SESSION.get(players_url)
    players = players_response.json().get("players", [])

    # Fetch the last 5 matches for the team
    matches_url = (
        f"https://footapi7.p.rapidapi.com/api/team/{team_id}/matches/previous/0"
    )
    next_matches_response = SESSION.get(matches_url)
    all_matches = next_matches_response.json().get("events", [])
    # print(all_matches[0]["status"])

    # Fetch the next match for the team
    next_matches_url = (
        f"https://footapi7.p.rapidapi.com/api/team/{team_id}/matches/next/0"
    )
    next_matches_response = SESSION.get(next_matches_url)
    next_matches = next_matches_response.json().get("events", [])
    next_match_id = next_matches[0]["id"]

    near_matches_url = (
        next_matches_url
    ) = f"https://footapi7.p.rapidapi.com/api/team/{team_id}/matches/near"
    near_matches_response = SESSION.get(near_matches_url)
    near_matches = near_matches_response.json().get("previousEvent", [])
    previous_event = near_matches["status"]
    # print(previous_event)
    previous_match_id = near_matches["id"]

    near_matches_response = SESSION.get(near_matches_url)
    near_matches = near_matches_response.json().get("nextEvent", [])
    next_match = near_matches["status"]
    next_match_id = near_matches["id"]
    if previous_event["type"] == "inprogress":
        # print("game in progress")
        live_match_id = previous_match_id
    if previous_event["type"] != "inprogress":
        # print("game coming up")
        live_match_id = next_match_id

    # Fetch lineups for the match
    lineup_url = f"https://footapi7.p.rapidapi.com/api/match/{live_match_id}/lineups"
    lineup_response = SESSION.get(lineup_url)

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

    # Build incidents map once per match: match_id -> {player_id: (yellow_count, red_bool)}
    incidents_by_match = {}
    for match in last_5_finished_matches:
        match_id = match["id"]
        try:
            incidents_url = f"https://footapi7.p.rapidapi.com/api/match/{match_id}/incidents"
            incidents_response = SESSION.get(incidents_url)
            incidents = []
            if incidents_response.status_code == 200:
                try:
                    incidents = incidents_response.json().get("incidents", [])
                except json.JSONDecodeError:
                    incidents = []
            per_player = {}
            for incident in incidents:
                player_id = incident.get("player", {}).get("id")
                if not player_id:
                    continue
                iclass = incident.get("incidentClass")
                if iclass in ["yellow", "yellowRed"]:
                    yc, rc = per_player.get(player_id, (0, False))
                    per_player[player_id] = (yc + 1, rc or iclass in ["red", "yellowRed"])  # yellowRed implies both
                elif iclass == "red":
                    yc, rc = per_player.get(player_id, (0, False))
                    per_player[player_id] = (yc, True)
            incidents_by_match[match_id] = per_player
        except Exception as e:
            print(f"Incidents fetch failed for match {match_id}: {e}")
            incidents_by_match[match_id] = {}

    # Prepare bulk rows for upsert inside one transaction
    conn = get_new_connection()
    rows_to_write = []

    for player_data in players:
        player_id = player_data["player"]["id"]

        rows_for_player = []
        minutes_sum = 0
        minutes_count = 0

        for match in last_5_finished_matches:
            match_id = match["id"]
            statistics_url = f"https://footapi7.p.rapidapi.com/api/match/{match_id}/player/{player_id}/statistics"
            statistics_response = SESSION.get(statistics_url)
            was_fouled = 0
            fouls = 0
            shot_off = 0
            shot_on = 0
            minutes_played = 0
            if statistics_response.status_code == 200:
                try:
                    statistics = statistics_response.json().get("statistics", {})
                    was_fouled = statistics.get("wasFouled", 0)
                    fouls = statistics.get("fouls", 0)
                    shot_off = statistics.get("shotOffTarget", 0)
                    shot_on = statistics.get("onTargetScoringAttempt", 0)
                    minutes_played = statistics.get("minutesPlayed", 0) or 0
                except JSONDecodeError:
                    pass
            if isinstance(minutes_played, (int, float)):
                minutes_sum += minutes_played
                minutes_count += 1

            yc, rc = incidents_by_match.get(match_id, {}).get(player_id, (0, False))
            # Store per-match minutes directly in avg_minutes_played column for compatibility
            rows_for_player.append((
                match_id,
                player_id,
                was_fouled,
                fouls,
                shot_off,
                shot_on,
                yc,
                1 if rc else 0,
                float(minutes_played),
            ))

        # Average still computed for potential reporting, but we now persist per-match minutes
        avg_minutes = (minutes_sum / minutes_count) if minutes_count > 0 else 0.0
        rows_to_write.extend(rows_for_player)

    try:
        conn.execute("BEGIN")
        upsert_rows(conn, rows_to_write)
        conn.commit()
    except Exception as e:
        print(f"Bulk upsert failed: {e}")
        conn.rollback()
    finally:
        conn.close()


get_fixtures()
