# wordplay.py
"""
Offline group detectors. These need no API key and catch the
mechanical categories NYT likes to use (hidden words, anagrams,
shared beginnings/endings), plus a few common trivia lists.

They cannot understand meaning, so they are a fallback and a
second opinion rather than a full solver.
"""

from collections import defaultdict
from itertools import combinations
from math import comb

from connections_solver.candidate import Candidate
from connections_solver.constants import GROUP_SIZE

# === BUILT-IN CATEGORY LISTS ===
CATEGORIES = {
    "Colors": ["RED", "BLUE", "GREEN", "YELLOW", "ORANGE", "PURPLE", "PINK", "BROWN",
               "BLACK", "WHITE", "GRAY", "GREY", "TAN", "TEAL", "NAVY", "CYAN", "INDIGO",
               "VIOLET", "MAROON", "BEIGE", "LIME", "GOLD", "SILVER", "AMBER", "CORAL"],
    "Numbers": ["ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE",
                "TEN", "ELEVEN", "TWELVE", "TWENTY", "HUNDRED", "THOUSAND", "MILLION"],
    "Animals": ["CAT", "DOG", "COW", "PIG", "HEN", "RAT", "BAT", "APE", "ELK", "EMU",
                "OWL", "EEL", "ANT", "BEE", "YAK", "GNU", "FOX", "HORSE", "MOUSE",
                "SHEEP", "GOAT", "LION", "TIGER", "BEAR", "WOLF", "DEER", "HARE", "SEAL",
                "CRAB", "TOAD", "FROG", "MOLE", "LAMB", "COLT", "MULE", "BOAR", "OTTER",
                "EAGLE", "HAWK", "CROW", "DOVE", "SWAN", "DUCK", "GOOSE", "SNAKE", "WHALE",
                "SHARK", "CAMEL", "ZEBRA", "PANDA", "KOALA", "MOOSE", "BISON", "LLAMA"],
    "Body parts": ["ARM", "LEG", "EAR", "EYE", "LIP", "HIP", "TOE", "RIB", "JAW", "GUM",
                   "SHIN", "CHIN", "HAND", "FOOT", "KNEE", "NECK", "BACK", "HEAD", "NOSE",
                   "HEEL", "PALM", "NAIL", "BROW", "LASH", "LUNG", "LIVER", "HEART",
                   "ELBOW", "WRIST", "ANKLE", "THUMB", "TOOTH", "SKULL", "SPINE", "CALF"],
    "Planets": ["MERCURY", "VENUS", "EARTH", "MARS", "JUPITER", "SATURN", "URANUS",
                "NEPTUNE", "PLUTO"],
    "Greek letters": ["ALPHA", "BETA", "GAMMA", "DELTA", "EPSILON", "ZETA", "ETA",
                      "THETA", "IOTA", "KAPPA", "LAMBDA", "MU", "NU", "XI", "OMICRON",
                      "PI", "RHO", "SIGMA", "TAU", "UPSILON", "PHI", "CHI", "PSI", "OMEGA"],
    "Chess pieces": ["KING", "QUEEN", "ROOK", "BISHOP", "KNIGHT", "PAWN"],
    "Card suits": ["HEART", "HEARTS", "DIAMOND", "DIAMONDS", "CLUB", "CLUBS",
                   "SPADE", "SPADES"],
    "Days of the week": ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY",
                         "SATURDAY", "SUNDAY"],
    "Months": ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY",
               "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"],
    "Zodiac signs": ["ARIES", "TAURUS", "GEMINI", "CANCER", "LEO", "VIRGO", "LIBRA",
                     "SCORPIO", "SAGITTARIUS", "CAPRICORN", "AQUARIUS", "PISCES"],
}

MIN_HIDDEN_LENGTH = 3   # Shorter hidden words match far too often
MIN_AFFIX_LENGTH = 3    # Shortest shared prefix/suffix worth reporting
MAX_MATCHES = 7         # Ignore patterns that match most of the board

# Base confidence for each kind of pattern
MEMBER_SCORE = 0.6
HIDDEN_SCORE = 0.5
ANAGRAM_SCORE = 0.7
PALINDROME_SCORE = 0.5
AFFIX_SCORE = 0.35


def find_wordplay_groups(words):
    """
    Runs every detector over the board.

    Args:
        words (list[str]): Remaining (normalized) words.

    Returns:
        list[Candidate]: Candidate groups, highest score first.
    """
    matches = []  # [(theme, matching words, base score)]
    matches += _category_matches(words)
    matches += _anagram_matches(words)
    matches += _palindrome_matches(words)
    matches += _affix_matches(words)

    best = {}
    for theme, matched, base in matches:
        if not GROUP_SIZE <= len(matched) <= MAX_MATCHES:
            continue
        # Spread confidence across the possible picks when there are red herrings
        score = base / comb(len(matched), GROUP_SIZE)
        for group in combinations(sorted(matched), GROUP_SIZE):
            group = frozenset(group)
            if group not in best or best[group].score < score:
                best[group] = Candidate(group, theme, score, "wordplay")

    return sorted(best.values(), key=lambda c: c.score, reverse=True)


def _letters(word):
    """Word with spaces and punctuation removed."""
    return "".join(ch for ch in word if ch.isalpha())


def _category_matches(words):
    """Words that are list members, or hide a list member inside them."""
    results = []
    for name, members in CATEGORIES.items():
        members = set(members)
        exact = [w for w in words if _letters(w) in members]
        results.append((name, exact, MEMBER_SCORE))

        hidden = [w for w in words if _hides_member(_letters(w), members)]
        results.append((f"Hidden {name.lower()}", hidden, HIDDEN_SCORE))
    return results


def _hides_member(word, members):
    """True if a member appears inside word without being the whole word."""
    return any(
        len(m) >= MIN_HIDDEN_LENGTH and m in word and m != word
        for m in members
    )


def _anagram_matches(words):
    """Groups of words that are anagrams of each other."""
    by_letters = defaultdict(list)
    for w in words:
        by_letters["".join(sorted(_letters(w)))].append(w)
    return [("Anagrams of each other", group, ANAGRAM_SCORE) for group in by_letters.values()]


def _palindrome_matches(words):
    """Words that read the same backwards."""
    found = [w for w in words if len(_letters(w)) > 2 and _letters(w) == _letters(w)[::-1]]
    return [("Palindromes", found, PALINDROME_SCORE)]


def _affix_matches(words):
    """Words that share a beginning or ending of at least MIN_AFFIX_LENGTH letters."""
    results = []
    for kind, cut in (("Start with", lambda w, n: w[:n]), ("End with", lambda w, n: w[-n:])):
        groups = defaultdict(set)
        for w in words:
            letters = _letters(w)
            for n in range(MIN_AFFIX_LENGTH, len(letters)):
                groups[cut(letters, n)].add(w)
        for affix, matched in groups.items():
            # Longer shared affixes are stronger evidence
            score = AFFIX_SCORE * min(1.0, len(affix) / 4)
            results.append((f"{kind} {affix}", matched, score))
    return results
