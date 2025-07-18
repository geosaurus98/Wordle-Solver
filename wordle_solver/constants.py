# constants.py
"""
Constants for the Wordle Solver project.
"""

WORD_LENGTH = 5  # Number of letters in each Wordle word
WIN_FEEDBACK = 'g' * WORD_LENGTH  # The feedback string representing a win (all greens)
WORD_LIST_PATH = "wordle_words.csv"  # Default path to the word list CSV
FEEDBACK_OPTIONS = ['g', 'y', 'b']  # Valid feedback characters: green, yellow, black
FEEDBACK_MAP = {
    'g': 'green',
    'y': 'yellow',
    'b': 'black',
    'x': 'black',  # Alias for black
    'n': 'black',  # Alias for black
    'e': 'black'   # Alias for black
}  # Mapping of feedback characters to their meanings