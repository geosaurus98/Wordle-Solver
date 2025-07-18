# scoring.py
"""
Implements scoring logic for Wordle guesses.
"""

from collections import Counter

def score_words(words):
    """
    Scores words based on letter frequency across all candidate words.

    Args:
        words (list[str]): List of candidate words.

    Returns:
        list[tuple[str, int]]: Sorted list of (word, score) tuples in descending score order.
    """

    # Count frequency of each letter across all candidate words
    freq = Counter("".join(words))
    scores = {}

    for word in words:
        # Score is the sum of frequencies of each unique letter in the word
        scores[word] = sum(freq[c] for c in set(word))

    # Sort words by score, highest first
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def get_top_scored_words(word_list, past_guesses, top_n=1):
    """
    Returns the highest scoring word(s), excluding any that have already been guessed.

    Args:
        word_list (list[str]): List of candidate words.
        past_guesses (list[str]): Words that have already been guessed.
        top_n (int): Number of top-scoring words to return.

    Returns:
        list[str] or str: Top N scored words as a list, or single string if top_n == 1.
    """
        
    # Filter out previously guessed words and score the rest
    scored = [
        (word, score)
        for word, score in score_words(word_list)
        if word not in past_guesses
    ]

    # Return top_n results as list or single word
    return scored[:top_n] if top_n > 1 else (scored[0][0] if scored else None)