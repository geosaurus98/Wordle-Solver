from collections import Counter, defaultdict

DIGITS = set(range(1, 8))


class NumberWaffleSolver:
    def __init__(self, values, locked, sum_constraints=None):
        """
        values: dict[(r,c)] = digit for every playable tile
        locked: set[(r,c)] of green / fixed positions
        sum_constraints: list of tuples ((r1,c1), (r2,c2), total)
        """
        self.values = values
        self.locked = set(locked)
        self.positions = sorted(values.keys())
        self.sum_constraints = sum_constraints or []

        # Even rows are full rows, even cols are full cols
        self.groups = []
        for r in [0, 2, 4, 6]:
            self.groups.append([(r, c) for c in range(7)])
        for c in [0, 2, 4, 6]:
            self.groups.append([(r, c) for r in range(7)])

        self.cell_groups = defaultdict(list)
        for gi, g in enumerate(self.groups):
            for p in g:
                self.cell_groups[p].append(gi)

        # Since we are swapping existing tiles, total counts must stay the same
        self.required_counts = Counter(values.values())

    def initial_domains(self):
        domains = {}
        for p in self.positions:
            if p in self.locked:
                domains[p] = {self.values[p]}
            else:
                domains[p] = set(range(1, 8))
        return domains

    def propagate(self, domains):
        """
        Constraint propagation:
        1. Every full row/col is a permutation of 1..7
        2. Global multiset of digits is preserved
        3. Sum constraints restrict diagonal clue pairs
        """
        changed = True

        while changed:
            changed = False

            # -------------------------------------------------
            # 1) Row/column permutation constraints
            # -------------------------------------------------
            for group in self.groups:
                fixed_vals = [next(iter(domains[p])) for p in group if len(domains[p]) == 1]

                if len(fixed_vals) != len(set(fixed_vals)):
                    return None

                fixed_set = set(fixed_vals)

                # Remove fixed values from undecided cells in same group
                for p in group:
                    if len(domains[p]) > 1:
                        new_domain = domains[p] - fixed_set
                        if not new_domain:
                            return None
                        if new_domain != domains[p]:
                            domains[p] = new_domain
                            changed = True

                # If a missing digit only fits in one place, force it
                missing = DIGITS - set(fixed_vals)
                for d in missing:
                    spots = [p for p in group if d in domains[p]]
                    if not spots:
                        return None
                    if len(spots) == 1 and len(domains[spots[0]]) > 1:
                        domains[spots[0]] = {d}
                        changed = True

            # -------------------------------------------------
            # 2) Global count constraints
            # -------------------------------------------------
            assigned = Counter(
                next(iter(domains[p])) for p in domains if len(domains[p]) == 1
            )

            for d in range(1, 8):
                need = self.required_counts[d]
                have = assigned[d]

                if have > need:
                    return None

                undecided_spots = [p for p in domains if len(domains[p]) > 1 and d in domains[p]]
                remaining = need - have

                if remaining > len(undecided_spots):
                    return None

                if remaining == 0:
                    for p in undecided_spots:
                        new_domain = domains[p] - {d}
                        if not new_domain:
                            return None
                        if new_domain != domains[p]:
                            domains[p] = new_domain
                            changed = True

                elif remaining == len(undecided_spots):
                    for p in undecided_spots:
                        if domains[p] != {d}:
                            domains[p] = {d}
                            changed = True

            # -------------------------------------------------
            # 3) Sum constraints
            # -------------------------------------------------
            for p1, p2, total in self.sum_constraints:
                d1 = domains[p1]
                d2 = domains[p2]

                valid_d1 = {a for a in d1 if any(a + b == total for b in d2)}
                valid_d2 = {b for b in d2 if any(a + b == total for a in d1)}

                if not valid_d1 or not valid_d2:
                    return None

                if valid_d1 != d1:
                    domains[p1] = valid_d1
                    changed = True

                if valid_d2 != d2:
                    domains[p2] = valid_d2
                    changed = True

        return domains

    def search(self, domains):
        domains = {p: set(v) for p, v in domains.items()}
        domains = self.propagate(domains)
        if domains is None:
            return None

        if all(len(v) == 1 for v in domains.values()):
            return {p: next(iter(v)) for p, v in domains.items()}

        # Choose the most constrained undecided cell
        p = min((p for p in domains if len(domains[p]) > 1), key=lambda x: len(domains[x]))

        for d in sorted(domains[p]):
            new_domains = {q: set(v) for q, v in domains.items()}
            new_domains[p] = {d}
            result = self.search(new_domains)
            if result is not None:
                return result

        return None

    def solve_board(self):
        domains = self.initial_domains()
        return self.search(domains)

    def make_swap_sequence(self, target):
        """
        Turn current board into target using swaps of non-locked tiles.
        Valid sequence, not guaranteed minimum.
        """
        current = dict(self.values)
        movable = [p for p in self.positions if p not in self.locked]
        swaps = []

        for p in movable:
            if current[p] == target[p]:
                continue

            needed = target[p]
            best_q = None
            best_score = (-1, -1)

            for q in movable:
                if q == p:
                    continue
                if current[q] != needed:
                    continue

                # Prefer a swap that also fixes q
                score = (
                    1 if current[p] == target[q] else 0,
                    1 if current[q] != target[q] else 0
                )
                if score > best_score:
                    best_score = score
                    best_q = q

            if best_q is None:
                raise RuntimeError(f"No swap candidate found for {p}")

            current[p], current[best_q] = current[best_q], current[p]
            swaps.append((p, best_q))

        return swaps

    @staticmethod
    def print_board(board):
        for r in range(7):
            row = []
            for c in range(7):
                if (r, c) in board:
                    row.append(str(board[(r, c)]))
                else:
                    row.append("·")
            print(" ".join(row))


# ------------------------------------------------------------
# YOUR PUZZLE
# ------------------------------------------------------------

values = {
    (0,0):6, (0,1):7, (0,2):7, (0,3):2, (0,4):2, (0,5):7, (0,6):5,
    (1,0):1,          (1,2):3,          (1,4):7,          (1,6):6,
    (2,0):3, (2,1):5, (2,2):1, (2,3):1, (2,4):7, (2,5):4, (2,6):2,
    (3,0):5,          (3,2):4,          (3,4):5,          (3,6):3,
    (4,0):2, (4,1):2, (4,2):3, (4,3):4, (4,4):1, (4,5):1, (4,6):6,
    (5,0):5,          (5,2):4,          (5,4):5,          (5,6):3,
    (6,0):4, (6,1):6, (6,2):6, (6,3):6, (6,4):4, (6,5):5, (6,6):7,
}

locked = {
    (0,2), (0,4),
    (2,0), (2,2), (2,4), (2,6),
    (3,2), (3,4),
    (4,0), (4,2), (4,4), (4,6),
    (6,2), (6,4),
}

# Sum clues you gave:
sum_constraints = [
    ((0,1), (1,0), 13),
    ((0,3), (1,2), 5),
    ((0,5), (1,4), 11),

    ((4,1), (3,0), 10),
    ((2,3), (3,2), 10),
    ((4,5), (3,6), 8),

    ((6,1), (5,2), 6),
    ((6,3), (5,4), 5),
    ((6,5), (5,6), 12),
]

solver = NumberWaffleSolver(values, locked, sum_constraints)
solution = solver.solve_board()

if solution is None:
    print("No solution found.")
else:
    print("Solved board:")
    solver.print_board(solution)

    swaps = solver.make_swap_sequence(solution)
    print("\nSwap sequence:")
    for i, (a, b) in enumerate(swaps, 1):
        print(f"{i:2d}. swap {a} <-> {b}")