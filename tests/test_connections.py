"""
Unit tests for the Connections solver. Run with:
    python -m unittest discover tests
"""

import json
import unittest
from types import SimpleNamespace

from connections_solver.claude_helper import get_claude_groups, parse_groups, ClaudeUnavailable
from connections_solver.constants import CORRECT, ONE_AWAY, WRONG
from connections_solver.puzzle import ConnectionsPuzzle, parse_words
from connections_solver.solver import rank_candidates, suggest_groups
from connections_solver.candidate import Candidate
from connections_solver.wordplay import find_wordplay_groups

# A board with four clear groups
BOARD = [
    "RED", "BLUE", "GREEN", "PINK",          # Colors
    "KING", "QUEEN", "ROOK", "PAWN",         # Chess pieces
    "MARS", "VENUS", "SATURN", "PLUTO",      # Planets
    "ALPHA", "BETA", "GAMMA", "DELTA",       # Greek letters
]
COLORS = frozenset(BOARD[:4])
CHESS = frozenset(BOARD[4:8])


class FakeClient:
    """Stands in for anthropic.Anthropic and returns a canned answer."""

    def __init__(self, payload, stop_reason="end_turn"):
        text = payload if isinstance(payload, str) else json.dumps(payload)
        self.response = SimpleNamespace(
            stop_reason=stop_reason,
            content=[SimpleNamespace(type="text", text=text)],
        )
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class ParseWordsTests(unittest.TestCase):
    def test_spaces(self):
        self.assertEqual(parse_words("red blue  green"), ["RED", "BLUE", "GREEN"])

    def test_commas_allow_phrases(self):
        self.assertEqual(parse_words("ice cream, hot dog,pie"), ["ICE CREAM", "HOT DOG", "PIE"])


class PuzzleTests(unittest.TestCase):
    def setUp(self):
        self.puzzle = ConnectionsPuzzle(BOARD)

    def test_duplicate_words_rejected(self):
        with self.assertRaises(ValueError):
            ConnectionsPuzzle(BOARD[:15] + ["RED"])

    def test_correct_guess_removes_words(self):
        self.puzzle.record_guess(COLORS, CORRECT, "Colors")
        self.assertEqual(len(self.puzzle.remaining), 12)
        self.assertEqual(self.puzzle.mistakes, 0)

    def test_repeat_guess_rejected(self):
        guess = {"RED", "BLUE", "GREEN", "KING"}
        self.puzzle.record_guess(guess, ONE_AWAY)
        with self.assertRaises(ValueError):
            self.puzzle.record_guess(guess, ONE_AWAY)

    def test_wrong_rules_out_three_overlap(self):
        self.puzzle.record_guess({"RED", "BLUE", "KING", "QUEEN"}, WRONG)
        # COLORS shares only two words with the wrong guess, so still possible
        self.assertTrue(self.puzzle.is_possible_group(COLORS))
        self.assertFalse(self.puzzle.is_possible_group({"RED", "BLUE", "KING", "PINK"}))

    def test_one_away_requires_three_overlap_somewhere(self):
        self.puzzle.record_guess({"RED", "BLUE", "GREEN", "KING"}, ONE_AWAY)
        self.assertIsNotNone(self.puzzle.find_partition(COLORS))
        # A split where no group holds three of the guess is impossible
        bad = [
            {"RED", "BLUE", "ROOK", "QUEEN"}, {"GREEN", "PINK", "KING", "PAWN"},
            set(BOARD[8:12]), set(BOARD[12:]),
        ]
        self.assertFalse(self.puzzle.is_possible_partition(bad))

    def test_lost_after_four_mistakes(self):
        guesses = [
            {"RED", "KING", "MARS", "ALPHA"}, {"BLUE", "QUEEN", "VENUS", "BETA"},
            {"GREEN", "ROOK", "SATURN", "GAMMA"}, {"PINK", "PAWN", "PLUTO", "DELTA"},
        ]
        for g in guesses:
            self.puzzle.record_guess(g, WRONG)
        self.assertTrue(self.puzzle.is_lost)


class WordplayTests(unittest.TestCase):
    def test_finds_category_groups(self):
        groups = {c.words: c.theme for c in find_wordplay_groups(BOARD)}
        self.assertEqual(groups.get(COLORS), "Colors")
        self.assertEqual(groups.get(CHESS), "Chess pieces")

    def test_hidden_words(self):
        words = ["SCATTER", "DOGMA", "PIGEON", "CRATE", "TABLE", "LAMP", "SOFA", "RUG"]
        groups = {c.words: c.theme for c in find_wordplay_groups(words)}
        self.assertEqual(groups.get(frozenset(words[:4])), "Hidden animals")

    def test_anagrams(self):
        words = ["LISTEN", "SILENT", "ENLIST", "TINSEL", "APPLE", "PEAR"]
        groups = {c.words: c.theme for c in find_wordplay_groups(words)}
        self.assertEqual(groups.get(frozenset(words[:4])), "Anagrams of each other")


class ClaudeHelperTests(unittest.TestCase):
    def setUp(self):
        self.puzzle = ConnectionsPuzzle(BOARD)

    def test_parses_groups_and_drops_invalid(self):
        data = {"groups": [
            {"words": ["red", "Blue", "GREEN", "pink"], "theme": "Colors", "confidence": 0.9},
            {"words": ["KING", "QUEEN", "ROOK"], "theme": "Too short", "confidence": 0.9},
            {"words": ["KING", "QUEEN", "ROOK", "BISHOP"], "theme": "Not on board", "confidence": 0.9},
        ]}
        groups = parse_groups(data, self.puzzle.remaining)
        self.assertEqual([g.words for g in groups], [COLORS])

    def test_request_includes_history(self):
        self.puzzle.record_guess({"RED", "BLUE", "GREEN", "KING"}, ONE_AWAY)
        client = FakeClient({"groups": []})
        get_claude_groups(self.puzzle, client=client)
        prompt = client.calls[0]["messages"][0]["content"]
        self.assertIn("one away", prompt)

    def test_refusal_raises(self):
        client = FakeClient({"groups": []}, stop_reason="refusal")
        with self.assertRaises(ClaudeUnavailable):
            get_claude_groups(self.puzzle, client=client)


class SolverTests(unittest.TestCase):
    def setUp(self):
        self.puzzle = ConnectionsPuzzle(BOARD)

    def test_claude_suggestion_ranked_first(self):
        client = FakeClient({"groups": [
            {"words": sorted(CHESS), "theme": "Chess pieces", "confidence": 0.95},
        ]})
        suggestions, warning = suggest_groups(self.puzzle, client=client)
        self.assertIsNone(warning)
        self.assertEqual(suggestions[0].words, CHESS)

    def test_contradicted_candidates_removed(self):
        self.puzzle.record_guess(COLORS, WRONG)
        cands = [Candidate(COLORS, "Colors", 0.9, "claude")]
        self.assertEqual(rank_candidates(self.puzzle, cands), [])

    def test_last_group_is_automatic(self):
        for group in (COLORS, CHESS, frozenset(BOARD[8:12])):
            self.puzzle.record_guess(group, CORRECT)
        ranked = rank_candidates(self.puzzle, [])
        self.assertEqual(ranked[0].words, frozenset(BOARD[12:]))

    def test_claude_failure_falls_back(self):
        client = FakeClient("not json")
        suggestions, warning = suggest_groups(self.puzzle, client=client)
        self.assertIsNotNone(warning)
        self.assertTrue(suggestions)  # Wordplay still finds the groups


if __name__ == "__main__":
    unittest.main()
