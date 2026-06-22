import tkinter as tk
from collections import Counter, defaultdict

DIGITS = set(range(1, 8))


class NumberWaffleSolver:
    def __init__(self, values, locked, sum_constraints=None):
        self.values = values
        self.locked = set(locked)
        self.positions = sorted(values.keys())
        self.sum_constraints = sum_constraints or []

        self.groups = []
        for r in [0, 2, 4, 6]:
            self.groups.append([(r, c) for c in range(7)])
        for c in [0, 2, 4, 6]:
            self.groups.append([(r, c) for r in range(7)])

        self.cell_groups = defaultdict(list)
        for gi, g in enumerate(self.groups):
            for p in g:
                self.cell_groups[p].append(gi)

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
        changed = True

        while changed:
            changed = False

            for group in self.groups:
                fixed_vals = [next(iter(domains[p])) for p in group if len(domains[p]) == 1]

                if len(fixed_vals) != len(set(fixed_vals)):
                    return None

                fixed_set = set(fixed_vals)

                for p in group:
                    if len(domains[p]) > 1:
                        new_domain = domains[p] - fixed_set
                        if not new_domain:
                            return None
                        if new_domain != domains[p]:
                            domains[p] = new_domain
                            changed = True

                missing = DIGITS - set(fixed_vals)
                for d in missing:
                    spots = [p for p in group if d in domains[p]]
                    if not spots:
                        return None
                    if len(spots) == 1 and len(domains[spots[0]]) > 1:
                        domains[spots[0]] = {d}
                        changed = True

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

        p = min((p for p in domains if len(domains[p]) > 1), key=lambda x: len(domains[x]))

        for d in sorted(domains[p]):
            new_domains = {q: set(v) for q, v in domains.items()}
            new_domains[p] = {d}
            result = self.search(new_domains)
            if result is not None:
                return result

        return None

    def solve_board(self):
        return self.search(self.initial_domains())

    def make_swap_sequence(self, target):
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


class WaffleVisualizer:
    def __init__(self, initial_board, solution, clue_values, swaps):
        self.initial_board = dict(initial_board)
        self.board = dict(initial_board)
        self.solution = dict(solution)
        self.clue_values = clue_values
        self.swaps = swaps
        self.step_index = 0
        self.cell_size = 80
        self.margin = 20
        self.autoplay_job = None

        self.root = tk.Tk()
        self.root.title("Number Waffle Visualizer")

        canvas_size = self.margin * 2 + self.cell_size * 7
        self.canvas = tk.Canvas(self.root, width=canvas_size, height=canvas_size, bg="white")
        self.canvas.pack(pady=10)

        controls = tk.Frame(self.root)
        controls.pack()

        tk.Button(controls, text="<< Reset", command=self.reset_board, width=10).grid(row=0, column=0, padx=5)
        tk.Button(controls, text="< Prev", command=self.prev_step, width=10).grid(row=0, column=1, padx=5)
        tk.Button(controls, text="Next >", command=self.next_step, width=10).grid(row=0, column=2, padx=5)
        tk.Button(controls, text="Autoplay", command=self.autoplay, width=10).grid(row=0, column=3, padx=5)
        tk.Button(controls, text="Stop", command=self.stop_autoplay, width=10).grid(row=0, column=4, padx=5)

        self.status = tk.Label(self.root, text="", font=("Arial", 12))
        self.status.pack(pady=8)

        self.draw()

    def cell_bbox(self, r, c):
        x1 = self.margin + c * self.cell_size
        y1 = self.margin + r * self.cell_size
        x2 = x1 + self.cell_size
        y2 = y1 + self.cell_size
        return x1, y1, x2, y2

    def draw(self, highlight=None):
        self.canvas.delete("all")

        for r in range(7):
            for c in range(7):
                x1, y1, x2, y2 = self.cell_bbox(r, c)

                if (r, c) in self.board:
                    is_correct = self.board[(r, c)] == self.solution[(r, c)]

                    if highlight and (r, c) in highlight:
                        fill = "#ffd966"   # yellow for active swap
                    elif is_correct:
                        fill = "#6fb65e"   # green when correct
                    else:
                        fill = "#d9d9d9"   # grey otherwise

                    self.canvas.create_rectangle(
                        x1, y1, x2, y2,
                        fill=fill, outline="white", width=3
                    )
                    self.canvas.create_text(
                        (x1 + x2) / 2,
                        (y1 + y2) / 2,
                        text=str(self.board[(r, c)]),
                        font=("Arial", 28, "bold"),
                        fill="white" if is_correct else "black"
                    )

                elif (r, c) in self.clue_values:
                    self.canvas.create_oval(
                        x1 + 12, y1 + 12, x2 - 12, y2 - 12,
                        fill="#444444", outline=""
                    )
                    self.canvas.create_text(
                        (x1 + x2) / 2,
                        (y1 + y2) / 2,
                        text=str(self.clue_values[(r, c)]),
                        font=("Arial", 20, "bold"),
                        fill="white"
                    )
                else:
                    self.canvas.create_rectangle(
                        x1, y1, x2, y2,
                        fill="white", outline="white"
                    )

        total_steps = len(self.swaps)
        correct_count = sum(
            1 for pos in self.board
            if self.board[pos] == self.solution[pos]
        )
        self.status.config(text=f"Step {self.step_index} / {total_steps}    Correct tiles: {correct_count}/{len(self.board)}")

    def apply_steps(self, n):
        self.board = dict(self.initial_board)
        for i in range(n):
            a, b = self.swaps[i]
            self.board[a], self.board[b] = self.board[b], self.board[a]

    def reset_board(self):
        self.stop_autoplay()
        self.step_index = 0
        self.apply_steps(self.step_index)
        self.draw()

    def next_step(self):
        self.stop_autoplay()
        if self.step_index < len(self.swaps):
            a, b = self.swaps[self.step_index]
            self.board[a], self.board[b] = self.board[b], self.board[a]
            self.step_index += 1
            self.draw(highlight={a, b})

    def prev_step(self):
        self.stop_autoplay()
        if self.step_index > 0:
            self.step_index -= 1
            self.apply_steps(self.step_index)
            a, b = self.swaps[self.step_index]
            self.draw(highlight={a, b})

    def autoplay(self):
        if self.autoplay_job is None:
            self._autoplay_step()

    def _autoplay_step(self):
        if self.step_index < len(self.swaps):
            a, b = self.swaps[self.step_index]
            self.board[a], self.board[b] = self.board[b], self.board[a]
            self.step_index += 1
            self.draw(highlight={a, b})
            self.autoplay_job = self.root.after(700, self._autoplay_step)
        else:
            self.autoplay_job = None

    def stop_autoplay(self):
        if self.autoplay_job is not None:
            self.root.after_cancel(self.autoplay_job)
            self.autoplay_job = None

    def run(self):
        self.root.mainloop()


