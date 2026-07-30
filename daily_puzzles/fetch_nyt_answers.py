"""
Fetch NYT Wordle answers from the public dated API:
  https://www.nytimes.com/svc/wordle/v2/YYYY-MM-DD.json

Builds nyt_answers.txt from all reachable past and future dates.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import date, timedelta
from pathlib import Path

import aiohttp


NYT_URL_TMPL = "https://www.nytimes.com/svc/wordle/v2/{date}.json"
DATA_DIR = Path(__file__).resolve().parent / "data"

# Original Wordle launched 2021-06-19; NYT took over ~2022-02-01.
# The API appears to serve from the very first puzzle.
FIRST_DATE = date(2021, 6, 19)


async def fetch_one(session: aiohttp.ClientSession, d: date) -> dict | None:
    url = NYT_URL_TMPL.format(date=d.isoformat())
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                return await resp.json(content_type=None)
            return None
    except Exception:
        return None


async def fetch_range(
    start: date,
    end: date,
    concurrency: int = 10,
) -> list[dict]:
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    results: list[dict] = []
    sem = asyncio.Semaphore(concurrency)

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; Wordle-archiver)",
        "Accept": "application/json",
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        async def bounded_fetch(d: date) -> dict | None:
            async with sem:
                return await fetch_one(session, d)

        tasks = [bounded_fetch(d) for d in days]
        t0 = time.monotonic()
        done = 0
        for coro in asyncio.as_completed(tasks):
            result = await coro
            if result and "solution" in result:
                results.append(result)
            done += 1
            if done % 100 == 0:
                elapsed = time.monotonic() - t0
                print(f"  {done}/{len(days)} fetched, {len(results)} answers so far ({elapsed:.0f}s)")

    results.sort(key=lambda r: r.get("print_date", ""))
    return results


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today()

    # Probe how far into the future the API serves.
    # Try up to 2 years ahead in small steps.
    future_probe_end = today + timedelta(days=730)

    print(f"Fetching from {FIRST_DATE} to {future_probe_end} ...")
    print(f"(This covers {(future_probe_end - FIRST_DATE).days + 1} dates)")

    answers = asyncio.run(fetch_range(FIRST_DATE, future_probe_end, concurrency=20))

    if not answers:
        print("No answers fetched — API may require authentication.")
        return

    words = [r["solution"].lower().strip() for r in answers if r.get("solution")]
    words = [w for w in words if len(w) == 5 and w.isalpha()]

    past = [r for r in answers if r.get("print_date", "") <= today.isoformat()]
    future = [r for r in answers if r.get("print_date", "") > today.isoformat()]

    print(f"\nTotal answers fetched : {len(answers)}")
    print(f"  Past (incl. today)  : {len(past)}")
    print(f"  Future pre-scheduled: {len(future)}")

    if answers:
        print(f"  Date range          : {answers[0]['print_date']} -> {answers[-1]['print_date']}")
        print(f"  Sample (last 5)     : {[r['solution'] for r in answers[-5:]]}")

    out_words = list(dict.fromkeys(words))  # dedup, preserve order
    out_path = DATA_DIR / "nyt_answers.txt"
    out_path.write_text("\n".join(out_words) + "\n", encoding="utf-8")
    print(f"\nWrote {len(out_words)} answers -> {out_path}")

    # Also save the full JSON for reference.
    report_path = DATA_DIR / "nyt_answers_api_report.json"
    report_path.write_text(
        json.dumps(
            {
                "fetched": len(answers),
                "past": len(past),
                "future": len(future),
                "date_range": [answers[0]["print_date"], answers[-1]["print_date"]] if answers else [],
                "sample": answers[-10:],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Report -> {report_path}")


if __name__ == "__main__":
    main()