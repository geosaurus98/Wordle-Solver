from __future__ import annotations

"""
Quordle solver for https://www.merriam-webster.com/games/quordle/#/

DOM structure (confirmed by live probe 2026-05-16):
  Boards: 4 parent divs, each containing 9 .quordle-guess-row children
  Tiles:  .quordle-box  inside each row (5 per row)
  Feedback classes on .quordle-box:
    bg-box-correct  =>  correct (green,  rgb 0,204,136)
    bg-box-diff     =>  present (yellow, rgb 255,204,0)
    <neither>       =>  absent
  Row aria-label patterns:
    "Row N. Current guess ."   - active input row
    "Row N. Future guess."     - not yet reached
    "Row N. Guess WORD. "      - committed guess
"""

import argparse
import asyncio
import time
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import Page, async_playwright

from .extract_word_lists import main as extract_main
from .solver import filter_candidates, is_solved_feedback, load_words, choose_next_guess


URL = "https://www.merriam-webster.com/games/quordle/#/classic"
_LANDING = "https://www.merriam-webster.com/games/quordle/#/"
DATA_DIR = Path(__file__).resolve().parent / "data"
NUM_BOARDS = 4
MAX_TURNS = 9

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
    board_selectors: list[str]  # e.g. ['[data-quordle-board="0"]', ...]
    rows_per_board: int


async def _dismiss_overlays(page: Page) -> None:
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


async def detect(page: Page) -> Detected:
    await page.wait_for_load_state("domcontentloaded")
    await asyncio.sleep(4.0)
    await _dismiss_overlays(page)
    await asyncio.sleep(0.5)

    result = await page.evaluate(
        """
        () => {
          // Group .quordle-guess-row elements by their direct parent.
          const rows = Array.from(document.querySelectorAll('.quordle-guess-row'));
          if (rows.length === 0) return null;

          const parentMap = new Map();
          rows.forEach(r => {
            const p = r.parentElement;
            if (!p) return;
            if (!parentMap.has(p)) parentMap.set(p, []);
            parentMap.get(p).push(r);
          });

          // Keep only parents with enough rows (boards have MAX_TURNS rows each).
          const boards = Array.from(parentMap.entries())
            .filter(([_p, rs]) => rs.length >= 6)
            .slice(0, 4);

          if (boards.length < 4) return null;

          boards.forEach(([p, _rs], i) => {
            p.setAttribute('data-quordle-board', String(i));
          });

          return {
            count: boards.length,
            selectors: boards.map((_b, i) => `[data-quordle-board="${i}"]`),
            rowsPerBoard: boards[0][1].length,
          };
        }
        """
    )

    if not result or int(result.get("count", 0)) < NUM_BOARDS:
        raise RuntimeError(
            f"Could not detect {NUM_BOARDS} Quordle boards "
            f"(found {result.get('count') if result else 0}). "
            "Ensure .quordle-guess-row elements exist on the page."
        )

    return Detected(
        board_selectors=result["selectors"][:NUM_BOARDS],
        rows_per_board=int(result["rowsPerBoard"]),
    )


async def current_row_index(page: Page, detected: Detected, board_idx: int = 0) -> int:
    """Return the index of the 'Current guess' row within the given board."""
    sel = detected.board_selectors[board_idx]
    return int(
        await page.evaluate(
            """
            (boardSel) => {
              const b = document.querySelector(boardSel);
              if (!b) return 0;
              const rows = Array.from(b.querySelectorAll('.quordle-guess-row'));
              for (let i = 0; i < rows.length; i++) {
                const aria = (rows[i].getAttribute('aria-label') || '').toLowerCase();
                if (aria.includes('current guess')) return i;
              }
              return rows.length;
            }
            """,
            sel,
        )
    )


