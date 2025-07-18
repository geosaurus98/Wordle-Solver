# test_suite.py
"""
Test mode for benchmarking the solver's performance on all words.
"""

from constants import WORD_LENGTH, WIN_FEEDBACK
from filtering import filter_words_for_word
from helpers import normalize_feedback, score_words
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from collections import defaultdict

def simulate_feedback(solution, guess):
    """
    Generates feedback string for a guess against the actual solution.

    Args:
        solution (str): The correct word.
        guess (str): The guessed word.

    Returns:
        str: Feedback string in 'g', 'y', 'b' format.
    """

    feedback = ['b'] * WORD_LENGTH  # Start with all gray
    solution_chars = list(solution)
    guess_chars = list(guess)
    used = [False] * WORD_LENGTH  # Track used positions for yellow logic

    # First pass: green (correct letter and position)
    for i in range(WORD_LENGTH):
        if guess_chars[i] == solution_chars[i]:
            feedback[i] = 'g'
            used[i] = True
            solution_chars[i] = None  # Mark solution letter as used

    # Second pass: yellow (correct letter, wrong position)
    for i in range(WORD_LENGTH):
        if feedback[i] == 'b' and guess_chars[i] in solution_chars:
            idx = solution_chars.index(guess_chars[i])
            if not used[idx]:
                feedback[i] = 'y'
                solution_chars[idx] = None  # Mark letter as used

    return ''.join(feedback)


def test_solver_on_all_words(openers, full_words_list):
    """
    Tests the solver's success rate using a given opener set across all words.

    Args:
        openers (list[str]): List of initial guesses to use before switching to scoring.
        full_words_list (list[str]): Full dictionary of target words.
    """

    successes = 0  # Number of words solved
    max_guesses_allowed = 6  # Max guesses per word (like Wordle rules)
    total_words = len(full_words_list)
    guess_counts = []  # Track number of guesses per word
    solved_words = []

    for solution in full_words_list:
        candidate_words = full_words_list.copy()  # Reset candidates each round
        solved = False
        past_guesses = []
        guess_count = 0

        while guess_count < max_guesses_allowed:
            # Use opener guesses first
            if guess_count < len(openers):
                guess = openers[guess_count]
            else:
                # If only one candidate remains, use it
                if len(candidate_words) == 1:
                    guess = candidate_words[0]
                else:
                    # Score remaining words and choose the best one
                    scored = [
                        (word, score)
                        for word, score in score_words(candidate_words)
                        if word not in past_guesses
                    ]
                    if not scored:
                        break  # No valid guesses left
                    guess = scored[0][0]

            past_guesses.append(guess)
            feedback = simulate_feedback(solution, guess)

            # Check if the word is solved
            if normalize_feedback(feedback) == WIN_FEEDBACK:
                successes += 1
                guess_counts.append(guess_count + 1)
                solved_words.append(solution)
                solved = True
                break
            else:
                # Filter remaining candidates based on feedback
                candidate_words = filter_words_for_word(candidate_words, guess, feedback)
                guess_count += 1

        if not solved:
            guess_counts.append(None)  # Word was not solved

    # Print test results
    print(f"\n📊 Test Summary for Openers: {openers}")
    print(f"✅ Solved: {successes}/{total_words}")
    if guess_counts:
        solved_counts = [g for g in guess_counts if g is not None]
        print(f"📈 Avg Guesses for Solved: {sum(solved_counts) / len(solved_counts):.2f}")
    generate_position_heatmap(solved_words)

def generate_position_heatmap(solved_words):
    """
    Plots a heatmap showing frequency of each letter at each position.

    Args:
        solved_words (list[str]): List of successfully solved words.
    """
    position_counts = [defaultdict(int) for _ in range(5)]

    # Count letter occurrences at each position
    for word in solved_words:
        for i, char in enumerate(word):
            position_counts[i][char] += 1

    # Get sorted alphabet and build a matrix
    alphabet = sorted(set(char for pos in position_counts for char in pos))
    heat_matrix = np.array([
        [position_counts[pos].get(char, 0) for pos in range(5)]
        for char in alphabet
    ])

    # Normalize to frequencies
    heat_matrix = heat_matrix / heat_matrix.sum(axis=0, keepdims=True)

    # Plot heatmap
    plt.figure(figsize=(10, 8))
    sns.heatmap(heat_matrix, annot=True, cmap='YlGnBu', xticklabels=[f'Pos {i+1}' for i in range(5)], yticklabels=alphabet)
    plt.title("📈 Letter Frequency Heatmap by Position (Solved Words Only)")
    plt.xlabel("Letter Position")
    plt.ylabel("Letter")
    plt.tight_layout()
    plt.show()
