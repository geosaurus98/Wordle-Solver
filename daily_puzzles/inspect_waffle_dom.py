from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright


URL = "https://wafflegame.net/daily"


async def main() -> None:
    out_dir = Path(__file__).resolve().parent / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    shot = out_dir / "waffle_inspect.png"

    selectors = [
        "[data-testid]",
        "[data-state]",
        "[role=button]",
        "button",
        ".tile",
        ".cell",
        ".board",
        ".waffle",
        "svg",
        "canvas",
    ]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1200, "height": 1000})
        await page.goto(URL, wait_until="domcontentloaded", timeout=120_000)
        await asyncio.sleep(4.0)

        print(f"title: {await page.title()!r}")
        print(f"url:   {page.url!r}")

        for sel in selectors:
            try:
                n = await page.eval_on_selector_all(sel, "els => els.length")
            except Exception:
                n = "ERR"
            print(f"{sel:14} -> {n}")

        # Show some candidate interactive elements.
        samples = await page.evaluate(
            """
            () => {
              const els = Array.from(document.querySelectorAll('[role=button],button,.tile,.cell'));
              const out = [];
              for (const el of els.slice(0, 30)) {
                out.push({
                  tag: el.tagName.toLowerCase(),
                  role: el.getAttribute('role'),
                  testid: el.getAttribute('data-testid'),
                  className: (el.className || '').toString(),
                  text: (el.textContent || '').trim().slice(0, 10),
                  attrs: Array.from(el.attributes).slice(0, 8).map(a => [a.name, a.value]),
                });
              }
              return out;
            }
            """
        )
        print("\nSamples:")
        for s in samples:
            print(s)

        await page.screenshot(path=str(shot), full_page=True)
        print(f"\nWrote screenshot: {shot}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

