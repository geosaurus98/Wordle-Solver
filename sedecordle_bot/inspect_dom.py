from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright


URL = "https://www.sedecordle.com/?mode=daily"


async def main() -> None:
    out_dir = Path(__file__).resolve().parent / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    shot = out_dir / "inspect.png"

    selectors = [
        "[data-letter]",
        "[data-state]",
        "[data-evaluation]",
        ".tile",
        ".board",
        ".game",
        ".grid",
        "div[class*=board]",
        "div[class*=tile]",
        "div[class*=grid]",
        "main",
        "table",
        "tr",
        "td",
        "button",
        "svg",
    ]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        await page.goto(URL, wait_until="networkidle")
        await asyncio.sleep(0.5)

        counts = {}
        for sel in selectors:
            try:
                counts[sel] = await page.eval_on_selector_all(sel, "els => els.length")
            except Exception:
                counts[sel] = "ERR"

        print("Selector counts:")
        for k, v in counts.items():
            print(f"  {k:18} -> {v}")

        # Dump some of the biggest classnames to help find boards/tiles.
        classes = await page.evaluate(
            """
            () => {
              const els = Array.from(document.querySelectorAll('div'));
              const counts = new Map();
              for (const el of els) {
                const c = (el.className || '').toString();
                if (!c) continue;
                counts.set(c, (counts.get(c) || 0) + 1);
              }
              const arr = Array.from(counts.entries()).sort((a,b)=>b[1]-a[1]).slice(0,40);
              return arr.map(([cls,n]) => ({cls, n}));
            }
            """
        )
        print("\nTop div.className frequencies:")
        for item in classes:
            print(f"  {item['n']:4}  {item['cls']}")

        tag_counts = await page.evaluate(
            """
            () => {
              const els = Array.from(document.querySelectorAll('*'));
              const counts = new Map();
              for (const el of els) {
                const t = el.tagName.toLowerCase();
                counts.set(t, (counts.get(t) || 0) + 1);
              }
              return Array.from(counts.entries()).sort((a,b)=>b[1]-a[1]).slice(0,25);
            }
            """
        )
        print("\nTop tag frequencies:")
        for tag, n in tag_counts:
            print(f"  {n:4}  <{tag}>")

        td_classes = await page.evaluate(
            """
            () => {
              const els = Array.from(document.querySelectorAll('td'));
              const counts = new Map();
              for (const el of els) {
                const c = (el.className || '').toString().trim();
                counts.set(c, (counts.get(c) || 0) + 1);
              }
              return Array.from(counts.entries()).sort((a,b)=>b[1]-a[1]).slice(0,40)
                .map(([cls,n]) => ({cls, n}));
            }
            """
        )
        print("\nTop td.className frequencies:")
        for item in td_classes:
            print(f"  {item['n']:4}  {item['cls']!r}")

        board_table_stats = await page.evaluate(
            """
            () => {
              const tables = Array.from(document.querySelectorAll('table'));
              const stats = [];
              for (const t of tables) {
                const rows = Array.from(t.querySelectorAll('tr'));
                const rowLens = rows.map(r => r.querySelectorAll('td').length);
                const maxRow = rowLens.length ? Math.max(...rowLens) : 0;
                const minRow = rowLens.length ? Math.min(...rowLens) : 0;
                stats.push({ rows: rows.length, minRow, maxRow });
              }
              const boardLike = stats.filter(s => s.rows === 21 && s.minRow === 5 && s.maxRow === 5).length;
              const rowDist = {};
              for (const s of stats) rowDist[s.rows] = (rowDist[s.rows] || 0) + 1;
              return { tableCount: stats.length, boardLike, rowDist };
            }
            """
        )
        print("\nTable stats:")
        print(f"  tables: {board_table_stats['tableCount']}, board-like(21x5): {board_table_stats['boardLike']}")
        print(f"  row-count distribution: {board_table_stats['rowDist']}")

        sample_html = await page.evaluate(
            """
            () => {
              const td = document.querySelector('td');
              if (!td) return null;
              const el = td;
              return {
                tag: el.tagName.toLowerCase(),
                className: el.className,
                attrs: Array.from(el.attributes).map(a=>[a.name,a.value]),
                text: el.textContent,
                outerHTML: el.outerHTML.slice(0, 300)
              };
            }
            """
        )
        if sample_html:
            print("\nSample <td> element:")
            print(f"  className: {sample_html['className']!r}")
            print(f"  attrs: {sample_html['attrs']!r}")
            print(f"  text: {sample_html['text']!r}")
            print(f"  outerHTML (truncated): {sample_html['outerHTML']!r}")

        sample_board_td = await page.evaluate(
            """
            () => {
              const tds = Array.from(document.querySelectorAll('td.box'));
              const td = tds.find(el => !String(el.className || '').includes('button')) || null;
              if (!td) return null;
              return {
                className: td.className,
                attrs: Array.from(td.attributes).map(a=>[a.name,a.value]),
                text: td.textContent,
                outerHTML: td.outerHTML.slice(0, 300)
              };
            }
            """
        )
        if sample_board_td:
            print("\nSample 'td.box' (non-button):")
            print(f"  className: {sample_board_td['className']!r}")
            print(f"  attrs: {sample_board_td['attrs']!r}")
            print(f"  text: {sample_board_td['text']!r}")
            print(f"  outerHTML (truncated): {sample_board_td['outerHTML']!r}")

        await page.screenshot(path=str(shot), full_page=True)
        print(f"\nWrote screenshot to: {shot}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

