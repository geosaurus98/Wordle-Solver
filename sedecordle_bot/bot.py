from __future__ import annotations

import argparse
import asyncio
import time
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import Page, async_playwright

from .extract_word_lists import main as extract_main
from .solver import (
    filter_candidates,
    is_solved_feedback,
    load_words,
    choose_next_guess,
)


ROOT_URL = "https://www.sedecordle.com/?mode=daily"


@dataclass
class DetectedBoards:
    tile_selector: str
    board_selectors: list[str]  # selectors like [data-bot-board="0"]
    tiles_per_board: int


ABSENT_BG = "rgb(24, 26, 27)"
PRESENT_BG = "rgb(255, 204, 0)"
CORRECT_BG = "rgb(0, 204, 136)"


async def _dismiss_overlays(page: Page) -> None:
    # Best-effort: close help/patch notes/cookie modals if present.
    selectors = [
        'button[aria-label="close"]',
        'button[aria-label="Close"]',
        "button:has-text(\"close\")",
        "button:has-text(\"Close\")",
        "button:has(svg)",
        ".modal button",
        ".dialog button",
    ]
    for sel in selectors:
        try:
            await page.locator(sel).first.click(timeout=500)
            await asyncio.sleep(0.1)
        except Exception:
            pass


async def detect_boards(page: Page) -> DetectedBoards:
    await page.wait_for_load_state("domcontentloaded")
    await asyncio.sleep(0.2)
    await _dismiss_overlays(page)
    res = await page.evaluate(
        """
        () => {
          const tables = Array.from(document.querySelectorAll('table'));
          const boards = [];
          for (const t of tables) {
            const rows = Array.from(t.querySelectorAll('tr'));
            if (rows.length !== 21) continue;
            if (!rows.every(r => r.querySelectorAll('td').length === 5)) continue;
            boards.push(t);
          }
          boards.forEach((b,i)=>b.setAttribute('data-bot-board', String(i)));
          return {
            count: boards.length,
            boardSelectors: boards.map((_,i)=>`table[data-bot-board="${i}"]`),
          };
        }
        """
    )
    if not res or int(res.get("count", 0)) < 16:
        raise RuntimeError(f"Failed to detect 16 board tables (found {res.get('count') if res else 'none'}).")

    return DetectedBoards(
        tile_selector="td",
        board_selectors=res["boardSelectors"][:16],
        tiles_per_board=105,
    )


async def focus_game(page: Page) -> None:
    try:
        await page.click("body", timeout=1000)
    except Exception:
        pass


async def submit_guess(page: Page, guess: str) -> None:
    await focus_game(page)
    await page.keyboard.type(guess, delay=15)
    await page.keyboard.press("Enter")


async def clear_current_guess(page: Page, n: int = 5) -> None:
    await focus_game(page)
    for _ in range(n):
        await page.keyboard.press("Backspace")


async def current_turn_index(page: Page, detected: DetectedBoards, board_idx: int) -> int:
    """
    Returns the index of the first fully-empty row for a given board table.
    This corresponds to the "current guess row" (i.e., how many guesses have been committed).
    """
    sel = detected.board_selectors[board_idx]
    return int(
        await page.evaluate(
            """
            (boardSel) => {
              const b = document.querySelector(boardSel);
              if (!b) return 0;
              const rows = Array.from(b.querySelectorAll('tr'));
              for (let i = 0; i < rows.length; i++) {
                const tds = Array.from(rows[i].querySelectorAll('td'));
                if (tds.every(td => (td.textContent || '').trim() === '')) return i;
              }
              return rows.length;
            }
            """,
            sel,
        )
    )


async def guesses_left(page: Page) -> int | None:
    """
    Reads the on-page remaining guess counter shown as '21/21', '20/21', etc.
    Returns the remaining guesses (left side) or None if not found.
    """
    txt = await page.evaluate(
        """
        () => {
          const els = Array.from(document.querySelectorAll('td'));
          for (const el of els) {
            const t = (el.textContent || '').trim();
            if (/^\\d{1,2}\\/\\d{1,2}$/.test(t)) return t;
          }
          return null;
        }
        """
    )
    if not txt:
        return None
    try:
        left_s, _total_s = str(txt).split("/", 1)
        return int(left_s)
    except Exception:
        return None


