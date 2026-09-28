"""Jira's side of the suite: building the adapter, and checking a project is
ready for the generic cases.

Nothing on a Jira project is provisioned by API here. Labels are
free-form (one exists once an issue carries it), and issue types, the
hierarchy and workflow statuses are Jira admin settings. So `provision`
reads the board and, when the config does not fit, stops for the operator
with what to change (the Phase 5 probe, 2026-09-27).
"""

from __future__ import annotations

from datetime import date
from typing import Callable

from adapters.jira.adapter import JiraAdapter
from adapters.jira.transport import DEFAULT_THROTTLE, JiraTransport
from conformance.cases import Context, NeedsOperator
from server import secrets
from server.config import BoardConfig
from server.model import State


def make_adapter(
    config: BoardConfig, *, throttle: float = DEFAULT_THROTTLE, today: Callable[[], date] = date.today,
) -> tuple[JiraAdapter, Callable[[], list[tuple[str, str]]]]:
    """The adapter on a real transport, plus that transport's wire log."""
    conn = config.connection
    user_env = conn.user_env or ""
    transport = JiraTransport(conn.base_url or conn.ids["site"], lambda: secrets.get(user_env),
                              lambda: secrets.get(conn.token_env), throttle=throttle)
    return JiraAdapter(config, transport, today=today), lambda: transport.log


def provision(ctx: Context) -> None:
    a = ctx.adapter
    assert isinstance(a, JiraAdapter)
    board = a.describe_board()
    if board.problems:
        raise NeedsOperator(
            "the project does not fit the config; fix it in Jira (work types, the hierarchy, the workflow's "
            "statuses, the board) or in the config, then re-run: " + "; ".join(board.problems)
        )
    ctx.note(f"{board.features.get('style')} project {board.project_key}, {board.features.get('board_type')} "
             f"board {a.board_id}: nothing to create (labels are free-form; types and statuses are Jira settings)")
    by_name = {s.name.lower(): s for s in board.states}
    ctx.note("statuses and their categories: " + ", ".join(
        f"{state.value} = {name} [{by_name[name.lower()].group}]" for state, name in ctx.config.states.items()))
    cancelled = by_name[ctx.config.states[State.CANCELLED].lower()]
    if cancelled.group != "done":
        ctx.note(f"{cancelled.name!r} sits in the {cancelled.group!r} category, so Jira's sprint close and "
                 "reports count cancelled work as unfinished")
