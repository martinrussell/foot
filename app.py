from flask import Flask, render_template
import requests
from datetime import datetime

from datetime import datetime

# ... [Other code]


app = Flask(__name__)


@app.template_filter("datetimeformat")
def datetimeformat(value, format="%H:%M:%S"):
    """Convert a Unix timestamp to a formatted date-time string"""
    return datetime.fromtimestamp(value).strftime(format)


# Move headers outside the function
HEADERS = {
    "X-RapidAPI-Key": "b42bc11359msh98e3d09a1e9557dp173da4jsn260d881d9ab9",
    "X-RapidAPI-Host": "footapi7.p.rapidapi.com",
}


@app.route("/")
def fixtures():
    # Get today's date
    today = datetime.now().strftime("%d/%m/%Y")
    day, month, year = today.split("/")

    # Construct the API endpoint dynamically
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

    return render_template("match_detail.html", match=match, lineups=lineups)


if __name__ == "__main__":
    app.run(debug=True)
