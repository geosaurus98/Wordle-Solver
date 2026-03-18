from __future__ import annotations

import argparse
import asyncio
import time
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import Page, async_playwright

from .extract_word_lists import main as extract_main
from .solver import choose_next_guess, filter_candidates, is_solved_feedback, load_words


URL = "https://www.sedecordle.com/savior"


@dataclass(frozen=True)
class Detected:
    board_selectors: list[str]  # div[data-bot-board="0"] etc


async def _dismiss_overlays(page: Page) -> None:
    selectors = [
        'button[aria-label="close"]',
        'button[aria-label="Close"]',
        "button:has-text(\"close\")",
        "button:has-text(\"Close\")",
        ".modal button",
        ".dialog button",
    ]
    for sel in selectors:
        try:
            await page.locator(sel).first.click(timeout=500)
            await asyncio.sleep(0.1)
        except Exception:
            pass


async def detect(page: Page) -> Detected:
    await page.wait_for_load_state("domcontentloaded")
    await asyncio.sleep(0.7)
    await _dismiss_overlays(page)
    await asyncio.sleep(0.3)

    res = await page.evaluate(
        """
        () => {
          const boards = Array.from(document.querySelectorAll('div.board'));
          const picked = [];
          for (const b of boards) {
            const cells = b.querySelectorAll('div.cell');
            const n = cells.length;
            if (n >= 100 && n % 5 === 0) picked.push(b);
          }
          picked.forEach((b,i)=>b.setAttribute('data-bot-board', String(i)));
          return { count: picked.length, sels: picked.map((_,i)=>`div.board[data-bot-board="${i}"]`) };
        }
        """
    )
    if not res or int(res.get("count", 0)) < 16:
        raise RuntimeError(f"Failed to detect 16 Savior boards (found {res.get('count') if res else 'none'}).")
    return Detected(board_selectors=res["sels"][:16])


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


async def guesses_left(page: Page) -> int | None:
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
        left_s, _ = str(txt).split("/", 1)
        return int(left_s)
    except Exception:
        return None