# ------------------------------------------------------------
# PUZZLE DATA
# ------------------------------------------------------------

values = {
    (0,0):7, (0,1):6, (0,2):3, (0,3):7, (0,4):4, (0,5):3, (0,6):4,
    (1,0):1,          (1,2):6,          (1,4):3,          (1,6):2,
    (2,0):4, (2,1):6, (2,2):5, (2,3):6, (2,4):7, (2,5):7, (2,6):2,
    (3,0):6,          (3,2):5,          (3,4):7,          (3,6):1,
    (4,0):1, (4,1):3, (4,2):4, (4,3):5, (4,4):2, (4,5):7, (4,6):3,
    (5,0):6,          (5,2):2,          (5,4):7,          (5,6):6,
    (6,0):1, (6,1):1, (6,2):2, (6,3):6, (6,4):5, (6,5):5, (6,6):1,
}

locked = {
    (0,2), (0,4),
    (2,0), (2,2),(2,3), (2,4), (2,6),
    (4,0), (4,2), (4,3), (4,4), (4,6),
    (6,2), (6,4),
}

sum_constraints = [
    ((0,1), (1,0), 8),
    ((0,3), (1,4), 12),
    ((0,5), (1,6), 12),
    ((2,1), (3,0), 3),
    ((4,3), (3,2), 12),
    ((2,5), (3,4), 6),
    ((6,1), (5,0), 13),
    ((6,3), (5,2), 13),
    ((4,5), (5,6), 13),
]

clue_values = {
    (1,1): 8,
    (1,3): 12,
    (1,5): 12,
    (3,1): 3,
    (3,3): 12,
    (3,5): 6,
    (5,1): 13,
    (5,3): 13,
    (5,5): 13,
}


# ------------------------------------------------------------
# SOLVE + VISUALIZE
# ------------------------------------------------------------

solver = NumberWaffleSolver(values, locked, sum_constraints)
solution = solver.solve_board()

if solution is None:
    print("No solution found.")
else:
    swaps = solver.make_swap_sequence(solution)
    print("Solution found.")
    print("Swaps:", swaps)

    app = WaffleVisualizer(values, solution, clue_values, swaps)
    app.run()