from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

from playwright.async_api import Page, async_playwright

from .solver import load_word_list
from .waffle_solver import Tile, WafflePuzzle, plan_swaps, solve_waffle, waffle_positions


URL = "https://wafflegame.net/daily"
DATA_DIR = Path(__file__).resolve().parent / "data"


async def _dismiss_overlays(page: Page) -> None:
    selectors = [
        "button.button--close",
        "button:has-text(\"OK\")",
        "button:has-text(\"Got it\")",
        "button:has-text(\"Accept\")",
        "button:has-text(\"I agree\")",
        "button:has-text(\"Continue\")",
        "button:has-text(\"Close\")",
    ]
    for _ in range(6):
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


async def read_tiles(page: Page) -> WafflePuzzle:
    await page.wait_for_load_state("domcontentloaded")
    await asyncio.sleep(1.0)
    await _dismiss_overlays(page)
    await asyncio.sleep(0.3)

    tiles = await page.evaluate(
        """
        () => {
          const els = Array.from(document.querySelectorAll('div.tile.draggable'));
          return els.map(el => {
            const posRaw = el.getAttribute('data-pos') || '';
            let pos = null;
            try { pos = JSON.parse(posRaw); } catch(e) { pos = null; }
            const cls = (el.className || '').toString().split(/\\s+/);
            const text = (el.textContent || '').trim();
            const color =
              cls.includes('green') ? 'green' :
              cls.includes('yellow') ? 'yellow' :
              cls.includes('grey') ? 'grey' :
              cls.includes('gray') ? 'grey' :
              'white';
            return {
              x: pos && typeof pos.x === 'number' ? pos.x : null,
              y: pos && typeof pos.y === 'number' ? pos.y : null,
              letter: text,
              color,
              className: (el.className || '').toString(),
            };
          });
        }
        """
    )

    out: dict[tuple[int, int], Tile] = {}
    for t in tiles:
        if t.get("x") is None or t.get("y") is None:
            continue
        x = int(t["x"])
        y = int(t["y"])
        letter = (t.get("letter") or "").strip()
        if not letter:
            continue
        out[(x, y)] = Tile(x=x, y=y, letter=letter.lower(), color=str(t.get("color") or "white"))

    if len(out) != 21:
        raise RuntimeError(f"Expected 21 tiles, found {len(out)}")

    return WafflePuzzle(tiles=out)


def load_5_letter_words() -> list[str]:
    # Reuse previously extracted word lists (Sedecordle + NYT) as a generic dictionary.
    words: set[str] = set()
    for p in (
        DATA_DIR / "nyt_allowed.txt",
        DATA_DIR / "allowed.txt",
        DATA_DIR / "nyt_answers.txt",
        DATA_DIR / "answers.txt",
    ):
        for w in load_word_list(p):
            words.add(w)
    # If nothing exists, caller should run extract scripts first.
    return sorted(words)


async def tile_element(page: Page, x: int, y: int):
    # Robust selection by parsing data-pos (avoids JSON spacing/order issues).
    handle = await page.evaluate_handle(
        """
        ({x,y}) => {
          const els = Array.from(document.querySelectorAll('div.tile.draggable'));
          for (const el of els) {
            const raw = el.getAttribute('data-pos');
            if (!raw) continue;
            let p = null;
            try { p = JSON.parse(raw); } catch(e) { p = null; }
            if (p && p.x === x && p.y === y) return el;
          }
          return null;
        }
        """,
        {"x": x, "y": y},
    )
    el = handle.as_element()
    if el is None:
        raise RuntimeError(f"Could not find tile element at ({x},{y})")
    return el


async def do_swap(page: Page, a: tuple[int, int], b: tuple[int, int]) -> None:
    ax, ay = a
    bx, by = b
    el1 = await tile_element(page, ax, ay)
    el2 = await tile_element(page, bx, by)

    # Waffle is drag-based; click-click often does nothing.
    try:
        await el1.scroll_into_view_if_needed()
        await el2.scroll_into_view_if_needed()
    except Exception:
        pass

    # Prefer built-in drag_to when available.
    try:
        await el1.drag_to(el2, timeout=5000)
    except Exception:
        # Fallback to mouse drag.
        b1 = await el1.bounding_box()
        b2 = await el2.bounding_box()
        if not b1 or not b2:
            raise
        await page.mouse.move(b1["x"] + b1["width"] / 2, b1["y"] + b1["height"] / 2)
        await page.mouse.down()
        await page.mouse.move(b2["x"] + b2["width"] / 2, b2["y"] + b2["height"] / 2)
        await page.mouse.up()

    await asyncio.sleep(0.2)


async def run_bot(headful: bool, slowmo_ms: int, url: str, user_data_dir: str | None, dry_run: bool) -> None:
    words = load_5_letter_words()
    if not words:
        raise RuntimeError(
            "No word list found. Run:\n"
            "  py -m sedecordle_bot.extract_word_lists\n"
            "  py -m sedecordle_bot.extract_nyt_word_lists"
        )

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
        await asyncio.sleep(1.2)
        await _dismiss_overlays(page)

        puzzle = await read_tiles(page)
        print("Read 21 tiles.")
        if dry_run:
            await context.close()
            return

        solution = solve_waffle(puzzle, words)
        current = {(t.x, t.y): t.letter.lower() for t in puzzle.tiles.values()}
        swaps = plan_swaps(current, solution)
        print(f"Planned swaps: {len(swaps)}")

        # Execute swaps.
        for i, (a, b) in enumerate(swaps, start=1):
            print(f"Swap {i}/{len(swaps)}: {a} <-> {b}")
            before = await read_tiles(page)
            await do_swap(page, a, b)
            await _dismiss_overlays(page)
            after = await read_tiles(page)
            ba = before.tiles[a].letter
            bb = before.tiles[b].letter
            aa = after.tiles[a].letter
            ab = after.tiles[b].letter
            if not ((aa == bb and ab == ba) or (aa == ba and ab == bb)):
                raise RuntimeError(
                    f"Swap did not take effect for {a}<->{b}. "
                    f"before({ba},{bb}) after({aa},{ab})"
                )

        await asyncio.sleep(1.0)
        await context.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headful", action="store_true", help="Show the browser window.")
    ap.add_argument("--slowmo", type=int, default=0, help="Playwright slowmo in ms.")
    ap.add_argument("--url", type=str, default=URL, help="Game URL.")
    ap.add_argument("--dry-run", action="store_true", help="Only read tiles and exit.")
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
            user_data_dir=args.user_data_dir,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()

