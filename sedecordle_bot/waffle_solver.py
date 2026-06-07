from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Iterable


Color = str  # "green" | "yellow" | "grey" | "white"


HOLES = {(1, 1), (1, 3), (3, 1), (3, 3)}


def waffle_positions() -> list[tuple[int, int]]:
    pos: list[tuple[int, int]] = []
    for y in range(5):
        for x in range(5):
            if (x, y) in HOLES:
                continue
            pos.append((x, y))
    return pos


def slot_positions() -> dict[str, list[tuple[int, int]]]:
    # 3 horizontal (rows 0,2,4) and 3 vertical (cols 0,2,4)
    slots: dict[str, list[tuple[int, int]]] = {}
    for y in (0, 2, 4):
        slots[f"R{y}"] = [(x, y) for x in range(5)]
    for x in (0, 2, 4):
        slots[f"C{x}"] = [(x, y) for y in range(5)]
    return slots


def pos_slots() -> dict[tuple[int, int], list[str]]:
    slots = slot_positions()
    out: dict[tuple[int, int], list[str]] = {}
    for s, ps in slots.items():
        for p in ps:
            out.setdefault(p, []).append(s)
    return out


@dataclass(frozen=True)
class Tile:
    x: int
    y: int
    letter: str
    color: Color


@dataclass(frozen=True)
class WafflePuzzle:
    # tiles keyed by (x,y)
    tiles: dict[tuple[int, int], Tile]

    def letters_multiset(self) -> dict[str, int]:
        c: dict[str, int] = {}
        for t in self.tiles.values():
            ch = t.letter.lower()
            c[ch] = c.get(ch, 0) + 1
        return c


def _word_matches_constraints(
    word: str,
    slot: str,
    slot_ps: list[tuple[int, int]],
    fixed_letters: dict[tuple[int, int], str],
    tiles: dict[tuple[int, int], Tile],
    pos_to_slots: dict[tuple[int, int], list[str]],
) -> bool:
    """
    Apply Waffle color constraints for tiles that "belong" to this slot:
    - green at p => word[i] must match fixed letter (handled by fixed_letters too)
    - yellow at p:
        - if tile belongs only to this slot: word must contain tile.letter somewhere but not at i
        - if tile belongs to two slots: enforce word[i] != tile.letter (membership handled later)
    - grey at p:
        - if tile belongs to this slot: word must not contain tile.letter anywhere
    """
    w = word.lower()

    # greens / fixed letters
    for i, p in enumerate(slot_ps):
        if p in fixed_letters and w[i] != fixed_letters[p]:
            return False

    # greys / yellows
    for i, p in enumerate(slot_ps):
        tile = tiles.get(p)
        if not tile:
            continue
        ch = tile.letter.lower()
        belongs = pos_to_slots.get(p, [])
        if slot not in belongs:
            continue

        if tile.color == "grey":
            if ch in w:
                return False
        elif tile.color == "yellow":
            if len(belongs) == 1:
                if w[i] == ch:
                    return False
                if ch not in w:
                    return False
            else:
                # intersection: can't be in this exact position, but may or may not be in this word
                if w[i] == ch:
                    return False

    return True


