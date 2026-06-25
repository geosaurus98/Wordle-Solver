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
    layout: str = "table"  # "table" (regular sedecordle) or "divboard" (sedec-order)


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

    # Try table layout first (regular sedecordle).
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
    if res and int(res.get("count", 0)) >= 16:
        return DetectedBoards(
            tile_selector="td",
            board_selectors=res["boardSelectors"][:16],
            tiles_per_board=105,
            layout="table",
        )

    # Fallback: div.board / div.cell layout (sedec-order).
    res2 = await page.evaluate(
        """
        () => {
          const boards = Array.from(document.querySelectorAll('div.board'));
          const picked = [];
          for (const b of boards) {
            const n = b.querySelectorAll('div.cell').length;
            if (n >= 100 && n % 5 === 0) picked.push(b);
          }
          picked.forEach((b,i) => b.setAttribute('data-bot-board', String(i)));
          return {
            count: picked.length,
            boardSelectors: picked.map((_,i) => `div.board[data-bot-board="${i}"]`),
          };
        }
        """
    )
    if res2 and int(res2.get("count", 0)) >= 16:
        return DetectedBoards(
            tile_selector="div.cell",
            board_selectors=res2["boardSelectors"][:16],
            tiles_per_board=105,
            layout="divboard",
        )

    table_count = res.get("count", 0) if res else 0
    div_count = res2.get("count", 0) if res2 else 0
    raise RuntimeError(
        f"Failed to detect 16 boards (table found {table_count}, divboard found {div_count})."
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
    sel = detected.board_selectors[board_idx]
    if detected.layout == "divboard":
        return int(
            await page.evaluate(
                """
                (boardIdx) => {
                  const boards = Array.from(document.querySelectorAll('div.board')).filter(b => b.querySelectorAll('div.cell').length >= 100);
                  const b = boards[boardIdx];
                  if (!b) return 0;
                  const cells = Array.from(b.querySelectorAll('div.cell'));
                  const rows = Math.floor(cells.length / 5);
                  for (let r = 0; r < rows; r++) {
                    const row = cells.slice(r*5, r*5+5);
                    if (row.map(c => (c.textContent || '').trim()).join('') === '') return r;
                  }
                  return rows;
                }
                """,
                board_idx,
            )
        )
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
    if detected.layout == "divboard":
        res = await page.evaluate(
            """
            ({boardCount, turnIdx}) => {
              function state(cell) {
                const cls = (cell.className || '').toLowerCase();
                if (cls.includes('green')) return 2;
                if (cls.includes('yellow')) return 1;
                return 0;
              }
              const allBoards = Array.from(document.querySelectorAll('div.board')).filter(b => b.querySelectorAll('div.cell').length >= 100);
              const out = [];
              for (let i = 0; i < boardCount; i++) {
                const b = allBoards[i];
                if (!b) { out.push([null,null,null,null,null]); continue; }
                const cells = Array.from(b.querySelectorAll('div.cell'));
                const row = cells.slice(turnIdx*5, turnIdx*5+5);
                if (row.length !== 5) { out.push([null,null,null,null,null]); continue; }
                out.push(row.map(state));
              }
              return out;
            }
            """,
            {"boardCount": len(boards), "turnIdx": turn_idx},
        )
    else:
        res = await page.evaluate(
            """
            ({boards, turnIdx, absentBg, presentBg, correctBg}) => {
              function state(td) {
                const bg = getComputedStyle(td).backgroundColor;
                if (bg === correctBg) return 2;
                if (bg === presentBg) return 1;
                if (bg === absentBg) return 0;
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
    out2: list[list[int]] = []
    for row in res:
        out2.append([int(x) if x is not None else -1 for x in row])
    return out2


async def read_guess_for_turn(page: Page, detected: DetectedBoards, turn_idx: int, board_idx: int = 0) -> str | None:
    sel = detected.board_selectors[board_idx]
    if detected.layout == "divboard":
        guess = await page.evaluate(
            """
            ({boardIdx, turnIdx}) => {
              const boards = Array.from(document.querySelectorAll('div.board')).filter(b => b.querySelectorAll('div.cell').length >= 100);
              const b = boards[boardIdx];
              if (!b) return null;
              const cells = Array.from(b.querySelectorAll('div.cell'));
              const row = cells.slice(turnIdx*5, turnIdx*5+5);
              if (row.length !== 5) return null;
              const letters = row.map(c => (c.textContent || '').trim()).join('');
              return letters.length === 5 ? letters.toLowerCase() : null;
            }
            """,
            {"boardIdx": board_idx, "turnIdx": turn_idx},
        )
    else:
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
    first_guess: str,
    result: dict | None = None,
) -> dict | None:
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
        print(f"Detected 16 boards (layout={detected.layout}, tile={detected.tile_selector})")
        if dry_run:
            await context.close()
            return

        board_candidates: list[list[str]] = [list(answers) for _ in range(16)]
        solved = [False] * 16
        guessed: set[str] = set()
        _board_answers: list[str | None] = [None] * 16
        _board_guesses: list[list[dict]] = [[] for _ in range(16)]

        await bootstrap_from_existing_rows(page, detected, allowed, board_candidates, solved, guessed)

        opener_queue = [
            w.strip().lower()
            for w in (first_guess or "").split(",")
            if w.strip()
        ]

        # In sequential mode (sedec-order), board N’s colors only appear after board N-1
        # is solved. Track which boards are active and replay history when a new one unlocks.
        sequential = "sedec-order" in url.lower()
        active_boards: set[int] = {0} if sequential else set(range(16))
        guess_history: list[tuple[int, str]] = []  # (turn_idx, guess) for retroactive catch-up

        while not all(solved):
            try:
                turn_board_idx = next(i for i, s in enumerate(solved) if not s)
            except StopIteration:
                break

            turn_idx = await current_turn_index(page, detected, turn_board_idx)
            if turn_idx >= max_turns:
                break

            active_allowed = [w for w in allowed if w not in guessed]
            if not active_allowed:
                raise RuntimeError("No allowed guesses left (all words already guessed).")

            # For guess selection, only consider currently active boards.
            active_candidates = [
                (c if not solved[i] and (not sequential or i in active_boards) else [])
                for i, c in enumerate(board_candidates)
            ]

            # Consume openers first; once the queue is empty, switch to adaptive.
            guess: str | None = None
            while opener_queue:
                candidate = opener_queue[0]
                if candidate not in guessed and candidate in allowed:
                    guess = opener_queue.pop(0)
                    break
                opener_queue.pop(0)

            if guess is None:
                # Finish small boards sooner to avoid running out of turns.
                small_threshold = 5
                small = sorted(
                    (
                        (len(c), i)
                        for i, c in enumerate(board_candidates)
                        if not solved[i] and len(c) > 0 and (not sequential or i in active_boards)
                    ),
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

            if guess is None:
                guess = choose_next_guess(active_allowed, active_candidates)
            if guess in guessed:
                guess = next(w for w in active_allowed if w not in guessed)
            print(f"Turn {turn_idx+1}/{max_turns}: guessing {guess}")

            before_turn = turn_idx
            before_left = await guesses_left(page)
            await submit_guess(page, guess)
            accepted = await wait_for_acceptance(page, detected, turn_board_idx, before_turn, before_left, timeout_s=9.0)
            if not accepted:
                after_left = await guesses_left(page)
                after_turn = await current_turn_index(page, detected, turn_board_idx)
                try:
                    shot_path = Path(__file__).resolve().parent / "data" / "bot_not_accepted.png"
                    await page.screenshot(path=str(shot_path), full_page=True)
                except Exception:
                    shot_path = None
                print(
                    f"  Guess ‘{guess}’ not accepted (invalid/unsubmitted). "
                    f"guesses_left {before_left}->{after_left}, turn {before_turn}->{after_turn}. "
                    + (f"screenshot={shot_path}" if shot_path else "")
                )
                allowed = [w for w in allowed if w != guess]
                for bi in range(len(board_candidates)):
                    if guess in board_candidates[bi]:
                        board_candidates[bi] = [w for w in board_candidates[bi] if w != guess]
                await clear_current_guess(page, 5)
                continue

            before_counts = [len(c) for c in board_candidates]
            guessed.add(guess)
            guess_history.append((before_turn, guess))
            allowed = [w for w in allowed if w != guess]

            await asyncio.sleep(0.35)  # allow color updates to settle
            feedbacks = await read_feedback_for_turn(page, detected, before_turn)

            newly_activated: list[int] = []
            for bi, fb in enumerate(feedbacks):
                if solved[bi]:
                    continue
                if sequential and bi not in active_boards:
                    continue
                if any(x < 0 for x in fb):
                    continue
                filtered = filter_candidates(board_candidates[bi], guess, fb)
                if filtered:
                    board_candidates[bi] = filtered
                _board_guesses[bi].append({
                    "word": guess,
                    "feedback": list(fb),
                    "candidates_before": before_counts[bi],
                    "candidates_after": len(board_candidates[bi]),
                })
                if is_solved_feedback(fb):
                    solved[bi] = True
                    _board_answers[bi] = guess
                    if sequential and bi + 1 < 16:
                        active_boards.add(bi + 1)
                        newly_activated.append(bi + 1)

            # Retroactively apply all prior guesses for each newly unlocked board.
            for new_bi in newly_activated:
                print(f"  Board {new_bi+1} unlocked — replaying {len(guess_history)-1} prior turns...")
                await asyncio.sleep(1.5)  # wait for the newly revealed colors to settle
                for hist_turn, hist_guess in guess_history[:-1]:  # exclude the current turn
                    hist_fbs = await read_feedback_for_turn(page, detected, hist_turn)
                    hist_fb = hist_fbs[new_bi]
                    if any(x < 0 for x in hist_fb):
                        continue
                    filtered = filter_candidates(board_candidates[new_bi], hist_guess, hist_fb)
                    if filtered:
                        board_candidates[new_bi] = filtered
                    if is_solved_feedback(hist_fb):
                        solved[new_bi] = True
                        break

            # Progress report
            remaining = [len(c) for c in board_candidates]
            print("  Remaining candidates (min/median/max): "
                  f"{min(remaining)}/{sorted(remaining)[len(remaining)//2]}/{max(remaining)}; "
                  f"solved={sum(1 for x in solved if x)}/16")

        print("Done.")
        print(f"Solved {sum(1 for x in solved if x)}/16.")
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
    ap.add_argument("--max-turns", type=int, default=21, help="Max guesses to play.")
    ap.add_argument("--url", type=str, default=ROOT_URL, help="Game URL.")
    ap.add_argument("--dry-run", action="store_true", help="Only detect boards, then exit.")
    ap.add_argument(
        "--user-data-dir",
        type=str,
        default=None,
        help="Use a persistent browser profile directory (saves localStorage/cookies across runs).",
    )
    ap.add_argument(
        "--first-guess",
        type=str,
        default="AROSE,UNTIL",
        help="Comma-separated opener sequence played before the adaptive solver. Default: AROSE,UNTIL.",
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
            first_guess=args.first_guess,
        )
    )


if __name__ == "__main__":
    main()

