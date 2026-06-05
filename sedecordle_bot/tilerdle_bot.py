from __future__ import annotations

"""
Tilerdle solver for https://knotwise.games/games/tilerdle

Fetches the day's puzzle from the REST API (no browser needed) and extracts
the hidden words from the tile letter grids.
"""

import datetime
from collections import defaultdict

import requests
import urllib3

urllib3.disable_warnings()

from .game_result import GameResult

URL = "https://knotwise.games/games/tilerdle"
_API = "https://knotwise.games/api/tilerdle/puzzle/{date}"


def _extract_words(tiles: list[dict]) -> list[str]:
    """
    Group non-null letter cells by wordIndex, sort by letterIndex, then split into
    contiguous runs.

    Background: in Tilerdle's crossword grid the letterIndex encodes each letter's
    absolute position within its word.  Across-word tiles contain all letters for
    those words (contiguous run), while down-word tiles omit intersection cells
    (which are attributed to the crossing across tile).  Splitting on non-contiguous
    gaps separates the complete across words from the scattered intersection letters
    of down words, and filtering to length >= 3 removes the uninformative fragments.
    """
    words_map: dict[int, dict[int, str]] = defaultdict(dict)
    for tile in tiles:
        for row in tile.get("grid", []):
            for cell in row:
                if cell:
                    letter, word_idx, letter_idx = cell
                    words_map[word_idx][letter_idx] = letter.upper()

    results: list[str] = []
    for _, letters in sorted(words_map.items()):
        sorted_pairs = sorted(letters.items())  # [(letter_idx, letter), ...]
        # Split into runs of consecutive letterIndices (step == 1)
        run: list[str] = [sorted_pairs[0][1]]
        for (prev_idx, _), (curr_idx, curr_letter) in zip(sorted_pairs, sorted_pairs[1:]):
            if curr_idx == prev_idx + 1:
                run.append(curr_letter)
            else:
                if len(run) >= 3:
                    results.append("".join(run))
                run = [curr_letter]
        if len(run) >= 3:
            results.append("".join(run))

    return results


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
        words = _extract_words(data.get("tiles", []))
    except Exception as exc:
        return GameResult(game="Tilerdle", url=URL, date=date_str, error=f"Parse error: {exc}")

    return GameResult(
        game="Tilerdle",
        url=URL,
        date=date_str,
        extra={
            "theme": theme,
            "grid_size": grid_size,
            "words": words,
        },
    )
