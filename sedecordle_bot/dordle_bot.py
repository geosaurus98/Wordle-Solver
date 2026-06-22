from __future__ import annotations

"""
Dordle solver for https://zaratustra.itch.io/dordle

DOM structure (confirmed by live probe 2026-05-16):
  Game is hosted in an iframe at html-classic.itch.zone
  Box IDs: box{board},{row},{col}  (board=1|2, row=1-7, col=1-5, all 1-indexed)
  Feedback via inline style attribute on committed tiles:
    background-image: linear-gradient(...var(--nc)...) => present  (yellow, #fc0)
    background-color: var(--okc)                       => correct  (green,  #0c8)
    background-color: var(--bgc)                       => absent   (white,  #fff)
  Empty tiles: background-color: var(--bgc) with no text content
  Must click #daily to start daily game from the title screen.
"""

import argparse
import asyncio
import time
from pathlib import Path

from playwright.async_api import Frame, Page, async_playwright

from .extract_word_lists import main as extract_main
from .solver import filter_candidates, is_solved_feedback, load_words, choose_next_guess


URL = "https://zaratustra.itch.io/dordle"
DATA_DIR = Path(__file__).resolve().parent / "data"
NUM_BOARDS = 2
MAX_TURNS = 7


async def _dismiss_overlays(ctx: Page | Frame) -> None:
    selectors = [
        "button:has-text(\"Close\")",
        "button:has-text(\"OK\")",
        "button:has-text(\"Got it\")",
        "button:has-text(\"Accept\")",
        "button:has-text(\"Continue\")",
        "button[aria-label=\"Close\"]",
        "button[aria-label=\"close\"]",
    ]
    for _ in range(4):
        clicked = False
        for sel in selectors:
            try:
                loc = ctx.locator(sel).first
                if await loc.count() == 0:
                    continue
                await loc.click(timeout=500)
                await asyncio.sleep(0.12)
                clicked = True
            except Exception:
                pass
        if not clicked:
            break


async def _get_game_frame(page: Page) -> Page | Frame:
    """Return the itch.io game iframe frame (or page if not found)."""
    for btn_sel in [
        ".load_iframe_btn",
        "button:has-text('Run game')",
        "button:has-text('Play')",
        "a:has-text('Run game')",
    ]:
        try:
            btn = page.locator(btn_sel).first
            if await btn.count() > 0:
                await btn.click(timeout=2000)
                await asyncio.sleep(2.0)
                break
        except Exception:
            pass

    await asyncio.sleep(1.5)

    for _ in range(8):
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            url = frame.url or ""
            if not url or "about:blank" in url:
                continue
            try:
                n = await frame.evaluate("() => document.body ? document.body.children.length : 0")
                if int(n) > 0:
                    return frame
            except Exception:
                pass
        await asyncio.sleep(0.5)

    return page


async def _start_daily_game(game: Page | Frame) -> bool:
    """Click the #daily button to start the daily game. Returns True if successful."""
    for _ in range(10):
        try:
            el = game.locator("#daily").first
            if await el.count() > 0:
                await el.click(timeout=2000)
                await asyncio.sleep(1.5)
                # Confirm game div is visible
                game_div = game.locator("#game").first
                if await game_div.count() > 0:
                    style = await game_div.get_attribute("style") or ""
                    if "display: none" not in style and "display:none" not in style:
                        return True
        except Exception:
            pass
        await asyncio.sleep(0.5)
    return False


