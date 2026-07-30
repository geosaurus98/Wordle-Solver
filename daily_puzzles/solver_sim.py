from __future__ import annotations

from .game_result import BoardResult, GuessStep
from .solver import (
    choose_best_guess_single_board,
    filter_candidates,
    is_solved_feedback,
    score_guess,
)


def simulate_single_board(
    answer: str,
    allowed: list[str],
    answers_list: list[str],
    max_turns: int = 6,
    opening_guesses: tuple[str, ...] | list[str] = ("arose", "linty", "chump"),
    board_index: int = 0,
) -> BoardResult:
    """
    Simulate the optimal solver against a known answer without using a browser.
    Returns the complete guess path as a BoardResult.
    """
    candidates = list(answers_list)
    guessed: set[str] = set()
    guesses: list[GuessStep] = []

    for _turn in range(max_turns):
        before = len(candidates)

        # Play opening guesses in order before switching to the adaptive solver.
        opening_guess = None
        for og in opening_guesses:
            if og in guessed:
                continue        # already played
            if og in allowed:
                opening_guess = og
            break               # stop at first unplayed (playable or not)

        if opening_guess:
            guess = opening_guess
        else:
            guess = choose_best_guess_single_board(allowed, candidates, guessed=guessed)

        if guess in guessed:
            remaining = [w for w in allowed if w not in guessed]
            guess = remaining[0] if remaining else allowed[0]

        feedback = list(score_guess(guess, answer))
        guessed.add(guess)
        filtered = filter_candidates(candidates, guess, feedback)
        if filtered:
            candidates = filtered

        guesses.append(GuessStep(
            word=guess,
            feedback=feedback,
            candidates_before=before,
            candidates_after=len(candidates),
        ))

        if is_solved_feedback(feedback):
            return BoardResult(
                board_index=board_index,
                answer=answer,
                guesses=guesses,
                solved=True,
            )

    return BoardResult(
        board_index=board_index,
        answer=answer,
        guesses=guesses,
        solved=False,
    )
