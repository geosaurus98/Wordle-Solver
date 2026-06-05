from __future__ import annotations

"""
Tilerdle solver for https://knotwise.games/games/tilerdle

Fetches the day's puzzle from the REST API (no browser needed) and extracts
the hidden words from the tile letter grids.

Crossword structure
-------------------
Each tile cell encodes [letter, wordIndex, letterIndex].  letterIndex is the
absolute position of that letter within its word (column for across words,
row for down words).

* Across words   – letterIndex values are consecutive (step = 1).  Every
                   letter of the word is present in a moveable tile.
* Down words     – letterIndex values step by 2 (e.g. 8, 10, 12).  The
                   odd-index positions are crossword intersections whose cells
                   are owned by the crossing across tile, so only the
                   non-intersection letters appear in the down tile.
                   A down word with 3 visible letters is actually 5 letters
                   long (positions p, p+1*, p+2, p+3*, p+4 where * = gap).

Single-letter fragments and words with < 3 visible letters are discarded.
"""

import datetime
from collections import defaultdict

import requests
import urllib3

urllib3.disable_warnings()

from .game_result import GameResult

URL = "https://knotwise.games/games/tilerdle"
_API = "https://knotwise.games/api/tilerdle/puzzle/{date}"


def _extract_words(tiles: list[dict]) -> dict[str, list[str]]:
    """
    Return {"across": [...], "down": [...]} where:
      across – complete words from contiguous-step-1 letterIndex runs (>= 3 letters)
      down   – partial sequences from step-2 letterIndex patterns (>= 3 visible letters),
               formatted as "A_H_A" to show the two unknown intersection letters
    """
    words_map: dict[int, dict[int, str]] = defaultdict(dict)
    for tile in tiles:
        for row in tile.get("grid", []):
            for cell in row:
                if cell:
                    letter, word_idx, letter_idx = cell
                    words_map[word_idx][letter_idx] = letter.upper()

    across: list[str] = []
    down: list[str] = []

    for _, letters in sorted(words_map.items()):
        sorted_pairs = sorted(letters.items())  # [(letterIdx, letter), ...]
        n = len(sorted_pairs)
        if n < 2:
            continue

        steps = [sorted_pairs[i + 1][0] - sorted_pairs[i][0] for i in range(n - 1)]

        if all(s == 1 for s in steps):
            # Contiguous run — complete across word.
            word = "".join(ltr for _, ltr in sorted_pairs)
            if len(word) >= 3:
                across.append(word)

        elif all(s == 2 for s in steps):
            # Pure step-2 — down word, only non-intersection letters visible.
            # Format as "A_H_A" to show the unknown intersection positions.
            letters_list = [ltr for _, ltr in sorted_pairs]
            if len(letters_list) >= 3:
                down.append("_".join(letters_list))

        else:
            # Mixed pattern (e.g. RECEPTION: steps 1…1,2,2) — the long contiguous
            # prefix is the across word; any step-2 tail is discarded.
            best_run: list[str] = []
            current_run: list[str] = [sorted_pairs[0][1]]
            for i in range(1, n):
                if steps[i - 1] == 1:
                    current_run.append(sorted_pairs[i][1])
                else:
                    if len(current_run) > len(best_run):
                        best_run = current_run[:]
                    current_run = [sorted_pairs[i][1]]
            if len(current_run) > len(best_run):
                best_run = current_run
            if len(best_run) >= 3:
                across.append("".join(best_run))

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
