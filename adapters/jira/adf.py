"""Markdown ↔ Atlassian Document Format (ADF), the body shape Jira's v3 API
takes and returns for descriptions and comments. Stdlib only, the same
Markdown subset as the Plane renderer (`adapters.plane.markdown`): headings,
paragraphs, bullet / numbered lists (nested by indentation), fenced code,
block quotes, and inline bold / italic / code / links. Anything else stays
literal text.

ADF rules this respects (developer.atlassian.com, …/apis/document/): a text
node is never empty, a `code` mark combines only with `link`, and a
`listItem` holds block nodes (a paragraph), never bare text.

`to_markdown` is the read side: it walks whatever ADF Jira returns and
writes Markdown back, keeping unknown inline nodes' text where they carry
one (mentions, emoji, cards), so a description written here reads back as
the Markdown it was written from.
"""

from __future__ import annotations

import re
from typing import Any

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
_FENCE = re.compile(r"^\s*(```|~~~)\s*([\w-]*)\s*$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")

_INLINE = re.compile(
    r"(?P<code>`[^`]+`)"
    r"|(?P<link>\[(?P<ltext>[^\]]+)\]\((?P<lhref>[^)\s]+)\))"
    r"|(?P<bold>\*\*(?P<btext>[^*]+)\*\*|(?<!\w)__(?P<btext2>[^_]+)__(?!\w))"
    r"|(?P<em>\*(?P<etext>[^*]+)\*|(?<!\w)_(?P<etext2>[^_]+)_(?!\w))"
)  # underscores only at word boundaries, so snake_case_names stay literal
_SAFE_HREF = re.compile(r"^(https?://|mailto:|/|#)", re.IGNORECASE)

Node = dict[str, Any]


def empty() -> Node:
    return {"version": 1, "type": "doc", "content": []}


# --- Markdown → ADF -------------------------------------------------------------------


def _text(text: str, marks: tuple[Node, ...]) -> list[Node]:
    if not text:
        return []
    node: Node = {"type": "text", "text": text}
    if marks:
        node["marks"] = [dict(m) for m in marks]
    return [node]


def _merge(nodes: list[Node]) -> list[Node]:
    """Join neighbouring text nodes that carry the same marks."""
    out: list[Node] = []
    for n in nodes:
        prev = out[-1] if out else None
        if prev and prev["type"] == n["type"] == "text" and prev.get("marks") == n.get("marks"):
            out[-1] = {**prev, "text": prev["text"] + n["text"]}
        else:
            out.append(n)
    return out


def render_inline(text: str, marks: tuple[Node, ...] = ()) -> list[Node]:
    """Inline Markdown → ADF text nodes carrying marks."""
    return _merge(_inline(text, marks))


def _inline(text: str, marks: tuple[Node, ...]) -> list[Node]:
    out: list[Node] = []
    pos = 0
    for m in _INLINE.finditer(text):
        out += _text(text[pos : m.start()], marks)
        if m.group("code"):
            links = tuple(mk for mk in marks if mk["type"] == "link")  # code combines only with link
            out += _text(m.group("code")[1:-1], links + ({"type": "code"},))
        elif m.group("link"):
            href = m.group("lhref")
            if _SAFE_HREF.match(href):
                out += render_inline(m.group("ltext"), marks + ({"type": "link", "attrs": {"href": href}},))
            else:  # javascript: and friends stay text
                out += _text(m.group(0), marks)
        elif m.group("bold"):
            out += render_inline(m.group("btext") or m.group("btext2") or "", marks + ({"type": "strong"},))
        elif m.group("em"):
            out += render_inline(m.group("etext") or m.group("etext2") or "", marks + ({"type": "em"},))
        pos = m.end()
    out += _text(text[pos:], marks)
    return out


def _paragraph(lines: list[str]) -> Node:
    content: list[Node] = []
    for n, line in enumerate(lines):
        if n:
            content.append({"type": "hardBreak"})
        content += render_inline(line)
    return {"type": "paragraph", "content": content}


def render(markdown: str) -> Node:
    """Render a Markdown document to an ADF `doc`. Empty input → an empty doc."""
    return {"version": 1, "type": "doc", "content": _blocks(markdown)}


