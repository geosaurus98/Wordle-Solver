from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright


URL = "https://www.britannica.com/games/octordle/daily"


async def main() -> None:
    out_dir = Path(__file__).resolve().parent / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    shot = out_dir / "octordle_inspect.png"

    selectors = [
        "[data-testid]",
        "[data-state]",
        "[data-evaluation]",
        "[data-letter]",
        '[aria-label*="correct"]',
        '[aria-label*="present"]',
        '[aria-label*="absent"]',
        ".tile",
        ".board",
        ".grid",
        "main",
        "button",
        "[role=dialog]",
        "[role=alert]",
    ]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        await page.goto(URL, wait_until="domcontentloaded", timeout=120_000)
        await asyncio.sleep(4.0)

        print(f"title: {await page.title()!r}")
        print(f"url:   {page.url!r}")

        for sel in selectors:
            try:
                n = await page.locator(sel).count()
            except Exception:
                n = "ERR"
            print(f"{sel:24} -> {n}")

        # Peek at a few tile-like elements.
        board_probe = await page.evaluate(
            """
            () => {
              const b = document.querySelector('.board');
              if (!b) return null;
              const desc = Array.from(b.querySelectorAll('*'));
              const tagCounts = new Map();
              const classCounts = new Map();
              for (const el of desc) {
                const t = el.tagName.toLowerCase();
                tagCounts.set(t, (tagCounts.get(t) || 0) + 1);
                const c = (el.className || '').toString();
                if (c) classCounts.set(c, (classCounts.get(c) || 0) + 1);
              }
              const topTags = Array.from(tagCounts.entries()).sort((a,b)=>b[1]-a[1]).slice(0, 15);
              const topClasses = Array.from(classCounts.entries()).sort((a,b)=>b[1]-a[1]).slice(0, 25);
              const firstChildren = Array.from(b.children).slice(0, 10).map(el => ({
                tag: el.tagName.toLowerCase(),
                className: (el.className || '').toString(),
                text: (el.textContent || '').trim().slice(0, 20),
                attrs: Array.from(el.attributes).slice(0, 10).map(a => [a.name, a.value]),
              }));
              return {
                boardTag: b.tagName.toLowerCase(),
                boardClass: (b.className || '').toString(),
                boardAttrs: Array.from(b.attributes).map(a => [a.name, a.value]),
                topTags,
                topClasses: topClasses.map(([cls,n])=>({cls,n})),
                firstChildren,
                outerHTML: b.outerHTML.slice(0, 400),
              };
            }
            """
        )
        print("\nBoard probe:")
        print(board_probe)

        await page.screenshot(path=str(shot), full_page=True)
        print(f"\nWrote screenshot: {shot}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

