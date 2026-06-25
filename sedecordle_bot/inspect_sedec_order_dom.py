import asyncio
from playwright.async_api import async_playwright


async def inspect():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://www.sedecordle.com/sedec-order", wait_until="domcontentloaded")
        await asyncio.sleep(2)

        # Check a sample of committed cells (turn 0 should have content after page loads)
        info = await page.evaluate("""() => {
            const boards = Array.from(document.querySelectorAll('div.board'));
            if (!boards.length) return {error: 'no boards'};
            const b = boards[0];
            const cells = Array.from(b.querySelectorAll('div.cell'));
            // Sample first 5 cells (turn 0)
            const sample = cells.slice(0, 10).map(c => ({
                text: c.textContent.trim(),
                cls: c.className,
                bg: window.getComputedStyle(c).backgroundColor,
            }));
            return {boards: boards.length, cells: cells.length, sample};
        }""")
        print(info)
        await browser.close()


asyncio.run(inspect())
