import requests
import time
from flask import Flask, render_template, jsonify
from config import HEADERS
from requests.exceptions import JSONDecodeError
import sqlite3

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


def insert_data(match_id, player_id, fouls_data, cards_data, avg_minutes_played_dict):
    fouls_data = fouls_data[player_id].get(match_id, {})
    cards_data = cards_data[player_id].get(match_id, {})

    # Extract average minutes played for the player
    avg_minutes_played = avg_minutes_played_dict.get(player_id, 0)

    was_fouled = fouls_data.get("wasFouled", 0)
    fouls = fouls_data.get("fouls", 0)
    shot_off_target = fouls_data.get("shotOffTarget", 0)
    shot_on_target = fouls_data.get("shotOnTarget", 0)
    yellow_cards_count = cards_data.get("yellowCardsCount", 0)
    red_card = cards_data.get("redCard", False)

    sql = """ INSERT INTO player_match_statistics(match_id, player_id, wasFouled, fouls, shotOffTarget, shotOnTarget, yellowCardsCount, redCard, avg_minutes_played)
              VALUES(?,?,?,?,?,?,?,?,?) """

    conn_local = get_new_connection()
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
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        cur.close()
        conn_local.close()

    # Print a confirmation message
    print(f"Data for player ID {player_id} in match ID {match_id} successfully added.")


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
    matches_response = requests.get(matches_url, headers=HEADERS)
    all_matches = matches_response.json().get("events", [])
    last_5_matches = all_matches[::-1][:5]
    last_5_finished_matches = [
        match
        for match in all_matches[::-1]
        if match.get("status", {}).get("type") == "finished"
    ][:5]

    fouls_data = {}
    cards_data = {}
    avg_minutes_played = {}

    for player_data in players:
        player_id = player_data["player"]["id"]

        # Initialize data structures for fouls and cards for this player
        fouls_data[player_id] = {}
        cards_data[player_id] = {}

        total_minutes = 0
        match_count = 0

        for match in last_5_finished_matches:
            match_id = match["id"]
            exists, stats = fetch_statistics_if_exists(match_id, player_id)
            if exists:
                print(
                    f"Data for match ID {match_id} and player ID {player_id} already exists."
                )
                # Unpack the statistics
                (
                    was_fouled,
                    fouls,
                    shot_off_target,
                    shot_on_target,
                    yellow_cards_count,
                    red_card,
                    avg_minutes_played,
                ) = stats
                fouls_data[player_id][match_id] = {
                    "wasFouled": was_fouled,
                    "fouls": fouls,
                    "shotOffTarget": shot_off_target,
                    "shotOnTarget": shot_on_target,
                    "minutesPlayed": avg_minutes_played,  # Assuming avg_minutes_played refers to minutesPlayed
                }
                cards_data[player_id][match_id] = {
                    "yellowCardsCount": yellow_cards_count,
                    "redCard": red_card,
                }
                continue

            # API request to get statistics for player in the match
            statistics_url = f"https://footapi7.p.rapidapi.com/api/match/{match_id}/player/{player_id}/statistics"
            statistics_response = requests.get(statistics_url, headers=HEADERS)

            # Check if response status code is OK (200) and handle JSON decode error
            if statistics_response.status_code == 200:
                try:
                    statistics = statistics_response.json().get("statistics", {})

                    # Store the fouls data in the nested dictionary
                    fouls_data[player_id][match_id] = {
                        "wasFouled": statistics.get("wasFouled", 0),
                        "fouls": statistics.get("fouls", 0),
                        "shotOffTarget": statistics.get("shotOffTarget", 0),
                        "shotOnTarget": statistics.get("onTargetScoringAttempt", 0),
                        "minutesPlayed": statistics.get("minutesPlayed", 0),
                    }

                    # Update total_minutes and match_count for average calculation
                    minutes = fouls_data[player_id][match_id].get("minutesPlayed", 0)
                    if isinstance(minutes, (int, float)):
                        total_minutes += minutes
                        match_count += 1

                except JSONDecodeError:
                    print(
                        f"Failed to decode JSON for match {match_id} and player {player_id}"
                    )
                    fouls_data[player_id][match_id] = {
                        "wasFouled": "no data",
                        "fouls": "no data",
                        "shotOffTarget": "no data",
                        "shotOnTarget": "no data",
                        "minutesPlayed": "no data",
                    }

            cards_data[player_id][match_id] = {
                "yellowCardsCount": 0,
                "redCard": False,
            }

            # API request to get incidents for the match
            incidents_url = (
                f"https://footapi7.p.rapidapi.com/api/match/{match_id}/incidents"
            )
            incidents_response = requests.get(incidents_url, headers=HEADERS)

            try:
                if incidents_response.status_code == 200:
                    try:
                        incidents = incidents_response.json().get("incidents", [])
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

                        cards_data[player_id][match_id] = {
                            "yellowCardsCount": yellow_cards_count,
                            "redCard": red_card,
                        }

                    except json.JSONDecodeError:
                        print("Error decoding JSON from the response")
                        # Handle the error, e.g., by logging it and setting incidents to an empty list
                        incidents = []
                else:
                    print(
                        f"Failed to fetch incidents. Status code: {incidents_response.status_code}"
                    )
                    incidents = []  # Set default as empty list on failure

                # Calculate the average and store it outside the inner match loop
                avg_minutes = total_minutes / match_count if match_count > 0 else 0
                avg_minutes_played[player_id] = avg_minutes
                print("Mins", avg_minutes)

            except Exception as e:
                print(f"An error occurred: {e}")
            # Pass fouls_data, cards_data, and avg_minutes_played to your template
            # Pass avg_minutes_played as a dictionary to your insert_data function
            insert_data(match_id, player_id, fouls_data, cards_data, avg_minutes_played)

    return render_template(
        "team_detail.html",
        team=team,
        players=players,
        matches=last_5_finished_matches,
        fouls_data=fouls_data,
        cards_data=cards_data,
        avg_minutes_played=avg_minutes_played,
    )
