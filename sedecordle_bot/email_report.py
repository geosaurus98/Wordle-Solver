from __future__ import annotations

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .game_result import GameResult

_EMOJI = {0: "⬛", 1: "\U0001f7e8", 2: "\U0001f7e9"}  # ⬛ 🟨 🟩

_GAME_COLORS = {
    "Wordle": "#538d4e",
    "Dordle": "#b59f3b",
    "Quordle": "#3a7dc9",
    "Octordle": "#c97d3a",
    "Sedecordle": "#9b3ac9",
    "Waffle": "#c93a3a",
    "NumberWaffle": "#e07b39",
    "Tilerdle": "#3a9bc9",
}


def _fb_emoji(feedback: list[int]) -> str:
    return "".join(_EMOJI[f] for f in feedback)


def _guess_table_single(board_guesses: list[dict]) -> str:
    rows = []
    for i, g in enumerate(board_guesses):
        emoji = _fb_emoji(g["feedback"])
        cb = g.get("candidates_before", "?")
        ca = g.get("candidates_after", "?")
        rows.append(
            f'<tr>'
            f'<td style="color:#888;padding:2px 8px 2px 0;font-size:0.85em">{i+1}</td>'
            f'<td style="font-family:monospace;font-weight:bold;letter-spacing:2px;padding:2px 10px 2px 0">'
            f'{g["word"].upper()}</td>'
            f'<td style="font-size:1.1em;padding:2px 10px 2px 0">{emoji}</td>'
            f'<td style="color:#888;font-size:0.8em">{cb}&rarr;{ca}</td>'
            f'</tr>'
        )
    return "<table>" + "".join(rows) + "</table>"


def _guess_table_multi(board_guesses_all: list[list[dict]], board_answers: list[str | None]) -> str:
    """Build a shared-guess table showing all boards side by side."""
    num_boards = len(board_guesses_all)
    max_turns = max((len(bg) for bg in board_guesses_all), default=0)
    if max_turns == 0:
        return "<p>No guesses recorded.</p>"

    header_cells = '<th style="padding:2px 6px">#</th><th style="padding:2px 10px">Guess</th>'
    for bi in range(num_boards):
        ans = board_answers[bi] if board_answers and bi < len(board_answers) else None
        label = f"Board {bi+1}" + (f"<br><small>{ans.upper() if ans else '?'}</small>" if ans else "")
        header_cells += f'<th style="padding:2px 8px;text-align:center">{label}</th>'

    rows = [f'<tr>{header_cells}</tr>']

    # Collect all (turn_index, guess, feedback_per_board) rows
    # board_guesses_all[bi][turn] but turns may differ if a board was solved early.
    # Build a unified sequence by matching on the guess word.
    unified: list[tuple[str, list[list[int] | None]]] = []
    seen_words: dict[str, list[list[int] | None]] = {}
    for bi, bg in enumerate(board_guesses_all):
        for step in bg:
            w = step["word"]
            if w not in seen_words:
                seen_words[w] = [None] * num_boards
                unified.append((w, seen_words[w]))
            seen_words[w][bi] = step["feedback"]

    for turn_i, (word, feedbacks) in enumerate(unified):
        cells = (
            f'<td style="color:#888;font-size:0.85em;padding:2px 6px">{turn_i+1}</td>'
            f'<td style="font-family:monospace;font-weight:bold;letter-spacing:2px;padding:2px 10px">'
            f'{word.upper()}</td>'
        )
        for bi in range(num_boards):
            fb = feedbacks[bi]
            if fb is None:
                cells += '<td style="text-align:center;color:#ccc">—</td>'
            else:
                solved_mark = " ✓" if is_all_correct(fb) else ""
                cells += f'<td style="text-align:center;font-size:1.05em">{_fb_emoji(fb)}{solved_mark}</td>'
        rows.append(f'<tr>{cells}</tr>')

    return '<table style="border-collapse:collapse">' + "".join(rows) + "</table>"


def is_all_correct(fb: list[int]) -> bool:
    return len(fb) == 5 and all(x == 2 for x in fb)


def _waffle_grid_html(_initial_grid: dict, solution_words: dict) -> str:
    """Show the solution words for the Waffle puzzle."""
    slot_labels = {
        "R0": "Row 1", "R2": "Row 2 (mid)", "R4": "Row 3",
        "C0": "Col 1", "C2": "Col 2 (mid)", "C4": "Col 3",
    }
    if not solution_words:
        return ""
    lines = []
    for slot, word in sorted(solution_words.items()):
        label = slot_labels.get(slot, slot)
        lines.append(f'<li><strong>{label}:</strong> {word.upper()}</li>')
    return "<ul style='margin:8px 0'>" + "".join(lines) + "</ul>"


