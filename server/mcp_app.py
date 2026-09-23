"""The MCP server: eleven domain tools over `BoardService` (design:
agentic_optimization_research roadmap/14 §5 layer 3, D11–D13), on the
official `mcp` SDK's `MCPServer`.

Each tool is a thin wrapper. The conventions, the drafts and the error
wording live in `server.service`. A `ToolFailure` becomes a `ToolError`,
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

from server.service import BoardService, ToolFailure

LevelName = Literal["initiative", "epic", "feature", "story", "bug", "task"]
StateName = Literal["backlog", "todo", "in_progress", "done", "cancelled"]

READ = ToolAnnotations(read_only_hint=True)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False)

INSTRUCTIONS = """\
Backlog administration for one board, over a canonical work-item model
(initiative > epic > feature > story / bug > task). Start with describe_board.
Creating an item takes two calls: propose_item checks the draft and returns a
preview and a token; show the preview to the requester and, once they say yes,
call commit_item with that token. When describe_board reports confirm =
"never", commit without pausing. Nothing can be deleted: finish work by
setting its state to done or cancelled."""


def build(service: BoardService) -> MCPServer:
    mcp = MCPServer("agentic-administration", instructions=INSTRUCTIONS)

    def call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except ToolFailure as exc:
            raise ToolError(str(exc)) from None

    # -- reads --------------------------------------------------------------

    @mcp.tool(annotations=READ)
    def describe_board() -> dict[str, Any]:
        """Read the live board and check the board config against it: work-item
        types, states, labels, members, features (modules), iterations, the
        capabilities record, the confirm mode and the naming rules. `problems`
        lists every mismatch, and every write refuses until it is empty. Call
        it first, and again after the board changes."""
        return call(service.describe_board)

    @mcp.tool(annotations=READ)
    def find_items(
        query: str = "",
        external_id: str | None = None,
        level: LevelName | None = None,
        state: StateName | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search the board's work items. `query` is free text on titles;
        `external_id` is an exact idempotency-key lookup; `level` and `state`
        narrow the result. With no arguments, lists the board. Use get_item
        for a known key such as AA-12."""
        return {"items": call(service.find_items, query, external_id=external_id,
                              level=level, state=state, limit=limit)}

    @mcp.tool(annotations=READ)
    def get_item(ref: str) -> dict[str, Any]:
        """One work item by its key (e.g. AA-12) or id, with its current labels,
        state, parent, feature and iteration."""
        return call(service.get_item, ref)

    @mcp.tool(annotations=READ)
    def get_iteration(iteration: str) -> dict[str, Any]:
        """One iteration (sprint / cycle) by name or id, with its dates and its
        state (planned, active or closed) as the tracker reports it now."""
        return call(service.get_iteration, iteration)

    # -- create: propose, then commit -----------------------------------------

    @mcp.tool(annotations=READ)
    def propose_item(
        intake_id: str,
        level: LevelName,
        title: str,
        description: str = "",
        part: str = "",
        parent: str | None = None,
        feature: str | None = None,
        initiative: str | None = None,
        component: str | None = None,
        iteration: str | None = None,
        assignees: list[str] | None = None,
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        """Draft a new work item and check it against the live board. Writes
        nothing. Returns a token (valid 30 minutes), the preview to show the
        requester, and any warnings, such as a suggested title when the board's
        title case isn't met. The server adds the review label and sets
        external_id to `intake_id`, or `intake_id/part` when one intake becomes
        several items (e.g. part="story-2"). `description` is Markdown. `parent`
        is a key or id (a story's or bug's epic, a task's story or bug);
        `feature` names one of the board's features; `iteration` is an open
        iteration's name or id. To change anything, propose again."""
        return call(
            service.propose_item, intake_id, level, title, description,
            part=part, parent=parent, feature=feature, initiative=initiative,
            component=component, iteration=iteration,
            assignees=assignees or (), labels=labels or (),
        )

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True))
    def commit_item(token: str) -> dict[str, Any]:
        """Create exactly the item propose_item previewed under this token.
        Call it only after the requester has confirmed, unless the board's
        confirm mode is "never". Safe to retry with the same token: if the item
        already exists, it is returned (`already_existed`), not duplicated."""
        return call(service.commit_item, token)

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
    ) -> dict[str, Any]:
        """Change fields of an existing item; omitted fields stay as they are.
        `labels` and `assignees` REPLACE the whole set, so call get_item first
        and send the full list. The product owner's review clears the review
        label this way. Retire work with state "done" or "cancelled"; it cannot
        be deleted."""
        return call(service.update_item, ref, title=title, description=description, state=state,
                    assignees=assignees, labels=labels, parent=parent, feature=feature)

    @mcp.tool(annotations=WRITE)
    def add_comment(ref: str, body: str) -> dict[str, Any]:
        """Add a Markdown comment to an item (by key or id)."""
        return call(service.add_comment, ref, body)

    @mcp.tool(annotations=WRITE)
    def create_iteration(name: str, start: str | None = None, end: str | None = None) -> dict[str, Any]:
        """Create an iteration (sprint / cycle). The name must follow the
        board's naming.iteration pattern (e.g. 202610); `start` and `end` are
        ISO dates."""
        return call(service.create_iteration, name, start, end)

    @mcp.tool(annotations=WRITE)
    def move_to_iteration(items: list[str], iteration: str) -> dict[str, Any]:
        """Put items (keys or ids) into an open iteration (name or id)."""
        return call(service.move_to_iteration, items, iteration)

    @mcp.tool(annotations=WRITE)
    def close_iteration(iteration: str) -> dict[str, Any]:
        """Close an iteration (name or id). Items still open stay where they
        are. Rollover means closing and then moving those items with
        move_to_iteration."""
        return call(service.close_iteration, iteration)

    return mcp
