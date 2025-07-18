# filtering.py
"""
Filters candidate words based on a guess and feedback.
"""

from constants import WORD_LENGTH
from helpers import normalize_feedback

def filter_words_for_word(words, guess, feedback):
    """
    Filters a list of words to those matching the given feedback for a guess.

    Args:
        words (list[str]): Candidate words.
        guess (str): The guessed word.
        feedback (str): Feedback in 'g', 'y', 'b' format.

    Returns:
        list[str]: Filtered list of valid words.
    """

    feedback = normalize_feedback(feedback)  # Standardize feedback to 'g', 'y', 'b'
    new_words = []

    for word in words:
        match = True
        used = [False] * WORD_LENGTH  # Tracks matched letters in the candidate word

        # First pass: handle green matches
        for i in range(WORD_LENGTH):
            if feedback[i] == 'g':  # Green: correct letter in correct position
                if word[i] != guess[i]:
                    match = False
                    break
                used[i] = True  # Mark this position as used

        if not match:
            continue  # Skip to next candidate word

        # Second pass: handle yellow matches
        for i in range(WORD_LENGTH):
            if feedback[i] == 'y':  # Yellow: correct letter in wrong position
                found = False
                for j in range(WORD_LENGTH):
                    if not used[j] and word[j] == guess[i] and j != i:
                        used[j] = True  # Mark as used
                        found = True
                        break
                if not found:
                    match = False
                    break

        if not match:
            continue  # Skip to next candidate word

        # Third pass: handle black/gray letters
        for i in range(WORD_LENGTH):
            if feedback[i] == 'b':  # Black/gray: letter should not be present
                # Count how many times this letter is allowed based on g/y feedback
                allowed = sum(
                    1 for k in range(WORD_LENGTH)
                    if guess[k] == guess[i] and feedback[k] in ('g', 'y')
                )
                if word.count(guess[i]) > allowed:
                    match = False
                    break

        if match:
            new_words.append(word)  # Word passed all checks

    return new_words
