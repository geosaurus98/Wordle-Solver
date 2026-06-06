from __future__ import annotations

"""
Tilerdle solver for https://knotwise.games/games/tilerdle

Fetches the day's puzzle from the REST API (no browser needed) and extracts
all crossword words directly from the tile letter data.

Crossword structure
-------------------
Each tile cell encodes [letter, x, y] where x is the absolute grid column
and y is the absolute grid row of that letter in the solved crossword.
(Confirmed from the game's JS source: cells are parsed as
 {value: letter, answer: {x: col, y: row}}.)

We build the full solved grid from all tile cells, then scan rows for across
words and columns for down words (consecutive letter runs >= 3 letters).
"""

import datetime

import requests
import urllib3

urllib3.disable_warnings()

from .game_result import GameResult

URL = "https://knotwise.games/games/tilerdle"
_API = "https://knotwise.games/api/tilerdle/puzzle/{date}"


def _extract_words(tiles: list[dict]) -> dict[str, list[str]]:
    """
    Return {"across": [...], "down": [...]} of all crossword words (>= 3 letters).

    Each cell [letter, x, y] gives the letter's solved grid position.
    We build grid[(x, y)] = letter, then scan rows (across) and columns (down)
    for consecutive letter runs.
    """
    grid: dict[tuple[int, int], str] = {}
    for tile in tiles:
        for row in tile.get("grid", []):
            for cell in row:
                if cell:
                    letter, x, y = cell
                    grid[(x, y)] = letter.upper()

    if not grid:
        return {"across": [], "down": []}

    max_x = max(x for x, _ in grid)
    max_y = max(y for _, y in grid)

    across: list[str] = []
    down: list[str] = []

    # Scan each row for consecutive letter runs (across words)
    for row_y in range(max_y + 1):
        run = ""
        for col_x in range(max_x + 2):  # +2 to flush the last run
            letter = grid.get((col_x, row_y), "")
            if letter:
                run += letter
            else:
                if len(run) >= 3:
                    across.append(run)
                run = ""

    # Scan each column for consecutive letter runs (down words)
    for col_x in range(max_x + 1):
        run = ""
        for row_y in range(max_y + 2):  # +2 to flush the last run
            letter = grid.get((col_x, row_y), "")
            if letter:
                run += letter
            else:
                if len(run) >= 3:
                    down.append(run)
                run = ""

    return {"across": across, "down": down}


def run_bot() -> GameResult:
    date_str = str(datetime.date.today())
    api_url = _API.format(date=date_str)
    try:
        r = requests.get(api_url, timeout=10, verify=False)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        return GameResult(game="Tilerdle", url=URL, date=date_str, error=str(exc))

    try:
        theme = data.get("theme", "?")
        grid_size = data.get("gridSize", "?")
        word_groups = _extract_words(data.get("tiles", []))
    except Exception as exc:
        return GameResult(game="Tilerdle", url=URL, date=date_str, error=f"Parse error: {exc}")

    return GameResult(
        game="Tilerdle",
        url=URL,
        date=date_str,
        extra={
            "theme": theme,
            "grid_size": grid_size,
            "across": word_groups["across"],
            "down": word_groups["down"],
        },
    )
