"""Temporary diagnostic: deep fiber scan + full response dump."""
from __future__ import annotations
import asyncio, json
from playwright.async_api import async_playwright

NYT_URL = "https://www.nytimes.com/games/wordle/index.html"

FIBER_JS = """
() => {
    function findInFiber(node, depth) {
        if (!node || depth > 25) return null;
        try {
            for (const prop of [node.memoizedProps, node.memoizedState]) {
                if (!prop || typeof prop !== 'object') continue;
                for (const [k, v] of Object.entries(prop)) {
                    if (typeof v === 'string' && /^[a-z]{5}$/.test(v) &&
                        (k.toLowerCase().includes('solution') || k.toLowerCase().includes('answer') ||
                         k.toLowerCase().includes('word') || k.toLowerCase().includes('target'))) {
                        return {key: k, value: v, depth};
                    }
                    if (Array.isArray(v) && v.length > 50 && v.length < 5000 &&
                        v.slice(0,20).every(x => typeof x === 'string' && x.length === 5)) {
                        return {key: k, type: 'array', count: v.length, sample: v.slice(0,8), depth};
                    }
                }
            }
        } catch(e) {}
        const r1 = findInFiber(node.child, depth + 1);
        if (r1) return r1;
        return findInFiber(node.sibling, depth + 1);
    }
    const root = document.querySelector('#__next') || document.body;
    const fk = Object.keys(root).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
    if (!fk) return {error: 'no fiber key'};
    return findInFiber(root[fk], 0) || {error: 'nothing found'};
}
"""

async def main() -> None:
    responses: list[tuple[str, str, int, str]] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        async def capture(resp):
            try:
                if resp.status != 200:
                    return
                ct = (resp.headers or {}).get("content-type", "")
                if not any(x in ct.lower() for x in ("javascript", "json", "text")):
                    return
                txt = await resp.text()
                responses.append((resp.url, ct, len(txt), txt[:300]))
            except Exception:
                pass

        page.on("response", lambda r: asyncio.create_task(capture(r)))
        await page.goto(NYT_URL, wait_until="domcontentloaded", timeout=120_000)
        await asyncio.sleep(8.0)

        solution = await page.evaluate(FIBER_JS)
        print("React fiber scan:", json.dumps(solution, indent=2))

        # Also try: look for any window properties that look like game config
        game_config = await page.evaluate("""
        () => {
            const out = {};
            const interesting = ['__gameData', '__wordleData', '__puzzleData', 'gameData',
                                 '__NYT_GAMES', 'WordleGame', '__NEXT_DATA__'];
            for (const k of interesting) {
                try {
                    if (window[k] !== undefined) out[k] = JSON.stringify(window[k]).slice(0, 500);
                } catch(e) {}
            }
            // __NEXT_DATA__ is standard Next.js
            const nd = document.getElementById('__NEXT_DATA__');
            if (nd) out['__NEXT_DATA__'] = nd.textContent.slice(0, 1000);
            return out;
        }
        """)
        print("\nGame config candidates:", json.dumps(game_config, indent=2))

        await browser.close()

    responses.sort(key=lambda x: x[2])
    print(f"\nAll {len(responses)} responses by size:")
    for url, ct, size, preview in responses:
        short = url.split("?")[0][-90:]
        print(f"  {size:8d}  {short}")
        if size < 50_000 and "word" in url.lower():
            print(f"           preview: {preview[:120]}")

if __name__ == "__main__":
    asyncio.run(main())