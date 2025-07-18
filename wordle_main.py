# wordle_main.py
"""
Main entry point for the Wordle Solver program.
Prompts user to choose a mode and executes the solver.
"""

from loader import load_word_list
from interface import get_opener_guesses, select_game_mode
from modes.multi_solver import play_multi_solver
from modes.sequence_solver import play_sequence_solver
from test_suite import test_solver_on_all_words

def get_number_of_words():
    """Prompt the user for how many words to solve and validate input."""
    while True:
        try:
            num_words = int(input("\U0001f522 How many words to solve? ").strip())
            if num_words < 1:
                raise ValueError
            return num_words
        except ValueError:
            print("\u274c Please enter a valid number.")

def handle_test_mode(opener_guesses, word_list):
    """Run the test suite and skip interactive gameplay."""
    test_solver_on_all_words(opener_guesses, word_list)

def play_selected_mode(mode, num_words, opener_guesses, word_list):
    """Run the game loop for the selected mode."""
    solver_function = play_multi_solver if mode == '1' else play_sequence_solver
    while solver_function(num_words, opener_guesses, word_list):
        pass  # Replay until user exits

def choose_and_play_mode():
    """Handles game mode selection and dispatch."""
    word_list = load_word_list()

    while True:
        mode = select_game_mode()
        opener_guesses = get_opener_guesses()

        if mode == '3':
            handle_test_mode(opener_guesses, word_list)
            continue

        num_words = get_number_of_words()
        play_selected_mode(mode, num_words, opener_guesses, word_list)

def main():
    """Main interactive loop to replay or exit."""
    while True:
        choose_and_play_mode()
        again = input("\n🔁 Would you like to choose a new game mode? (y/n): ").strip().lower()
        if again != 'y':
            print("\n👋 Thanks for playing Word Solver!")
            break

# === RUN MAIN ===
if __name__ == "__main__":
    main()