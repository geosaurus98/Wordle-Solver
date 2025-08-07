# filtering.py
"""
Filters candidate words based on a guess and feedback.
"""

from wordle_solver.constants import WORD_LENGTH
from wordle_solver.helpers import normalize_feedback

def filter_words_for_word(words, guess, feedback):
    feedback = normalize_feedback(feedback)
    new_words = []

    for word in words:
        match = True
        used = [False] * WORD_LENGTH

        # 1) Greens: lock positions
        for i in range(WORD_LENGTH):
            if feedback[i] == 'g':
                if word[i] != guess[i]:
                    match = False
                    break
                used[i] = True
        if not match:
            continue

        # 2) Yellows: explicitly ban the letter in that spot
        for i in range(WORD_LENGTH):
            if feedback[i] == 'y':
                if word[i] == guess[i]:   # <--- key line
                    match = False
                    break
        if not match:
            continue

        # 3) Yellows: ensure the letter exists elsewhere (respecting used slots)
        for i in range(WORD_LENGTH):
            if feedback[i] == 'y':
                found = False
                for j in range(WORD_LENGTH):
                    if j != i and not used[j] and word[j] == guess[i]:
                        used[j] = True
                        found = True
                        break
                if not found:
                    match = False
                    break
        if not match:
            continue

        # 4) Correct per-letter count constraints
        for ch in set(guess):
            idxs = [i for i in range(WORD_LENGTH) if guess[i] == ch]
            colored = sum(feedback[i] in ('g', 'y') for i in idxs)
            blacks  = sum(feedback[i] == 'b' for i in idxs)

            if colored == 0:
                # All occurrences of ch in this guess were black -> ch absent
                if ch in word:
                    match = False
                    break
            elif blacks > 0:
                # Mix of colored and black in this guess -> exact count == colored
                if word.count(ch) != colored:
                    match = False
                    break
            else:
                # Only colored (no blacks) -> lower bound only
                if word.count(ch) < colored:
                    match = False
                    break

        if not match:
            continue

        new_words.append(word)


    return new_words
