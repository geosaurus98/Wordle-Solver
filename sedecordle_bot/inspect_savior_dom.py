from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright


URL = "https://www.sedecordle.com/savior"


async def main() -> None:
    out_dir = Path(__file__).resolve().parent / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    shot = out_dir / "savior_inspect.png"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        await page.goto(URL, wait_until="domcontentloaded", timeout=120_000)
        await asyncio.sleep(3.0)

        counts = await page.evaluate(
            """
            () => {
              const q = (s) => document.querySelectorAll(s).length;
              return {
                tables: q('table'),
                trs: q('tr'),
                tds: q('td'),
                divs: q('div'),
                tiles: q('.tile'),
                dailygames: q('.dailygames'),
                boxButtons: q('td.box.button'),
                scripts: q('script'),
                bodyTextStart: (document.body && document.body.innerText || '').slice(0, 300),
              };
            }
            """
        )
        print(counts)

        more = await page.evaluate(
            """
            () => {
              const tables = Array.from(document.querySelectorAll('table'));
              const tableStats = tables.map(t => {
                const rows = Array.from(t.querySelectorAll('tr'));
                const rowLens = rows.map(r => r.querySelectorAll('td').length);
                return { rows: rows.length, min: rowLens.length ? Math.min(...rowLens) : 0, max: rowLens.length ? Math.max(...rowLens) : 0 };
              });
              const tdClasses = new Map();
              for (const td of Array.from(document.querySelectorAll('td'))) {
                const c = (td.className || '').toString().trim();
                tdClasses.set(c, (tdClasses.get(c) || 0) + 1);
              }
              const topTdClasses = Array.from(tdClasses.entries()).sort((a,b)=>b[1]-a[1]).slice(0, 20).map(([cls,n])=>({cls,n}));
              return { tableStats, topTdClasses };
            }
            """
        )
        print("tableStats/topTdClasses:", more)

        div_info = await page.evaluate(
            """
            () => {
              const divs = Array.from(document.querySelectorAll('div'));
              const counts = new Map();
              for (const el of divs) {
                const c = (el.className || '').toString().trim();
                if (!c) continue;
                counts.set(c, (counts.get(c) || 0) + 1);
              }
              const top = Array.from(counts.entries()).sort((a,b)=>b[1]-a[1]).slice(0, 40)
                .map(([cls,n]) => ({cls, n}));

              // likely tile elements: textContent is single letter and has backgroundColor not transparent
              const tiles = [];
              for (const el of divs) {
                const t = (el.textContent || '').trim();
                if (t.length !== 1 || !/[A-Z]/i.test(t)) continue;
                const bg = getComputedStyle(el).backgroundColor;
                if (!bg || bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent') continue;
                const rect = el.getBoundingClientRect();
                if (rect.width < 20 || rect.height < 20) continue;
                tiles.push({
                  text: t,
                  className: (el.className || '').toString(),
                  bg,
                  w: Math.round(rect.width),
                  h: Math.round(rect.height),
                });
                if (tiles.length >= 20) break;
              }

              return { topDivClasses: top, tileLikeSamples: tiles };
            }
            """
        )
        print("div info:", div_info)

        await page.screenshot(path=str(shot), full_page=True)
        print(f"Wrote screenshot: {shot}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

