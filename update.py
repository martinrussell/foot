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
import asyncio
import aiohttp
from datetime import datetime


async def get_player_stats(session, sem, player_id, match_id):
    print("Getting Stats")
    async with sem:
        await asyncio.sleep(0.1)  # Delay to prevent burst requests
        try:
            player_url = f"https://footapi7.p.rapidapi.com/api/match/{match_id}/player/{player_id}/statistics"
            async with session.get(player_url, headers=HEADERS) as response:
                response.raise_for_status()
                player_match_stats = await response.json()
                print(player_id, match_id, player_match_stats["statistics"]["rating"])
        except aiohttp.ClientResponseError as e:
            print(f"Request error: {e}")
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")


async def get_players(team_id, match_id):
    print("Getting Players")
    url = f"https://footapi7.p.rapidapi.com/api/team/{team_id}/players"
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        players = response.json()
        for player in players["player"]:
            player_id = player["id"]
            get_player_stats(player_id)
    else:
        print("Error in fetching players")


def retrieve_previous_fixtures(team_id, match_ids):
    for match_id in match_ids:
        url = f"https://footapi7.p.rapidapi.com/api/team/{team_id}/matches/previous/{match_id}"
        response = requests.get(url, headers=HEADERS)
        if response.status_code == 200:
            all_matches = response.json()
            print(f"Matches for match_id {match_id}: {len(all_matches)}")
            for match in all_matches["events"]:
                get_players(team_id, match["id"])
        else:
            print(f"Error in fetching matches for match_id {match_id}")


def get_fixtures():
    today = datetime.now().strftime("%d/%m/%Y")
    day, month, year = today.split("/")
    url = f"https://footapi7.p.rapidapi.com/api/matches/top/{day}/{month}/{year}"
    response = requests.get(url, headers=HEADERS)
    data = response.json()
    events = data.get("events", [])

    for event in events:
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

            retrieve_previous_fixtures(home_team_id, match_ids=range(10))
            retrieve_previous_fixtures(away_team_id, match_ids=range(10))


if __name__ == "__main__":
    get_fixtures()
