"""
DOM inspection script for NumberWaffle and Tilerdle.
Dumps tile structure, CSS classes, feedback indicators, and interaction patterns.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from playwright.async_api import async_playwright

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCREENSHOTS_DIR = Path(__file__).resolve().parent.parent / "debug_screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

async def dump_all_ids_and_classes(page, label: str):
    """Print all elements that have an id or a non-empty class attribute."""
    print(f"\n{'='*70}")
    print(f"  {label} — elements with id or class")
    print(f"{'='*70}")
    elements = await page.evaluate("""() => {
        const results = [];
        document.querySelectorAll('*').forEach(el => {
            const id = el.id || '';
            const cls = el.className || '';
            const tag = el.tagName.toLowerCase();
            const text = (el.innerText || '').slice(0, 80).replace(/\\n/g, ' ');
            const attrs = {};
            for (const a of el.attributes) {
                if (!['id','class','style'].includes(a.name)) {
                    attrs[a.name] = a.value.slice(0, 100);
                }
            }
            if (id || cls) {
                results.push({ tag, id, cls, text, attrs });
            }
        });
        return results;
    }""")
    for e in elements:
        print(f"  <{e['tag']}> id={e['id']!r:30s} class={e['cls']!r:60s}")
        if e['attrs']:
            print(f"         attrs={e['attrs']}")
        if e['text'].strip():
            print(f"         text={e['text']!r}")


async def dump_grid_structure(page, selector: str, label: str):
    """Inspect every element matching the selector."""
    print(f"\n{'='*70}")
    print(f"  {label} — grid cells matching '{selector}'")
    print(f"{'='*70}")
    cells = await page.evaluate(f"""() => {{
        const cells = [];
        document.querySelectorAll('{selector}').forEach((el, i) => {{
            const style = window.getComputedStyle(el);
            cells.push({{
                index: i,
                tag: el.tagName.toLowerCase(),
                id: el.id,
                cls: el.className,
                text: (el.innerText || '').slice(0, 40).replace(/\\n/g, ' '),
                bgColor: style.backgroundColor,
                color: style.color,
                attrs: Object.fromEntries(
                    Array.from(el.attributes).map(a => [a.name, a.value.slice(0, 120)])
                )
            }});
        }});
        return cells;
    }}""")
    for c in cells:
        print(f"  [{c['index']:3d}] <{c['tag']}> id={c['id']!r} cls={c['cls']!r}")
        print(f"         text={c['text']!r}  bg={c['bgColor']}  fg={c['color']}")
        if c['attrs']:
            safe = {k: v for k, v in c['attrs'].items() if k not in ('id', 'class', 'style')}
            if safe:
                print(f"         attrs={safe}")


# ---------------------------------------------------------------------------
# NumberWaffle
# ---------------------------------------------------------------------------

async def inspect_number_waffle(pw):
    print("\n" + "#"*70)
    print("## NumberWaffle  https://wafflegame.net/numberwaffle")
    print("#"*70)

    browser = await pw.chromium.launch(headless=True)
    context = await browser.new_context(viewport={"width": 1280, "height": 900})
    page = await context.new_page()

    await page.goto("https://wafflegame.net/numberwaffle", wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(4000)  # let JS render
    await page.screenshot(path=str(SCREENSHOTS_DIR / "numberwaffle_initial.png"))
    print("\n[Screenshot] numberwaffle_initial.png saved")

    # Dismiss any modal / overlay
    for selector in [
        'button:has-text("Play")',
        'button:has-text("OK")',
        'button:has-text("Got it")',
        'button:has-text("Close")',
        '[aria-label="Close"]',
        '.modal button',
        '.overlay button',
        '.dialog button',
    ]:
        try:
            btn = page.locator(selector).first
            if await btn.is_visible(timeout=1500):
                await btn.click()
                await page.wait_for_timeout(600)
                print(f"[Dismissed overlay via: {selector}]")
                break
        except Exception:
            pass

    await page.screenshot(path=str(SCREENSHOTS_DIR / "numberwaffle_after_dismiss.png"))

    # Print page title / URL
    print(f"\nTitle: {await page.title()}")
    print(f"URL  : {page.url}")

    # Full id/class dump
    await dump_all_ids_and_classes(page, "NumberWaffle")

    # Try common waffle-style tile selectors
    for sel in [
        '.tile', '.cell', '.waffle-tile', '.letter', '.square',
        '[data-state]', '[data-letter]', '[class*="tile"]', '[class*="cell"]',
        '[class*="square"]', '[class*="Tile"]', '[class*="Cell"]',
        'td', '.grid div', '.board div',
    ]:
        count = await page.locator(sel).count()
        if count:
            print(f"\n  Selector '{sel}' matched {count} elements")
            await dump_grid_structure(page, sel, f"NumberWaffle — {sel}")
            break  # show the richest match; comment out to see all

    # Also check what interactive elements exist (buttons, inputs)
    print("\n--- Interactive elements ---")
    interactive = await page.evaluate("""() => {
        const r = [];
        document.querySelectorAll('button, input, select, [role="button"], [tabindex]').forEach(el => {
            r.push({
                tag: el.tagName.toLowerCase(),
                id: el.id,
                cls: el.className,
                text: (el.innerText || el.value || el.placeholder || '').slice(0, 60),
                type: el.type || '',
                role: el.getAttribute('role') || '',
                tabindex: el.getAttribute('tabindex') || '',
            });
        });
        return r;
    }""")
    for e in interactive:
        print(f"  <{e['tag']}> id={e['id']!r} cls={e['cls']!r} text={e['text']!r} type={e['type']!r} role={e['role']!r}")

    # Attempt to click a tile and see what changes
    print("\n--- Attempting to interact with tiles ---")
    # Try clicking something that looks like a tile
    tile_clicked = False
    for sel in ['.tile', '.cell', '[data-state]', 'td', '[class*="tile"]', '[class*="cell"]']:
        tiles = page.locator(sel)
        count = await tiles.count()
        if count >= 3:
            print(f"  Clicking first tile via '{sel}'")
            await tiles.nth(0).click()
            await page.wait_for_timeout(400)
            # Try typing a number
            await page.keyboard.press('1')
            await page.wait_for_timeout(300)
            await page.screenshot(path=str(SCREENSHOTS_DIR / "numberwaffle_after_click.png"))
            print("  [Screenshot] numberwaffle_after_click.png")
            # Show what changed
            await dump_grid_structure(page, sel, f"NumberWaffle after click — {sel}")
            tile_clicked = True
            break
    if not tile_clicked:
        print("  Could not find tile elements to click")

    # Check for keyboard handler hints in script tags
    print("\n--- Checking <script> tags for clues ---")
    scripts = await page.evaluate("""() => {
        return Array.from(document.querySelectorAll('script[src]')).map(s => s.src);
    }""")
    for s in scripts:
        print(f"  <script src={s!r}>")

    # Look for React/Vue root or app state
    app_info = await page.evaluate("""() => {
        const info = {};
        if (window.__NEXT_DATA__) info.nextData = JSON.stringify(window.__NEXT_DATA__).slice(0, 500);
        if (window.__NUXT__) info.nuxt = 'present';
        if (window.React) info.react = 'present';
        if (window.__react_fiber) info.reactFiber = 'present';
        // look for any global game state
        for (const key of Object.keys(window)) {
            if (key.toLowerCase().includes('game') || key.toLowerCase().includes('state') || key.toLowerCase().includes('waffle')) {
                try {
                    const val = JSON.stringify(window[key]);
                    if (val && val.length < 600) info[key] = val;
                } catch {}
            }
        }
        return info;
    }""")
    print("\n--- Window globals related to game/state ---")
    for k, v in app_info.items():
        print(f"  {k}: {v}")

    await browser.close()


# ---------------------------------------------------------------------------
# Tilerdle
# ---------------------------------------------------------------------------

async def inspect_tilerdle(pw):
    print("\n" + "#"*70)
    print("## Tilerdle  https://knotwise.games/games/tilerdle")
    print("#"*70)

    browser = await pw.chromium.launch(headless=True)
    context = await browser.new_context(viewport={"width": 1280, "height": 900})
    page = await context.new_page()

    await page.goto("https://knotwise.games/games/tilerdle", wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(4000)  # let JS render
    await page.screenshot(path=str(SCREENSHOTS_DIR / "tilerdle_initial.png"))
    print("\n[Screenshot] tilerdle_initial.png saved")

    # Dismiss overlays
    for selector in [
        'button:has-text("Play")',
        'button:has-text("Start")',
        'button:has-text("OK")',
        'button:has-text("Got it")',
        'button:has-text("Close")',
        '[aria-label="Close"]',
        '.modal button',
        '.overlay button',
        '.dialog button',
        'button:has-text("Accept")',
    ]:
        try:
            btn = page.locator(selector).first
            if await btn.is_visible(timeout=1500):
                await btn.click()
                await page.wait_for_timeout(600)
                print(f"[Dismissed overlay via: {selector}]")
        except Exception:
            pass

    await page.screenshot(path=str(SCREENSHOTS_DIR / "tilerdle_after_dismiss.png"))

    print(f"\nTitle: {await page.title()}")
    print(f"URL  : {page.url}")

    await dump_all_ids_and_classes(page, "Tilerdle")

    # Try tile/cell selectors
    print("\n--- Searching for tile/cell elements ---")
    for sel in [
        '.tile', '.cell', '[data-state]', '[data-color]',
        '[class*="tile"]', '[class*="Tile"]',
        '[class*="cell"]', '[class*="Cell"]',
        '[class*="color"]', '[class*="Color"]',
        '[class*="guess"]', '[class*="Guess"]',
        '[class*="row"]', '[class*="Row"]',
        'button', '[role="button"]',
        '[class*="palette"]', '[class*="option"]',
    ]:
        count = await page.locator(sel).count()
        if count:
            print(f"  '{sel}' => {count} elements")

    # Show detailed dump for most promising selectors
    for sel in ['[class*="tile"]', '[class*="cell"]', '[class*="color"]', 'button', '[data-state]']:
        count = await page.locator(sel).count()
        if count and count < 200:
            await dump_grid_structure(page, sel, f"Tilerdle — {sel}")

    # Interactive elements
    print("\n--- Interactive elements ---")
    interactive = await page.evaluate("""() => {
        const r = [];
        document.querySelectorAll('button, input, select, [role="button"], [tabindex]').forEach(el => {
            r.push({
                tag: el.tagName.toLowerCase(),
                id: el.id,
                cls: el.className,
                text: (el.innerText || el.value || el.placeholder || '').slice(0, 80),
                type: el.type || '',
                role: el.getAttribute('role') || '',
            });
        });
        return r;
    }""")
    for e in interactive:
        print(f"  <{e['tag']}> id={e['id']!r} cls={e['cls']!r} text={e['text']!r} type={e['type']!r} role={e['role']!r}")

    # Attempt to make a guess: click palette color then submit
    print("\n--- Attempting a test guess ---")
    # Find palette/color picker buttons
    palette_clicked = 0
    for sel in ['[class*="palette"] button', '[class*="color"] button', '[class*="option"]',
                '[class*="pick"]', '[class*="select"]', 'button[style*="background"]']:
        btns = page.locator(sel)
        count = await btns.count()
        if count >= 5:
            print(f"  Found {count} palette items via '{sel}', clicking first 5")
            for i in range(min(5, count)):
                await btns.nth(i).click()
                await page.wait_for_timeout(300)
            palette_clicked = count
            break

    if palette_clicked == 0:
        # Try clicking any buttons that look like colors
        print("  Trying to click first 5 buttons as color choices")
        btns = page.locator('button')
        total = await btns.count()
        print(f"  Total buttons: {total}")
        for i in range(min(5, total)):
            txt = await btns.nth(i).inner_text()
            cls = await btns.nth(i).get_attribute('class') or ''
            print(f"    Button {i}: text={txt!r} cls={cls!r}")

    # Look for a Submit/Enter button
    for sel in [
        'button:has-text("Submit")',
        'button:has-text("Enter")',
        'button:has-text("Guess")',
        'button:has-text("Check")',
        '[class*="submit"]',
        '[class*="enter"]',
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=800):
                print(f"  Found submit button via '{sel}', clicking")
                await btn.click()
                await page.wait_for_timeout(600)
                await page.screenshot(path=str(SCREENSHOTS_DIR / "tilerdle_after_guess.png"))
                print("  [Screenshot] tilerdle_after_guess.png")
                break
        except Exception:
            pass

    # Check for game state in JS
    print("\n--- Window globals related to game/state ---")
    app_info = await page.evaluate("""() => {
        const info = {};
        if (window.__NEXT_DATA__) info.nextData = JSON.stringify(window.__NEXT_DATA__).slice(0, 800);
        if (window.__NUXT__) info.nuxt = 'present';
        for (const key of Object.keys(window)) {
            if (/game|state|puzzle|guess|tile|color|wordle/i.test(key)) {
                try {
                    const val = JSON.stringify(window[key]);
                    if (val && val.length < 600) info[key] = val;
                } catch {}
            }
        }
        return info;
    }""")
    for k, v in app_info.items():
        print(f"  {k}: {v}")

    # Full HTML snapshot (truncated) for manual review
    print("\n--- Body innerHTML (first 4000 chars) ---")
    html = await page.evaluate("() => document.body.innerHTML.replace(/\\s+/g, ' ').slice(0, 4000)")
    print(html)

    await browser.close()


# ---------------------------------------------------------------------------
# NumberWaffle — deeper tile inspection after initial run
# ---------------------------------------------------------------------------

async def inspect_number_waffle_deep(pw):
    """Second pass: try every plausible tile selector and dump full body HTML."""
    print("\n" + "#"*70)
    print("## NumberWaffle — deep HTML dump")
    print("#"*70)

    browser = await pw.chromium.launch(headless=True)
    context = await browser.new_context(viewport={"width": 1280, "height": 900})
    page = await context.new_page()

    await page.goto("https://wafflegame.net/numberwaffle", wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(4000)

    # Dismiss
    for selector in ['button:has-text("Play")', 'button:has-text("OK")', 'button:has-text("Close")',
                     '[aria-label="Close"]']:
        try:
            btn = page.locator(selector).first
            if await btn.is_visible(timeout=1200):
                await btn.click()
                await page.wait_for_timeout(500)
        except Exception:
            pass

    print("\n--- Body innerHTML (first 6000 chars) ---")
    html = await page.evaluate("() => document.body.innerHTML.replace(/\\s+/g, ' ').slice(0, 6000)")
    print(html)

    # Try ALL tile selectors and report counts
    print("\n--- Selector survey ---")
    selectors = [
        '.tile', '.cell', '.square', '.letter', '.number',
        '[data-state]', '[data-letter]', '[data-row]', '[data-col]', '[data-index]',
        '[class*="tile"]', '[class*="Tile"]',
        '[class*="cell"]', '[class*="Cell"]',
        '[class*="square"]', '[class*="Square"]',
        '[class*="letter"]', '[class*="Letter"]',
        '[class*="number"]', '[class*="Number"]',
        '[class*="waffle"]', '[class*="Waffle"]',
        '[class*="grid"]', '[class*="Grid"]',
        '[class*="board"]', '[class*="Board"]',
        'td', 'tr', 'table',
    ]
    for sel in selectors:
        count = await page.locator(sel).count()
        if count:
            print(f"  '{sel}' => {count}")

    await browser.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    async with async_playwright() as pw:
        await inspect_number_waffle(pw)
        await inspect_tilerdle(pw)
        await inspect_number_waffle_deep(pw)

    print("\n\nDone. Screenshots saved to:", SCREENSHOTS_DIR)


if __name__ == "__main__":
    asyncio.run(main())
