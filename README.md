# Wordle Bots

Playwright-driven solvers for several daily Wordle variants: Sedecordle (16 boards), NYT Wordle (1 board), Octordle (8 boards), and Waffle.

## Setup

```powershell
py -m pip install -r requirements.txt
py -m playwright install chromium
```

## Sedecordle (16 boards)

Extract the word list (saved under `sedecordle_bot\data\`):

```powershell
py -m sedecordle_bot.extract_word_lists
```

Run the bot (opens `AROSE` → `UNTIL`, then adaptive):

```powershell
py -m sedecordle_bot.bot --headful
```

Sedec-order mode (same bot, different URL):

```powershell
py -m sedecordle_bot.bot --headful --url https://www.sedecordle.com/sedec-order
```

Savior mode (first 4 guesses pre-filled by the site — bot takes over from there):

```powershell
py -m sedecordle_bot.savior_bot --headful
```

Persist state across runs (cookies/localStorage):

```powershell
py -m sedecordle_bot.bot --headful --user-data-dir .\sedecordle_profile
```

## NYT Wordle (1 board)

Run the bot — word lists are fetched automatically on first run and refreshed daily:

```powershell
py -m sedecordle_bot.nyt_wordle_bot --headful
```

To refresh word lists manually:

```powershell
py -m sedecordle_bot.extract_nyt_word_lists
```

Persist NYT state across runs (optional):

```powershell
py -m sedecordle_bot.nyt_wordle_bot --headful --user-data-dir .\nyt_wordle_profile
```

## Octordle (8 boards)

```powershell
py -m sedecordle_bot.octordle_bot --headful
```

Dry-run (detect boards only, no guesses):

```powershell
py -m sedecordle_bot.octordle_bot --dry-run
```

## Waffle (5×5, 21 tiles)

```powershell
py -m sedecordle_bot.waffle_bot --headful
```

Dry-run (read tiles and solve internally, no interaction):

```powershell
py -m sedecordle_bot.waffle_bot --dry-run
```

## NYT Sudoku (easy / medium / hard)

Run the NYT Sudoku bot:

```powershell
py -m sedecordle_bot.nyt_sudoku_bot --headful --difficulty easy
```

Other difficulties:

```powershell
py -m sedecordle_bot.nyt_sudoku_bot --headful --difficulty medium
py -m sedecordle_bot.nyt_sudoku_bot --headful --difficulty hard
```

Dry-run (read board + solve locally, do not type into page):

```powershell
py -m sedecordle_bot.nyt_sudoku_bot --difficulty hard --dry-run
```

Persistent browser profile (optional):

```powershell
py -m sedecordle_bot.nyt_sudoku_bot --headful --difficulty medium --user-data-dir .\nyt_sudoku_profile
```

## Notes

- Tile evaluations are read from the page DOM after each guess and used to update per-board constraints.
- Guess selection is heuristic: maximises information across unsolved boards, switching to direct solves when a board's candidate set is small.
- The sedecordle and NYT bots play two fixed openers (`AROSE`, `UNTIL`) before switching to adaptive. Override with `--first-guess WORD1,WORD2`.
- Savior mode skips openers — the site pre-fills the first 4 guesses, so the bot bootstraps from those and plays adaptively from turn 5.
