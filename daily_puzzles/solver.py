from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


DATA_DIR = Path(__file__).resolve().parent / "data"

# States follow Wordle semantics:
# - "correct": right letter, right position (green)
# - "present": letter in word but wrong position (yellow)
# - "absent": letter not in word (grey) — subject to Wordle duplicate-letter rules.
State = int  # 0=absent, 1=present, 2=correct


def load_word_list(path: Path) -> list[str]:
    words: list[str] = []
    if not path.exists():
        return words
    for line in path.read_text(encoding="utf-8").splitlines():
        w = line.strip().lower()
        if len(w) == 5 and w.isalpha():
            words.append(w)
    # Dedup preserving order
    seen = set()
    out = []
    for w in words:
        if w in seen:
            continue
        seen.add(w)
        out.append(w)
    return out


def load_words() -> tuple[list[str], list[str]]:
    allowed = load_word_list(DATA_DIR / "allowed.txt")
    answers = load_word_list(DATA_DIR / "answers.txt")
    if not answers:
        answers = allowed
    return allowed, answers


def score_guess(guess: str, answer: str) -> tuple[State, State, State, State, State]:
    """
    Returns Wordle-style feedback for guess vs answer with correct duplicate-letter handling.
    """
    g = guess.lower()
    a = answer.lower()
    out: list[State] = [0, 0, 0, 0, 0]

    # First pass: mark correct, count remaining letters in answer.
    remaining: dict[str, int] = {}
    for i in range(5):
        if g[i] == a[i]:
            out[i] = 2
        else:
            remaining[a[i]] = remaining.get(a[i], 0) + 1

    # Second pass: mark present where possible.
    for i in range(5):
        if out[i] == 2:
            continue
        c = g[i]
        if remaining.get(c, 0) > 0:
            out[i] = 1
            remaining[c] -= 1

    return tuple(out)  # type: ignore[return-value]


def filter_candidates(candidates: Sequence[str], guess: str, feedback: Sequence[State]) -> list[str]:
    fb = tuple(int(x) for x in feedback)
    return [w for w in candidates if score_guess(guess, w) == fb]


@dataclass(frozen=True)
class GuessFeatures:
    word: str
    uniq_letters: tuple[str, ...]
    repeats: int


def _features(words: Iterable[str]) -> list[GuessFeatures]:
    feats: list[GuessFeatures] = []
    for w in words:
        uniq = tuple(sorted(set(w)))
        repeats = 5 - len(uniq)
        feats.append(GuessFeatures(word=w, uniq_letters=uniq, repeats=repeats))
    return feats


def choose_next_guess(
    allowed: Sequence[str],
    board_candidates: Sequence[Sequence[str]],
    prefer_solutions_when_small: bool = True,
) -> str:
    """
    Pick a single guess to apply to all boards.

    Heuristic:
    - (Optional) prefer solution-words when boards are small (handled by caller).
    - Otherwise score each allowed guess by aggregating per-board "uncertainty" in letters/positions
      computed from that board's current candidate set.
    """
    unsolved = [c for c in board_candidates if len(c) > 1]
    if not unsolved:
        # Arbitrary; caller should stop before this.
        return allowed[0]

    # Precompute guess features once per call; allowed is stable but small enough.
    allowed_feats = _features(allowed)

    # Precompute per-board frequencies.
    per_board_letter_freq: list[dict[str, int]] = []
    per_board_pos_freq: list[list[dict[str, int]]] = []
    per_board_n: list[int] = []

    for cand in board_candidates:
        n = len(cand)
        per_board_n.append(n)
        letter_freq: dict[str, int] = {}
        pos_freq: list[dict[str, int]] = [dict() for _ in range(5)]
        if n > 0:
            for w in cand:
                seen = set()
                for i, ch in enumerate(w):
                    pos_freq[i][ch] = pos_freq[i].get(ch, 0) + 1
                    if ch not in seen:
                        letter_freq[ch] = letter_freq.get(ch, 0) + 1
                        seen.add(ch)
        per_board_letter_freq.append(letter_freq)
        per_board_pos_freq.append(pos_freq)

    def board_weight(n: int) -> float:
        if n <= 2:
            return 3.0
        if n <= 10:
            return 2.2
        if n <= 50:
            return 1.6
        return 1.0

    best_word = allowed_feats[0].word
    best_score = -1.0

    for gf in allowed_feats:
        s = 0.0
        w = gf.word
        for bi, n in enumerate(per_board_n):
            if n <= 1:
                continue
            lw = board_weight(n)
            lf = per_board_letter_freq[bi]
            pf = per_board_pos_freq[bi]

            denom = float(n * n) if n > 0 else 1.0

            # Letter presence uncertainty (best near 50/50).
            for ch in gf.uniq_letters:
                f = float(lf.get(ch, 0))
                s += lw * (f * (n - f) / denom)

            # Positional uncertainty (also best near 50/50).
            for i in range(5):
                f = float(pf[i].get(w[i], 0))
                s += lw * 0.35 * (f * (n - f) / denom)

        # Penalize repeats slightly (usually less informative).
        s -= 0.12 * gf.repeats

        if s > best_score:
            best_score = s
            best_word = gf.word

    return best_word


