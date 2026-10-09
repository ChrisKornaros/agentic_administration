"""The MCP server: eleven domain tools over `Boards`, one `BoardService` per
board (design: agentic_optimization_research roadmap/14 §5 layer 3,
D11–D13, D43), on the official `mcp` SDK's `MCPServer`.

Each tool is a thin wrapper, and each takes the `board` it acts on, which
may be left out when the server serves one. The conventions, the drafts and
the error wording live in `server.service`. A `ToolFailure` becomes a `ToolError`,
which the client sees as an `is_error` result carrying that message; the
SDK keeps any other exception's text on the server. No tool deletes: the
annotations mark every write non-destructive, and work ends as `done` or
`cancelled`.
"""

from __future__ import annotations

from typing import Any, Callable, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from schema.intake import Intake
from server.model import to_jsonable
from server.service import Boards, BoardService, ToolFailure

LevelName = Literal["initiative", "epic", "feature", "story", "bug", "task"]
StateName = Literal["backlog", "todo", "in_progress", "done", "cancelled"]

READ = ToolAnnotations(read_only_hint=True)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False)

INSTRUCTIONS = """\
Backlog administration for one board or several, over a canonical work-item
model (initiative > epic > feature > story / bug > task). Start with
describe_board. When it lists several boards, use the one the request names,
or ask the requester which one, then pass that board to every tool and name
it in what you show them. Creating an item takes two calls: propose_item
checks the draft and returns a preview and a token; show the preview to the
requester and, once they say yes, call commit_item with that token. When describe_board reports confirm =
"never", commit without pausing. Nothing can be deleted: finish work by
setting its state to done or cancelled."""


