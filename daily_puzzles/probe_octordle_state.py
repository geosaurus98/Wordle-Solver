from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright


URL = "https://www.britannica.com/games/octordle/daily"


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        await page.goto(URL, wait_until="domcontentloaded", timeout=120_000)
        await asyncio.sleep(1.5)

        # Type a guess.
        await page.click("body")
        await page.keyboard.type("arose", delay=10)
        await page.keyboard.press("Enter")
        await asyncio.sleep(2.5)

        # Dump first row states for all 8 boards.
        rows = await page.evaluate(
            """
            () => {
              const out = [];
              const boards = Array.from(document.querySelectorAll('.board')).slice(0, 8);
              for (const b of boards) {
                const row = b.querySelectorAll('.board-row')[0];
                const letters = Array.from(row.querySelectorAll('.letter')).slice(0, 5);
                out.push({
                  boardId: b.id,
                  rowAria: row.getAttribute('aria-label'),
                  cells: letters.map(el => ({
                    text: (el.textContent || '').trim(),
                    className: (el.className || '').toString(),
                    aria: el.getAttribute('aria-label'),
                  })),
                });
              }
              return out;
            }
            """
        )
        for r in rows:
            print(r["boardId"], r["rowAria"])
            for c in r["cells"]:
                print(" ", c)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