async def turn_counter(page: Page) -> tuple[int, int] | None:
    """
    Returns (left, total) parsed from the on-page counter like '17/21'.
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
        left_s, total_s = str(txt).split("/", 1)
        return int(left_s), int(total_s)
    except Exception:
        return None


async def global_turn_index(page: Page) -> int:
    tc = await turn_counter(page)
    if not tc:
        return 0
    left, total = tc
    return max(0, total - left)


async def current_turn_index(page: Page, detected: Detected, board_idx: int = 0) -> int:
    sel = detected.board_selectors[board_idx]
    return int(
        await page.evaluate(
            """
            (boardSel) => {
              const b = document.querySelector(boardSel);
              if (!b) return 0;
              const cells = Array.from(b.querySelectorAll('div.cell'));
              const rows = Math.floor(cells.length / 5);
              for (let r = 0; r < rows; r++) {
                const row = cells.slice(r*5, r*5+5);
                const letters = row.map(c => (c.textContent || '').trim()).join('');
                if (!letters) return r;
              }
              return rows;
            }
            """,
            sel,
        )
    )


async def wait_for_acceptance(
    page: Page,
    detected: Detected,
    before_turn: int,
    before_left: int | None,
    timeout_s: float = 9.0,
) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if before_left is not None:
            now_left = await guesses_left(page)
            if now_left is not None and now_left == before_left - 1:
                return True
        else:
            # Fallback only if we can't read guesses-left counter.
            now_turn = await current_turn_index(page, detected, 0)
            if now_turn >= before_turn + 1:
                return True
        await asyncio.sleep(0.08)
    return False


async def read_guess_for_turn(page: Page, detected: Detected, turn_idx: int) -> str | None:
    sel = detected.board_selectors[0]
    guess = await page.evaluate(
        """
        ({boardSel, turnIdx}) => {
          const b = document.querySelector(boardSel);
          if (!b) return null;
          const cells = Array.from(b.querySelectorAll('div.cell'));
          const row = cells.slice(turnIdx*5, turnIdx*5+5);
          if (row.length !== 5) return null;
          const letters = row.map(c => (c.textContent || '').trim()).join('');
          return letters.length === 5 ? letters.toLowerCase() : null;
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


async def read_feedback_for_turn(page: Page, detected: Detected, turn_idx: int) -> list[list[int]]:
    return await page.evaluate(
        """
        ({boards, turnIdx}) => {
          function state(cell) {
            const cls = (cell.className || '').toLowerCase();
            if (cls.includes('green')) return 2;
            if (cls.includes('yellow')) return 1;
            return 0;
          }
          const out = [];
          for (const sel of boards) {
            const b = document.querySelector(sel);
            if (!b) { out.push([null,null,null,null,null]); continue; }
            const cells = Array.from(b.querySelectorAll('div.cell'));
            const row = cells.slice(turnIdx*5, turnIdx*5+5);
            if (row.length !== 5) { out.push([null,null,null,null,null]); continue; }
            out.push(row.map(state));
          }
          return out;
        }
        """,
        {"boards": detected.board_selectors, "turnIdx": turn_idx},
    )


async def bootstrap_existing(
    page: Page,
    detected: Detected,
    allowed: list[str],
    board_candidates: list[list[str]],
    solved: list[bool],
    guessed: set[str],
) -> None:
    turns = await global_turn_index(page)
    if turns <= 0:
        return
    for t in range(turns):
        guess = await read_guess_for_turn(page, detected, t)
        if not guess or guess in guessed:
            continue
        fbs = await read_feedback_for_turn(page, detected, t)
        guessed.add(guess)
        if guess in allowed:
            allowed.remove(guess)
        for bi, fb in enumerate(fbs):
            if solved[bi]:
                continue
            if not fb or any(x is None for x in fb):
                continue
            fb2 = [int(x) for x in fb]
            filtered = filter_candidates(board_candidates[bi], guess, fb2)
            if filtered:
                board_candidates[bi] = filtered
            if is_solved_feedback(fb2):
                solved[bi] = True

    remaining = [len(c) for c in board_candidates]
    print(
        f"Bootstrapped from {turns} existing guesses. "
        f"Remaining (min/median/max): {min(remaining)}/{sorted(remaining)[len(remaining)//2]}/{max(remaining)}; "
        f"solved={sum(1 for x in solved if x)}/16"
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
    max_turns: int,
    dry_run: bool,
    user_data_dir: str | None,
) -> None:
    _ensure_word_lists_exist()
    allowed, answers = load_words()

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

        await page.goto(url, wait_until="domcontentloaded", timeout=120_000)
        await asyncio.sleep(0.8)
        await _dismiss_overlays(page)

        detected = await detect(page)
        print(f"Detected {len(detected.board_selectors)} boards (Savior layout)")
        if dry_run:
            await context.close()
            return

        board_candidates: list[list[str]] = [list(answers) for _ in range(16)]
        solved = [False] * 16
        guessed: set[str] = set()

        await bootstrap_existing(page, detected, allowed, board_candidates, solved, guessed)

        while not all(solved):
            turn_idx = await global_turn_index(page)
            if turn_idx >= max_turns:
                break

            active_allowed = [w for w in allowed if w not in guessed]
            if not active_allowed:
                raise RuntimeError("No allowed guesses left.")

            active_candidates = [c if not solved[i] else [] for i, c in enumerate(board_candidates)]

            # Aggressively finish small boards (Savior has fewer remaining turns).
            guess: str | None = None
            small_threshold = 6
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
                # Choose among solution candidates using multi-board info score.
                guess = choose_next_guess(opts, active_candidates)
                break

            if not guess:
                guess = choose_next_guess(active_allowed, active_candidates)
            if guess in guessed:
                guess = next(w for w in active_allowed if w not in guessed)

            print(f"Turn {turn_idx+1}/{max_turns}: guessing {guess}")
            before_left = await guesses_left(page)
            before_turn = turn_idx
            await submit_guess(page, guess)
            accepted = await wait_for_acceptance(page, detected, before_turn, before_left, timeout_s=9.0)
            if not accepted:
                print(f"  Guess '{guess}' not accepted; removing and retrying.")
                guessed.add(guess)
                if guess in allowed:
                    allowed.remove(guess)
                # If the game rejects the word, it cannot be an answer either.
                for bi in range(len(board_candidates)):
                    if guess in board_candidates[bi]:
                        board_candidates[bi] = [w for w in board_candidates[bi] if w != guess]
                await clear_current_guess(page, 5)
                continue

            guessed.add(guess)
            if guess in allowed:
                allowed.remove(guess)

            await asyncio.sleep(0.25)
            fbs = await read_feedback_for_turn(page, detected, before_turn)
            for bi, fb in enumerate(fbs):
                if solved[bi]:
                    continue
                if not fb or any(x is None for x in fb):
                    continue
                fb2 = [int(x) for x in fb]
                filtered = filter_candidates(board_candidates[bi], guess, fb2)
                if filtered:
                    board_candidates[bi] = filtered
                if is_solved_feedback(fb2):
                    solved[bi] = True

            remaining = [len(c) for c in board_candidates]
            print(
                "  Remaining (min/median/max): "
                f"{min(remaining)}/{sorted(remaining)[len(remaining)//2]}/{max(remaining)}; "
                f"solved={sum(1 for x in solved if x)}/16"
            )

        print("Done.")
        print(f"Solved {sum(1 for x in solved if x)}/16.")
        await context.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headful", action="store_true", help="Show the browser window.")
    ap.add_argument("--slowmo", type=int, default=0, help="Playwright slowmo in ms.")
    ap.add_argument("--url", type=str, default=URL, help="Game URL.")
    ap.add_argument("--max-turns", type=int, default=21, help="Max guesses to play.")
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
            url=args.url,
            max_turns=args.max_turns,
            dry_run=args.dry_run,
            user_data_dir=args.user_data_dir,
        )
    )


if __name__ == "__main__":
    main()