async def _current_row(game: Page | Frame) -> int:
    """
    Return the 0-based index of the current active row.
    Uses the maximum filled row across ALL boards so that after one board is
    solved (and its subsequent rows remain blank), progress on the remaining
    board is still correctly detected.
    """
    return int(
        await game.evaluate(
            """
            ({maxTurns, numBoards}) => {
              let maxFilled = 0;
              for (let board = 1; board <= numBoards; board++) {
                for (let row = 1; row <= maxTurns; row++) {
                  const el = document.getElementById('box' + board + ',' + row + ',1');
                  if (!el || el.textContent.trim() === '') {
                    maxFilled = Math.max(maxFilled, row - 1);
                    break;
                  }
                  if (row === maxTurns) maxFilled = Math.max(maxFilled, maxTurns);
                }
              }
              return maxFilled;
            }
            """,
            {"maxTurns": MAX_TURNS, "numBoards": NUM_BOARDS},
        )
    )


async def _read_row_feedback(game: Page | Frame, row_idx: int) -> list[list[int]]:
    """
    Read feedback for committed row row_idx (0-based) across both boards.
    Returns list of 2 x 5-element lists: 0=absent, 1=present, 2=correct.
    """
    return await game.evaluate(
        """
        ({rowIdx, numBoards}) => {
          const row = rowIdx + 1;  // convert to 1-based
          const out = [];
          for (let board = 1; board <= numBoards; board++) {
            const fb = [];
            for (let col = 1; col <= 5; col++) {
              const el = document.getElementById('box' + board + ',' + row + ',' + col);
              if (!el) { fb.push(0); continue; }
              const style = el.getAttribute('style') || '';
              if (style.includes('background-image')) {
                fb.push(1);  // present (yellow gradient via --nc)
              } else if (style.includes('--okc')) {
                fb.push(2);  // correct (green via --okc)
              } else {
                fb.push(0);  // absent (white --bgc)
              }
            }
            out.push(fb);
          }
          return out;
        }
        """,
        {"rowIdx": row_idx, "numBoards": NUM_BOARDS},
    )


def _ensure_word_lists_exist() -> None:
    data_dir = Path(__file__).resolve().parent / "data"
    if (data_dir / "allowed.txt").exists() and (data_dir / "answers.txt").exists():
        return
    extract_main()


