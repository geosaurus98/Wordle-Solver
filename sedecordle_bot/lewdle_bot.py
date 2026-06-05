from __future__ import annotations

"""
Lewdle solver for https://www.lewdlegame.com/App

Game characteristics (confirmed by live probe 2026-06-05):
  - 6-letter word, 6 attempts
  - Game state stored in localStorage:
      currentTarget  : JSON-string of base64(answer)
      words          : JSON array of 6 guess strings (empty string if not guessed yet)
      highlights     : JSON array of 6 six-char feedback strings
                       G = correct position (green)
                       Y = present but wrong position (yellow)
                       B = absent (black/grey)
      row            : current row index (int, 0-based)
  - Keyboard: div.testMainKey per letter, div.testDoubleKey for ENTER
  - Input: keyboard.type(word) + keyboard.press("Enter") works reliably
"""

import asyncio
import base64
import datetime
import time

from playwright.async_api import Page, async_playwright

from .game_result import BoardResult, GameResult, GuessStep

URL = "https://www.lewdlegame.com/App"
_WORD_LEN = 6
_MAX_TURNS = 6

# Highlight character → feedback int (0=absent, 1=present, 2=correct)
_HL_MAP = {"G": 2, "Y": 1, "B": 0}


def _parse_highlights(hl: str) -> list[int]:
    return [_HL_MAP.get(c, 0) for c in hl]


def _is_solved(hl: str) -> bool:
    return hl == "G" * _WORD_LEN


async def _dismiss_overlays(page: Page) -> None:
    selectors = [
        "button:has-text(\"Close\")",
        "button:has-text(\"OK\")",
        "button:has-text(\"Got it\")",
        "button:has-text(\"Accept\")",
        "button:has-text(\"I agree\")",
        "button:has-text(\"Continue\")",
        "[aria-label=\"Close\"]",
        "[aria-label=\"close\"]",
    ]
    for _ in range(4):
        clicked = False
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() == 0:
                    continue
                await loc.click(timeout=600)
                await asyncio.sleep(0.15)
                clicked = True
            except Exception:
                pass
        if not clicked:
            break


async def _read_state(page: Page) -> dict:
    """Read all relevant game state from localStorage."""
    return await page.evaluate("""
        () => {
            function ls(k) {
                var v = localStorage.getItem(k);
                try { return JSON.parse(v); } catch(e) { return v; }
            }
            return {
                currentTarget: ls('currentTarget'),
                words:         ls('words')      || ['','','','','',''],
                highlights:    ls('highlights') || ['BBBBBB','BBBBBB','BBBBBB','BBBBBB','BBBBBB','BBBBBB'],
                row:           parseInt(ls('row') || '0'),
                gameState:     ls('gameState')  || 'normal',
            };
        }
    """)


async def _submit_guess(page: Page, guess: str) -> None:
    """Type a guess and press Enter."""
    await _dismiss_overlays(page)
    try:
        await page.click("body", timeout=1000)
    except Exception:
        pass
    await page.keyboard.type(guess.upper(), delay=15)
    await page.keyboard.press("Enter")


async def _wait_for_guess_registered(page: Page, before_row: int, timeout_s: float = 8.0) -> bool:
    """
    Wait until the guess on before_row is registered (highlights change from all-B).
    On a first-try win the row counter stays at 0, so we detect success via the
    highlight string changing from 'BBBBBB' to anything else.
    """
    blank = "B" * _WORD_LEN
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        state = await page.evaluate(
            """
            (r) => {
                var hl = JSON.parse(localStorage.getItem('highlights') || '[]');
                var row = parseInt(localStorage.getItem('row') || '0');
                return {row: row, hl: hl[r] || 'BBBBBB'};
            }
            """,
            before_row,
        )
        # Accepted: highlights updated OR row advanced past before_row
        if state["hl"] != blank or state["row"] > before_row:
            return True
        await asyncio.sleep(0.08)
    return False


async def run_bot() -> GameResult:
    date_str = str(datetime.date.today())
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            context = await browser.new_context(
                viewport={"width": 1400, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/137.0.0.0 Safari/537.36"
                ),
                locale="en-US",
            )
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            page = await context.new_page()

            await page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
            await asyncio.sleep(3.0)
            await _dismiss_overlays(page)
            await asyncio.sleep(0.5)

            # Read game state
            state = await _read_state(page)
            raw_target = state.get("currentTarget", "")
            if not raw_target:
                await browser.close()
                return GameResult(
                    game="Lewdle", url=URL, date=date_str,
                    error="Could not read currentTarget from localStorage",
                )

            # Decode the target word from base64
            try:
                target = base64.b64decode(raw_target).decode("utf-8").upper()
            except Exception as exc:
                await browser.close()
                return GameResult(
                    game="Lewdle", url=URL, date=date_str,
                    error=f"Failed to decode currentTarget {raw_target!r}: {exc}",
                )

            words: list[str] = [w.upper() for w in state.get("words", [""] * _MAX_TURNS)]
            highlights: list[str] = state.get("highlights", ["B" * _WORD_LEN] * _MAX_TURNS)
            row: int = state.get("row", 0)

            # Reconstruct guesses already on the board
            guesses: list[GuessStep] = []
            for i in range(row):
                if words[i]:
                    guesses.append(GuessStep(
                        word=words[i],
                        feedback=_parse_highlights(highlights[i]),
                    ))

            # Check if game is already solved or exhausted
            already_solved = row > 0 and _is_solved(highlights[row - 1])
            already_done = already_solved or row >= _MAX_TURNS

            if not already_done:
                # Submit the target word directly — we know the answer from localStorage
                before_row = row
                await _submit_guess(page, target)
                accepted = await _wait_for_guess_registered(page, before_row, timeout_s=8.0)

                if not accepted:
                    # Word might not be in the valid list — read back state anyway
                    pass

                await asyncio.sleep(0.4)  # allow flip animation
                state2 = await _read_state(page)
                new_row = state2.get("row", before_row)
                new_words = [w.upper() for w in state2.get("words", words)]
                new_highlights = state2.get("highlights", highlights)
                blank = "B" * _WORD_LEN

                if accepted and new_highlights[before_row] != blank:
                    # Guess was registered — could be correct (GGGGGG) or wrong (any other)
                    guesses.append(GuessStep(
                        word=new_words[before_row],
                        feedback=_parse_highlights(new_highlights[before_row]),
                    ))
                    row = max(new_row, before_row + 1)  # row may stay 0 on first-try win
                    highlights = new_highlights
                else:
                    # Word was rejected (not in Dicktionary)
                    guesses.append(GuessStep(word=target, feedback=[0] * _WORD_LEN))

            # Determine final solved status — check the last committed highlight
            last_committed = len(guesses) - 1
            solved = last_committed >= 0 and _is_solved(
                highlights[last_committed] if last_committed < len(highlights) else ""
            )

            board = BoardResult(
                board_index=0,
                answer=target if solved else None,
                guesses=guesses,
                solved=solved,
            )

            await browser.close()

        return GameResult(
            game="Lewdle",
            url=URL,
            date=date_str,
            boards=[board],
            extra={"target": target},
        )

    except Exception as exc:
        return GameResult(game="Lewdle", url=URL, date=date_str, error=str(exc))
