import requests
from config import HEADERS
import os
from flask import current_app
from flask import Flask, render_template, jsonify
from requests.exceptions import JSONDecodeError


def fetch_last_10_matches(team_id, current_match_id):
    url = f"https://footapi7.p.rapidapi.com/api/team/{team_id}/matches/previous/0"
    response = requests.get(url, headers=HEADERS)
    matches = response.json().get("events", [])
    print(matches)

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
