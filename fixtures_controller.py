from config import HEADERS
import requests
from datetime import datetime
from collections import defaultdict
from flask import Flask, render_template, jsonify


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
