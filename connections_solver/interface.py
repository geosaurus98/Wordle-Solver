# interface.py
"""
Interactive Connections solver: enter the board, get suggestions,
report what the game said, repeat.
"""

from connections_solver.claude_helper import is_available
from connections_solver.constants import (
    BOARD_SIZE, GROUP_SIZE, MAX_MISTAKES, MAX_SUGGESTIONS, FEEDBACK_MAP, CORRECT, ONE_AWAY
)
from connections_solver.puzzle import ConnectionsPuzzle, parse_words
from connections_solver.solver import suggest_groups


def read_board():
    """
    Prompts for the 16 words until a valid board is entered.

    Returns:
        ConnectionsPuzzle | None: New puzzle, or None if the user exits.
    """
    print(f"\n📋 Enter the {BOARD_SIZE} words on the board.")
    print("Separate with spaces, or with commas if any entry has a space (e.g. ICE CREAM).")
    while True:
        text = input("Words: ").strip()
        if text.lower() == 'exit':
            return None
        words = parse_words(text)
        if len(words) != BOARD_SIZE:
            print(f"❌ Got {len(words)} words; need exactly {BOARD_SIZE}.")
            continue
        try:
            return ConnectionsPuzzle(words)
        except ValueError as e:
            print(f"❌ {e}")


def print_board(puzzle):
    """Shows solved groups, remaining words and mistakes left."""
    print()
    for i, (group, theme) in enumerate(puzzle.solved, 1):
        print(f"✅ Group {i}: {', '.join(sorted(group))}" + (f" — {theme}" if theme else ""))
    remaining = puzzle.remaining
    for row in range(0, len(remaining), GROUP_SIZE):
        print("   " + " | ".join(remaining[row:row + GROUP_SIZE]))
    print(f"❤️  Mistakes left: {MAX_MISTAKES - puzzle.mistakes}")


def print_suggestions(suggestions):
    """Lists the top suggestions, numbered for quick selection."""
    if not suggestions:
        print("🤔 No confident groups found. Enter your own guess.")
        return
    print("\n💡 Suggestions:")
    for i, cand in enumerate(suggestions[:MAX_SUGGESTIONS], 1):
        print(f"{i} - {cand.label()}  [{cand.theme}] ({cand.score:.0%}, {cand.source})")


def read_guess(puzzle, suggestions):
    """
    Prompts for the next guess: a suggestion number or four words.

    Returns:
        tuple[frozenset, str] | None: The guessed group and its theme
        (if known), or None if the user exits.
    """
    shown = suggestions[:MAX_SUGGESTIONS]
    while True:
        text = input("\nEnter a suggestion number or your own 4 words (or 'exit'): ").strip()
        if text.lower() == 'exit':
            return None
        if text.isdigit() and 1 <= int(text) <= len(shown):
            chosen = shown[int(text) - 1]
            return chosen.words, chosen.theme

        group = frozenset(parse_words(text))
        try:
            puzzle.validate_group(group)
        except ValueError as e:
            print(f"❌ {e}")
            continue
        if any(group == past for past, _ in puzzle.history):
            print("⚠️ You already tried that group.")
            continue
        theme = next((c.theme for c in suggestions if c.words == group), "")
        return group, theme


def read_feedback():
    """
    Prompts for the game's response to a guess.

    Returns:
        str | None: CORRECT, ONE_AWAY or WRONG, or None if the user exits.
    """
    while True:
        text = input("Result? c = correct, o = one away, w = wrong: ").strip().lower()
        if text == 'exit':
            return None
        if text in FEEDBACK_MAP:
            return FEEDBACK_MAP[text]
        print("❌ Please enter c, o or w.")


def play_connections(use_claude=True):
    """
    Runs one game of the interactive solver.

    Returns:
        bool: True to play again, False to stop.
    """
    print("\n🔗 Welcome to the Connections Solver!")
    if use_claude and not is_available():
        print("ℹ️ The 'anthropic' package isn't installed; using offline wordplay hints only.")
        use_claude = False
    print("Type 'exit' anytime to quit.")

    puzzle = read_board()
    if puzzle is None:
        return False

    while not puzzle.is_won and not puzzle.is_lost:
        print_board(puzzle)
        if use_claude:
            print("\n⏳ Asking Claude...")
        suggestions, warning = suggest_groups(puzzle, use_claude=use_claude)
        if warning:
            print(f"⚠️ {warning} Using offline wordplay hints only.")
            use_claude = False
        print_suggestions(suggestions)

        guess = read_guess(puzzle, suggestions)
        if guess is None:
            return False
        group, theme = guess

        # Final group needs no confirmation
        feedback = CORRECT if len(puzzle.remaining) == GROUP_SIZE else read_feedback()
        if feedback is None:
            return False
        puzzle.record_guess(group, feedback, theme)

        if feedback == ONE_AWAY:
            print("😬 One away! Three of those words belong together.")

    print_board(puzzle)
    if puzzle.is_won:
        print(f"\n🎉 Solved with {puzzle.mistakes} mistake(s)!")
    else:
        print("\n💀 Out of mistakes. Better luck tomorrow!")

    again = input("\n🔁 Solve another puzzle? (y/n): ").strip().lower()
    return again == 'y'
