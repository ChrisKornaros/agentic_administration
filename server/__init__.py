"""agentic_administration server package — the canonical model lives in
`server.model`; the MCP server and skills arrive in Phase 3."""

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
