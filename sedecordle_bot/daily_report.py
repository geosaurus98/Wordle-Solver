from __future__ import annotations

"""
daily_report.py — Runs all puzzle solvers and emails the results.

Usage:
    py -m sedecordle_bot.daily_report

Environment variables required:
    GMAIL_APP_PASSWORD   — Gmail App Password (not your account password).
                           Generate at https://myaccount.google.com/apppasswords

Optional:
    PUZZLE_EMAIL_TO      — Recipient (default: geosaurus98@gmail.com)
    PUZZLE_EMAIL_FROM    — Sender Gmail address (default: geosaurus98@gmail.com)
    PUZZLE_FIRST_GUESS   — Opening guess for all Wordle-style games (default: arose)
"""

import argparse
import asyncio
import datetime
import os
import sys
import traceback
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from .game_result import BoardResult, GameResult, GuessStep, WaffleSwapStep
from .email_report import build_html_report, send_gmail
from .solver import load_word_list
from .solver_sim import simulate_single_board


DATA_DIR = Path(__file__).resolve().parent / "data"
NYT_API = "https://www.nytimes.com/svc/wordle/v2/{date}.json"
DEFAULT_TO = "geosaurus98@gmail.com"
DEFAULT_FROM = "geosaurus98@gmail.com"
DEFAULT_FIRST_GUESS = "arose"


# ---------------------------------------------------------------------------
# Wordle — uses NYT API and offline simulation (no browser)
# ---------------------------------------------------------------------------

def _run_wordle(date_str: str, first_guess: str) -> GameResult:
    url = "https://www.nytimes.com/games/wordle/index.html"
    try:
        r = requests.get(NYT_API.format(date=date_str), timeout=10, verify=False)
        r.raise_for_status()
        answer = r.json()["solution"].strip().lower()
    except Exception as exc:
        return GameResult(game="Wordle", url=url, date=date_str, error=f"NYT API: {exc}")

    allowed_path = DATA_DIR / "nyt_allowed.txt"
    answers_path = DATA_DIR / "nyt_answers.txt"
    allowed = load_word_list(allowed_path) or load_word_list(DATA_DIR / "allowed.txt")
    answers = load_word_list(answers_path) or allowed

    if not allowed:
        return GameResult(
            game="Wordle", url=url, date=date_str,
            error=f"NYT word lists not found (answer={answer}). Run: py -m sedecordle_bot.extract_nyt_word_lists",
        )

    board = simulate_single_board(answer, allowed, answers, max_turns=6, first_guess=first_guess)
    return GameResult(game="Wordle", url=url, date=date_str, boards=[board])


# ---------------------------------------------------------------------------
# Multi-board browser games — share a common result-conversion helper
# ---------------------------------------------------------------------------

def _make_boards_from_result(raw: dict, num_boards: int, game: str) -> list[BoardResult]:
    board_answers: list[str | None] = raw.get("board_answers", [None] * num_boards)
    board_guesses: list[list[dict]] = raw.get("board_guesses", [[] for _ in range(num_boards)])
    boards: list[BoardResult] = []
    for bi in range(num_boards):
        ans = board_answers[bi] if bi < len(board_answers) else None
        steps = []
        for g in (board_guesses[bi] if bi < len(board_guesses) else []):
            steps.append(GuessStep(
                word=g["word"],
                feedback=g["feedback"],
                candidates_before=g.get("candidates_before", 0),
                candidates_after=g.get("candidates_after", 0),
            ))
        boards.append(BoardResult(
            board_index=bi,
            answer=ans,
            guesses=steps,
            solved=ans is not None,
        ))
    return boards


# ---------------------------------------------------------------------------
# Dordle
# ---------------------------------------------------------------------------

async def _run_dordle_async(first_guess: str) -> GameResult:
    from .dordle_bot import run_bot, URL
    raw: dict = {}
    try:
        await run_bot(
            headful=False,
            slowmo_ms=0,
            url=URL,
            dry_run=False,
            user_data_dir=None,
            max_turns=7,
            first_guess=first_guess,
            result=raw,
        )
    except Exception as exc:
        return GameResult(
            game="Dordle", url=URL,
            date=str(datetime.date.today()),
            error=str(exc),
        )
    boards = _make_boards_from_result(raw, 2, "Dordle")
    return GameResult(game="Dordle", url=URL, date=str(datetime.date.today()), boards=boards)


# ---------------------------------------------------------------------------
# Quordle
# ---------------------------------------------------------------------------

