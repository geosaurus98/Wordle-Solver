from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

import requests
from playwright.async_api import async_playwright


ROOT_URL = "https://www.sedecordle.com/?mode=daily"
BASE_URL = "https://www.sedecordle.com/"
DATA_DIR = Path(__file__).resolve().parent / "data"


@dataclass(frozen=True)
class WordListExtraction:
    allowed: list[str]
    answers: list[str]
    scripts: list[str]
    runs: list[dict]
    sources: list[dict]


_SCRIPT_SRC_RE = re.compile(r"""<script[^>]+src=["']([^"']+)["']""", re.IGNORECASE)
_WORD_LITERAL_RE = re.compile(r"""(["'])([a-z]{5})\1""")
_COMMA_SEP_RE = re.compile(r"""^\s*,\s*$""")
_WORD_TOKEN_RE = re.compile(r"""\b[a-z]{5}\b""")


def _fetch_text(url: str, timeout_s: int = 30) -> str:
    r = requests.get(url, timeout=timeout_s)
    r.raise_for_status()
    return r.text


def _iter_script_urls(html: str) -> list[str]:
    srcs = _SCRIPT_SRC_RE.findall(html)
    # Keep JS-ish assets only; ignore analytics etc.
    out: list[str] = []
    for src in srcs:
        full = urljoin(BASE_URL, src)
        if ".js" in full:
            out.append(full)
    # Deduplicate preserving order
    seen = set()
    deduped = []
    for u in out:
        if u in seen:
            continue
        seen.add(u)
        deduped.append(u)
    return deduped


def _runs_of_words(js: str, min_run: int = 1000) -> list[list[str]]:
    """
    Extract "runs" of 5-letter string literals that look like JS arrays:
    "aaaaa","aaaab","aaaac",...
    """
    matches = list(_WORD_LITERAL_RE.finditer(js))
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


def _unique_sorted(words: Iterable[str]) -> list[str]:
    return sorted(set(w.lower() for w in words if w and w.isalpha() and len(w) == 5))


async def _extract_via_playwright() -> tuple[list[str], list[str], list[dict]]:
    """
    Some Sedecordle variants load wordlists via network requests rather than embedding
    them in JS bundles. This observes responses and looks for large sets of 5-letter words.
    """
    captured: list[dict] = []
    texts: list[tuple[str, str, str]] = []  # (url, content_type, text)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        async def on_response(resp):
            try:
                if resp.status != 200:
                    return
                ct = (resp.headers or {}).get("content-type", "")
                ct_l = ct.lower()
                if not any(x in ct_l for x in ("text", "json", "javascript")):
                    return
                # Avoid pulling huge assets into memory.
                try:
                    txt = await resp.text()
                except Exception:
                    return
                if not txt or len(txt) < 10_000:
                    return
                if len(txt) > 12_000_000:
                    return
                texts.append((resp.url, ct, txt))
            except Exception:
                return

        page.on("response", lambda resp: asyncio.create_task(on_response(resp)))

        await page.goto(ROOT_URL, wait_until="networkidle")
        await asyncio.sleep(0.8)  # allow any late async fetches
        await browser.close()

    # Try structured run extraction first (finds proper array literals, less noise).
    # Fall back to broad token scan if no runs found.
    run_candidates: list[tuple[int, str, str, list[str]]] = []
    for url, ct, txt in texts:
        for run in _runs_of_words(txt, min_run=500):
            uniq = _unique_sorted(run)
            if len(uniq) >= 500:
                run_candidates.append((len(uniq), url, ct, uniq))

    if run_candidates:
        run_candidates.sort(reverse=True, key=lambda x: x[0])
        candidates = run_candidates
    else:
        candidates = []
        for url, ct, txt in texts:
            words = _WORD_TOKEN_RE.findall(txt.lower())
            uniq = _unique_sorted(words)
            if len(uniq) >= 500:
                candidates.append((len(uniq), url, ct, uniq))
        candidates.sort(reverse=True, key=lambda x: x[0])

    if not candidates:
        return [], [], captured

    allowed = candidates[0][3]
    answers: list[str] = []
    if len(candidates) > 1:
        # Pick a smaller-but-still-large list as answers, if present.
        for cnt, url, ct, uniq in candidates[1:]:
            if 500 <= cnt < len(allowed) - 200:
                answers = uniq
                break
    if not answers:
        answers = allowed

    captured = [
        {"url": url, "content_type": ct, "unique_5_letter_words": cnt, "sample": uniq[:10]}
        for (cnt, url, ct, uniq) in candidates[:10]
    ]
    return allowed, answers, captured


def extract_from_site() -> WordListExtraction:
    html = _fetch_text(ROOT_URL)
    script_urls = _iter_script_urls(html)

    all_runs: list[dict] = []
    best_allowed: list[str] = []
    second_best: list[str] = []
    sources: list[dict] = []

    for url in script_urls:
        js = _fetch_text(url)
        runs = _runs_of_words(js)
        for run in runs:
            uniq = _unique_sorted(run)
            all_runs.append(
                {
                    "script": url,
                    "run_len": len(run),
                    "unique_len": len(uniq),
                    "sample": uniq[:10],
                }
            )
            if len(uniq) > len(best_allowed):
                second_best = best_allowed
                best_allowed = uniq
            elif len(uniq) > len(second_best):
                second_best = uniq

    # Fallback: if we couldn't detect array-runs, just take any 5-letter literals.
    if not best_allowed:
        all_words: list[str] = []
        for url in script_urls:
            js = _fetch_text(url)
            all_words.extend(m.group(2) for m in _WORD_LITERAL_RE.finditer(js))
        best_allowed = _unique_sorted(all_words)
        if best_allowed:
            sources.append({"method": "js_literal_scan", "script_count": len(script_urls), "unique": len(best_allowed)})

    allowed = best_allowed
    answers = second_best

    # Heuristic: answers list (if present) is typically smaller but still large.
    if not answers or len(answers) < 500 or len(answers) >= len(allowed) - 200:
        answers = allowed

    # Final fallback: observe network responses using Playwright.
    if not allowed:
        allowed2, answers2, captured = asyncio.run(_extract_via_playwright())
        allowed = allowed2
        answers = answers2
        if captured:
            sources.append({"method": "playwright_network_scan", "candidates": captured})

    return WordListExtraction(
        allowed=allowed,
        answers=answers,
        scripts=script_urls,
        runs=sorted(all_runs, key=lambda d: d["unique_len"], reverse=True)[:20],
        sources=sources,
    )


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    extraction = extract_from_site()
    (DATA_DIR / "allowed.txt").write_text("\n".join(extraction.allowed) + "\n", encoding="utf-8")
    (DATA_DIR / "answers.txt").write_text("\n".join(extraction.answers) + "\n", encoding="utf-8")
    (DATA_DIR / "extraction_report.json").write_text(
        json.dumps(
            {
                "root_url": ROOT_URL,
                "script_count": len(extraction.scripts),
                "allowed_count": len(extraction.allowed),
                "answers_count": len(extraction.answers),
                "top_runs": extraction.runs,
                "scripts": extraction.scripts,
                "sources": extraction.sources,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Wrote {len(extraction.allowed)} allowed guesses -> {DATA_DIR / 'allowed.txt'}")
    print(f"Wrote {len(extraction.answers)} answers -> {DATA_DIR / 'answers.txt'}")
    print(f"Wrote report -> {DATA_DIR / 'extraction_report.json'}")


if __name__ == "__main__":
    main()
