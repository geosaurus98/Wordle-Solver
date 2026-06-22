from __future__ import annotations

from dataclasses import dataclass

Digits = set[int]


ALL_DIGITS: Digits = set(range(1, 10))


@dataclass(frozen=True)
class SudokuBoard:
    """
    9x9 Sudoku board with 0 for empty cells.
    """

    cells: tuple[tuple[int, ...], ...]

    @staticmethod
    def from_rows(rows: list[list[int]]) -> "SudokuBoard":
        if len(rows) != 9 or any(len(r) != 9 for r in rows):
            raise ValueError("Sudoku board must be 9x9")
        for r in rows:
            for v in r:
                if not isinstance(v, int) or v < 0 or v > 9:
                    raise ValueError("Board values must be integers in [0,9]")
        return SudokuBoard(cells=tuple(tuple(v for v in row) for row in rows))

    def to_rows(self) -> list[list[int]]:
        return [list(r) for r in self.cells]


def _box_origin(r: int, c: int) -> tuple[int, int]:
    return (r // 3) * 3, (c // 3) * 3


def _candidate_map(board: list[list[int]]) -> dict[tuple[int, int], Digits]:
    cands: dict[tuple[int, int], Digits] = {}
    for r in range(9):
        for c in range(9):
            if board[r][c] != 0:
                continue
            used: Digits = set(board[r][x] for x in range(9) if board[r][x] != 0)
            used |= set(board[y][c] for y in range(9) if board[y][c] != 0)
            br, bc = _box_origin(r, c)
            for y in range(br, br + 3):
                for x in range(bc, bc + 3):
                    if board[y][x] != 0:
                        used.add(board[y][x])
            opts = ALL_DIGITS - used
            cands[(r, c)] = opts
    return cands


def _is_complete(board: list[list[int]]) -> bool:
    return all(board[r][c] != 0 for r in range(9) for c in range(9))


def _validate_no_duplicates(board: list[list[int]]) -> bool:
    def ok_group(vals: list[int]) -> bool:
        nz = [v for v in vals if v != 0]
        return len(nz) == len(set(nz))

    for r in range(9):
        if not ok_group([board[r][c] for c in range(9)]):
            return False
    for c in range(9):
        if not ok_group([board[r][c] for r in range(9)]):
            return False
    for br in (0, 3, 6):
        for bc in (0, 3, 6):
            group: list[int] = []
            for r in range(br, br + 3):
                for c in range(bc, bc + 3):
                    group.append(board[r][c])
            if not ok_group(group):
                return False
    return True


def _apply_constraint_propagation(board: list[list[int]]) -> bool:
    """
    Repeatedly apply:
    - naked singles
    - hidden singles (row / col / box)
    Returns False if contradiction appears.
    """
    while True:
        changed = False
        cands = _candidate_map(board)

        for (r, c), opts in cands.items():
            if len(opts) == 0:
                return False
            if len(opts) == 1:
                board[r][c] = next(iter(opts))
                changed = True

        if changed:
            continue

        cands = _candidate_map(board)

        # Hidden singles in rows
        for r in range(9):
            needed = {d: [] for d in range(1, 10)}
            for c in range(9):
                if board[r][c] != 0:
                    continue
                for d in cands[(r, c)]:
                    needed[d].append((r, c))
            for d, spots in needed.items():
                if len(spots) == 1:
                    rr, cc = spots[0]
                    board[rr][cc] = d
                    changed = True

        if changed:
            continue

        # Hidden singles in columns
        for c in range(9):
            needed = {d: [] for d in range(1, 10)}
            for r in range(9):
                if board[r][c] != 0:
                    continue
                for d in cands[(r, c)]:
                    needed[d].append((r, c))
            for d, spots in needed.items():
                if len(spots) == 1:
                    rr, cc = spots[0]
                    board[rr][cc] = d
                    changed = True

        if changed:
            continue

        # Hidden singles in boxes
        for br in (0, 3, 6):
            for bc in (0, 3, 6):
                needed = {d: [] for d in range(1, 10)}
                for r in range(br, br + 3):
                    for c in range(bc, bc + 3):
                        if board[r][c] != 0:
                            continue
                        for d in cands[(r, c)]:
                            needed[d].append((r, c))
                for d, spots in needed.items():
                    if len(spots) == 1:
                        rr, cc = spots[0]
                        board[rr][cc] = d
                        changed = True

        if not changed:
            # Check no empty cell has zero options.
            cands = _candidate_map(board)
            if any(len(opts) == 0 for opts in cands.values()):
                return False
            return True


def _search(board: list[list[int]]) -> list[list[int]] | None:
    if not _validate_no_duplicates(board):
        return None
    if not _apply_constraint_propagation(board):
        return None
    if _is_complete(board):
        return board

    cands = _candidate_map(board)
    (r, c), opts = min(cands.items(), key=lambda kv: len(kv[1]))
    if not opts:
        return None

    for d in sorted(opts):
        nxt = [row[:] for row in board]
        nxt[r][c] = d
        solved = _search(nxt)
        if solved is not None:
            return solved
    return None


def solve_sudoku(board: SudokuBoard) -> SudokuBoard:
    rows = board.to_rows()
    solved = _search(rows)
    if solved is None:
        raise ValueError("Sudoku puzzle appears unsatisfiable")
    return SudokuBoard.from_rows(solved)