async def _run_quordle_async(first_guess: str) -> GameResult:
    from .quordle_bot import run_bot, URL
    raw: dict = {}
    try:
        await run_bot(
            headful=False,
            slowmo_ms=0,
            url=URL,
            dry_run=False,
            user_data_dir=None,
            max_turns=9,
            first_guess=first_guess,
            result=raw,
        )
    except Exception as exc:
        return GameResult(
            game="Quordle", url=URL,
            date=str(datetime.date.today()),
            error=str(exc),
        )
    boards = _make_boards_from_result(raw, 4, "Quordle")
    return GameResult(game="Quordle", url=URL, date=str(datetime.date.today()), boards=boards)


# ---------------------------------------------------------------------------
# Octordle
# ---------------------------------------------------------------------------

async def _run_octordle_async(first_guess: str) -> GameResult:
    from .octordle_bot import run_bot, URL
    raw: dict = {}
    try:
        await run_bot(
            headful=False,
            slowmo_ms=0,
            url=URL,
            dry_run=False,
            user_data_dir=None,
            max_turns=13,
            first_guess=first_guess,
            result=raw,
        )
    except Exception as exc:
        return GameResult(
            game="Octordle", url=URL,
            date=str(datetime.date.today()),
            error=str(exc),
        )
    boards = _make_boards_from_result(raw, 8, "Octordle")
    return GameResult(game="Octordle", url=URL, date=str(datetime.date.today()), boards=boards)


# ---------------------------------------------------------------------------
# Sedecordle
# ---------------------------------------------------------------------------

async def _run_sedecordle_async(first_guess: str) -> GameResult:
    from .bot import run_bot, ROOT_URL
    raw: dict = {}
    try:
        await run_bot(
            headful=False,
            slowmo_ms=0,
            max_turns=21,
            url=ROOT_URL,
            dry_run=False,
            user_data_dir=None,
            result=raw,
        )
    except Exception as exc:
        return GameResult(
            game="Sedecordle", url=ROOT_URL,
            date=str(datetime.date.today()),
            error=str(exc),
        )
    boards = _make_boards_from_result(raw, 16, "Sedecordle")
    return GameResult(game="Sedecordle", url=ROOT_URL, date=str(datetime.date.today()), boards=boards)


# ---------------------------------------------------------------------------
# Waffle — read-only (no guesses submitted)
# ---------------------------------------------------------------------------

async def _run_waffle_async() -> GameResult:
    from .waffle_bot import URL, load_5_letter_words, read_tiles, _dismiss_overlays
    from .waffle_solver import solve_waffle, plan_swaps, slot_positions
    from playwright.async_api import async_playwright

    words = load_5_letter_words()
    if not words:
        return GameResult(
            game="Waffle", url=URL,
            date=str(datetime.date.today()),
            error="No word lists found. Run extract scripts first.",
        )

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(viewport={"width": 1200, "height": 1000})
            page = await context.new_page()
            await page.goto(URL, wait_until="domcontentloaded", timeout=120_000)
            import asyncio as _asyncio
            await _asyncio.sleep(1.2)
            await _dismiss_overlays(page)
            puzzle = await read_tiles(page)
            await browser.close()
    except Exception as exc:
        return GameResult(
            game="Waffle", url=URL,
            date=str(datetime.date.today()),
            error=f"Browser error: {exc}",
        )

    try:
        solution = solve_waffle(puzzle, words)
    except ValueError as exc:
        return GameResult(
            game="Waffle", url=URL,
            date=str(datetime.date.today()),
            error=f"Solver error: {exc}",
        )

    current = {(t.x, t.y): t.letter.lower() for t in puzzle.tiles.values()}
    swaps_raw = plan_swaps(current, solution)
    slots = slot_positions()

    waffle_words = {s: "".join(solution.get(p, "?") for p in ps) for s, ps in slots.items()}
    waffle_swaps = [
        WaffleSwapStep(
            from_pos=a,
            to_pos=b,
            from_letter=current.get(a, "?"),
            to_letter=current.get(b, "?"),
        )
        for a, b in swaps_raw
    ]
    initial_grid = {
        f"{t.x},{t.y}": {"letter": t.letter, "color": t.color}
        for t in puzzle.tiles.values()
    }

    return GameResult(
        game="Waffle",
        url=URL,
        date=str(datetime.date.today()),
        waffle_swaps=waffle_swaps,
        waffle_words=waffle_words,
    )


# ---------------------------------------------------------------------------
# NumberWaffle — browser, read-only
# ---------------------------------------------------------------------------