def is_solved_feedback(feedback: Sequence[State]) -> bool:
    return len(feedback) == 5 and all(int(x) == 2 for x in feedback)


def encode_feedback(feedback: Sequence[State]) -> int:
    """
    Base-3 encoding of a 5-tile feedback into [0, 242].
    """
    code = 0
    for x in feedback:
        code = code * 3 + int(x)
    return code


def choose_best_guess_single_board(
    allowed: Sequence[str],
    candidates: Sequence[str],
    *,
    guessed: set[str] | None = None,
    max_pool: int = 1200,
) -> str:
    """
    Single-board guess chooser tuned for 6-guess Wordle.

    Strategy:
    - If <=2 candidates, just play a candidate (avoid repeats).
    - Otherwise, score guesses by minimizing expected remaining candidates:
        minimize sum(partition_size^2) over feedback partitions.
      (Equivalent to maximizing Gini information.)
    - To keep it fast, consider a pool of up to max_pool guesses chosen by letter-frequency score,
      plus all current candidates.
    """
    if not candidates:
        # Caller shouldn't let this happen; fall back.
        return allowed[0]

    gset = guessed or set()

    # If already narrow, just try solutions.
    if len(candidates) <= 2:
        for w in candidates:
            if w not in gset:
                return w
        return candidates[0]

    # If the candidate set is extremely large (e.g. we couldn't extract the official answer list),
    # downsample for scoring to keep runtime reasonable. Filtering still uses the full set.
    scoring_candidates = list(candidates)
    if len(scoring_candidates) > 5000:
        step = max(1, len(scoring_candidates) // 4000)
        scoring_candidates = scoring_candidates[::step]

    # Build a pool biased toward informative guesses.
    # Letter frequency in candidates (presence, not count).
    lf: dict[str, int] = {}
    for w in scoring_candidates:
        for ch in set(w):
            lf[ch] = lf.get(ch, 0) + 1

    def info_score(word: str) -> int:
        seen = set()
        s = 0
        for ch in word:
            if ch in seen:
                continue
            seen.add(ch)
            s += lf.get(ch, 0)
        return s

    allowed_filtered = [w for w in allowed if w not in gset]
    # Take top max_pool by info_score.
    scored = sorted(allowed_filtered, key=info_score, reverse=True)
    pool = scored[:max_pool]
    # Ensure we always include candidates (so we can choose an actual solution when best).
    pool_set = set(pool)
    for w in candidates:
        if w in gset:
            continue
        if w not in pool_set:
            pool.append(w)
            pool_set.add(w)

    n = len(scoring_candidates)
    best = pool[0]
    best_cost = float("inf")

    for guess in pool:
        # Partition candidates by feedback code.
        counts = [0] * 243
        for ans in scoring_candidates:
            counts[encode_feedback(score_guess(guess, ans))] += 1
        # Expected remaining proportional to sum(size^2).
        cost = 0
        for c in counts:
            cost += c * c
        # Prefer guesses that are also candidates when close.
        if cost < best_cost or (cost == best_cost and guess in candidates and best not in candidates):
            best_cost = cost
            best = guess

    return best

