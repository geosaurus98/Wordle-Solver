from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

from playwright.async_api import Page, async_playwright

from .extract_nyt_word_lists import main as extract_nyt_main
from .fetch_nyt_answers import main as fetch_nyt_answers_main
from .solver import (
    State,
    choose_best_guess_single_board,
    filter_candidates,
    is_solved_feedback,
    load_word_list,
)


NYT_URL = "https://www.nytimes.com/games/wordle/index.html"
DATA_DIR = Path(__file__).resolve().parent / "data"


TILE_SELECTORS = [
    '[data-testid="tile"]',
    '[data-state][data-testid*="tile"]',
    'div[class*="Tile-module_tile"]',
]


async def _dismiss_overlays(page: Page) -> None:
    # Best effort. Wordle often shows tutorial / stats / cookie prompts.
    selectors = [
        'button[aria-label="Close"]',
        'button[aria-label="close"]',
        "button:has-text(\"Close\")",
        "button:has-text(\"Continue\")",
        "button:has-text(\"OK\")",
        "button:has-text(\"Got it\")",
        "button:has-text(\"Play\")",
        "button:has-text(\"I Agree\")",
        "button:has-text(\"Accept\")",
        "button:has-text(\"No Thanks\")",
        "button:has-text(\"Not Now\")",
        "[data-testid=\"close-button\"]",
    ]
    for _ in range(6):
        clicked = False
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() == 0:
                    continue
                await loc.click(timeout=500)
                await asyncio.sleep(0.15)
                clicked = True
            except Exception:
                pass
        if not clicked:
            break


async def _start_game_if_needed(page: Page) -> None:
    # Landing screen has a big "Play" button before the board exists.
    try:
        play = page.locator("button:has-text(\"Play\"), a:has-text(\"Play\")").first
        if await play.count() > 0:
            await play.click(timeout=1500)
            await asyncio.sleep(0.5)
    except Exception:
        pass


async def detect_tiles(page: Page) -> str:
    await page.wait_for_load_state("domcontentloaded")
    deadline = time.monotonic() + 20.0
    last_err: Exception | None = None

    while time.monotonic() < deadline:
        await _dismiss_overlays(page)
        await _start_game_if_needed(page)
        await _dismiss_overlays(page)

        for sel in TILE_SELECTORS:
            try:
                # Use locator engine (pierces shadow DOM); document.querySelectorAll does not.
                n = await page.locator(sel).count()
                if int(n) >= 30:
                    return sel
            except Exception as e:
                last_err = e

        await asyncio.sleep(0.35)

    raise RuntimeError(f"Could not find Wordle tiles on the page. Last error: {last_err}")


async def _tiles_row_states(page: Page, tile_sel: str, row_idx: int) -> list[int] | None:
    loc = page.locator(tile_sel)
    res = await loc.evaluate_all(
        """
        (tiles, rowIdx) => {
          if (!tiles || tiles.length < 30) return null;
          const start = rowIdx * 5;
          const row = tiles.slice(start, start + 5);
          if (row.length !== 5) return null;

          function normState(t) {
            const ds = (t.getAttribute('data-state') || '').toLowerCase();
            const aria = (t.getAttribute('aria-label') || '').toLowerCase();
            const cls = (t.className || '').toLowerCase();
            const s = (ds + ' ' + aria + ' ' + cls).trim();
            if (s.includes('correct')) return 2;
            if (s.includes('present')) return 1;
            if (s.includes('absent')) return 0;
            return null;
          }
          return row.map(normState);
        }
        """,
        row_idx,
    )
    if not res:
        return None
    row = [int(x) if x is not None else -1 for x in res]
    if any(x < 0 for x in row):
        return None
    return row


async def current_row_index(page: Page, tile_sel: str) -> int:
    loc = page.locator(tile_sel)
    return int(
        await loc.evaluate_all(
            """
            (tiles) => {
              if (!tiles || tiles.length < 30) return 0;
              for (let r = 0; r < 6; r++) {
                const row = tiles.slice(r*5, r*5+5);
                const letters = row.map(t => (t.textContent || '').trim()).join('');
                if (letters.length === 0) return r;
              }
              return 6;
            }
            """
        )
    )


