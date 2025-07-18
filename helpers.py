# helpers.py
"""
General utility functions used across the Wordle Solver.
"""

from constants import WORD_LENGTH
from collections import Counter

def normalize_feedback(feedback):
    """
    Converts gray indicators to 'b'.

    Args:
        feedback (str): Raw feedback string using 'g', 'y', and various gray indicators ('x', 'n', 'e').

    Returns:
        str: Normalized feedback using only 'g', 'y', 'b'.
    """
    return ''.join('b' if c in 'xne' else c for c in feedback)


def get_feedback_input(label, guess):
    """
    Prompts the user to input feedback for a given guess.

    Args:
        label (str): Label for the word slot (e.g., "Word 1").
        guess (str): The guessed word (not directly used, but could be shown).

    Returns:
        str | None: Normalized feedback string or None if user exits.
    """
    while True:
        feedback = input(f"Enter feedback for {label} (e.g. gxgxn): ").strip().lower()
        if feedback == 'exit':
            return None
        elif len(feedback) == WORD_LENGTH:
            return feedback
        print(f"\u274c Invalid feedback. Please enter {WORD_LENGTH} characters.")


def get_top_scored_words(word_list, past_guesses, top_n=1):
    """
    Selects the top-scoring word(s) from the candidate list, excluding any already guessed.

    Args:
        word_list (list[str]): List of candidate words.
        past_guesses (list[str]): Words that have already been guessed.
        top_n (int): Number of top words to return.

    Returns:
        list[str] or str: Top N scored words, or the best single word as string if top_n == 1.
    """
    scored = [
        (word, score)
        for word, score in score_words(word_list)
        if word not in past_guesses
    ]
    return scored[:top_n] if top_n > 1 else (scored[0][0] if scored else None)


def print_top_suggestions(label, word_list):
    """
    Prints the top 3 word suggestions for a given word slot.

    Args:
        label (str): Label for the word (e.g., "Word 2").
        word_list (list[str]): List of remaining candidate words.
    """
    from scoring import score_words  # Local import to avoid circular dependency
    top = score_words(word_list)[:3]
    print(f"{label}: " + ", ".join(f"{w} ({s})" for w, s in top))


def score_words(words):
    """
    Scores words based on letter frequency across all candidate words.

    Args:
        words (list[str]): List of candidate words.

    Returns:
        list[tuple[str, int]]: Words sorted by score in descending order.
    """
    freq = Counter("".join(words))  # Frequency of each letter in the candidate list
    scores = {}
    for word in words:
        scores[word] = sum(freq[c] for c in set(word))  # Score = sum of unique letter frequencies
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