def build(boards: Boards) -> MCPServer:
    mcp = MCPServer("agentic-administration", instructions=INSTRUCTIONS)

    def call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except ToolFailure as exc:
            raise ToolError(str(exc)) from None

    def on(board: str | None) -> BoardService:
        return call(boards.get, board)

    # -- reads --------------------------------------------------------------

    @mcp.tool(annotations=READ)
    def describe_board(board: str | None = None) -> dict[str, Any]:
        """Read the live board and check the board config against it: work-item
        types, states, labels, members, features (modules), iterations, the
        custom `fields` (each with its kind, options and the levels that carry
        it), the capabilities record, the board type, the confirm mode, the
        review label (null when review is off), the naming rules and the item
        `templates` (each with its level, title pattern, description skeleton,
        feature, labels, field values, state, and the weekdays `days` it fills
        with the date `dates` says). `problems` lists every mismatch, and every
        write refuses until it is empty. Call it first, and again after the
        board changes.

        When the server serves several boards and no `board` is given, it
        lists them instead (`boards`: each one's name, description, backend,
        board type and project), reading no tracker. Every tool takes the
        `board` it acts on by that name; with one board it may be left out."""
        return call(boards.describe_board, board)

    @mcp.tool(annotations=READ)
    def find_items(
        query: str = "",
        external_id: str | None = None,
        level: LevelName | None = None,
        state: StateName | None = None,
        iteration: str | None = None,
        label: str | None = None,
        limit: int = 20,
        board: str | None = None,
    ) -> dict[str, Any]:
        """Search the board's work items. `query` is free text on titles;
        `external_id` is an exact idempotency-key lookup; `level` and `state`
        narrow the result; `iteration` (a name or id) keeps the items that are
        in that iteration now, a closed one included, which is what a rollover
        reads; `label` keeps the items carrying that label, so the board's
        review label gives the review queue. With no arguments, lists the
        board. Use get_item for a known key such as AA-12."""
        return {"items": call(on(board).find_items, query, external_id=external_id, level=level,
                              state=state, iteration=iteration, label=label, limit=limit)}

    @mcp.tool(annotations=READ)
    def get_item(ref: str, board: str | None = None) -> dict[str, Any]:
        """One work item by its key (e.g. AA-12) or id, with its current labels,
        state, parent, feature, iteration, dates and custom-field values."""
        return call(on(board).get_item, ref)

    @mcp.tool(annotations=READ)
    def get_iteration(iteration: str, board: str | None = None) -> dict[str, Any]:
        """One iteration (sprint / cycle) by name or id, with its dates and its
        state (planned, active or closed) as the tracker reports it now."""
        return call(on(board).get_iteration, iteration)

    # -- create: propose, then commit -----------------------------------------

    @mcp.tool(annotations=READ)
    def propose_item(
        intake: Intake | None = None,
        part: str = "",
        template: str = "",
        intake_id: str = "",
        level: LevelName | None = None,
        title: str = "",
        description: str = "",
        parent: str | None = None,
        feature: str | None = None,
        initiative: str | None = None,
        component: str | None = None,
        iteration: str | None = None,
        assignees: list[str] | None = None,
        labels: list[str] | None = None,
        start_date: str | None = None,
        target_date: str | None = None,
        fields: dict[str, Any] | None = None,
        board: str | None = None,
    ) -> dict[str, Any]:
        """Draft a new work item and check it against the live board. Writes
        nothing. Returns the board's name, a token (valid 30 minutes), the
        preview to show the requester, and any warnings, such as a suggested
        title when the board's title case isn't met. The server adds the review
        label when the board has one and sets external_id to `intake_id`, or
        `intake_id/part` when one intake becomes several items.

        From an intake record (the usual path): pass `intake` and, when it has
        several parts, the `part` to propose. The record supplies the id, level,
        title, placement and the Markdown description with its acceptance
        criteria, so leave those arguments out. A part whose parent is
        `#<part>` needs that part committed first.

        Without a record: pass `intake_id`, `level` and `title`. `description`
        is Markdown; `parent` is a key or id (a story's or bug's epic, a task's
        story or bug); `feature` names one of the board's features; `iteration`
        is an open iteration's name or id.

        From a template (one describe_board lists): pass `template` and
        `intake_id`, but not `level`. The template supplies the level, feature,
        labels, field values and state. Your title, feature and dates win, and
        your labels and field values are added. Leave `title` out to fill the
        template's title pattern from the item's date. Your `description` goes
        where the skeleton says `{description}`; a skeleton without that slot
        takes none.

        In every case, `start_date` and `target_date` are ISO dates, and `fields`
        sets the board's custom fields by the names describe_board lists: true
        or false, a number, text, an option name, or a list of option names for
        a multi-valued one. To change anything, propose again."""
        return call(
            on(board).propose_item, intake_id, level or "", title, description,
            intake=to_jsonable(intake) if intake is not None else None,
            part=part, template=template, parent=parent, feature=feature, initiative=initiative,
            component=component, iteration=iteration,
            assignees=assignees or (), labels=labels or (),
            start_date=start_date, target_date=target_date, fields=fields,
        )

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True))
    def commit_item(token: str, board: str | None = None) -> dict[str, Any]:
        """Create exactly the item propose_item previewed under this token.
        Call it only after the requester has confirmed, unless the board's
        confirm mode is "never". Safe to retry with the same token: if the item
        already exists, it is returned (`already_existed`), not duplicated. A
        token proposed on another board is refused."""
        return call(boards.commit_item, token, board)

    # -- other writes ---------------------------------------------------------

    @mcp.tool(annotations=WRITE)
    def update_item(
        ref: str,
        title: str | None = None,
        description: str | None = None,
        state: StateName | None = None,
        assignees: list[str] | None = None,
        labels: list[str] | None = None,
        parent: str | None = None,
        feature: str | None = None,
        start_date: str | None = None,
        target_date: str | None = None,
        fields: dict[str, Any] | None = None,
        board: str | None = None,
    ) -> dict[str, Any]:
        """Change fields of an existing item; omitted fields stay as they are.
        `labels` and `assignees` REPLACE the whole set, so call get_item first
        and send the full list. The product owner's review clears the review
        label this way. `start_date` / `target_date` are ISO dates; `fields`
        sets only the custom fields it names. Retire work with state "done" or
        "cancelled"; it cannot be deleted."""
        return call(on(board).update_item, ref, title=title, description=description, state=state,
                    assignees=assignees, labels=labels, parent=parent, feature=feature,
                    start_date=start_date, target_date=target_date, fields=fields)

    @mcp.tool(annotations=WRITE)
    def add_comment(ref: str, body: str, board: str | None = None) -> dict[str, Any]:
        """Add a Markdown comment to an item (by key or id)."""
        return call(on(board).add_comment, ref, body)

    @mcp.tool(annotations=WRITE)
    def create_iteration(
        name: str, start: str | None = None, end: str | None = None, board: str | None = None,
    ) -> dict[str, Any]:
        """Create an iteration (sprint / cycle), or return the one that already
        has this name; it never makes a duplicate, and refuses when the existing
        one's dates differ from those given. The name must follow the board's
        naming.iteration pattern (e.g. 202610); `start` and `end` are ISO dates.
        An iteration whose dates cover today is active afterwards, so calling
        this on its first day also starts a sprint that was created ahead of
        time."""
        return call(on(board).create_iteration, name, start, end)

    @mcp.tool(annotations=WRITE)
    def move_to_iteration(items: list[str], iteration: str, board: str | None = None) -> dict[str, Any]:
        """Put items (keys or ids) into an open iteration (name or id)."""
        return call(on(board).move_to_iteration, items, iteration)

    @mcp.tool(annotations=WRITE)
    def close_iteration(iteration: str, board: str | None = None) -> dict[str, Any]:
        """Close an iteration (name or id). Items still open stay where they
        are. Rollover is: close it, make sure the next one exists with
        create_iteration, then move what find_items(iteration=…) shows neither
        done nor cancelled with move_to_iteration."""
        return call(on(board).close_iteration, iteration)

    return mcp