def solve_waffle(
    puzzle: WafflePuzzle,
    word_list: Iterable[str],
) -> dict[tuple[int, int], str]:
    """
    Returns a solved grid mapping (x,y)->letter for all 21 positions.
    Raises ValueError if no solution found.
    """
    tiles = puzzle.tiles
    slots = slot_positions()
    p2s = pos_slots()

    # Fixed letters from greens.
    fixed: dict[tuple[int, int], str] = {}
    for p, t in tiles.items():
        if t.color == "green":
            fixed[p] = t.letter.lower()

    # Global multiset of letters must match.
    remaining = puzzle.letters_multiset()

    # Candidate words per slot.
    words = [w.strip().lower() for w in word_list if isinstance(w, str)]
    words = [w for w in words if len(w) == 5 and w.isalpha()]

    slot_cands: dict[str, list[str]] = {}
    for s, ps in slots.items():
        c: list[str] = []
        for w in words:
            if _word_matches_constraints(w, s, ps, fixed, tiles, p2s):
                c.append(w)
        slot_cands[s] = c
        if not c:
            raise ValueError(f"No candidate words for slot {s}")

    # Backtracking over slots with letter multiset pruning.
    assigned_letters: dict[tuple[int, int], str] = {}
    chosen_words: dict[str, str] = {}
    current_grid = {(t.x, t.y): t.letter.lower() for t in puzzle.tiles.values()}
    best_solution: dict[tuple[int, int], str] | None = None
    best_swap_count: int | None = None

    # Pre-sort slots by candidate count (dynamic MRV below as well).
    slot_order = sorted(slots.keys(), key=lambda s: len(slot_cands[s]))

    def can_place_word(s: str, w: str) -> bool:
        ps = slots[s]
        # letter conflicts / multiset
        needed: dict[str, int] = {}
        for i, p in enumerate(ps):
            ch = w[i]
            if p in assigned_letters:
                if assigned_letters[p] != ch:
                    return False
            else:
                needed[ch] = needed.get(ch, 0) + 1
        for ch, k in needed.items():
            if remaining.get(ch, 0) < k:
                return False
        return True

    def place_word(s: str, w: str) -> list[tuple[int, int]]:
        ps = slots[s]
        changed: list[tuple[int, int]] = []
        for i, p in enumerate(ps):
            ch = w[i]
            if p not in assigned_letters:
                assigned_letters[p] = ch
                remaining[ch] -= 1
                changed.append(p)
        chosen_words[s] = w
        return changed

    def unplace_word(s: str, changed: list[tuple[int, int]]) -> None:
        w = chosen_words.pop(s)
        for p in changed:
            ch = assigned_letters.pop(p)
            remaining[ch] += 1

    def satisfies_intersection_yellows() -> bool:
        """
        For intersection tiles that are yellow: the letter must appear in at least one of its two words.
        """
        for p, t in tiles.items():
            if t.color != "yellow":
                continue
            belongs = p2s.get(p, [])
            if len(belongs) != 2:
                continue
            ch = t.letter.lower()
            # Must appear in at least one of the two words (somewhere not at p, already enforced).
            ok = False
            for s in belongs:
                w = chosen_words.get(s)
                if w and ch in w:
                    ok = True
            if not ok:
                return False
        return True

    def backtrack(idx: int) -> bool:
        nonlocal best_solution, best_swap_count
        if idx == len(slot_order):
            # All slots picked, all positions should be filled.
            if len(assigned_letters) != 21:
                return False
            if any(v != 0 for v in remaining.values()):
                return False
            if not satisfies_intersection_yellows():
                return False

            candidate = dict(assigned_letters)
            try:
                swaps = plan_swaps(current_grid, candidate, max_swaps=15)
            except ValueError:
                return False  # This word assignment needs >15 swaps — skip it.
            swap_count = len(swaps)
            if best_swap_count is None or swap_count < best_swap_count:
                best_swap_count = swap_count
                best_solution = candidate
                # Daily Waffle is designed for ≤10 swaps; stop searching once we hit that.
                if swap_count <= 10:
                    return True
            return False

        # Dynamic MRV: choose among remaining slots the one with smallest filtered cand count.
        remaining_slots = [s for s in slot_order if s not in chosen_words]
        best_s = None
        best_list: list[str] | None = None
        best_len = 10**9
        for s in remaining_slots:
            filtered = [w for w in slot_cands[s] if can_place_word(s, w)]
            if not filtered:
                return False
            if len(filtered) < best_len:
                best_len = len(filtered)
                best_s = s
                best_list = filtered
                if best_len == 1:
                    break
        assert best_s is not None and best_list is not None

        # Try candidates; prefer ones that use rarer letters (small heuristic).
        def rarity_score(w: str) -> int:
            s = 0
            for ch in set(w):
                s += remaining.get(ch, 0)
            return s

        for w in sorted(best_list, key=rarity_score):
            changed = place_word(best_s, w)
            if backtrack(idx + 1):
                return True
            unplace_word(best_s, changed)
        return False

    found_in_limit = backtrack(0)
    if not found_in_limit and best_solution is None:
        raise ValueError("No solution found")

    assert best_solution is not None
    return best_solution


def plan_swaps(
    current: dict[tuple[int, int], str],
    target: dict[tuple[int, int], str],
    max_swaps: int = 60,
) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """
    Produces a near-optimal/optimal swap plan (bounded search) to transform current->target.
    """
    return _plan_swaps_bounded(current, target, max_swaps=max_swaps)


def _plan_swaps_bounded(
    current: dict[tuple[int, int], str],
    target: dict[tuple[int, int], str],
    max_swaps: int,
) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """
    Depth-bounded search for a shortest swap sequence.
    Works well on Waffle-sized boards (21 tiles) and handles duplicate letters.
    """
    pos = waffle_positions()
    cur0 = tuple(current[p] for p in pos)
    tgt = [target[p] for p in pos]
    n = len(pos)

    if cur0 == tuple(tgt):
        return []

    def mismatch_count(state: tuple[str, ...]) -> int:
        return sum(1 for i in range(n) if state[i] != tgt[i])

    # admissible lower bound: one swap can fix at most two mismatches
    def lower_bound(state: tuple[str, ...]) -> int:
        return ceil(mismatch_count(state) / 2)

    best_seen_remaining: dict[tuple[str, ...], int] = {}
    path: list[tuple[int, int]] = []
    answer: list[tuple[int, int]] | None = None

    def dfs(state: tuple[str, ...], remaining_depth: int) -> bool:
        nonlocal answer
        if state == tuple(tgt):
            answer = list(path)
            return True
        if lower_bound(state) > remaining_depth:
            return False

        prev_best = best_seen_remaining.get(state)
        if prev_best is not None and prev_best >= remaining_depth:
            return False
        best_seen_remaining[state] = remaining_depth

        # Focus on the first incorrect index; try swaps that place the needed letter there.
        i = next(idx for idx in range(n) if state[idx] != tgt[idx])
        want = tgt[i]

        candidates: list[tuple[int, int]] = []
        for j in range(n):
            if j == i:
                continue
            if state[j] != want:
                continue
            gain = (state[i] == tgt[j]) + (state[j] == tgt[i])  # 0..2
            # Prefer swaps that repair two indices, then one.
            candidates.append((2 - gain, j))

        # Fallback in degenerate states (should be rare with valid multisets).
        if not candidates:
            for j in range(n):
                if j == i:
                    continue
                if state[j] != tgt[j]:
                    candidates.append((2, j))

        for _, j in sorted(candidates):
            lst = list(state)
            lst[i], lst[j] = lst[j], lst[i]
            nxt = tuple(lst)
            path.append((i, j))
            if dfs(nxt, remaining_depth - 1):
                return True
            path.pop()
        return False

    for depth in range(lower_bound(cur0), max_swaps + 1):
        best_seen_remaining.clear()
        path.clear()
        if dfs(cur0, depth):
            assert answer is not None
            return [(pos[i], pos[j]) for i, j in answer]

    raise ValueError(f"Could not produce swap plan within {max_swaps} swaps")

