# constants.py
"""
Constants for the Connections Solver.
"""

GROUP_SIZE = 4      # Words in each group
NUM_GROUPS = 4      # Groups in each puzzle
BOARD_SIZE = GROUP_SIZE * NUM_GROUPS  # 16 words on the board
MAX_MISTAKES = 4    # Wrong guesses allowed before the game ends

# Feedback codes the user types after each guess
CORRECT = 'correct'
ONE_AWAY = 'one_away'
WRONG = 'wrong'
FEEDBACK_MAP = {
    'c': CORRECT,
    'y': CORRECT,   # Alias for correct ("yes")
    'o': ONE_AWAY,
    '1': ONE_AWAY,  # Alias for one away
    'w': WRONG,
    'n': WRONG,     # Alias for wrong ("no")
    'x': WRONG,     # Alias for wrong
}

# Claude API settings used for semantic suggestions
CLAUDE_MODEL = "claude-opus-5-5"
CLAUDE_EFFORT = "high"
MAX_SUGGESTIONS = 3  # Suggestions shown per turn
