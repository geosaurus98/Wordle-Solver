from __future__ import annotations

import argparse
import asyncio
import datetime
import time
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import Page, async_playwright

from .extract_word_lists import main as extract_main
from .solver import filter_candidates, is_solved_feedback, load_words, choose_next_guess


URL = "https://www.merriam-webster.com/games/octordle/daily"
DATA_DIR = Path(__file__).resolve().parent / "data"

# Browser stealth settings to bypass Cloudflare's bot challenge on MW pages.
_STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-setuid-sandbox",
    "--disable-infobars",
]
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/137.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class Detected:
    board_selectors: list[str]  # ["#board-1", ...]
    rows: int


async def _dismiss_overlays(page: Page) -> None:
    # Best-effort: cookie, newsletter, help, etc.
    selectors = [
        "button:has-text(\"Close\")",
        "button:has-text(\"OK\")",
        "button:has-text(\"Got it\")",
        "button:has-text(\"Accept\")",
        "button:has-text(\"I agree\")",
        "button:has-text(\"Continue\")",
        "button[aria-label=\"Close\"]",
        "button[aria-label=\"close\"]",
    ]
    for _ in range(6):
        clicked = False
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() == 0:
                    continue
                await loc.click(timeout=600)
                await asyncio.sleep(0.12)
                clicked = True
            except Exception:
                pass
        if not clicked:
            break


def _today_puzzle_number() -> int:
    """
    Calculate today's Octordle puzzle number from the known epoch.
    Puzzle 1 was published on 2022-01-25 (epoch = 2022-01-24, day 0 unused).
    Verified: puzzle 1593 on 2026-06-05, (date(2026,6,5) - date(2022,1,24)).days == 1593.
    """
    epoch = datetime.date(2022, 1, 24)
    return (datetime.date.today() - epoch).days




async def _navigate_to_daily_game(page) -> None:
    """
    Navigate to today's Octordle daily puzzle.

    Direct navigation to the archive URL triggers a JS migration redirect that
    loops through Britannica and can take 60+ s.  The reliable approach is:

      1. Navigate to the hub (merriam-webster.com/games/octordle/).
         The page shows "Loading.." while it bootstraps user/session state
         via async API calls.  We wait 15 s to let that settle.
      2. Use a JS location assignment to navigate to today's archive URL.
         With session state set the SPA routes directly (no Britannica detour).
      3. Poll until the 8 game boards appear (~5-8 s).

    Total elapsed: ~25-30 s.  The puzzle number is derived from the known epoch
    (2022-01-24, verified: puzzle 1593 on 2026-06-05).
    """
    _HUB = "https://www.merriam-webster.com/games/octordle/"

    puzzle_num = _today_puzzle_number()
    daily_url = f"https://www.merriam-webster.com/games/octordle/daily/{puzzle_num}?archive=1"
    print(f"  Octordle puzzle #{puzzle_num}: navigating via hub...")

    # Step 1: Navigate to the hub so the SPA bootstraps its session state.
    try:
        await page.goto(_HUB, wait_until="domcontentloaded", timeout=60_000)
    except Exception:
        pass
    # Give the hub 25 s to complete async initialisation (stays on "Loading.." visually,
    # but state is being set by background XHR/cookie calls).
    await asyncio.sleep(25.0)

    # Step 2: JS-navigate to the archive URL (SPA intercepts, no Britannica redirect).
    # The evaluate raises "Execution context was destroyed" because the navigation
    # immediately invalidates the frame — that's expected; just ignore it.
    try:
        await page.evaluate(f"window.location.href = '{daily_url}'")
    except Exception:
        pass

    # Step 3: Poll for boards (typically appear within 8 s of the JS navigate).
    deadline = time.monotonic() + 45.0
    while time.monotonic() < deadline:
        n = await page.locator(".board").count()
        if n >= 8:
            break
        await asyncio.sleep(0.5)

    await _dismiss_overlays(page)


