# solver.py
"""
Collects candidate groups from the wordplay detectors, removes any
that contradict earlier feedback, and ranks the rest.
"""

from connections_solver.candidate import Candidate
from connections_solver.constants import GROUP_SIZE
from connections_solver.wordplay import find_wordplay_groups

def rank_candidates(puzzle, candidates):
    """
    Merges duplicate groups, drops any that can't be right given the
    feedback so far, and sorts the rest by confidence.

    Args:
        puzzle (ConnectionsPuzzle): Current game state.
        candidates (list[Candidate]): Proposed groups.

    Returns:
        list[Candidate]: Possible groups, most confident first.
    """
    # The last four words must be a group
    if len(puzzle.remaining) == GROUP_SIZE:
        group = frozenset(puzzle.remaining)
        theme = next((c.theme for c in candidates if c.words == group), "Last group")
        return [Candidate(group, theme, 1.0, "elimination")]

    merged = {}
    for cand in candidates:
        current = merged.get(cand.words)
        if current is None or cand.score > current.score:
            merged[cand.words] = cand

    possible = [
        c for c in merged.values()
        if puzzle.is_possible_group(c.words) and puzzle.find_partition(c.words) is not None
    ]
    return sorted(possible, key=lambda c: c.score, reverse=True)


def suggest_groups(puzzle):
    """
    Returns ranked suggestions for the next guess.

    Returns:
        list[Candidate]: Possible groups, most confident first.
    """
    return rank_candidates(puzzle, find_wordplay_groups(puzzle.remaining))
