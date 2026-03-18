from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from playwright.async_api import async_playwright


NYT_URL = "https://www.nytimes.com/games/wordle/index.html"
DATA_DIR = Path(__file__).resolve().parent / "data"


@dataclass(frozen=True)
class WordListExtraction:
    allowed: list[str]
    answers: list[str]
    sources: list[dict]


_WORD_LITERAL_RE = re.compile(r"""(["'])([a-z]{5})\1""")
_COMMA_SEP_RE = re.compile(r"""^\s*,\s*$""")


def _unique_sorted(words: Iterable[str]) -> list[str]:
    return sorted(set(w.lower() for w in words if w and w.isalpha() and len(w) == 5))


def _runs_of_words(js: str, min_run: int = 500) -> list[list[str]]:
    """
    Extract "runs" of 5-letter string literals that look like JS arrays:
    "cigar","rebut","sissy",...
    """
    matches = list(_WORD_LITERAL_RE.finditer(js.lower()))
    if not matches:
        return []

    runs: list[list[str]] = []
    cur: list[str] = [matches[0].group(2)]
    prev_end = matches[0].end()

    for m in matches[1:]:
        between = js[prev_end : m.start()]
        if _COMMA_SEP_RE.match(between):
            cur.append(m.group(2))
        else:
            if len(cur) >= min_run:
                runs.append(cur)
            cur = [m.group(2)]
        prev_end = m.end()

    if len(cur) >= min_run:
        runs.append(cur)
    return runs


async def _extract_via_playwright() -> WordListExtraction:
    texts: list[tuple[str, str, str]] = []  # (url, content_type, text)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        async def on_response(resp):
            try:
                if resp.status != 200:
                    return
                url = resp.url
                ct = (resp.headers or {}).get("content-type", "")
                ct_l = ct.lower()
                # Mostly care about JS/JSON.
                if not any(x in ct_l for x in ("javascript", "json", "text")):
                    return
                if len(url) > 300:
                    return
                txt = await resp.text()
                # Some word lists are smaller; don't filter too aggressively.
                if not txt or len(txt) < 8_000:
                    return
                if len(txt) > 15_000_000:
                    return
                texts.append((url, ct, txt))
            except Exception:
                return

        page.on("response", lambda resp: asyncio.create_task(on_response(resp)))

        # Wordle keeps background requests open, so "networkidle" can hang.
        await page.goto(NYT_URL, wait_until="domcontentloaded", timeout=120_000)
        # Allow time for JS bundles to load.
        await asyncio.sleep(6.0)
        await browser.close()

    # Find large runs of 5-letter literals.
    candidates: list[tuple[int, str, str, list[str]]] = []  # (unique_len, url, ct, uniq_words)
    for url, ct, txt in texts:
        for run in _runs_of_words(txt, min_run=500):
            uniq = _unique_sorted(run)
            if len(uniq) >= 500:
                candidates.append((len(uniq), url, ct, uniq))

    # Deduplicate by word set size+url; keep top.
    candidates.sort(reverse=True, key=lambda x: x[0])

    sources = [
        {"url": url, "content_type": ct, "unique_5_letter_words": cnt, "sample": uniq[:10]}
        for (cnt, url, ct, uniq) in candidates[:10]
    ]

    if not candidates:
        return WordListExtraction(allowed=[], answers=[], sources=sources)

    allowed = candidates[0][3]
    # Wordle has a smaller answer list; pick a second run that is smaller but still big enough.
    answers: list[str] = []
    for cnt, url, ct, uniq in candidates[1:]:
        if 1500 <= cnt < len(allowed) - 500:
            answers = uniq
            break
    if not answers:
        # Reasonable fallback: treat allowed as answers too.
        answers = allowed

    return WordListExtraction(allowed=allowed, answers=answers, sources=sources)


def extract_from_site() -> WordListExtraction:
    return asyncio.run(_extract_via_playwright())


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    extraction = extract_from_site()

    (DATA_DIR / "nyt_allowed.txt").write_text("\n".join(extraction.allowed) + "\n", encoding="utf-8")
    (DATA_DIR / "nyt_answers.txt").write_text("\n".join(extraction.answers) + "\n", encoding="utf-8")
    (DATA_DIR / "nyt_extraction_report.json").write_text(
        json.dumps(
            {
                "root_url": NYT_URL,
                "allowed_count": len(extraction.allowed),
                "answers_count": len(extraction.answers),
                "sources": extraction.sources,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Wrote {len(extraction.allowed)} allowed -> {DATA_DIR / 'nyt_allowed.txt'}")
    print(f"Wrote {len(extraction.answers)} answers -> {DATA_DIR / 'nyt_answers.txt'}")
    print(f"Wrote report -> {DATA_DIR / 'nyt_extraction_report.json'}")


if __name__ == "__main__":
    main()

