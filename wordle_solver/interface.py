# interface.py
"""
Handles user input for game mode and opener configuration.
"""

from wordle_solver.constants import WORD_LENGTH

# === GLOBAL OPENER CONFIGURATION ===
DEFAULT_OPENERS = [
    ["arose"],                 # Option 1
    ["arose", "linty"],        # Option 2
    ["arose", "linty", "chump"]  # Option 3
]

def get_opener_guesses():
    """
    Prompts user to select or enter opener guesses.

    Returns:
        list[str]: List of opener guesses.
    """

    while True:
        try:
            # Display options for preset or custom opener sequences
            print("\n🧩 How many opening suggestions?")
            for idx, openers in enumerate(DEFAULT_OPENERS, 1):
                print(f"{idx} - {' + '.join(w.upper() for w in openers)}")
            print("4 - Rescue Mode (manually enter your own openers)")

            openers_num = int(input("Enter 1, 2, 3, or 4: ").strip())
            if openers_num < 1:
                raise ValueError

            if 1 <= openers_num <= len(DEFAULT_OPENERS):
                opener_guesses = list(DEFAULT_OPENERS[openers_num - 1])  # copy


            # Rescue Mode allows user-defined opener words
            elif openers_num == 4:
                opener_guesses = []
                print("🔧 Rescue Mode: Enter your custom opener words below.")
                while True:
                    word = input(
                        f"Enter custom opener #{len(opener_guesses)+1} (or press enter to finish): "
                    ).strip().lower()

                    if word == "":
                        break  # End input on empty string
                    elif word == 'exit':
                        print("Exiting Rescue Mode.")
                        return  # Exit function entirely
                    elif word in opener_guesses:
                        print("⚠️ Word already added.")
                    elif len(word) != WORD_LENGTH or not word.isalpha():
                        print(f"❌ Must be a valid {WORD_LENGTH}-letter word.")
                    else:
                        opener_guesses.append(word)

                # Ensure at least one opener is provided
                if not opener_guesses:
                    print("❌ You must enter at least one custom opener.")
                    continue

            break  # Valid option selected, exit loop

        except ValueError:
            print("❌ Please enter a valid positive integer.")
    
    return opener_guesses


def select_game_mode():
    """
    Prompts user to select a game mode.

    Returns:
        str: Selected game mode (as string '1', '2', or '3').
    """

    # Game mode options
    print("🧩 Welcome to Word Solver!")
    print("Choose a game mode to start:")
    print("1 - Multi-Word Solver (Parallel solving)")
    print("2 - Sequence Solver (One word at a time)")
    print("3 - Test Solver on All Words")
    print("4 - Exit\n")

    while True:
        mode = input("Enter 1, 2, 3, or 4: ").strip()

        # Validate input
        if mode not in ['1', '2', '3', '4']:
            print("❌ Invalid choice. Please enter 1, 2, 3, or 4.\n")
            continue

        if mode == '4':
            print("\n👋 Thanks for playing Word Solver!")
            exit()

        break  # Valid mode selected

    return mode
