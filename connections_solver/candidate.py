# candidate.py
"""
A proposed group of four words with the theme that links them.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Candidate:
    words: frozenset   # The four words
    theme: str         # What connects them
    score: float       # Confidence between 0 and 1
    source: str        # Which generator proposed it ("claude" or "wordplay")

    def label(self):
        """Words in alphabetical order, joined for display."""
        return ", ".join(sorted(self.words))