async def focus_game(page: Page) -> None:
    try:
        await page.click("body", timeout=1000)
    except Exception:
        pass


async def submit_guess(page: Page, guess: str) -> None:
    await _dismiss_overlays(page)
    await focus_game(page)
    await page.keyboard.type(guess, delay=20)
    await page.keyboard.press("Enter")


async def clear_current_guess(page: Page, n: int = 5) -> None:
    await focus_game(page)
    for _ in range(n):
        await page.keyboard.press("Backspace")


async def alert_text(page: Page) -> str | None:
    # Wordle shows toasts via role="alert".
    try:
        loc = page.locator('[role="alert"]').first
        if await loc.count() == 0:
            return None
        t = await loc.text_content()
        t = (t or "").strip()
        return t or None
    except Exception:
        return None


async def _check_toast(page: Page) -> str | None:
    """Single JS evaluation covering all NYT toast selectors."""
    try:
        result = await page.evaluate(
            """
            () => {
                const sels = ['[role="alert"]', '[data-testid="toast"]', '[class*="Toast"]', '[class*="toast"]'];
                const pats = ['not in word list', 'not a valid', 'not enough letters'];
                for (const sel of sels) {
                    for (const el of document.querySelectorAll(sel)) {
                        const t = (el.textContent || '').toLowerCase().trim();
                        if (t && pats.some(p => t.includes(p)))
                            return el.textContent.trim();
                    }
                }
                return null;
            }
            """
        )
        return result
    except Exception:
        return None


async def wait_for_evaluation_or_reject(page: Page, tile_sel: str, row_idx: int, timeout_s: float = 8.0) -> tuple[bool, list[int] | None, str | None]:
    # Sequential polling: check toast first (fast JS eval), then tile states.
    # No concurrent tasks — avoids CDP command interleaving issues.
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        txt = await _check_toast(page)
        if txt:
            return False, None, txt
        row = await _tiles_row_states(page, tile_sel, row_idx)
        if row is not None:
            return True, row, None
        await asyncio.sleep(0.05)
    return False, None, "timeout waiting for evaluation"


def _ensure_nyt_lists() -> tuple[list[str], list[str]]:
    import datetime, os
    allowed_path = DATA_DIR / "nyt_allowed.txt"
    answers_path = DATA_DIR / "nyt_answers.txt"
    if not allowed_path.exists():
        extract_nyt_main()
    # Refresh answers daily: the API gains one new entry each day.
    answers_stale = (
        not answers_path.exists()
        or datetime.date.fromtimestamp(os.path.getmtime(answers_path)) < datetime.date.today()
    )
    if answers_stale:
        print("Refreshing answer list from NYT API...")
        try:
            fetch_nyt_answers_main()
        except Exception as e:
            print(f"  Answer refresh failed ({e}), using existing file.")
    allowed = load_word_list(allowed_path)
    answers = load_word_list(answers_path)
    if not allowed:
        allowed = load_word_list(DATA_DIR / "allowed.txt")
    if not answers:
        answers = allowed
    return allowed, answers


