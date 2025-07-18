# sequence_solver.py
"""
Sequential solver mode implementation.
Solves one word at a time using shared guess feedback.
"""

from wordle_solver.constants import WORD_LENGTH, WIN_FEEDBACK
from wordle_solver.filtering import filter_words_for_word 
from wordle_solver.helpers import normalize_feedback, get_top_scored_words, print_top_suggestions
from collections import Counter

def play_sequence_solver(num_words, opener_guesses, full_word_list):
    """
    Runs the sequential solver mode.

    Args:
        num_words (int): Number of words to solve.
        opener_guesses (list[str]): List of opener guesses.
        full_word_list (list[str]): Valid Wordle words.
    """
    
    # Initialize word slots with metadata for each word
    word_slots = [{"label": f"Word {i+1}", "candidate_words": full_word_list.copy(), "solved": False} for i in range(num_words)]

    past_guesses = []       # Stores all past guesses made
    guess_count = 0         # Total number of guesses
    current_index = 0       # Index of current word being solved

    # Introductory message
    print(f"\n🧠 Welcome to Sequential {num_words}-Word Solver!")
    print("You must solve each word before moving to the next.")
    print("Feedback guide: g = green, y = yellow, x/n/e = gray.")
    print("Type 'exit' anytime to quit.\n")

    while current_index < num_words:
        word_state = word_slots[current_index]

        # If there are previous guesses, apply feedback for them
        if guess_count > 0:
            print(f"\n📝 Enter feedback for all previous guesses on {word_state['label']}:")
            for prev_guess in past_guesses:
                if word_state["solved"]:
                    break
                feedback = input(f"Feedback for {prev_guess.upper()} on {word_state['label']}: ").strip().lower()
                if feedback == 'exit':
                    return False
                if len(feedback) != WORD_LENGTH:
                    print("❌ Invalid feedback.")
                    return False

                # Filter possible candidates based on feedback
                word_state["candidate_words"] = filter_words_for_word(word_state["candidate_words"], prev_guess, feedback)

                # Check if word is solved from feedback
                if normalize_feedback(feedback) == WIN_FEEDBACK or len(word_state["candidate_words"]) == 1:
                    solved_word = word_state["candidate_words"][0]
                    print(f"✅ {word_state['label']} solved early from previous feedback!")
                    print(f"🟢 The word is: {solved_word.upper()}")
                    if solved_word not in past_guesses:
                        past_guesses.append(solved_word)
                    word_state["solved"] = True
                    guess_count += 1
                    break

        # Skip to next word if current one is already solved
        if word_state["solved"]:
            current_index += 1
            continue

        # Main guessing loop for current word
        while not word_state["solved"]:
            # Count how many openers have been used for this word
            local_guess_count = sum(1 for g in past_guesses if g in opener_guesses)

            # Use opener guess if any left, else use scored word
            use_openers = local_guess_count < len(opener_guesses)
            if use_openers:
                guess = opener_guesses[local_guess_count]
            else:
                # If only one candidate left, use it
                if len(word_state["candidate_words"]) == 1:
                    guess = word_state["candidate_words"][0]
                else:
                    guess = get_top_scored_words(word_state["candidate_words"], past_guesses)
                    if not guess:
                        print("⚠️ No guesses available.")
                        return False

            past_guesses.append(guess)
            print(f"\n🔍 Suggested guess #{guess_count + 1}: {guess.upper()}")
            guess_count += 1

            # Prompt for feedback
            feedback = input(f"Enter feedback for {word_state['label']} (e.g. gxgxn): ").strip().lower()
            if feedback == 'exit':
                return False
            if len(feedback) != WORD_LENGTH:
                print("❌ Invalid feedback.")
                return False

            # Filter candidates based on feedback
            word_state["candidate_words"] = filter_words_for_word(word_state["candidate_words"], guess, feedback)

            # Check if solved
            if normalize_feedback(feedback) == WIN_FEEDBACK or len(word_state["candidate_words"]) == 1:
                solved_word = word_state["candidate_words"][0] if len(word_state["candidate_words"]) == 1 else guess
                print(f"🟢 The word is: {solved_word.upper()}")
                print(f"✅ {word_state['label']} has been solved!")
                if solved_word not in past_guesses:
                    past_guesses.append(solved_word)
                word_state["solved"] = True
                guess_count += 1
                current_index += 1
                break
            else:
                # If word is not yet solved, show progress
                if not word_state["candidate_words"]:
                    print(f"❌ No words candidate_words for {word_state['label']}.")
                    return False
                print(f"{len(word_state['candidate_words'])} words left for {word_state['label']}.")
                if guess_count >= 2:
                    print_top_suggestions(word_state["label"], word_state["candidate_words"])
                    print("-" * 40)

    # All words solved
    print(f"\n🎉 All {num_words} words solved in {guess_count} guesses total!")
