from __future__ import annotations

from dataclasses import dataclass, field

_EMOJI = {0: "⬛", 1: "\U0001f7e8", 2: "\U0001f7e9"}  # ⬛ 🟨 🟩


@dataclass
class GuessStep:
    word: str
    feedback: list[int]  # 0=absent 1=present 2=correct
    candidates_before: int = 0
    candidates_after: int = 0

    def emoji_row(self) -> str:
        return "".join(_EMOJI[f] for f in self.feedback)


@dataclass
class BoardResult:
    board_index: int
    answer: str | None  # None if board was not solved
    guesses: list[GuessStep]
    solved: bool

    def turns_used(self) -> int:
        return len(self.guesses)


@dataclass
class WaffleSwapStep:
    from_pos: tuple[int, int]
    to_pos: tuple[int, int]
    from_letter: str
    to_letter: str

    def describe(self) -> str:
        fx, fy = self.from_pos
        tx, ty = self.to_pos
        return (
            f"({fx},{fy}) {self.from_letter.upper()}"
            f" ↔ "
            f"({tx},{ty}) {self.to_letter.upper()}"
        )


@dataclass
class GameResult:
    game: str
    url: str
    date: str
    boards: list[BoardResult] = field(default_factory=list)
    waffle_swaps: list[WaffleSwapStep] | None = None
    waffle_words: dict[str, str] | None = None  # slot_name -> word e.g. {"R0": "crane"}
    extra: dict | None = None  # game-specific extra data
    error: str | None = None

    @property
    def solved_count(self) -> int:
        return sum(1 for b in self.boards if b.solved)

    @property
    def total_boards(self) -> int:
        return len(self.boards)

    @property
    def all_solved(self) -> bool:
        return self.total_boards > 0 and self.solved_count == self.total_boards

    @property
    def max_turns_used(self) -> int:
        return max((b.turns_used() for b in self.boards), default=0)
