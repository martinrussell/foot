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
from match_detail import (
    match_detail,
)  # match_detail.py should define a function match_detail
from team_detail import (
    team_detail,
)  # team_detail.py should define a function team_detail


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
    print(events[0])

    special_tournaments = [
        "UEFA Champions League",
        "UEFA Europa League",
        "UEFA Europa Conference League",
        "UEFA Youth League",
    ]

    # Define a status priority
    status_priority = {"inprogress": 1, "finished": 2, "notstarted": 3}

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

    # Sorting each group of events
    for tournament in grouped_events:
        grouped_events[tournament].sort(
            key=lambda x: status_priority.get(x["status"]["type"], 4)
        )

    return render_template(
        "fixtures.html", grouped_events=grouped_events, today=datetime.now()
    )


# Match Detail Page - match_detail.py
@app.route("/match/<int:match_id>", endpoint="match_detail")
def showMatchDetails(match_id):
    return match_detail(match_id)


@app.route("/team/<int:team_id>", endpoint="team_detail")
def showTeamDetail(team_id):
    return team_detail(team_id)


if __name__ == "__main__":
    app.run(debug=True)
