"""agentic_administration server package — the canonical model lives in
`server.model`, the board config in `server.config`, the secret boundary in
`server.secrets`; the MCP server is `server.mcp_app` over the domain
service `server.service` (run it with `python -m server <board.toml>`, or
`python -m server boards/` for every board in a directory)."""

from importlib import metadata

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

# What both MCP servers report to a host; pyproject.toml holds the number.
try:
    __version__ = metadata.version("agentic-administration")
except metadata.PackageNotFoundError:  # run from a checkout that was never installed
    __version__ = ""
