from __future__ import annotations

import asyncio
import sys
from playwright.async_api import async_playwright


URL = "https://www.sedecordle.com/?mode=daily"


async def main() -> None:
    guess = (sys.argv[1] if len(sys.argv) > 1 else "raise").lower()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        await page.goto(URL, wait_until="networkidle")
        await asyncio.sleep(0.3)

        # Find the 16 board tables (21 rows, 5 cols).
        boards = await page.evaluate(
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
              boards.forEach((b,i)=>b.setAttribute('data-probe-board', String(i)));
              return boards.length;
            }
            """
        )
        print(f"boards detected: {boards}")

        def dump_row(label: str) -> None:
            print(label)

        before = await page.evaluate(
            """
            () => {
              const b = document.querySelector('[data-probe-board="0"]');
              const row = b.querySelectorAll('tr')[0];
              const tds = Array.from(row.querySelectorAll('td'));
              return tds.map(td => ({
                text: td.textContent,
                className: td.className,
                styleAttr: td.getAttribute('style') || '',
                bg: getComputedStyle(td).backgroundColor,
                color: getComputedStyle(td).color
              }));
            }
            """
        )
        print("row0 before:", before)

        await page.click("body")
        await page.keyboard.type(guess, delay=10)
        await page.keyboard.press("Enter")

        # Wait a bit for evaluation animations
        await asyncio.sleep(4.0)

        after = await page.evaluate(
            """
            () => {
              const b = document.querySelector('[data-probe-board="0"]');
              const row = b.querySelectorAll('tr')[0];
              const tds = Array.from(row.querySelectorAll('td'));
              return tds.map(td => ({
                text: td.textContent,
                className: td.className,
                styleAttr: td.getAttribute('style') || '',
                bg: getComputedStyle(td).backgroundColor,
                color: getComputedStyle(td).color
              }));
            }
            """
        )
        print("row0 after:", after)

        palette = await page.evaluate(
            """
            () => {
              const out = new Map();
              for (let bi = 0; bi < 16; bi++) {
                const b = document.querySelector(`[data-probe-board="${bi}"]`);
                if (!b) continue;
                const row = b.querySelectorAll('tr')[0];
                const tds = Array.from(row.querySelectorAll('td'));
                for (const td of tds) {
                  const bg = getComputedStyle(td).backgroundColor;
                  out.set(bg, (out.get(bg) || 0) + 1);
                }
              }
              return Array.from(out.entries()).sort((a,b)=>b[1]-a[1]).map(([bg,n])=>({bg,n}));
            }
            """
        )
        print("row0 palette across 16 boards:", palette)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