def _numberwaffle_grid_html(solution_grid: dict[str, str]) -> str:
    """Render the 7x7 NumberWaffle solution as an HTML table."""
    td_tile = (
        'style="width:26px;height:26px;text-align:center;vertical-align:middle;'
        'background:#f5f5f5;font-family:monospace;font-weight:bold;font-size:1em;'
        'border:1px solid #ddd"'
    )
    td_clue = (
        'style="width:26px;height:26px;text-align:center;vertical-align:middle;'
        'background:#e0e0e0;color:#aaa;font-size:0.8em;border:1px solid #ddd"'
    )
    rows = []
    for y in range(7):
        cells = []
        for x in range(7):
            if x % 2 == 1 and y % 2 == 1:
                cells.append(f'<td {td_clue}>·</td>')
            else:
                digit = solution_grid.get(f"{x},{y}", "?")
                cells.append(f'<td {td_tile}>{digit}</td>')
        rows.append(f'<tr>{"".join(cells)}</tr>')
    return (
        '<table style="border-collapse:collapse;margin:8px 0">'
        + "".join(rows)
        + "</table>"
    )


def _game_card_html(gr: GameResult) -> str:
    color = _GAME_COLORS.get(gr.game, "#538d4e")

    if gr.error:
        body = f'<p style="color:#c0392b"><strong>Error:</strong> {gr.error}</p>'
        status = "❌ Error"
    elif gr.game == "NumberWaffle":
        extra = gr.extra or {}
        n_swaps = len(gr.waffle_swaps) if gr.waffle_swaps else 0
        swaps_remaining = extra.get("swaps_remaining", "?")
        puzzle_num = extra.get("puzzle_number", "?")
        solution_grid = extra.get("solution_grid", {})
        if gr.waffle_swaps is not None:
            swap_list = "".join(
                f'<li>{i+1}. ({s.from_pos[0]},{s.from_pos[1]}) {s.from_letter}'
                f' ↔ ({s.to_pos[0]},{s.to_pos[1]}) {s.to_letter}</li>'
                for i, s in enumerate(gr.waffle_swaps)
            )
            body = (
                f"<p><strong>Puzzle #{puzzle_num}</strong> &nbsp;|&nbsp; "
                f"<strong>Swaps needed:</strong> {n_swaps} "
                f"<span style='color:#888'>(of {swaps_remaining} allowed)</span></p>"
                + "<p style='margin:4px 0'><strong>Solution grid:</strong></p>"
                + _numberwaffle_grid_html(solution_grid)
                + f'<ol style="font-family:monospace;margin-top:8px">{swap_list}</ol>'
            )
            status = f"✅ {n_swaps} swaps"
        else:
            body = "<p>No NumberWaffle data captured.</p>"
            status = "?"
    elif gr.game == "Tilerdle":
        extra = gr.extra or {}
        theme = extra.get("theme", "?")
        grid_size = extra.get("grid_size", "?")
        # Support both old ("words") and new ("across"/"down") formats.
        across_words = extra.get("across") or extra.get("words") or []
        down_words = extra.get("down") or []
        total = len(across_words) + len(down_words)
        if total:
            def _word_li(w: str, color: str) -> str:
                return (
                    f'<li style="font-family:monospace;font-weight:bold;'
                    f'letter-spacing:2px;color:{color}">{w}</li>'
                )
            across_items = "".join(_word_li(w, "#1a1a1a") for w in across_words)
            down_items = "".join(_word_li(w, "#555") for w in down_words)

            sections = []
            if across_items:
                sections.append(
                    f'<p style="margin:6px 0 2px"><strong>Across</strong></p>'
                    f'<ul style="margin:4px 0 8px">{across_items}</ul>'
                )
            if down_items:
                sections.append(
                    f'<p style="margin:6px 0 2px"><strong>Down</strong>'
                    f' <span style="color:#aaa;font-size:0.8em;font-weight:normal">'
                    f'(partial — _ = intersection letter)</span></p>'
                    f'<ul style="margin:4px 0 8px">{down_items}</ul>'
                )

            body = (
                f'<p><strong>Theme:</strong> {theme} &nbsp;|&nbsp; '
                f'<strong>Grid:</strong> {grid_size}×{grid_size}</p>'
                + "".join(sections)
            )
            status = (
                f"✅ {len(across_words)} across"
                + (f" + {len(down_words)} down (partial)" if down_words else "")
            )
        else:
            body = f"<p>Theme: {theme}</p><p>No words extracted.</p>"
            status = "?"
    elif gr.game == "Waffle":
        if gr.waffle_swaps is not None and gr.waffle_words is not None:
            n_swaps = len(gr.waffle_swaps)
            swap_list = "".join(
                f'<li>{i+1}. ({s.from_pos[0]},{s.from_pos[1]}) {s.from_letter.upper()}'
                f' ↔ ({s.to_pos[0]},{s.to_pos[1]}) {s.to_letter.upper()}</li>'
                for i, s in enumerate(gr.waffle_swaps)
            )
            body = (
                f"<p><strong>Swaps needed:</strong> {n_swaps}</p>"
                + _waffle_grid_html({}, gr.waffle_words)
                + f'<ol style="font-family:monospace;margin-top:8px">{swap_list}</ol>'
            )
            status = f"✅ {n_swaps} swaps"
        else:
            body = "<p>No waffle data captured.</p>"
            status = "?"
    else:
        # Wordle-style games
        boards = gr.boards
        if not boards:
            body = "<p>No board data.</p>"
            status = "?"
        elif len(boards) == 1:
            b = boards[0]
            answer_line = (
                f'<p style="font-size:1.15em"><strong>Answer: '
                f'<span style="color:{color}">{b.answer.upper() if b.answer else "?"}</span></strong></p>'
            )
            body = answer_line + _guess_table_single([
                {"word": g.word, "feedback": g.feedback,
                 "candidates_before": g.candidates_before, "candidates_after": g.candidates_after}
                for g in b.guesses
            ])
            status = (
                f"✅ {b.turns_used()} guesses" if b.solved else "❌ Not solved"
            )
        else:
            # Multi-board
            answers = [b.answer for b in boards]
            answers_str = " &nbsp;|&nbsp; ".join(
                f'<span style="color:{color};font-weight:bold">'
                f'{(a or "?").upper()}</span>'
                for a in answers
            )
            answer_line = f'<p><strong>Answers:</strong> {answers_str}</p>'
            board_guesses_all = [
                [{"word": g.word, "feedback": g.feedback,
                  "candidates_before": g.candidates_before, "candidates_after": g.candidates_after}
                 for g in b.guesses]
                for b in boards
            ]
            body = answer_line + _guess_table_multi(board_guesses_all, answers)
            solved = gr.solved_count
            total = gr.total_boards
            status = f"✅ {solved}/{total}" if solved == total else f"⚠️ {solved}/{total}"

    return f"""
<div style="background:white;border-radius:10px;margin:16px 0;padding:16px 20px;
            border-left:5px solid {color};box-shadow:0 2px 6px rgba(0,0,0,0.08)">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
    <span style="font-size:1.3em;font-weight:bold;color:#1a1a1a">{gr.game}</span>
    <span style="font-size:0.9em;color:#555">{status}</span>
  </div>
  {body}
  <p style="font-size:0.75em;color:#aaa;margin-top:10px">
    <a href="{gr.url}" style="color:#aaa">{gr.url}</a>
  </p>
</div>
"""


