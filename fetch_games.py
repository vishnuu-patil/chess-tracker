# requests lets us call the Chess.com API over the internet
import requests
# csv lets us read and write the games.csv file
import csv
# os lets us check whether a file already exists
import os
# re lets us pull the opening name out of the game text
import re
# time lets us pause briefly between API calls to be polite
import time
# datetime lets us turn the game's timestamp into a readable date
from datetime import datetime, timezone

# your Chess.com username (the API expects it in lowercase)
USERNAME = "Mainlysimp".lower()
# the file where all games will be saved
CSV_FILE = "games.csv"
# Chess.com asks API users to identify themselves with a User-Agent header
HEADERS = {"User-Agent": f"chess-tracker (user: {USERNAME})"}
# the columns we will save for every game
COLUMNS = ["date", "color", "result", "my_rating", "opp_rating",
           "time_class", "time_control", "rated", "opening", "url"]
# result codes Chess.com uses that all mean the game was a draw
DRAW_CODES = {"agreed", "repetition", "stalemate", "insufficient",
              "50move", "timevsinsufficient"}


# this function reads games.csv and returns the links of games we already saved
def load_saved_urls():
    # if the file doesn't exist yet, nothing is saved, so return an empty set
    if not os.path.exists(CSV_FILE):
        # an empty set means "no games saved yet"
        return set()
    # open the existing csv file for reading
    with open(CSV_FILE, newline="", encoding="utf-8") as f:
        # return the set of all game links found in the "url" column
        return {row["url"] for row in csv.DictReader(f)}


# this function turns Chess.com's detailed result code into win, loss or draw
def simplify_result(code):
    # "win" means I won
    if code == "win":
        # report it as a win
        return "win"
    # any of the draw codes means a draw
    if code in DRAW_CODES:
        # report it as a draw
        return "draw"
    # everything else (checkmated, resigned, timeout, abandoned) is a loss
    return "loss"


# this function digs the opening name out of the game's PGN text
def get_opening(pgn):
    # look for the line that holds the opening link, like [ECOUrl "https://.../openings/Sicilian-Defense"]
    match = re.search(r'\[ECOUrl "https://www\.chess\.com/openings/([^"]+)"\]', pgn or "")
    # if there is no opening info, return a placeholder
    if not match:
        # we could not find the opening
        return "Unknown"
    # take the link's last part, which looks like "Sicilian-Defense-Open-Najdorf-6.Be3"
    slug = match.group(1)
    # cut off the move numbers at the end (everything from the first "-digit" onward)
    slug = re.split(r"-\d", slug)[0]
    # turn dashes into spaces so it reads like a normal name
    return slug.replace("-", " ")


# this function converts one raw game from the API into one clean row
def build_row(game):
    # figure out which color I played by comparing usernames
    if game["white"]["username"].lower() == USERNAME:
        # I was white, so I am the white side and the opponent is black
        me, opp, color = game["white"], game["black"], "white"
    # otherwise I was black
    else:
        # I am the black side and the opponent is white
        me, opp, color = game["black"], game["white"], "black"
    # convert the end time (seconds since 1970) into a YYYY-MM-DD date
    date = datetime.fromtimestamp(game["end_time"], tz=timezone.utc).strftime("%Y-%m-%d")
    # return the clean row as a dictionary matching our columns
    return {
        # the day the game ended
        "date": date,
        # white or black
        "color": color,
        # win, loss or draw
        "result": simplify_result(me["result"]),
        # my rating after this game
        "my_rating": me.get("rating"),
        # my opponent's rating
        "opp_rating": opp.get("rating"),
        # bullet, blitz, rapid or daily
        "time_class": game.get("time_class"),
        # the exact time control, like "600" or "180+2"
        "time_control": game.get("time_control"),
        # True if it was a rated game
        "rated": game.get("rated"),
        # the opening name pulled from the PGN
        "opening": get_opening(game.get("pgn")),
        # the link to the game, which also acts as its unique ID
        "url": game["url"],
    }


# this is the main function that runs everything
def main():
    # load links of games we already saved so we can skip them
    saved = load_saved_urls()
    # remember whether the file is new, so we know to write the header row
    is_new_file = not os.path.exists(CSV_FILE)
    # ask Chess.com for the list of monthly archive links for my account
    resp = requests.get(f"https://api.chess.com/pub/player/{USERNAME}/games/archives",
                        headers=HEADERS, timeout=30)
    # stop with a clear error if the request failed (wrong username, no internet, etc.)
    resp.raise_for_status()
    # the response holds a list of monthly URLs under "archives"
    archives = resp.json()["archives"]
    # count how many new games we add, just for the final message
    added = 0
    # open games.csv in append mode so old rows are kept
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        # create a writer that knows our column names
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        # if the file is brand new, write the column names first
        if is_new_file:
            # write the header row
            writer.writeheader()
        # go through each monthly archive, counting from 1 so we can show progress
        for number, month_url in enumerate(archives, start=1):
            # print which month we are on so you can see it is working
            print(f"Fetching month {number} of {len(archives)}...", flush=True)
            # try to download this month, but don't crash if it is slow or fails
            try:
                # download that month's games (gives up after 30 seconds)
                month = requests.get(month_url, headers=HEADERS, timeout=30)
            # if the request timed out or the connection broke, handle it here
            except requests.exceptions.RequestException:
                # tell me which month failed
                print(f"  Skipped {month_url} (network problem). Run again to retry it.")
                # move on to the next month
                continue
            # if this month failed to load properly, skip it and move on
            if month.status_code != 200:
                # tell me which month was skipped
                print(f"  Skipped {month_url} (status {month.status_code}).")
                # move on to the next month
                continue
            # go through every game in that month
            for game in month.json().get("games", []):
                # skip games without a link, and skip ones we already saved
                if "url" not in game or game["url"] in saved:
                    # go to the next game
                    continue
                # skip odd variants (like chess960) that lack the standard fields
                if "white" not in game or "black" not in game:
                    # go to the next game
                    continue
                # convert the raw game to a clean row and write it to the file
                writer.writerow(build_row(game))
                # remember this link so duplicates inside this run are skipped too
                saved.add(game["url"])
                # add one to our counter
                added += 1
            # save this month's rows to disk now, so a stop mid-run loses nothing
            f.flush()
            # pause half a second before the next month so we don't hammer the API
            time.sleep(0.5)
    # tell me how many new games were saved
    print(f"Done. Added {added} new games to {CSV_FILE}.")


# only run main() when this file is run directly (not when imported)
if __name__ == "__main__":
    # start the script
    main()