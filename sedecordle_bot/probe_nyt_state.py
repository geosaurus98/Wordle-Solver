"""
Diagnostic script: probe the live NYT Wordle page to find where the answer list lives.

Checks:
  1. All network responses (no size floor) for runs of 5-letter words at any threshold
  2. window / localStorage / sessionStorage for game state
  3. Deep search of window object for arrays of 5-letter strings
  4. Today's solution word if extractable from JS state
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from playwright.async_api import async_playwright


NYT_URL = "https://www.nytimes.com/games/wordle/index.html"
OUT_DIR = Path(__file__).resolve().parent / "data"

_WORD_RE = re.compile(r"""(["'])([a-z]{5})\1""")
_COMMA_RE = re.compile(r"""^\s*,\s*$""")


def _word_runs(text: str, min_run: int = 20) -> list[list[str]]:
    matches = list(_WORD_RE.finditer(text.lower()))
    if not matches:
        return []
    runs: list[list[str]] = []
    cur = [matches[0].group(2)]
    prev_end = matches[0].end()
    for m in matches[1:]:
        if _COMMA_RE.match(text[prev_end:m.start()]):
            cur.append(m.group(2))
        else:
            if len(cur) >= min_run:
                runs.append(cur)
            cur = [m.group(2)]
        prev_end = m.end()
    if len(cur) >= min_run:
        runs.append(cur)
    return runs


async def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    responses: list[tuple[str, str, str]] = []  # (url, content_type, text)

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
                if txt:
                    responses.append((resp.url, ct, txt))
            except Exception:
                pass

        page.on("response", lambda r: asyncio.create_task(capture(r)))
        await page.goto(NYT_URL, wait_until="domcontentloaded", timeout=120_000)
        await asyncio.sleep(8.0)

        # --- 1. localStorage / sessionStorage ---
        storage = await page.evaluate("""() => {
            const out = {};
            for (let i = 0; i < localStorage.length; i++) {
                const k = localStorage.key(i);
                out['local:' + k] = localStorage.getItem(k);
            }
            for (let i = 0; i < sessionStorage.length; i++) {
                const k = sessionStorage.key(i);
                out['session:' + k] = sessionStorage.getItem(k);
            }
            return out;
        }""")

        # --- 2. Deep window scan for arrays of 5-letter strings ---
        word_arrays = await page.evaluate("""() => {
            const seen = new Set();
            const results = [];
            function isWord(s) { return typeof s === 'string' && /^[a-z]{5}$/.test(s); }
            function scan(obj, path, depth) {
                if (depth > 6 || seen.has(obj)) return;
                seen.add(obj);
                try {
                    if (Array.isArray(obj)) {
                        const words = obj.filter(isWord);
                        if (words.length >= 20) {
                            results.push({
                                path, count: words.length,
                                sample: words.slice(0, 10),
                                total_len: obj.length
                            });
                            return;
                        }
                    }
                    if (obj && typeof obj === 'object') {
                        for (const key of Object.keys(obj).slice(0, 100)) {
                            try { scan(obj[key], path + '.' + key, depth + 1); }
                            catch(e) {}
                        }
                    }
                } catch(e) {}
            }
            scan(window, 'window', 0);
            return results;
        }""")

        # --- 3. Today's solution from game state ---
        solution_candidates = await page.evaluate("""() => {
            const results = {};
            // Common NYT game state patterns
            const checks = [
                () => window.__wordle_state,
                () => window.wordle,
                () => window.gameData,
                () => {
                    // Look for React fiber with solution
                    const board = document.querySelector('[data-testid="game-board"]');
                    if (!board) return null;
                    const key = Object.keys(board).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                    if (!key) return null;
                    let fiber = board[key];
                    for (let i = 0; i < 30 && fiber; i++) {
                        const s = fiber.memoizedState;
                        if (s && s.memoizedState && typeof s.memoizedState === 'string' && s.memoizedState.length === 5)
                            return { solution_from_fiber: s.memoizedState };
                        fiber = fiber.return;
                    }
                    return null;
                }
            ];
            checks.forEach((fn, i) => {
                try { const r = fn(); if (r) results['check_' + i] = r; } catch(e) {}
            });
            // Also scan all string properties of window for a 5-letter word labelled 'solution'/'answer'/'word'
            for (const key of Object.keys(window)) {
                try {
                    const v = window[key];
                    if (typeof v === 'string' && /^[a-z]{5}$/.test(v))
                        results['window.' + key] = v;
                } catch(e) {}
            }
            return results;
        }""")

        await browser.close()

    # --- Analyse responses ---
    print(f"\n{'='*60}")
    print(f"Network responses captured: {len(responses)}")
    print(f"{'='*60}")

    all_runs: list[tuple[int, str, list[str]]] = []
    for url, ct, txt in responses:
        for run in _word_runs(txt, min_run=20):
            unique = sorted(set(w for w in run if w.isalpha()))
            all_runs.append((len(unique), url, unique))

    all_runs.sort(reverse=True)
    print(f"\nWord runs found (>=20 words), sorted by size:")
    for cnt, url, words in all_runs[:20]:
        short_url = url.split('?')[0][-80:]
        print(f"  {cnt:5d} words  {short_url}")
        print(f"         sample: {words[:8]}")

    # --- localStorage ---
    print(f"\n{'='*60}")
    print("Storage entries:")
    for k, v in sorted(storage.items()):
        snippet = (v or "")[:120].replace("\n", " ")
        print(f"  {k}: {snippet}")

    # --- Window word arrays ---
    print(f"\n{'='*60}")
    print("Window arrays of 5-letter words:")
    for item in word_arrays:
        print(f"  {item['path']}  count={item['count']}  total_len={item['total_len']}")
        print(f"    sample: {item['sample']}")

    # --- Solution candidates ---
    print(f"\n{'='*60}")
    print("Solution/state candidates from window:")
    for k, v in solution_candidates.items():
        print(f"  {k}: {v}")

    # --- Save a full run dump ---
    dump = {
        "run_sizes": [(cnt, url.split("?")[0][-80:]) for cnt, url, _ in all_runs],
        "storage": storage,
        "window_word_arrays": word_arrays,
        "solution_candidates": solution_candidates,
    }
    out = OUT_DIR / "nyt_probe_report.json"
    out.write_text(json.dumps(dump, indent=2), encoding="utf-8")
    print(f"\nFull report -> {out}")


if __name__ == "__main__":
    asyncio.run(main())