async def detect(page: Page) -> Detected:
    n = await page.locator(".board").count()
    if n < 8:
        raise RuntimeError(f"Expected 8 boards, found {n}")

    # Boards have ids board-1..board-8
    board_selectors = [f"#board-{i}" for i in range(1, 9)]

    rows = await page.locator(f"{board_selectors[0]} .board-row").count()
    if rows <= 0:
        raise RuntimeError("Could not detect board rows.")

    return Detected(board_selectors=board_selectors, rows=int(rows))


async def current_row_index(page: Page, detected: Detected, board_idx: int = 0) -> int:
    sel = detected.board_selectors[board_idx]
    return int(
        await page.evaluate(
            """
            (boardSel) => {
              const b = document.querySelector(boardSel);
              if (!b) return 0;
              const rows = Array.from(b.querySelectorAll('.board-row'));
              for (let i = 0; i < rows.length; i++) {
                const aria = (rows[i].getAttribute('aria-label') || '').toLowerCase();
                if (aria.includes('current guess')) return i;
              }
              // If not found, assume full (game over / solved)
              return rows.length;
            }
            """,
            sel,
        )
    )


async def submit_guess(page: Page, guess: str) -> None:
    await _dismiss_overlays(page)
    try:
        await page.click("body", timeout=1000)
    except Exception:
        pass
    await page.keyboard.type(guess, delay=12)
    await page.keyboard.press("Enter")


async def clear_current_guess(page: Page, n: int = 5) -> None:
    try:
        await page.click("body", timeout=1000)
    except Exception:
        pass
    for _ in range(n):
        await page.keyboard.press("Backspace")


async def wait_for_acceptance(
    page: Page,
    detected: Detected,
    before_row: int,
    timeout_s: float = 8.0,
) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        now = await current_row_index(page, detected, 0)
        if now >= before_row + 1:
            return True
        await asyncio.sleep(0.08)
    return False


def _state_from_classes(cls: str) -> int:
    c = cls.lower()
    if "exact-match" in c:
        return 2
    if "word-match" in c:
        return 1
    return 0


