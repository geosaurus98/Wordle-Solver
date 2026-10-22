# claude_helper.py
"""
Asks Claude for themed groups. This is where the solver gets its
understanding of meaning (synonyms, pop culture, "___ BALL", etc.).

Needs the `anthropic` package and an API key (ANTHROPIC_API_KEY or an
`ant auth login` profile). Without them the solver falls back to the
offline wordplay detectors.
"""

import json

from connections_solver.candidate import Candidate
from connections_solver.constants import CLAUDE_MODEL, CLAUDE_EFFORT, GROUP_SIZE, CORRECT, ONE_AWAY, WRONG

try:
    import anthropic
except ImportError:  # Optional dependency
    anthropic = None

# SDK errors (missing key, auth, rate limit, network, server) that mean "use the fallback"
API_ERRORS = (anthropic.AnthropicError,) if anthropic else ()

SYSTEM_PROMPT = """You are an expert solver of the New York Times game Connections.
The board holds 16 words that form exactly four groups of four. Each group shares a
specific connection. Categories are often tricky: fill-in-the-blank phrases (___ BALL),
homophones, hidden words, words that follow or precede another word, slang, brands,
pop culture, and words with several meanings. The puzzle includes red herrings: words
that seem to fit one group but belong to another. Groups are ranked yellow (easiest),
green, blue, purple (trickiest, usually wordplay).

Work out a full split of the remaining words into groups of four, double-checking that
every word is used exactly once. Then list the groups you would consider, most
confident first. Include your full split, plus alternative groups for any words you are
unsure about. Use the words exactly as written on the board. Respect the feedback from
earlier guesses: a "wrong" guess means no group contains three or more of those words;
"one away" means exactly three of those words form part of one group."""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "words": {"type": "array", "items": {"type": "string"}},
                    "theme": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["words", "theme", "confidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["groups"],
    "additionalProperties": False,
}

FEEDBACK_LABELS = {CORRECT: "correct", ONE_AWAY: "one away", WRONG: "wrong"}


class ClaudeUnavailable(Exception):
    """Raised when Claude cannot be used (missing package, key or network)."""


def is_available():
    """True if the anthropic package is installed."""
    return anthropic is not None


def build_prompt(puzzle):
    """Describes the current board and guess history for Claude."""
    lines = ["Remaining words:", ", ".join(puzzle.remaining)]

    if puzzle.solved:
        lines.append("\nAlready solved (these words are gone):")
        for group, theme in puzzle.solved:
            lines.append(f"- {', '.join(sorted(group))}" + (f" ({theme})" if theme else ""))

    wrong_guesses = [(g, f) for g, f in puzzle.history if f != CORRECT]
    if wrong_guesses:
        lines.append("\nIncorrect guesses so far:")
        for group, feedback in wrong_guesses:
            lines.append(f"- {', '.join(sorted(group))}: {FEEDBACK_LABELS[feedback]}")

    lines.append("\nSuggest up to 8 candidate groups of exactly four words each, with a "
                 "short theme and a confidence between 0 and 1.")
    return "\n".join(lines)


def get_claude_groups(puzzle, client=None):
    """
    Asks Claude for candidate groups for the current board.

    Args:
        puzzle (ConnectionsPuzzle): Current game state.
        client: Optional pre-built Anthropic client (used by tests).

    Returns:
        list[Candidate]: Valid candidate groups, as proposed by Claude.

    Raises:
        ClaudeUnavailable: If the request cannot be made or is declined.
    """
    if client is None:
        if anthropic is None:
            raise ClaudeUnavailable("Install the 'anthropic' package to use Claude.")
        try:
            client = anthropic.Anthropic()
        except anthropic.AnthropicError as e:
            raise ClaudeUnavailable(f"Could not create Claude client: {e}") from e

    try:
        response = client.beta.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={
                "effort": CLAUDE_EFFORT,
                "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA},
            },
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_prompt(puzzle)}],
        )
    except API_ERRORS as e:
        raise ClaudeUnavailable(f"Claude request failed: {e}") from e
    except TypeError as e:
        # The SDK raises TypeError when no API key or login is configured
        if "authentication" not in str(e):
            raise
        raise ClaudeUnavailable("No Claude API key found (set ANTHROPIC_API_KEY).") from e

    if response.stop_reason == "refusal":
        raise ClaudeUnavailable("Claude declined this request.")
    if response.stop_reason == "max_tokens":
        raise ClaudeUnavailable("Claude's answer was cut off.")

    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ClaudeUnavailable("Claude returned an unreadable answer.") from e

    return parse_groups(data, puzzle.remaining)


def parse_groups(data, remaining):
    """
    Converts Claude's JSON into Candidates, dropping any group that
    doesn't use exactly four distinct words from the board.
    """
    lookup = {w.upper(): w for w in remaining}
    candidates = []
    for item in data.get("groups", []):
        words = frozenset(lookup.get(" ".join(str(w).split()).upper()) for w in item.get("words", []))
        if None in words or len(words) != GROUP_SIZE or len(item.get("words", [])) != GROUP_SIZE:
            continue
        confidence = min(max(float(item.get("confidence", 0)), 0.0), 1.0)
        candidates.append(Candidate(words, item.get("theme", "").strip(), confidence, "claude"))
    return candidates
