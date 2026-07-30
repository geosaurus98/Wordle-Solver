from __future__ import annotations

"""
NumberWaffle solver for https://wafflegame.net/numberwaffle

The puzzle state (including solution) is stored in localStorage['wffl_prod_nwstate'].
The solution and puzzle fields are 49-char strings encoding the 7x7 grid row-by-row;
positions where x%2==1 AND y%2==1 are clue positions (stored as '#').
"""

import asyncio
import datetime

from playwright.async_api import async_playwright

from .game_result import GameResult, WaffleSwapStep

URL = "https://wafflegame.net/numberwaffle"
_LS_KEY = "wffl_prod_nwstate"


def _parse_grid(s: str) -> dict[tuple[int, int], str]:
    """Parse 49-char grid string into {(x,y): digit} for tile positions only."""
    result: dict[tuple[int, int], str] = {}
    for i, ch in enumerate(s):
        x, y = i % 7, i // 7
        if ch != "#":
            result[(x, y)] = ch
    return result


def _plan_swaps(
    current: dict[tuple[int, int], str],
    target: dict[tuple[int, int], str],
) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """
    Greedy swap planner: returns a minimal list of (pos_a, pos_b) pairs.

    Key constraint: pos_b must itself be a mismatch (state[pos_b] != target[pos_b]).
    Without this, the planner displaces an already-correct tile and cycles forever.
    Since current and target contain the same multiset of digits, a needed digit is
    always available at some mismatch position whenever pos_a is a mismatch.
    """
    state = dict(current)
    swaps: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for _ in range(len(state) * 2):
        mismatches = [p for p, v in state.items() if v != target[p]]
        if not mismatches:
            break
        pos_a = mismatches[0]
        needed = target[pos_a]
        # Only pick pos_b from mismatch positions to avoid displacing a correct tile.
        pos_b = next(
            (p for p in mismatches if state[p] == needed and p != pos_a),
            None,
        )
        if pos_b is None:
            break
        state[pos_a], state[pos_b] = state[pos_b], state[pos_a]
        swaps.append((pos_a, pos_b))
    return swaps


async def run_bot() -> GameResult:
    date_str = str(datetime.date.today())
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(viewport={"width": 1200, "height": 900})
            page = await ctx.new_page()
            await page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
            await asyncio.sleep(3)

            for sel in [
                "button:has-text('OK')", "button:has-text('Got it')",
                "button:has-text('Play')", "button:has-text('Accept')",
                "[aria-label='close']", "[aria-label='Close']",
            ]:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        await el.click(timeout=1000)
                        await asyncio.sleep(0.3)
                except Exception:
                    pass

            await asyncio.sleep(1)

            raw = await page.evaluate(f"""
                () => {{
                    const v = localStorage.getItem('{_LS_KEY}');
                    return v ? JSON.parse(v) : null;
                }}
            """)
            await browser.close()
    except Exception as exc:
        return GameResult(game="NumberWaffle", url=URL, date=date_str, error=str(exc))

    if not raw:
        return GameResult(
            game="NumberWaffle", url=URL, date=date_str,
            error=f"localStorage key '{_LS_KEY}' not found — game may not have loaded",
        )

    solution_str = raw.get("solution", "")
    puzzle_str = raw.get("puzzle", "")
    if not solution_str or not puzzle_str:
        return GameResult(
            game="NumberWaffle", url=URL, date=date_str,
            error="Missing solution/puzzle in localStorage",
        )

    solution_grid = _parse_grid(solution_str)
    current_grid = _parse_grid(puzzle_str)

    swaps_raw = _plan_swaps(current_grid, solution_grid)
    waffle_swaps = [
        WaffleSwapStep(
            from_pos=a,
            to_pos=b,
            from_letter=current_grid[a],
            to_letter=current_grid[b],
        )
        for a, b in swaps_raw
    ]

    return GameResult(
        game="NumberWaffle",
        url=URL,
        date=date_str,
        waffle_swaps=waffle_swaps,
        extra={
            "solution_grid": {f"{x},{y}": v for (x, y), v in solution_grid.items()},
            "puzzle_grid": {f"{x},{y}": v for (x, y), v in current_grid.items()},
            "clues": raw.get("clues", []),
            "swaps_remaining": raw.get("swapsRemaining", "?"),
            "puzzle_number": raw.get("currentPuzzle", "?"),
        },
    )
