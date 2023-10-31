from flask import Flask, render_template, jsonify
import requests
from datetime import datetime
from requests.exceptions import JSONDecodeError
import time
import os

from collections import defaultdict
import json
from config import HEADERS


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
    print(last_5_finished_matches)

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
            # API request to get statistics for player in the match
            statistics_url = f"https://footapi7.p.rapidapi.com/api/match/{match_id}/player/{player_id}/statistics"
            statistics_response = requests.get(statistics_url, headers=HEADERS)

            # Check if response status code is OK (200) and handle JSON decode error
            if statistics_response.status_code == 200:
                try:
                    statistics = statistics_response.json().get("statistics", {})
                    print("Player Statistics : ", statistics)
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

            except Exception as e:
                print(f"An error occurred: {e}")
            # Pass fouls_data, cards_data, and avg_minutes_played to your template
    return render_template(
        "team_detail.html",
        team=team,
        players=players,
        matches=last_5_finished_matches,
        fouls_data=fouls_data,
        cards_data=cards_data,
        avg_minutes_played=avg_minutes_played,
    )