async def _run_numberwaffle_async() -> GameResult:
    from .numberwaffle_bot import run_bot
    try:
        return await run_bot()
    except Exception as exc:
        from .numberwaffle_bot import URL
        return GameResult(
            game="NumberWaffle", url=URL,
            date=str(datetime.date.today()),
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Tilerdle — HTTP only, no browser
# ---------------------------------------------------------------------------

def _run_tilerdle() -> GameResult:
    from .tilerdle_bot import run_bot
    try:
        return run_bot()
    except Exception as exc:
        from .tilerdle_bot import URL
        return GameResult(
            game="Tilerdle", url=URL,
            date=str(datetime.date.today()),
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def _run_all(first_guess: str) -> list[GameResult]:
    date_str = str(datetime.date.today())
    results: list[GameResult] = []

    # Wordle is synchronous (HTTP only)
    print("=== Wordle ===")
    results.append(_run_wordle(date_str, first_guess))
    print(f"  {results[-1].boards[0].answer if results[-1].boards else results[-1].error}")

    # Tilerdle is HTTP-only — run synchronously before the browser queue.
    print("=== Tilerdle ===")
    try:
        tilerdle_gr = _run_tilerdle()
    except Exception:
        from .tilerdle_bot import URL as _TILERDLE_URL
        tilerdle_gr = GameResult(game="Tilerdle", url=_TILERDLE_URL, date=date_str, error=traceback.format_exc())
    results.append(tilerdle_gr)
    if tilerdle_gr.error:
        print(f"  ERROR: {tilerdle_gr.error[:120]}")
    else:
        words = (tilerdle_gr.extra or {}).get("words", [])
        print(f"  Theme: {(tilerdle_gr.extra or {}).get('theme')}; words: {words}")

    # Browser-based games run sequentially to avoid resource pressure.
    for label, coro in [
        ("Dordle",        _run_dordle_async(first_guess)),
        ("Quordle",       _run_quordle_async(first_guess)),
        ("Octordle",      _run_octordle_async(first_guess)),
        ("Sedecordle",    _run_sedecordle_async(first_guess)),
        ("Waffle",        _run_waffle_async()),
        ("NumberWaffle",  _run_numberwaffle_async()),
    ]:
        print(f"=== {label} ===")
        try:
            gr = await coro
        except Exception as exc:
            gr = GameResult(game=label, url="", date=date_str, error=traceback.format_exc())
        results.append(gr)
        if gr.error:
            print(f"  ERROR: {gr.error[:120]}")
        elif gr.game in ("Waffle", "NumberWaffle"):
            n = len(gr.waffle_swaps) if gr.waffle_swaps else "?"
            print(f"  {n} swaps")
        else:
            print(f"  Solved {gr.solved_count}/{gr.total_boards}")

    return results


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Run all daily puzzle solvers and email results.")
    ap.add_argument("--no-email", action="store_true", help="Build report but skip sending email.")
    ap.add_argument("--print-html", action="store_true", help="Print the HTML report to stdout.")
    ap.add_argument("--first-guess", type=str, default=None, help="Opening guess (default: arose).")
    args = ap.parse_args(argv)

    first_guess = (args.first_guess or os.getenv("PUZZLE_FIRST_GUESS") or DEFAULT_FIRST_GUESS).lower()
    to_addr = os.getenv("PUZZLE_EMAIL_TO", DEFAULT_TO)
    from_addr = os.getenv("PUZZLE_EMAIL_FROM", DEFAULT_FROM)
    app_password = os.getenv("GMAIL_APP_PASSWORD", "")

    results = asyncio.run(_run_all(first_guess))
    date_str = str(datetime.date.today())
    html = build_html_report(date_str, results)

    if args.print_html:
        print(html)

    if args.no_email:
        print("--no-email set; skipping send.")
        report_path = DATA_DIR / f"report_{date_str}.html"
        report_path.write_text(html, encoding="utf-8")
        print(f"Report saved to: {report_path}")
        return

    if not app_password:
        print(
            "GMAIL_APP_PASSWORD not set. Set it as an environment variable and re-run.\n"
            "  setx GMAIL_APP_PASSWORD \"your-app-password\"\n"
            "Report saved locally instead.",
            file=sys.stderr,
        )
        DATA_DIR.mkdir(exist_ok=True)
        report_path = DATA_DIR / f"report_{date_str}.html"
        report_path.write_text(html, encoding="utf-8")
        print(f"Report saved to: {report_path}")
        return

    subject = f"Daily Puzzles — {date_str}"
    try:
        send_gmail(html, subject, to_addr, from_addr, app_password)
        print(f"Email sent to {to_addr}")
    except Exception as exc:
        print(f"Failed to send email: {exc}", file=sys.stderr)
        DATA_DIR.mkdir(exist_ok=True)
        report_path = DATA_DIR / f"report_{date_str}.html"
        report_path.write_text(html, encoding="utf-8")
        print(f"Report saved to: {report_path}")


if __name__ == "__main__":
    main()
