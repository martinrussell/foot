from flask import Flask, render_template
import requests
from datetime import datetime

app = Flask(__name__)

HEADERS = {
    "X-RapidAPI-Key": "b42bc11359msh98e3d09a1e9557dp173da4jsn260d881d9ab9",
    "X-RapidAPI-Host": "footapi7.p.rapidapi.com",
}


@app.template_filter("datetimeformat")
def datetimeformat(value, format="%H:%M:%S"):
    """Convert a Unix timestamp to a formatted date-time string"""
    return datetime.fromtimestamp(value).strftime(format)


@app.route("/")
def fixtures():
    today = datetime.now().strftime("%d/%m/%Y")
    day, month, year = today.split("/")
    url = f"https://footapi7.p.rapidapi.com/api/matches/top/{day}/{month}/{year}"

    response = requests.get(url, headers=HEADERS)
    data = response.json()
    events = data.get("events", [])

    return render_template("fixtures.html", events=events)


@app.route("/match/<int:match_id>")
def match_detail(match_id):
    # Fetch match details
    match_url = f"https://footapi7.p.rapidapi.com/api/match/{match_id}"
    match_response = requests.get(match_url, headers=HEADERS)
    match = match_response.json().get("event", {})

    # Fetch lineups for the match
    lineup_url = f"https://footapi7.p.rapidapi.com/api/match/{match_id}/lineups"
    lineup_response = requests.get(lineup_url, headers=HEADERS)
    lineups = lineup_response.json()

    # Fetch substitution incidents for the match
    incidents_url = f"https://footapi7.p.rapidapi.com/api/match/{match_id}/incidents"
    incidents_response = requests.get(incidents_url, headers=HEADERS)
    incidents = incidents_response.json().get("incidents", [])

    # Process substitution incidents
    subbed_in = {}
    subbed_out = {}
    goal_scorers = {}
    assists = {}  # New dictionary to store player assists and their times

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

    return render_template(
        "match_detail.html",
        match=match,
        lineups=lineups,
        goal_scorers=goal_scorers,
        subbed_in=subbed_in,
        subbed_out=subbed_out,
        assists=assists,  # Add the assists dictionary to the template
    )


if __name__ == "__main__":
    app.run(debug=True)