async def run_bot(
    *,
    headful: bool,
    slowmo_ms: int,
    url: str,
    dry_run: bool,
    user_data_dir: str | None,
    max_turns: int,
    opening_guesses: tuple[str, ...] | list[str] = ("arose", "linty", "chump"),
    result: dict | None = None,
) -> dict | None:
    _ensure_word_lists_exist()
    allowed, answers = load_words()
    if not allowed or not answers:
        raise RuntimeError("Word lists missing. Run: py -m sedecordle_bot.extract_word_lists")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not headful, slow_mo=slowmo_ms or 0)
        context = await browser.new_context(viewport={"width": 1400, "height": 900})
        page = await context.new_page()

        await page.goto(url, wait_until="domcontentloaded", timeout=120_000)
        await asyncio.sleep(1.5)
        await _dismiss_overlays(page)

        game = await _get_game_frame(page)
        await _dismiss_overlays(game)

        # Start the daily game from the title screen
        started = await _start_daily_game(game)
        if not started:
            raise RuntimeError("Could not start daily Dordle game (could not click #daily).")

        if dry_run:
            await context.close()
            return result

        board_candidates: list[list[str]] = [list(answers) for _ in range(NUM_BOARDS)]
        solved = [False] * NUM_BOARDS
        guessed: set[str] = set()
        _board_answers: list[str | None] = [None] * NUM_BOARDS
        _board_guesses: list[list[dict]] = [[] for _ in range(NUM_BOARDS)]
        _consecutive_rejections = 0
        _MAX_CONSECUTIVE_REJECTIONS = 20

        while not all(solved):
            row_idx = await _current_row(game)
            if row_idx >= max_turns:
                break

            active_allowed = [w for w in allowed if w not in guessed]
            if not active_allowed:
                break

            active_candidates = [c if not solved[i] else [] for i, c in enumerate(board_candidates)]

            # Play opening guesses in order, then fall through to adaptive solver.
            opening_guess = None
            for og in opening_guesses:
                if og in guessed:
                    continue
                if og in active_allowed:
                    opening_guess = og
                break  # stop at first unplayed opening

            if opening_guess:
                guess = opening_guess
            else:
                forced: str | None = None
                for bi, cand in enumerate(board_candidates):
                    if not solved[bi] and len(cand) == 1 and cand[0] not in guessed:
                        forced = cand[0]
                        break
                guess = forced or choose_next_guess(active_allowed, active_candidates)

            if guess in guessed:
                guess = next((w for w in active_allowed if w not in guessed), active_allowed[0])

            print(f"Turn {row_idx + 1}/{max_turns}: guessing {guess}")
            before_counts = [len(c) for c in board_candidates]

            # Give keyboard focus to the game area
            try:
                await game.locator(".table_guesses").first.click(timeout=1000)
            except Exception:
                try:
                    await game.locator("#game").first.click(timeout=1000)
                except Exception:
                    try:
                        await page.click("body", timeout=500)
                    except Exception:
                        pass

            await page.keyboard.type(guess, delay=15)
            await page.keyboard.press("Enter")

            # Wait for the row to advance (guess accepted)
            deadline = time.monotonic() + 9.0
            accepted = False
            while time.monotonic() < deadline:
                new_row = await _current_row(game)
                if new_row >= row_idx + 1:
                    accepted = True
                    break
                await asyncio.sleep(0.1)

            if not accepted:
                _consecutive_rejections += 1
                print(f"  '{guess}' not accepted; removing and retrying.")
                if _consecutive_rejections >= _MAX_CONSECUTIVE_REJECTIONS:
                    print(f"  Too many consecutive rejections ({_consecutive_rejections}); giving up this turn.")
                    break
                guessed.add(guess)
                allowed = [w for w in allowed if w != guess]
                for _ in range(5):
                    await page.keyboard.press("Backspace")
                continue

            _consecutive_rejections = 0
            guessed.add(guess)
            allowed = [w for w in allowed if w != guess]
            await asyncio.sleep(0.5)  # allow flip animations to complete

            feedbacks = await _read_row_feedback(game, row_idx)

            for bi, fb in enumerate(feedbacks):
                if solved[bi]:
                    continue
                filtered = filter_candidates(board_candidates[bi], guess, fb)
                if filtered:
                    board_candidates[bi] = filtered
                _board_guesses[bi].append({
                    "word": guess,
                    "feedback": fb,
                    "candidates_before": before_counts[bi],
                    "candidates_after": len(board_candidates[bi]),
                })
                if is_solved_feedback(fb):
                    solved[bi] = True
                    _board_answers[bi] = guess

            remaining = [len(c) for c in board_candidates]
            print(
                f"  candidates (min/max): {min(remaining)}/{max(remaining)}; "
                f"solved={sum(1 for x in solved if x)}/{NUM_BOARDS}"
            )

        print("Done.")
        print(f"Solved {sum(1 for x in solved if x)}/{NUM_BOARDS}.")
        if result is not None:
            result["board_answers"] = _board_answers
            result["board_guesses"] = _board_guesses
            result["solved_count"] = sum(1 for x in _board_answers if x is not None)
        await context.close()
        return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--slowmo", type=int, default=0)
    ap.add_argument("--url", type=str, default=URL)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-turns", type=int, default=MAX_TURNS)
    ap.add_argument("--opening-guesses", type=str, default="arose,linty,chump",
                    help="Comma-separated opening guess sequence (default: arose,linty,chump)")
    ap.add_argument("--user-data-dir", type=str, default=None)
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    asyncio.run(
        run_bot(
            headful=args.headful,
            slowmo_ms=args.slowmo,
            url=args.url,
            dry_run=args.dry_run,
            user_data_dir=args.user_data_dir,
            max_turns=args.max_turns,
            opening_guesses=tuple(g.strip().lower() for g in args.opening_guesses.split(",")),
        )
    )


if __name__ == "__main__":
    main()
