from __future__ import annotations

from dataclasses import dataclass
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
        if idx == len(slot_order):
            # All slots picked, all positions should be filled.
            if len(assigned_letters) != 21:
                return False
            if any(v != 0 for v in remaining.values()):
                return False
            return satisfies_intersection_yellows()

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

    if not backtrack(0):
        raise ValueError("No solution found")

    return dict(assigned_letters)


def plan_swaps(
    current: dict[tuple[int, int], str],
    target: dict[tuple[int, int], str],
) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """
    Produces a simple (not guaranteed minimal with duplicates) swap plan to transform current->target.
    """
    pos = waffle_positions()
    cur = [current[p] for p in pos]
    tgt = [target[p] for p in pos]

    swaps: list[tuple[tuple[int, int], tuple[int, int]]] = []

    def find_j(i: int) -> int | None:
        want = tgt[i]
        # Prefer swapping with a mispositioned tile that contains the wanted letter.
        for j in range(len(pos)):
            if i == j:
                continue
            if cur[j] == want and cur[j] != tgt[j]:
                return j
        for j in range(len(pos)):
            if i == j:
                continue
            if cur[j] == want:
                return j
        return None

    for _ in range(60):  # safety
        if cur == tgt:
            break
        i = next((k for k in range(len(pos)) if cur[k] != tgt[k]), None)
        if i is None:
            break
        j = find_j(i)
        if j is None:
            break
        cur[i], cur[j] = cur[j], cur[i]
        swaps.append((pos[i], pos[j]))

    return swaps