def _blocks(markdown: str) -> list[Node]:
    lines = markdown.replace("\r\n", "\n").split("\n")
    blocks: list[Node] = []
    para: list[str] = []
    quote: list[str] = []
    stack: list[tuple[int, Node]] = []  # open lists: (indent, bulletList / orderedList node)

    def flush_para() -> None:
        nonlocal para
        if para:
            blocks.append(_paragraph(para))
            para = []

    def flush_quote() -> None:
        nonlocal quote
        if quote:
            blocks.append({"type": "blockquote", "content": _blocks("\n".join(quote))})
            quote = []

    def flush_all() -> None:
        flush_para()
        flush_quote()
        stack.clear()

    def add_item(indent: int, kind: str, text: str) -> None:
        while stack and stack[-1][0] > indent:
            stack.pop()
        if stack and stack[-1][0] == indent and stack[-1][1]["type"] != kind:
            stack.pop()  # a sibling list of the other kind
        if not stack or stack[-1][0] < indent:
            lst: Node = {"type": kind, "content": []}
            if stack:
                stack[-1][1]["content"][-1]["content"].append(lst)  # nested under the open item
            else:
                blocks.append(lst)
            stack.append((indent, lst))
        stack[-1][1]["content"].append({"type": "listItem", "content": [_paragraph([text])]})

    i = 0
    while i < len(lines):
        line = lines[i]
        fence = _FENCE.match(line)
        if fence:
            flush_all()
            marker, lang = fence.group(1), fence.group(2)
            code: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(marker):
                code.append(lines[i])
                i += 1
            i += 1  # the closing fence (or EOF)
            block: Node = {"type": "codeBlock", "content": _text("\n".join(code), ())}
            if lang:
                block["attrs"] = {"language": lang}
            blocks.append(block)
            continue

        if not line.strip():
            flush_para()
            flush_quote()
            i += 1
            continue

        heading = _HEADING.match(line)
        if heading:
            flush_all()
            blocks.append({"type": "heading", "attrs": {"level": len(heading.group(1))},
                           "content": render_inline(heading.group(2))})
            i += 1
            continue

        q = _QUOTE.match(line)
        if q and not stack:
            flush_para()
            quote.append(q.group(1))
            i += 1
            continue

        item = _BULLET.match(line) or _NUMBERED.match(line)
        if item:
            flush_para()
            flush_quote()
            kind = "bulletList" if _BULLET.match(line) else "orderedList"
            add_item(len(item.group(1).expandtabs(4)), kind, item.group(2))
            i += 1
            continue

        if stack and line.startswith(" "):
            # continuation of the open list item
            last = stack[-1][1]["content"][-1]["content"][0]["content"]
            last[:] = _merge(last + _text(" ", ()) + render_inline(line.strip()))
            i += 1
            continue

        stack.clear()
        flush_quote()
        para.append(line.strip())
        i += 1

    flush_all()
    return blocks


# --- ADF → Markdown -------------------------------------------------------------------


def to_markdown(doc: Any) -> str:
    """ADF (or the plain string an older API gives) → Markdown text."""
    if doc is None:
        return ""
    if isinstance(doc, str):
        return doc.strip()
    if not isinstance(doc, dict):
        return ""
    return "\n\n".join(b for b in (_block_md(n, 0) for n in doc.get("content") or []) if b).strip()


def _inline_md(nodes: list[Node]) -> str:
    out: list[str] = []
    for n in nodes or []:
        kind = n.get("type")
        if kind == "text":
            out.append(_marked(n.get("text") or "", n.get("marks") or []))
        elif kind == "hardBreak":
            out.append("\n")
        elif kind in ("mention", "emoji", "status", "date"):
            attrs = n.get("attrs") or {}
            out.append(str(attrs.get("text") or attrs.get("shortName") or attrs.get("timestamp") or ""))
        elif kind in ("inlineCard", "blockCard"):
            out.append(str((n.get("attrs") or {}).get("url") or ""))
        elif n.get("content"):
            out.append(_inline_md(n["content"]))
    return "".join(out)


def _marked(text: str, marks: list[Node]) -> str:
    kinds = {m.get("type"): m for m in marks}
    if "code" in kinds:
        text = f"`{text}`"
    if "em" in kinds:
        text = f"*{text}*"
    if "strong" in kinds:
        text = f"**{text}**"
    if "strike" in kinds:
        text = f"~~{text}~~"
    if "link" in kinds:
        text = f"[{text}]({(kinds['link'].get('attrs') or {}).get('href', '')})"
    return text


def _block_md(n: Node, depth: int) -> str:
    kind = n.get("type")
    content = n.get("content") or []
    if kind == "paragraph":
        return _inline_md(content)
    if kind == "heading":
        return "#" * int((n.get("attrs") or {}).get("level") or 1) + " " + _inline_md(content)
    if kind in ("bulletList", "orderedList"):
        start = int((n.get("attrs") or {}).get("order") or 1)
        lines = []
        for k, item in enumerate(content):
            bullet = "-" if kind == "bulletList" else f"{start + k}."
            lines.append(_item_md(item, depth, bullet))
        return "\n".join(lines)
    if kind == "codeBlock":
        lang = (n.get("attrs") or {}).get("language") or ""
        return f"```{lang}\n{_inline_md(content)}\n```"
    if kind == "blockquote":
        inner = "\n\n".join(_block_md(c, 0) for c in content)
        return "\n".join(f"> {line}" if line else ">" for line in inner.split("\n"))
    if kind == "rule":
        return "---"
    if content:  # panels, expands, tables … keep their text
        return "\n\n".join(b for b in (_block_md(c, depth) for c in content) if b)
    return ""


def _item_md(item: Node, depth: int, bullet: str) -> str:
    pad = "  " * depth
    parts = item.get("content") or []
    head = next((p for p in parts if p.get("type") == "paragraph"), None)
    line = f"{pad}{bullet} {_inline_md(head.get('content') or []) if head else ''}"
    nested = [_block_md(p, depth + 1) for p in parts if p is not head]
    return "\n".join([line, *(x for x in nested if x)])
