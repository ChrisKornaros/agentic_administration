"""agentic_administration server package — the canonical model lives in
`server.model`, the board config in `server.config`, the secret boundary in
`server.secrets`; the MCP server is `server.mcp_app` over the domain
service `server.service` (run it with `python -m server <board.toml>`)."""

from server.model import (  # noqa: F401  (re-exported surface)
    CollapseRule,
    CollapseTarget,
    Capabilities,
    Comment,
    DescriptionFormat,
    InvalidWorkItem,
    ItemRef,
    Iteration,
    IterationState,
    Level,
    Materialization,
    State,
    WorkItem,
    to_jsonable,
)