async def read_feedback_for_row(page: Page, detected: Detected, row_idx: int) -> list[list[int]]:
    return await page.evaluate(
        """
        ({boards, rowIdx}) => {
          function stateFromClass(cls) {
            const c = (cls || '').toLowerCase();
            if (c.includes('exact-match')) return 2;
            if (c.includes('word-match')) return 1;
            return 0;
          }
          const out = [];
          for (const bSel of boards) {
            const b = document.querySelector(bSel);
            if (!b) { out.push([null,null,null,null,null]); continue; }
            const rows = Array.from(b.querySelectorAll('.board-row'));
            if (rowIdx >= rows.length) { out.push([null,null,null,null,null]); continue; }
            const cells = Array.from(rows[rowIdx].querySelectorAll('.letter')).slice(0,5);
            if (cells.length !== 5) { out.push([null,null,null,null,null]); continue; }
            out.push(cells.map(el => stateFromClass(el.className)));
          }
          return out;
        }
        """,
        {"boards": detected.board_selectors, "rowIdx": row_idx},
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
        raise RuntimeError("Word lists missing/empty. Run: py -m daily_puzzles.extract_word_lists")

    async with async_playwright() as p:
        if user_data_dir:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=not headful,
                slow_mo=slowmo_ms or 0,
                viewport={"width": 1400, "height": 900},
                args=_STEALTH_ARGS,
                user_agent=_USER_AGENT,
                locale="en-US",
            )
            page = context.pages[0] if context.pages else await context.new_page()
        else:
            browser = await p.chromium.launch(
                headless=not headful,
                slow_mo=slowmo_ms or 0,
                args=_STEALTH_ARGS,
            )
            context = await browser.new_context(
                viewport={"width": 1400, "height": 900},
                user_agent=_USER_AGENT,
                locale="en-US",
            )
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            page = await context.new_page()

        await _navigate_to_daily_game(page)
        detected = await detect(page)
        print(f"Detected {len(detected.board_selectors)} boards, rows={detected.rows}")
        if dry_run:
            await context.close()
            return

        board_candidates: list[list[str]] = [list(answers) for _ in range(8)]
        solved = [False] * 8
        guessed: set[str] = set()
        _board_answers: list[str | None] = [None] * 8
        _board_guesses: list[list[dict]] = [[] for _ in range(8)]

        while not all(solved):
            row_idx = await current_row_index(page, detected, 0)
            if row_idx >= max_turns:
                break

            # Forced play: if any unsolved board has one candidate, try it (once).
            forced: str | None = None
            for bi, cand in enumerate(board_candidates):
                if solved[bi]:
                    continue
                if len(cand) == 1 and cand[0] not in guessed:
                    forced = cand[0]
                    break

            active_allowed = [w for w in allowed if w not in guessed]
            if not active_allowed:
                raise RuntimeError("No allowed guesses left.")

            # Play opening guesses in order, then fall through to adaptive solver.
            opening_guess = None
            for og in opening_guesses:
                if og in guessed:
                    continue
                if og in active_allowed:
                    opening_guess = og
                break  # stop at first unplayed opening

            active_candidates = [c if not solved[i] else [] for i, c in enumerate(board_candidates)]
            guess = opening_guess or forced or choose_next_guess(active_allowed, active_candidates)
            if guess in guessed:
                guess = next(w for w in active_allowed if w not in guessed)

            print(f"Turn {row_idx+1}/{max_turns}: guessing {guess}")

            before_row = row_idx
            await submit_guess(page, guess)
            accepted = await wait_for_acceptance(page, detected, before_row, timeout_s=9.0)
            if not accepted:
                print(f"  Guess '{guess}' not accepted; removing and retrying.")
                guessed.add(guess)
                allowed = [w for w in allowed if w != guess]
                await clear_current_guess(page, 5)
                continue

            before_counts = [len(c) for c in board_candidates]
            guessed.add(guess)
            allowed = [w for w in allowed if w != guess]
            await asyncio.sleep(0.35)

            feedbacks = await read_feedback_for_row(page, detected, before_row)
            for bi, fb in enumerate(feedbacks):
                if solved[bi]:
                    continue
                if not fb or any(x is None for x in fb):
                    continue
                fb2 = [int(x) for x in fb]
                filtered = filter_candidates(board_candidates[bi], guess, fb2)
                if filtered:
                    board_candidates[bi] = filtered
                _board_guesses[bi].append({
                    "word": guess,
                    "feedback": fb2,
                    "candidates_before": before_counts[bi],
                    "candidates_after": len(board_candidates[bi]),
                })
                if is_solved_feedback(fb2):
                    solved[bi] = True
                    _board_answers[bi] = guess

            remaining = [len(c) for c in board_candidates]
            print(
                "  Remaining candidates (min/median/max): "
                f"{min(remaining)}/{sorted(remaining)[len(remaining)//2]}/{max(remaining)}; "
                f"solved={sum(1 for x in solved if x)}/8"
            )

        print("Done.")
        print(f"Solved {sum(1 for x in solved if x)}/8.")
        if result is not None:
            result["board_answers"] = _board_answers
            result["board_guesses"] = _board_guesses
            result["solved_count"] = sum(1 for x in _board_answers if x is not None)
        await context.close()
        return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headful", action="store_true", help="Show the browser window.")
    ap.add_argument("--slowmo", type=int, default=0, help="Playwright slowmo in ms.")
    ap.add_argument("--url", type=str, default=URL, help="Game URL.")
    ap.add_argument("--dry-run", action="store_true", help="Only detect boards, then exit.")
    ap.add_argument("--max-turns", type=int, default=13, help="Max guesses to play (Octordle daily is 13).")
    ap.add_argument("--opening-guesses", type=str, default="arose,linty,chump",
                    help="Comma-separated opening guess sequence (default: arose,linty,chump)")
    ap.add_argument(
        "--user-data-dir",
        type=str,
        default=None,
        help="Use a persistent browser profile directory (saves localStorage/cookies across runs).",
    )
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

