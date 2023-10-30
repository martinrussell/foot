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

app = Flask(__name__)
app.jinja_env.globals.update(zip=zip)


# Configuring cache
app.config[
    "CACHE_TYPE"
] = "simple"  # In-memory cache for development. For production, consider using "redis" or "memcached".
cache = Cache(app)

HEADERS = {
    "X-RapidAPI-Key": "b42bc11359msh98e3d09a1e9557dp173da4jsn260d881d9ab9",
    "X-RapidAPI-Host": "footapi7.p.rapidapi.com",
}


def fetchPlayerImage(playerId):
    # Ensure the saved image file has a .png extension
    filename = f"{playerId}_image.png"
    save_path = os.path.join(current_app.static_folder, "images", filename)

    # Check if the image file already exists
    if os.path.exists(save_path):
        # If it exists, return the relative path to the existing file
        return os.path.join("images", filename)

    # If the image file doesn't exist, download it
    url = f"https://footapi7.p.rapidapi.com/api/player/{playerId}/image"
    headers = {
        "X-RapidAPI-Key": "b42bc11359msh98e3d09a1e9557dp173da4jsn260d881d9ab9",
        "X-RapidAPI-Host": "footapi7.p.rapidapi.com",
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()

        # Save the image to the app's static folder
        with open(save_path, "wb") as f:
            f.write(response.content)

        # Return the relative path to the saved image
        return os.path.join("images", filename)

    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return None


@app.template_filter("datetimeformat")
def datetimeformat(value, format="%H:%M:%S"):
    """Convert a Unix timestamp to a formatted date-time string"""
    return datetime.fromtimestamp(value).strftime(format)


@app.template_filter("format_timestamp")
def format_timestamp(value, format="%d %b %Y"):
    return datetime.utcfromtimestamp(value).strftime(format)


@app.template_filter("formatdate")
def format_date(value, format="%d %b %Y"):
    date_obj = datetime.utcfromtimestamp(value)
    return date_obj.strftime(format)


app.jinja_env.filters["formatdate"] = format_date


@app.route("/")
def fixtures():
    today = datetime.now().strftime("%d/%m/%Y")
    day, month, year = today.split("/")
    url = f"https://footapi7.p.rapidapi.com/api/matches/top/{day}/{month}/{year}"
    response = requests.get(url, headers=HEADERS)
    data = response.json()
    events = data.get("events", [])

    special_tournaments = [
        "UEFA Champions League",
        "UEFA Europa League",
        "UEFA Europa Conference League",
        "UEFA Youth League",
    ]

    grouped_events = defaultdict(list)
    for event in events:
        tournament_name = event["tournament"]["name"]
        # Special handling for certain tournaments
        if any(
            special_tournament in tournament_name
            for special_tournament in special_tournaments
        ):
            tournament_name = tournament_name.split(",")[0].strip()
        grouped_events[tournament_name].append(event)

    return render_template("fixtures.html", grouped_events=grouped_events)


def fetch_last_10_matches(team_id, current_match_id):
    url = f"https://footapi7.p.rapidapi.com/api/team/{team_id}/matches/previous/0"
    response = requests.get(url, headers=HEADERS)
    matches = response.json().get("events", [])

    # Filter out the current match
    filtered_matches = [match for match in matches if match["id"] != current_match_id]

    # Add results to the matches
    for match in filtered_matches:
        # Check if winnerCode is present in match
        if "winnerCode" in match:
            if match["winnerCode"] == 1:
                match["result"] = (
                    "win" if match["homeTeam"]["id"] == team_id else "loss"
                )
            elif match["winnerCode"] == 2:
                match["result"] = (
                    "win" if match["awayTeam"]["id"] == team_id else "loss"
                )
            else:
                match["result"] = "draw"
        else:
            match[
                "result"
            ] = "pending"  # or any other suitable term to indicate the match hasn't been played

    return filtered_matches[-10:][::-1]  # Get the last 10 matches and reverse the list


@app.route("/match/<int:match_id>")
def match_detail(match_id):
    # Fetch match details
    match_url = f"https://footapi7.p.rapidapi.com/api/match/{match_id}"
    match_response = requests.get(match_url, headers=HEADERS)
    match = match_response.json().get("event", {})

    # Fetch lineups for the match
    lineup_url = f"https://footapi7.p.rapidapi.com/api/match/{match_id}/lineups"
    lineup_response = requests.get(lineup_url, headers=HEADERS)
    try:
        lineups = lineup_response.json()
        # Fetch and save player images for home players
        for player in lineups["home"]["players"]:
            player_id = player["player"]["id"]
            fetchPlayerImage(player_id)

        # Fetch and save player images for away players
        for player in lineups["away"]["players"]:
            player_id = player["player"]["id"]
            fetchPlayerImage(player_id)
    except ValueError:
        print(
            f"Error decoding JSON for lineups of match {match_id}. Response content: {lineup_response.content}"
        )
        lineups = {"home": {}, "away": {}}  # Ensuring structure with home and away keys

    # Fetch substitution incidents for the match
    incidents_url = f"https://footapi7.p.rapidapi.com/api/match/{match_id}/incidents"
    incidents_response = requests.get(incidents_url, headers=HEADERS)

    try:
        incidents = incidents_response.json().get("incidents", [])
    except ValueError:  # Catches JSONDecodeErrors
        print(
            f"Error decoding JSON for match {match_id}. Response content: {incidents_response.content}"
        )
        incidents = []

    # Fetch last 10 matches for home and away teams
    home_last_10 = fetch_last_10_matches(match["homeTeam"]["id"], match_id)
    away_last_10 = fetch_last_10_matches(match["awayTeam"]["id"], match_id)

    # Process substitution incidents
    subbed_in = {}
    subbed_out = {}
    goal_scorers = {}
    assists = {}  # New dictionary to store player assists and their times
    cards = {}  # Dictionary to store card incidents
    subbed_in = {}  # Dictionary to store players who are subbed in
    subbed_out = {}  # Dictionary to store players who are subbed out

    for incident in incidents:
        # Process goals and goal scorers
        if incident["incidentType"] == "goal" and "player" in incident:
            player_id = incident["player"]["id"]
            if player_id in goal_scorers:
                goal_scorers[player_id].append(incident["time"])
            else:
                goal_scorers[player_id] = [incident["time"]]

        # Process goal assists
        if incident["incidentType"] == "goal" and "assist1" in incident:
            assist_player_id = incident["assist1"]["id"]
            if assist_player_id in assists:
                assists[assist_player_id].append(incident["time"])
            else:
                assists[assist_player_id] = [incident["time"]]

        # Process substitutions
        elif incident["incidentType"] == "substitution":
            # Map the ID of the player coming in to the name of the player going out
            if incident["playerIn"]["id"] not in subbed_in:
                subbed_in[incident["playerIn"]["id"]] = {
                    "time": incident["time"],
                    "name": incident["playerOut"]["name"],
                }
            # Map the ID of the player going out to the name of the player coming in
            if incident["playerOut"]["id"] not in subbed_out:
                subbed_out[incident["playerOut"]["id"]] = {
                    "time": incident["time"],
                    "name": incident["playerIn"]["name"],
                }
        # Process cards
        if incident["incidentType"] == "card":
            player_id = incident["player"]["id"]
            if incident["incidentClass"] == "red":
                card_type = "Red"
            elif incident["incidentClass"] == "yellow":
                card_type = "Yellow"
            elif incident["incidentClass"] == "yellowRed":
                card_type = "YellowRed"
            else:
                continue

            if player_id not in cards:
                cards[player_id] = []
            cards[player_id].append({"time": incident["time"], "type": card_type})
        if incident["incidentType"] == "substitution":
            # Track the player subbed in
            sub_in_id = incident["playerIn"]["id"]
            subbed_in[sub_in_id] = {
                "time": incident["time"],
                "out_player_name": incident["playerOut"]["name"],
            }

            # Track the player subbed out
            sub_out_id = incident["playerOut"]["id"]
            subbed_out[sub_out_id] = {
                "time": incident["time"],
                "in_player_name": incident["playerIn"]["name"],
            }

    return render_template(
        "match_detail.html",
        match=match,
        lineups=lineups,
        goal_scorers=goal_scorers,
        subbed_in=subbed_in,
        subbed_out=subbed_out,
        assists=assists,  # Pass the assists dictionary to the template
        cards=cards,  # Add this line to pass the cards info to the template
        home_last_10=home_last_10,  # Pass the home team's last 10 matches to the template
        away_last_10=away_last_10,  # Pass the away team's last 10 matches to the template
    )


@app.route("/team/<int:team_id>")
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

        for match in last_5_matches:
            match_id = match["id"]

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

            cards_data[player_id][match_id] = {"yellowCardsCount": 0, "redCard": False}

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
        matches=last_5_matches,
        fouls_data=fouls_data,
        cards_data=cards_data,
        avg_minutes_played=avg_minutes_played,
    )


if __name__ == "__main__":
    app.run(debug=True)
