from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from playwright.async_api import Page, async_playwright

from .sudoku_solver import SudokuBoard, solve_sudoku


NYT_SUDOKU_URL = "https://www.nytimes.com/puzzles/sudoku"
DATA_DIR = Path(__file__).resolve().parent / "data"


async def _dismiss_overlays(page: Page) -> None:
    selectors = [
        'button[aria-label="Close"]',
        'button[aria-label="close"]',
        "button:has-text(\"Close\")",
        "button:has-text(\"Continue\")",
        "button:has-text(\"OK\")",
        "button:has-text(\"Got it\")",
        "button:has-text(\"Play\")",
        "button:has-text(\"Accept\")",
        "button:has-text(\"I Agree\")",
    ]
    for _ in range(6):
        clicked = False
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() == 0:
                    continue
                await loc.click(timeout=700)
                await asyncio.sleep(0.15)
                clicked = True
            except Exception:
                pass
        if not clicked:
            break


async def _select_difficulty(page: Page, difficulty: str) -> None:
    label = difficulty.capitalize()
    selectors = [
        f"button:has-text(\"{label}\")",
        f"[role=\"button\"]:has-text(\"{label}\")",
        f"text={label}",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() == 0:
                continue
            await loc.click(timeout=1000)
            await asyncio.sleep(0.25)
            return
        except Exception:
            continue


async def _read_board(page: Page) -> list[list[int]]:
    """
    Extract the Sudoku board from NYT page via broad selector heuristics.
    Returns 9x9 with 0 for empty.
    """
    rows = await page.evaluate(
        """
        () => {
          // Strategy 1: data-row/data-col on cells
          const byData = Array.from(document.querySelectorAll('[data-row][data-col]'));
          if (byData.length >= 81) {
            const g = Array.from({length: 9}, () => Array(9).fill(0));
            for (const el of byData) {
              const r = Number(el.getAttribute('data-row'));
              const c = Number(el.getAttribute('data-col'));
              if (!(r >= 0 && r < 9 && c >= 0 && c < 9)) continue;
              const txt = (el.getAttribute('data-value') || el.textContent || '').trim();
              const n = Number(txt);
              g[r][c] = Number.isInteger(n) && n >= 1 && n <= 9 ? n : 0;
            }
            return g;
          }

          // Strategy 2: explicit ARIA labels containing row/column and value.
          const ariaCells = Array.from(document.querySelectorAll('[role="button"], [role="gridcell"], button, td, div'));
          const re = /row\\s*(\\d).*column\\s*(\\d).*?(\\d)?/i;
          const g2 = Array.from({length: 9}, () => Array(9).fill(0));
          let seen = 0;
          for (const el of ariaCells) {
            const a = (el.getAttribute('aria-label') || '').toLowerCase();
            if (!a.includes('row') || !a.includes('column')) continue;
            const m = a.match(re);
            if (!m) continue;
            const r = Number(m[1]) - 1;
            const c = Number(m[2]) - 1;
            const n = Number(m[3] || (el.textContent || '').trim());
            if (!(r >= 0 && r < 9 && c >= 0 && c < 9)) continue;
            g2[r][c] = Number.isInteger(n) && n >= 1 && n <= 9 ? n : 0;
            seen += 1;
          }
          if (seen >= 60) return g2;

          // Strategy 3: read 81 visible grid-ish elements in DOM order.
          const candidates = Array.from(document.querySelectorAll('[role="gridcell"], td, button, div'))
            .filter(el => {
              const t = (el.textContent || '').trim();
              return t === '' || /^[1-9]$/.test(t);
            })
            .slice(0, 500);
          if (candidates.length >= 81) {
            const g3 = Array.from({length: 9}, () => Array(9).fill(0));
            let k = 0;
            for (const el of candidates) {
              if (k >= 81) break;
              const t = (el.textContent || '').trim();
              const v = /^[1-9]$/.test(t) ? Number(t) : 0;
              const r = Math.floor(k / 9);
              const c = k % 9;
              g3[r][c] = v;
              k += 1;
            }
            if (k === 81) return g3;
          }
          return null;
        }
        """
    )
    if not rows:
        raise RuntimeError("Could not extract Sudoku board from page")
    if len(rows) != 9 or any(len(r) != 9 for r in rows):
        raise RuntimeError("Extracted Sudoku board is not 9x9")
    return [[int(v) for v in r] for r in rows]


async def _fill_solution(page: Page, original: list[list[int]], solved: list[list[int]]) -> None:
    """
    Fill mutable Sudoku cells. We select a cell then type a number.
    """
    for r in range(9):
        for c in range(9):
            if original[r][c] != 0:
                continue
            value = solved[r][c]
            clicked = False
            selectors = [
                f'[data-row="{r}"][data-col="{c}"]',
                f'[aria-label*="row {r+1}"][aria-label*="column {c+1}"]',
                f'[role="gridcell"][aria-rowindex="{r+1}"][aria-colindex="{c+1}"]',
            ]
            for sel in selectors:
                try:
                    cell = page.locator(sel).first
                    if await cell.count() == 0:
                        continue
                    await cell.click(timeout=500)
                    clicked = True
                    break
                except Exception:
                    continue
            if not clicked:
                # Fallback: tab-navigation is unreliable; skip this cell with clear error.
                raise RuntimeError(f"Could not focus Sudoku cell ({r+1},{c+1}) for input")
            await page.keyboard.type(str(value), delay=10)
            await asyncio.sleep(0.03)


async def run_bot(
    difficulty: str,
    headful: bool,
    slowmo_ms: int,
    url: str,
    user_data_dir: str | None,
    dry_run: bool,
) -> None:
    async with async_playwright() as p:
        if user_data_dir:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=not headful,
                slow_mo=slowmo_ms or 0,
                viewport={"width": 1200, "height": 1000},
            )
            page = context.pages[0] if context.pages else await context.new_page()
        else:
            browser = await p.chromium.launch(headless=not headful, slow_mo=slowmo_ms or 0)
            context = await browser.new_context(viewport={"width": 1200, "height": 1000})
            page = await context.new_page()

        await page.goto(url, wait_until="domcontentloaded", timeout=120_000)
        await asyncio.sleep(1.0)
        await _dismiss_overlays(page)
        await _select_difficulty(page, difficulty)
        await _dismiss_overlays(page)
        await asyncio.sleep(0.5)

        board_rows = await _read_board(page)
        board = SudokuBoard.from_rows(board_rows)
        solved = solve_sudoku(board).to_rows()
        print(f"Solved Sudoku ({difficulty}) locally.")

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "nyt_sudoku_last_board.txt").write_text(
            "\n".join("".join(str(v) for v in row) for row in board_rows) + "\n",
            encoding="utf-8",
        )
        (DATA_DIR / "nyt_sudoku_last_solution.txt").write_text(
            "\n".join("".join(str(v) for v in row) for row in solved) + "\n",
            encoding="utf-8",
        )

        if not dry_run:
            await _fill_solution(page, board_rows, solved)
            print("Filled Sudoku board in browser.")

        await asyncio.sleep(0.8)
        await context.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--difficulty", type=str, default="easy", choices=["easy", "medium", "hard"])
    ap.add_argument("--headful", action="store_true", help="Show browser window.")
    ap.add_argument("--slowmo", type=int, default=0, help="Playwright slowmo in ms.")
    ap.add_argument("--url", type=str, default=NYT_SUDOKU_URL, help="Sudoku URL.")
    ap.add_argument("--dry-run", action="store_true", help="Read + solve only; do not fill cells.")
    ap.add_argument("--user-data-dir", type=str, default=None, help="Persistent browser profile directory.")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    asyncio.run(
        run_bot(
            difficulty=args.difficulty,
            headful=args.headful,
            slowmo_ms=args.slowmo,
            url=args.url,
            user_data_dir=args.user_data_dir,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()

