# Sedecordle bot (16-board Wordle solver)

This project automates the daily game at `https://www.sedecordle.com/?mode=daily` using Playwright and a simple multi-board constraint solver.

## Setup

```powershell
cd p:\DATA\GJ\UNI\Wordle
py -m pip install -r .\requirements.txt
py -m playwright install
```

## Run

Extract all word lists
py -m sedecordle_bot.extract_word_lists
py -m sedecordle_bot.extract_nyt_word_lists

Run Wordle, Octordle and sedecordle
py -m sedecordle_bot.bot --headful
py -m sedecordle_bot.savior_bot --headful
py -m sedecordle_bot.nyt_wordle_bot --headful
py -m sedecordle_bot.waffle_bot --headful
py -m sedecordle_bot.octordle_bot --headful

1) Extract the game's word list (saved under `sedecordle_bot\data\`):

```powershell
py -m sedecordle_bot.extract_word_lists
```

2) Run the bot (headful so you can watch it):

```powershell
py -m sedecordle_bot.bot --headful
```

Savior mode (first 4 guesses pre-filled):

```powershell
py -m sedecordle_bot.savior_bot --headful
```

If you want the progress to be saved across runs (cookies/localStorage), run with a persistent profile dir:

```powershell
py -m sedecordle_bot.bot --headful --user-data-dir .\sedecordle_profile
```

## NYT Wordle (single board)

Extract NYT Wordle word lists:

```powershell
py -m sedecordle_bot.extract_nyt_word_lists
```

Run the NYT Wordle bot:

```powershell
py -m sedecordle_bot.nyt_wordle_bot --headful
```

Persist NYT state (optional):

```powershell
py -m sedecordle_bot.nyt_wordle_bot --headful --user-data-dir .\nyt_wordle_profile
```

## Waffle (5x5, 21 tiles)

Run the Waffle daily bot:

```powershell
py -m sedecordle_bot.waffle_bot --headful
```

Dry-run (just read tiles + solve internally):

```powershell
py -m sedecordle_bot.waffle_bot --dry-run
```

## Octordle (8 boards)

Run the Octordle daily bot:

```powershell
py -m sedecordle_bot.octordle_bot --headful
```

Dry-run (just detect boards):

```powershell
py -m sedecordle_bot.octordle_bot --dry-run
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

- The bot reads tile evaluations from the page after each guess and updates constraints for all 16 boards.
- Guess selection is heuristic (information-seeking across unsolved boards + opportunistic solves when a board’s candidate set is small).
