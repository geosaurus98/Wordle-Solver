from __future__ import annotations

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright


URL = "https://www.sedecordle.com/savior"


async def main() -> None:
    out_dir = Path(__file__).resolve().parent / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "sedecordle_globals.json"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        await page.goto(URL, wait_until="domcontentloaded", timeout=120_000)
        await asyncio.sleep(2.0)

        data = await page.evaluate(
            """
            () => {
              function sampleStrings(iter, limit=30) {
                const out = [];
                let i = 0;
                for (const v of iter) {
                  if (typeof v === 'string') out.push(v);
                  if (++i >= limit) break;
                }
                return out;
              }

              const props = Object.getOwnPropertyNames(window);
              const found = [];

              for (const k of props) {
                let v;
                try { v = window[k]; } catch (e) { continue; }
                if (!v) continue;

                // Arrays of strings
                if (Array.isArray(v) && v.length >= 1000) {
                  const strs = v.filter(x => typeof x === 'string' && x.length === 5 && /^[a-z]+$/i.test(x)).slice(0, 200);
                  if (strs.length >= 200) {
                    found.push({ key: k, type: 'array', length: v.length, sample: strs.slice(0, 20) });
                  }
                }

                // Sets of strings
                if (v instanceof Set && v.size >= 1000) {
                  const samp = sampleStrings(v.values(), 500);
                  const five = samp.filter(x => x.length === 5 && /^[a-z]+$/i.test(x));
                  if (five.length >= 200) {
                    found.push({ key: k, type: 'set', length: v.size, sample: five.slice(0, 20) });
                  }
                }

                // Objects that look like maps: { word: 1 }
                if (typeof v === 'object' && !Array.isArray(v) && !(v instanceof Set)) {
                  try {
                    const keys = Object.keys(v);
                    if (keys.length >= 1000) {
                      const five = keys.filter(x => x.length === 5 && /^[a-z]+$/i.test(x));
                      if (five.length >= 500) {
                        found.push({ key: k, type: 'object-keys', length: keys.length, sample: five.slice(0, 20) });
                      }
                    }
                  } catch (e) {}
                }
              }

              return found.sort((a,b)=>b.length-a.length).slice(0, 25);
            }
            """
        )

        out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"Wrote: {out_path}")
        print(json.dumps(data[:5], indent=2))
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