def build_html_report(date_str: str, results: list[GameResult]) -> str:
    cards = "".join(_game_card_html(gr) for gr in results)
    def _is_success(gr: GameResult) -> bool:
        if gr.error:
            return False
        if gr.game in ("Waffle", "NumberWaffle"):
            return gr.waffle_swaps is not None
        if gr.game == "Tilerdle":
            e = gr.extra or {}
            return bool(e.get("across") or e.get("words"))
        return gr.all_solved

    solved_summary = ", ".join(
        f"{gr.game} {'✅' if _is_success(gr) else '❌'}"
        for gr in results
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Daily Puzzles &mdash; {date_str}</title>
</head>
<body style="font-family:Arial,Helvetica,sans-serif;background:#f0f0f0;margin:0;padding:16px">
<div style="max-width:720px;margin:0 auto">
  <div style="background:#1a1a2e;color:white;border-radius:10px;padding:20px 24px;margin-bottom:8px">
    <h1 style="margin:0;font-size:1.5em">Daily Puzzles</h1>
    <p style="margin:6px 0 0;color:#aaa;font-size:0.9em">{date_str} &nbsp;&mdash;&nbsp; {solved_summary}</p>
  </div>
  {cards}
  <p style="text-align:center;color:#aaa;font-size:0.75em;margin-top:24px">
    Generated by daily-puzzle-solver &mdash; George's automated solver
  </p>
</div>
</body>
</html>"""


def send_gmail(
    html: str,
    subject: str,
    to_addr: str,
    from_addr: str,
    app_password: str,
) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.attach(MIMEText(html, "html", "utf-8"))

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.ehlo()
        server.starttls(context=ctx)
        server.login(from_addr, app_password)
        server.sendmail(from_addr, to_addr, msg.as_string())