async def run_bot(
    headful: bool,
    slowmo_ms: int,
    url: str,
    user_data_dir: str | None,
    channel: str | None,
    profile_directory: str | None,
    dry_run: bool,
    first_guess: str,
    allowed: list[str],
    answers: list[str],
) -> None:
    # Suppress Windows-specific ConnectionResetError noise from Playwright pipe cleanup.
    loop = asyncio.get_running_loop()
    _orig_handler = loop.get_exception_handler() or loop.default_exception_handler
    loop.set_exception_handler(
        lambda lp, ctx: None if isinstance(ctx.get("exception"), ConnectionResetError) else _orig_handler(ctx)
    )

    async with async_playwright() as p:
        if user_data_dir:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=not headful,
                slow_mo=slowmo_ms or 0,
                viewport={"width": 1200, "height": 900},
                channel=channel,
                args=[f"--profile-directory={profile_directory}"] if profile_directory else None,
            )
            page = context.pages[0] if context.pages else await context.new_page()
        else:
            browser = await p.chromium.launch(headless=not headful, slow_mo=slowmo_ms or 0)
            context = await browser.new_context(viewport={"width": 1200, "height": 900})
            page = await context.new_page()

        await page.goto(url, wait_until="domcontentloaded")
        tile_sel = await detect_tiles(page)
        print(f"Detected tiles using selector: {tile_sel}")
        if dry_run:
            await context.close()
            return

        candidates = list(answers)
        guessed: set[str] = set()

        # Build opener queue: comma-separated words played in order before the adaptive solver.
        opener_queue = [
            w.strip().lower()
            for w in (first_guess or "").split(",")
            if w.strip()
        ]

        # Loop on actual game rows rather than attempt count so rejections don't waste turns.
        max_attempts = 20
        for attempt in range(max_attempts):
            await _dismiss_overlays(page)
            row_idx = await current_row_index(page, tile_sel)
            if row_idx >= 6:
                break

            # Consume openers in order; fall back to adaptive once the queue is empty.
            guess = None
            while opener_queue:
                candidate = opener_queue[0]
                if candidate not in guessed and candidate in allowed:
                    guess = opener_queue.pop(0)
                    break
                opener_queue.pop(0)  # skip invalid/already-guessed opener

            if guess is None:
                guess = choose_best_guess_single_board(allowed, candidates, guessed=guessed)
            if guess in guessed:
                guess = next(w for w in allowed if w not in guessed)

            print(f"Row {row_idx+1}/6: guessing {guess} (candidates={len(candidates)})")
            await submit_guess(page, guess)

            ok, fb, err = await wait_for_evaluation_or_reject(page, tile_sel, row_idx)
            if not ok or fb is None:
                print(f"  Guess rejected: {err}. Skipping '{guess}' and retrying row {row_idx+1}.")
                guessed.add(guess)
                allowed = [w for w in allowed if w != guess]
                candidates = [w for w in candidates if w != guess]
                await clear_current_guess(page, 5)
                await asyncio.sleep(0.3)
                continue

            # Let the tile flip animation finish before typing the next guess.
            await asyncio.sleep(2.0)
            guessed.add(guess)
            allowed = [w for w in allowed if w != guess]
            candidates2 = filter_candidates(candidates, guess, fb)
            if candidates2:
                candidates = candidates2

            if is_solved_feedback(fb):
                print("Solved.")
                break

        await context.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headful", action="store_true", help="Show the browser window.")
    ap.add_argument("--slowmo", type=int, default=0, help="Playwright slowmo in ms.")
    ap.add_argument("--url", type=str, default=NYT_URL, help="Game URL.")
    ap.add_argument("--channel", type=str, default="chrome", help="Browser channel (e.g. chrome, msedge).")
    ap.add_argument(
        "--profile-directory",
        type=str,
        default=None,
        help='Chrome profile directory name (e.g. "Default", "Profile 1"). Used with --user-data-dir.',
    )
    ap.add_argument(
        "--first-guess",
        type=str,
        default="AROSE,UNTIL",
        help=(
            "Comma-separated opener sequence played before the adaptive solver takes over. "
            "E.g. 'AROSE,LINTY' (default) or 'AROSE,LINTY,CHUMP'. "
            "After the openers the bot switches to minimax to exploit feedback."
        ),
    )
    ap.add_argument("--dry-run", action="store_true", help="Only detect tiles, then exit.")
    ap.add_argument(
        "--user-data-dir",
        type=str,
        default=None,
        help="Use a persistent browser profile directory (saves localStorage/cookies across runs).",
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    allowed, answers = _ensure_nyt_lists()
    if not allowed or not answers:
        raise RuntimeError("No word lists available.")
    asyncio.run(
        run_bot(
            headful=args.headful,
            slowmo_ms=args.slowmo,
            url=args.url,
            user_data_dir=args.user_data_dir,
            channel=(args.channel.strip() if args.channel else None),
            profile_directory=args.profile_directory,
            dry_run=args.dry_run,
            first_guess=args.first_guess,
            allowed=allowed,
            answers=answers,
        )
    )


if __name__ == "__main__":
    main()

