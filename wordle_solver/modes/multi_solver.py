# multi_solver.py
"""
Multi-word (parallel) solver mode implementation.
Each word is guessed simultaneously with shared guess history.
"""

from wordle_solver.constants import WORD_LENGTH, WIN_FEEDBACK
from wordle_solver.filtering import filter_words_for_word
from wordle_solver.helpers import normalize_feedback, get_feedback_input, print_top_suggestions, score_words
from collections import Counter

def play_multi_solver(num_words, opener_guesses, full_word_list):
    """
    Runs the multi-word solver mode.

    Args:
        num_words (int): Number of words to solve.
        opener_guesses (list[str]): Starting guesses.
        full_word_list (list[str]): All valid Wordle words.
    """

    # === INITIALIZE GAME STATE ===
    word_slots = [
        {
            "label": f"Word {i+1}",
            "candidate_words": full_word_list.copy(),
            "solved": False
        }
        for i in range(num_words)
    ]
    past_guesses = []
    feedback_log = {word_state["label"]: {} for word_state in word_slots}
    guess_count = 0

    # === MAIN GAME LOOP ===
    while True:

        # === SOLVE USING PREVIOUS FEEDBACK ===
        for word_state in word_slots:
            if word_state["solved"]:
                continue

            for prev_guess in past_guesses:
                if word_state["solved"]:
                    break
                feedback = feedback_log[word_state["label"]].get(prev_guess)
                if not feedback:
                    continue

                # Filter possible words based on past feedback
                word_state["candidate_words"] = filter_words_for_word(word_state["candidate_words"], prev_guess, feedback)

                # Check if the word is solved
                if normalize_feedback(feedback) == WIN_FEEDBACK or len(word_state["candidate_words"]) == 1:
                    solved_word = word_state["candidate_words"][0] if len(word_state["candidate_words"]) == 1 else prev_guess
                    print(f"✅ {word_state['label']} solved early from previous feedback!")
                    print(f"🟢 The word is: {solved_word.upper()}")
                    word_state["solved"] = True

                    # Add solved word to guess list for reuse
                    if solved_word not in past_guesses and solved_word not in opener_guesses:
                        opener_guesses.append(solved_word)
                    break

        # === WIN CONDITION CHECK ===
        if all(word_state["solved"] for word_state in word_slots):
            print(f"\n🎉 All {num_words} words solved in {guess_count} guesses!")
            break

        # === SELECT NEXT GUESS ===
        use_openers = guess_count < len(opener_guesses)

        if use_openers:
            # Use predefined opener
            guess = opener_guesses[guess_count]
        else:
            # Decide best guess based on remaining candidate words
            unsolved = [ws for ws in word_slots if not ws["solved"]]
            one_left = [ws for ws in unsolved if len(ws["candidate_words"]) == 1]

            if one_left:
                # Guess the known solution
                guess = one_left[0]["candidate_words"][0]
            else:
                few_left = [ws for ws in unsolved if len(ws["candidate_words"]) <= 3]

                if few_left:
                    # Score guesses from a nearly solved word
                    scored = [
                        (word, score)
                        for word, score in score_words(few_left[0]["candidate_words"])
                        if word not in past_guesses
                    ]
                elif len(unsolved) == 1:
                    # Score guesses from the only unsolved word
                    scored = [
                        (word, score)
                        for word, score in score_words(unsolved[0]["candidate_words"])
                        if word not in past_guesses
                    ]
                else:
                    # Score all words by letter frequency across remaining candidates
                    scored = sorted(
                        [
                            (w, sum(Counter("".join(ws["candidate_words"]))[c] for c in set(w)))
                            for w in full_word_list if w not in past_guesses
                        ],
                        key=lambda x: x[1],
                        reverse=True
                    )

                if not scored:
                    print("⚠️ No guesses available.")
                    return False

                guess = scored[0][0]

        # Record guess and display
        past_guesses.append(guess)
        print(f"\n🔍 Suggested guess #{guess_count + 1}: {guess.upper()}")

        # === GATHER FEEDBACK FOR EACH UNSOLVED WORD ===
        for word_state in word_slots:
            if word_state["solved"]:
                continue

            feedback = get_feedback_input(word_state["label"], guess)
            if feedback is None:
                return  # Exit on invalid input

            feedback_log[word_state["label"]][guess] = feedback

            # Check for win condition
            if normalize_feedback(feedback) == WIN_FEEDBACK:
                print(f"✅ {word_state['label']} has been solved!")
                word_state["solved"] = True
            else:
                # Filter candidate words using feedback
                word_state["candidate_words"] = filter_words_for_word(word_state["candidate_words"], guess, feedback)

        # === LOSS CHECK: No valid candidates left ===
        for word_state in word_slots:
            if not word_state["solved"] and not word_state["candidate_words"]:
                print(f"❌ No words candidate_words for {word_state['label']}.")
                return False

        # === DISPLAY REMAINING OPTIONS ===
        for word_state in word_slots:
            if not word_state["solved"]:
                print(f"{len(word_state['candidate_words'])} words left for {word_state['label']}.")

        # === SHOW TOP SUGGESTIONS ===
        if guess_count >= 2 and any(not ws["solved"] for ws in word_slots):
            print("🤖 Top suggestions per unsolved word:")
            for word_state in word_slots:
                if not word_state["solved"]:
                    print_top_suggestions(word_state["label"], word_state["candidate_words"])
            print("-" * 40)

        guess_count += 1
