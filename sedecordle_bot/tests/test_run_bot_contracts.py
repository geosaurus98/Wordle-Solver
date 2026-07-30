"""
Guards against the kind of bug that broke Sedecordle in daily_report.py for weeks:
daily_report.py called bot.run_bot(opening_guesses=...) but that function's
parameter is actually named first_guess. The mismatch only surfaces at runtime,
inside a try/except that swallows it into an emailed "error" card nobody reads.

These tests bind the exact kwargs daily_report.py passes to each run_bot()
against its real signature, with no browser/network involved, so a renamed
or removed parameter fails a fast test instead of silently degrading a game
in production for an indefinite amount of time.
"""
from __future__ import annotations

import inspect

import pytest


def _assert_bindable(func, kwargs: dict) -> None:
    inspect.signature(func).bind(**kwargs)


def test_dordle_run_bot_kwargs():
    from sedecordle_bot.dordle_bot import run_bot, URL
    _assert_bindable(run_bot, dict(
        headful=False, slowmo_ms=0, url=URL, dry_run=False,
        user_data_dir=None, max_turns=7,
        opening_guesses=("arose", "linty", "chump"), result={},
    ))


def test_quordle_run_bot_kwargs():
    from sedecordle_bot.quordle_bot import run_bot, URL
    _assert_bindable(run_bot, dict(
        headful=False, slowmo_ms=0, url=URL, dry_run=False,
        user_data_dir=None, max_turns=9,
        opening_guesses=("arose", "linty", "chump"), result={},
    ))


def test_octordle_run_bot_kwargs():
    from sedecordle_bot.octordle_bot import run_bot, URL
    _assert_bindable(run_bot, dict(
        headful=False, slowmo_ms=0, url=URL, dry_run=False,
        user_data_dir=None, max_turns=13,
        opening_guesses=("arose", "linty", "chump"), result={},
    ))


def test_sedecordle_run_bot_kwargs():
    from sedecordle_bot.bot import run_bot, ROOT_URL
    _assert_bindable(run_bot, dict(
        headful=False, slowmo_ms=0, max_turns=21, url=ROOT_URL,
        dry_run=False, user_data_dir=None,
        first_guess="arose,linty,chump", result={},
    ))


def test_numberwaffle_run_bot_takes_no_args():
    from sedecordle_bot.numberwaffle_bot import run_bot
    _assert_bindable(run_bot, {})


def test_tilerdle_run_bot_takes_no_args():
    from sedecordle_bot.tilerdle_bot import run_bot
    _assert_bindable(run_bot, {})


@pytest.mark.parametrize("module_name", [
    "dordle_bot", "quordle_bot", "octordle_bot",
])
def test_multiboard_bots_share_opening_guesses_param(module_name):
    """These three bots are meant to have interchangeable run_bot() signatures."""
    import importlib
    mod = importlib.import_module(f"sedecordle_bot.{module_name}")
    sig = inspect.signature(mod.run_bot)
    assert "opening_guesses" in sig.parameters
    assert "result" in sig.parameters
