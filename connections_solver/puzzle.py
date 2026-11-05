# puzzle.py
"""
Tracks the state of a Connections puzzle and the constraints that
guess feedback places on the possible groupings.

Feedback rules (from the NYT game):
    * correct  - the four words are a group.
    * one away - some group contains exactly three of the four words.
    * wrong    - no group contains three or more of the four words.
"""

from dataclasses import dataclass, field
from itertools import combinations

from connections_solver.constants import (
    GROUP_SIZE, MAX_MISTAKES, CORRECT, ONE_AWAY, WRONG
)


def normalize_word(word):
    """Uppercase and collapse whitespace so words compare consistently."""
    return " ".join(word.split()).upper()


def parse_words(text):
    """
    Splits a line of user input into words.
    Commas separate words when present (allowing multi-word entries
    such as "ICE CREAM"); otherwise whitespace is used.

    Returns:
        list[str]: Normalized words, empty entries removed.
    """
    parts = text.split(",") if "," in text else text.split()
    return [normalize_word(p) for p in parts if p.strip()]


@dataclass
class ConnectionsPuzzle:
    """State of one Connections game."""

    words: list
    solved: list = field(default_factory=list)   # [(frozenset, theme)]
    history: list = field(default_factory=list)  # [(frozenset, feedback)]

    def __post_init__(self):
        self.words = [normalize_word(w) for w in self.words]
        if len(set(self.words)) != len(self.words):
            raise ValueError("Duplicate words on the board.")

    # === STATE ===
    @property
    def remaining(self):
        """Words not yet placed in a solved group, in board order."""
        placed = set().union(*(group for group, _ in self.solved))
        return [w for w in self.words if w not in placed]

    @property
    def mistakes(self):
        return sum(1 for _, feedback in self.history if feedback != CORRECT)

    @property
    def is_won(self):
        return not self.remaining

    @property
    def is_lost(self):
        return self.mistakes >= MAX_MISTAKES

    # === GUESSES ===
    def record_guess(self, group, feedback, theme=""):
        """
        Records a guess and its feedback.

        Args:
            group (Iterable[str]): The four guessed words.
            feedback (str): CORRECT, ONE_AWAY or WRONG.
            theme (str): Optional theme for a correct group.
        """
        group = frozenset(normalize_word(w) for w in group)
        self.validate_group(group)
        if feedback not in (CORRECT, ONE_AWAY, WRONG):
            raise ValueError(f"Unknown feedback: {feedback}")
        if any(group == past for past, _ in self.history):
            raise ValueError("You already guessed that group.")

        self.history.append((group, feedback))
        if feedback == CORRECT:
            self.solved.append((group, theme))

    def validate_group(self, group):
        """Raises ValueError unless group is four distinct remaining words."""
        if len(group) != GROUP_SIZE:
            raise ValueError(f"A group must have exactly {GROUP_SIZE} different words.")
        unknown = set(group) - set(self.remaining)
        if unknown:
            raise ValueError(f"Not on the board: {', '.join(sorted(unknown))}")

    # === CONSTRAINTS ===
    def is_possible_group(self, group):
        """
        Checks a single group against the feedback so far.
        Partition-level rules (one away) are handled by is_possible_partition.
        """
        group = frozenset(group)
        if len(group) != GROUP_SIZE or not group <= set(self.remaining):
            return False
        for past, feedback in self.history:
            if feedback == CORRECT:
                continue
            overlap = len(group & past)
            if overlap == GROUP_SIZE:
                return False  # Already ruled out
            if feedback == WRONG and overlap >= GROUP_SIZE - 1:
                return False  # Would have been "one away"
        return True

    def is_possible_partition(self, groups):
        """Checks a full split of the remaining words against all feedback."""
        groups = [frozenset(g) for g in groups]
        if not all(self.is_possible_group(g) for g in groups):
            return False
        for past, feedback in self.history:
            if feedback == ONE_AWAY and not any(len(g & past) == GROUP_SIZE - 1 for g in groups):
                return False
        return True

    def find_partition(self, first_group=None, max_steps=200_000):
        """
        Searches for a split of the remaining words that fits all feedback.

        Args:
            first_group (Iterable[str] | None): Group the split must contain.
            max_steps (int): Search budget; the board is small, so this is
                only a safeguard.

        Returns:
            list[frozenset] | None: A consistent partition, or None.
        """
        remaining = self.remaining
        start = []
        if first_group is not None:
            first_group = frozenset(first_group)
            if not self.is_possible_group(first_group):
                return None
            start = [first_group]
            remaining = [w for w in remaining if w not in first_group]

        steps = 0

        def search(words, groups):
            nonlocal steps
            steps += 1
            if steps > max_steps:
                return None
            if not words:
                return groups if self.is_possible_partition(groups) else None
            anchor, rest = words[0], words[1:]
            for others in combinations(rest, GROUP_SIZE - 1):
                group = frozenset((anchor, *others))
                if self.is_possible_group(group):
                    leftover = [w for w in rest if w not in group]
                    found = search(leftover, groups + [group])
                    if found:
                        return found
            return None

        return search(remaining, start)

