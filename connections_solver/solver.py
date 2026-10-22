# solver.py
"""
Combines candidate groups from Claude and the wordplay detectors,
removes any that contradict earlier feedback, and ranks the rest.
"""

from connections_solver.candidate import Candidate
from connections_solver.claude_helper import get_claude_groups, ClaudeUnavailable
from connections_solver.constants import GROUP_SIZE
from connections_solver.wordplay import find_wordplay_groups

AGREEMENT_BONUS = 0.1  # Extra confidence when both sources propose a group


def gather_candidates(puzzle, use_claude=True, client=None):
    """
    Collects candidate groups from every available source.

    Args:
        puzzle (ConnectionsPuzzle): Current game state.
        use_claude (bool): Whether to ask Claude.
        client: Optional Anthropic client (used by tests).

    Returns:
        tuple[list[Candidate], str | None]: Candidates, and a warning
        message if Claude was requested but could not be used.
    """
    candidates = find_wordplay_groups(puzzle.remaining)
    warning = None
    if use_claude:
        try:
            candidates = get_claude_groups(puzzle, client=client) + candidates
        except ClaudeUnavailable as e:
            warning = str(e)
    return candidates, warning


def rank_candidates(puzzle, candidates):
    """
    Merges duplicate groups, drops any that can't be right given the
    feedback so far, and sorts the rest by confidence.

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
        if current is None:
            merged[cand.words] = cand
        elif current.source != cand.source:
            # Two independent sources agree: keep the better theme, add a bonus
            best = max(current, cand, key=lambda c: c.score)
            score = min(1.0, best.score + AGREEMENT_BONUS)
            merged[cand.words] = Candidate(best.words, best.theme, score, best.source)
        elif cand.score > current.score:
            merged[cand.words] = cand

    possible = [
        c for c in merged.values()
        if puzzle.is_possible_group(c.words) and puzzle.find_partition(c.words) is not None
    ]
    return sorted(possible, key=lambda c: c.score, reverse=True)


def suggest_groups(puzzle, use_claude=True, client=None):
    """
    Returns ranked suggestions for the next guess.

    Returns:
        tuple[list[Candidate], str | None]: Ranked suggestions and any warning.
    """
    candidates, warning = gather_candidates(puzzle, use_claude, client)
    return rank_candidates(puzzle, candidates), warning