async def wait_for_acceptance(
    page: Page,
    detected: DetectedBoards,
    board_idx: int,
    before_turn: int,
    before_left: int | None,
    timeout_s: float = 9.0,
) -> bool:
    """
    Polls until either:
    - the remaining-guesses counter decreases, or
    - the board's current row advances
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if before_left is not None:
            now_left = await guesses_left(page)
            if now_left is not None and now_left == before_left - 1:
                return True
        else:
            # Fallback only if we can't read guesses-left counter.
            now_turn = await current_turn_index(page, detected, board_idx)
            if now_turn >= before_turn + 1:
                return True
        await asyncio.sleep(0.08)
    return False


async def read_feedback_for_turn(page: Page, detected: DetectedBoards, turn_idx: int) -> list[list[int]]:
    boards = detected.board_selectors
    res: list[list[int]] = await page.evaluate(
        """
        ({boards, turnIdx, absentBg, presentBg, correctBg}) => {
          function state(td) {
            const bg = getComputedStyle(td).backgroundColor;
            if (bg === correctBg) return 2;
            if (bg === presentBg) return 1;
            if (bg === absentBg) return 0;
            // Fallback: unknown colors treated as absent (common for empty/unrevealed styling).
            return 0;
          }

          const out = [];
          for (const bSel of boards) {
            const b = document.querySelector(bSel);
            if (!b) { out.push([null,null,null,null,null]); continue; }
            const rows = Array.from(b.querySelectorAll('tr'));
            if (turnIdx >= rows.length) { out.push([null,null,null,null,null]); continue; }
            const tds = Array.from(rows[turnIdx].querySelectorAll('td'));
            if (tds.length !== 5) { out.push([null,null,null,null,null]); continue; }
            out.push(tds.map(state));
          }
          return out;
        }
        """,
        {"boards": boards, "turnIdx": turn_idx, "absentBg": ABSENT_BG, "presentBg": PRESENT_BG, "correctBg": CORRECT_BG},
    )
    # Convert nulls to -1 so caller can handle weird boards gracefully.
    out2: list[list[int]] = []
    for row in res:
        out2.append([int(x) if x is not None else -1 for x in row])
    return out2


async def read_guess_for_turn(page: Page, detected: DetectedBoards, turn_idx: int, board_idx: int = 0) -> str | None:
    """
    Reads the guess word (5 letters) shown on the grid for a given turn.
    In Sedecordle/Savior, the guess is shared across all boards, so any board works.
    """
    sel = detected.board_selectors[board_idx]
    guess = await page.evaluate(
        """
        ({boardSel, turnIdx}) => {
          const b = document.querySelector(boardSel);
          if (!b) return null;
          const rows = Array.from(b.querySelectorAll('tr'));
          if (turnIdx >= rows.length) return null;
          const tds = Array.from(rows[turnIdx].querySelectorAll('td'));
          if (tds.length !== 5) return null;
          const letters = tds.map(td => (td.textContent || '').trim()).join('');
          if (letters.length !== 5) return null;
          return letters.toLowerCase();
        }
        """,
        {"boardSel": sel, "turnIdx": turn_idx},
    )
    if not guess or not isinstance(guess, str):
        return None
    g = guess.strip().lower()
    if len(g) != 5 or not g.isalpha():
        return None
    return g


async def bootstrap_from_existing_rows(
    page: Page,
    detected: DetectedBoards,
    allowed: list[str],
    board_candidates: list[list[str]],
    solved: list[bool],
    guessed: set[str],
) -> None:
    """
    If the page already contains committed guesses (e.g. Savior mode pre-fills 4),
    apply those guesses to narrow candidates before continuing.
    """
    turns_played = await current_turn_index(page, detected, 0)
    if turns_played <= 0:
        return

    for t in range(turns_played):
        guess = await read_guess_for_turn(page, detected, t, board_idx=0)
        if not guess:
            continue
        if guess in guessed:
            continue

        feedbacks = await read_feedback_for_turn(page, detected, t)
        guessed.add(guess)
        if guess in allowed:
            allowed.remove(guess)

        for bi, fb in enumerate(feedbacks):
            if solved[bi]:
                continue
            if any(x < 0 for x in fb):
                continue
            filtered = filter_candidates(board_candidates[bi], guess, fb)
            if filtered:
                board_candidates[bi] = filtered
            if is_solved_feedback(fb):
                solved[bi] = True

    remaining = [len(c) for c in board_candidates]
    print(
        f"Bootstrapped from {turns_played} existing guesses. "
        f"Remaining (min/median/max): {min(remaining)}/{sorted(remaining)[len(remaining)//2]}/{max(remaining)}; "
        f"solved={sum(1 for x in solved if x)}/16"
    )


def _ensure_word_lists_exist() -> None:
    data_dir = Path(__file__).resolve().parent / "data"
    if (data_dir / "allowed.txt").exists() and (data_dir / "answers.txt").exists():
        return
    extract_main()


async def run_bot(
    headful: bool,
    slowmo_ms: int,
    max_turns: int,
    url: str,
    dry_run: bool,
    user_data_dir: str | None,
) -> None:
    _ensure_word_lists_exist()
    allowed, answers = load_words()
    if not allowed or not answers:
        raise RuntimeError("Word lists missing/empty. Run: py -m sedecordle_bot.extract_word_lists")

    async with async_playwright() as p:
        if user_data_dir:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=not headful,
                slow_mo=slowmo_ms or 0,
                viewport={"width": 1400, "height": 900},
            )
            page = context.pages[0] if context.pages else await context.new_page()
        else:
            browser = await p.chromium.launch(headless=not headful, slow_mo=slowmo_ms or 0)
            context = await browser.new_context(viewport={"width": 1400, "height": 900})
            page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(0.5)
        await _dismiss_overlays(page)

        detected = await detect_boards(page)
        print(f"Detected 16 boards using tiles '{detected.tile_selector}', tiles_per_board~{detected.tiles_per_board}")
        if dry_run:
            await context.close()
            return

        board_candidates: list[list[str]] = [list(answers) for _ in range(16)]
        solved = [False] * 16
        guessed: set[str] = set()

        await bootstrap_from_existing_rows(page, detected, allowed, board_candidates, solved, guessed)

        while not all(solved):
            try:
                turn_board_idx = next(i for i, s in enumerate(solved) if not s)
            except StopIteration:
                break

            turn_idx = await current_turn_index(page, detected, turn_board_idx)
            if turn_idx >= max_turns:
                break

            # If any *unsolved* board has exactly one candidate left, try that word next (once).
            active_allowed = [w for w in allowed if w not in guessed]
            if not active_allowed:
                raise RuntimeError("No allowed guesses left (all words already guessed).")

            active_candidates = [c if not solved[i] else [] for i, c in enumerate(board_candidates)]
            # Finish small boards sooner to avoid running out of turns.
            guess: str | None = None
            small_threshold = 5
            small = sorted(
                ((len(c), i) for i, c in enumerate(board_candidates) if not solved[i] and len(c) > 0),
                key=lambda x: x[0],
            )
            for n, bi in small:
                if n > small_threshold:
                    break
                opts = [w for w in board_candidates[bi] if w not in guessed]
                if not opts:
                    continue
                guess = choose_next_guess(opts, active_candidates)
                break

            if not guess:
                guess = choose_next_guess(active_allowed, active_candidates)
            if guess in guessed:
                # Shouldn't happen, but avoid repeats defensively.
                guess = next(w for w in active_allowed if w not in guessed)
            print(f"Turn {turn_idx+1}/{max_turns}: guessing {guess}")

            before_turn = turn_idx
            before_left = await guesses_left(page)
            await submit_guess(page, guess)
            accepted = await wait_for_acceptance(page, detected, turn_board_idx, before_turn, before_left, timeout_s=9.0)
            if not accepted:
                # Likely invalid/unsubmitted; remove and retry without consuming a turn.
                after_left = await guesses_left(page)
                after_turn = await current_turn_index(page, detected, turn_board_idx)
                try:
                    shot_path = Path(__file__).resolve().parent / "data" / "bot_not_accepted.png"
                    await page.screenshot(path=str(shot_path), full_page=True)
                except Exception:
                    shot_path = None
                print(
                    f"  Guess '{guess}' not accepted (invalid/unsubmitted). "
                    f"guesses_left {before_left}->{after_left}, turn {before_turn}->{after_turn}. "
                    f"{'screenshot='+str(shot_path) if shot_path else ''}"
                )
                allowed = [w for w in allowed if w != guess]
                # If the game rejects the word, it cannot be an answer either.
                for bi in range(len(board_candidates)):
                    if guess in board_candidates[bi]:
                        board_candidates[bi] = [w for w in board_candidates[bi] if w != guess]
                await clear_current_guess(page, 5)
                continue

            guessed.add(guess)
            allowed = [w for w in allowed if w != guess]

            await asyncio.sleep(0.35)  # allow color updates to settle
            feedbacks = await read_feedback_for_turn(page, detected, before_turn)

            for bi, fb in enumerate(feedbacks):
                if solved[bi]:
                    continue
                if any(x < 0 for x in fb):
                    # Could not parse this board’s row; skip filtering this time.
                    continue
                filtered = filter_candidates(board_candidates[bi], guess, fb)
                if filtered:
                    board_candidates[bi] = filtered
                if is_solved_feedback(fb):
                    solved[bi] = True

            # Progress report
            remaining = [len(c) for c in board_candidates]
            print("  Remaining candidates (min/median/max): "
                  f"{min(remaining)}/{sorted(remaining)[len(remaining)//2]}/{max(remaining)}; "
                  f"solved={sum(1 for x in solved if x)}/16")

        print("Done.")
        print(f"Solved {sum(1 for x in solved if x)}/16.")
        await context.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headful", action="store_true", help="Show the browser window.")
    ap.add_argument("--slowmo", type=int, default=0, help="Playwright slowmo in ms.")
    ap.add_argument("--max-turns", type=int, default=21, help="Max guesses to play.")
    ap.add_argument("--url", type=str, default=ROOT_URL, help="Game URL.")
    ap.add_argument("--dry-run", action="store_true", help="Only detect boards, then exit.")
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
            max_turns=args.max_turns,
            url=args.url,
            dry_run=args.dry_run,
            user_data_dir=args.user_data_dir,
        )
    )


if __name__ == "__main__":
    main()