async def current_shared_row(page: Page, detected: Detected) -> int:
    """
    Return the current shared guess row by checking ALL boards for a 'Current guess' row.
    When some boards are solved they lose the 'current guess' indicator; we use any remaining one.
    Returns max_turns (rows_per_board) when all boards are done.
    """
    return int(
        await page.evaluate(
            """
            (boards) => {
              for (const bSel of boards) {
                const b = document.querySelector(bSel);
                if (!b) continue;
                const rows = Array.from(b.querySelectorAll('.quordle-guess-row'));
                for (let i = 0; i < rows.length; i++) {
                  const aria = (rows[i].getAttribute('aria-label') || '').toLowerCase();
                  if (aria.includes('current guess')) return i;
                }
              }
              return 9;  // all done / max fallback
            }
            """,
            detected.board_selectors,
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


async def wait_for_acceptance(page: Page, detected: Detected, before_row: int, timeout_s: float = 8.0) -> bool:
    """Wait until the current-guess row advances past before_row."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        now = await current_shared_row(page, detected)
        if now >= before_row + 1:
            return True
        await asyncio.sleep(0.08)
    return False


async def read_feedback_for_row(page: Page, detected: Detected, row_idx: int) -> list[list[int]]:
    """
    Read tile states for a committed row across all 4 boards.
    Returns list of 4 x 5-element lists: 0=absent, 1=present, 2=correct.
    """
    return await page.evaluate(
        """
        ({boards, rowIdx}) => {
          function stateFromBox(box) {
            const cls = box.className || '';
            if (cls.includes('bg-box-correct')) return 2;
            if (cls.includes('bg-box-diff'))    return 1;
            return 0;
          }
          const out = [];
          for (const bSel of boards) {
            const b = document.querySelector(bSel);
            if (!b) { out.push([0,0,0,0,0]); continue; }
            const rows = Array.from(b.querySelectorAll('.quordle-guess-row'));
            if (rowIdx >= rows.length) { out.push([0,0,0,0,0]); continue; }
            const boxes = Array.from(rows[rowIdx].querySelectorAll('.quordle-box')).slice(0, 5);
            if (boxes.length !== 5) { out.push([0,0,0,0,0]); continue; }
            out.push(boxes.map(stateFromBox));
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
        raise RuntimeError("Word lists missing. Run: py -m daily_puzzles.extract_word_lists")

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

        # Navigate via the landing page and click into the game.
        # Direct goto to #/classic in headless mode doesn't trigger the hash router.
        landing = url.split("#")[0] + "#/"
        await page.goto(landing, wait_until="domcontentloaded", timeout=120_000)
        await asyncio.sleep(3.5)
        await _dismiss_overlays(page)
        await asyncio.sleep(0.5)
        # Click the first "Play" link (→ #/classic, the daily game)
        try:
            play_link = page.locator("a[href*='#/classic']").first
            if await play_link.count() > 0:
                await play_link.click(timeout=3000)
            else:
                # Fallback: navigate directly and hope JS is ready by now
                await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        except Exception:
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        detected = await detect(page)
        print(f"Detected {len(detected.board_selectors)} boards, {detected.rows_per_board} rows each")
        if dry_run:
            await context.close()
            return result

        board_candidates: list[list[str]] = [list(answers) for _ in range(NUM_BOARDS)]
        solved = [False] * NUM_BOARDS
        guessed: set[str] = set()
        _board_answers: list[str | None] = [None] * NUM_BOARDS
        _board_guesses: list[list[dict]] = [[] for _ in range(NUM_BOARDS)]

        while not all(solved):
            row_idx = await current_shared_row(page, detected)
            if row_idx >= max_turns:
                break

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

            print(f"Turn {row_idx + 1}/{max_turns}: guessing {guess}")
            before_counts = [len(c) for c in board_candidates]
            before_row = row_idx
            await submit_guess(page, guess)
            accepted = await wait_for_acceptance(page, detected, before_row, timeout_s=9.0)
            if not accepted:
                print(f"  '{guess}' not accepted; removing and retrying.")
                guessed.add(guess)
                allowed = [w for w in allowed if w != guess]
                await clear_current_guess(page, 5)
                continue

            guessed.add(guess)
            allowed = [w for w in allowed if w != guess]
            await asyncio.sleep(0.4)  # allow flip animations to complete

            feedbacks = await read_feedback_for_row(page, detected, before_row)
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
                f"  candidates (min/median/max): "
                f"{min(remaining)}/{sorted(remaining)[len(remaining)//2]}/{max(remaining)}; "
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
