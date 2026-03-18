from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright


DEFAULT_URL = "https://www.nytimes.com/games/wordle/index.html"


async def main() -> None:
    url_in = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    out_dir = Path(__file__).resolve().parent / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    shot = out_dir / "nyt_inspect.png"

    selectors = [
        '[data-testid="tile"]',
        '[data-testid="game-board"]',
        "[data-state]",
        "game-app",
        "main",
        "body",
        "div",
        "[role=dialog]",
        "[role=alert]",
        "button:has-text(\"Play\")",
        "a:has-text(\"Play\")",
        "button:has-text(\"Subscribe\")",
        "button:has-text(\"Log in\")",
    ]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1200, "height": 900})
        await page.goto(url_in, wait_until="domcontentloaded", timeout=120_000)
        await asyncio.sleep(5.0)

        title = await page.title()
        url = page.url
        print(f"title: {title!r}")
        print(f"url:   {url!r}")

        for sel in selectors:
            try:
                n = await page.locator(sel).count()
            except Exception:
                n = "ERR"
            print(f"{sel:26} -> {n}")

        body_text = await page.evaluate("() => (document.body && document.body.innerText || '').slice(0, 800)")
        print("\nbody text (first 500 chars):")
        print(body_text)

        await page.screenshot(path=str(shot), full_page=True)
        print(f"\nWrote screenshot: {shot}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

