"""Markdown → the HTML Plane's editor stores (`description_html`,
`comment_html`). Stdlib only, deliberately small: the subset an intake
skill writes — headings, paragraphs, bullet / numbered lists (nested by
indentation), fenced code, block quotes, and inline bold / italic / code /
links. Anything else stays literal text, escaped. Plain text in, a single
`<p>` out — the seed CLI's `_to_html` behaviour is the degenerate case.
"""

from __future__ import annotations

import html
import re

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


def render_inline(text: str) -> str:
    """Escape `text` and apply inline Markdown."""
    out: list[str] = []
    pos = 0
    for m in _INLINE.finditer(text):
        out.append(html.escape(text[pos : m.start()]))
        if m.group("code"):
            out.append(f"<code>{html.escape(m.group('code')[1:-1])}</code>")
        elif m.group("link"):
            href = m.group("lhref")
            label = render_inline(m.group("ltext"))
            if _SAFE_HREF.match(href):
                out.append(f'<a href="{html.escape(href, quote=True)}">{label}</a>')
            else:  # javascript: and friends stay text
                out.append(html.escape(m.group(0)))
        elif m.group("bold"):
            inner = m.group("btext") or m.group("btext2") or ""
            out.append(f"<strong>{render_inline(inner)}</strong>")
        elif m.group("em"):
            inner = m.group("etext") or m.group("etext2") or ""
            out.append(f"<em>{render_inline(inner)}</em>")
        pos = m.end()
    out.append(html.escape(text[pos:]))
    return "".join(out)


def render(markdown: str) -> str:
    """Render a Markdown document to Plane HTML. Empty input → empty string."""
    lines = markdown.replace("\r\n", "\n").split("\n")
    blocks: list[str] = []
    para: list[str] = []
    quote: list[str] = []
    # Open lists as a stack of (indent, tag); items close on dedent.
    lists: list[tuple[int, str]] = []
    item_open = False
    i = 0

    def flush_para() -> None:
        nonlocal para
        if para:
            blocks.append("<p>" + "<br>".join(render_inline(p) for p in para) + "</p>")
            para = []

    def flush_quote() -> None:
        nonlocal quote
        if quote:
            blocks.append("<blockquote>" + render(" \n".join(quote).replace(" \n", "\n")) + "</blockquote>")
            quote = []

    def close_lists(down_to: int = -1) -> None:
        nonlocal item_open
        while lists and lists[-1][0] > down_to:
            if item_open:
                blocks.append("</li>")
                item_open = False
            blocks.append(f"</{lists[-1][1]}>")
            lists.pop()
            if lists:
                item_open = True  # the parent item was left open for nesting

    def flush_all() -> None:
        flush_para()
        flush_quote()
        close_lists()

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
            cls = f' class="language-{html.escape(lang)}"' if lang else ""
            blocks.append(f"<pre><code{cls}>{html.escape(chr(10).join(code))}</code></pre>")
            continue

        if not line.strip():
            flush_para()
            flush_quote()
            i += 1
            continue

        heading = _HEADING.match(line)
        if heading:
            flush_all()
            n = len(heading.group(1))
            blocks.append(f"<h{n}>{render_inline(heading.group(2))}</h{n}>")
            i += 1
            continue

        q = _QUOTE.match(line)
        if q and not lists:
            flush_para()
            quote.append(q.group(1))
            i += 1
            continue

        item = _BULLET.match(line) or _NUMBERED.match(line)
        if item:
            flush_para()
            flush_quote()
            indent = len(item.group(1).expandtabs(4))
            tag = "ul" if _BULLET.match(line) else "ol"
            if lists and indent > lists[-1][0]:
                lists.append((indent, tag))  # nested: parent <li> stays open
                blocks.append(f"<{tag}>")
            else:
                close_lists(indent)
                if lists and lists[-1][0] == indent:
                    if lists[-1][1] != tag:  # sibling list of the other kind
                        close_lists(indent - 1)
                        lists.append((indent, tag))
                        blocks.append(f"<{tag}>")
                    elif item_open:
                        blocks.append("</li>")
                        item_open = False
                else:
                    lists.append((indent, tag))
                    blocks.append(f"<{tag}>")
            blocks.append(f"<li>{render_inline(item.group(2))}")
            item_open = True
            i += 1
            continue

        if lists and line.startswith(" ") and item_open:
            # continuation of the current list item
            blocks[-1] = blocks[-1] + " " + render_inline(line.strip())
            i += 1
            continue

        close_lists()
        flush_quote()
        para.append(line.strip())
        i += 1

    flush_all()
    return "".join(blocks)


def to_text(html_text: str) -> str:
    """The reverse, lossy: strip Plane HTML to readable plain text for reads
    (descriptions come back as `description_html`; a faithful HTML→Markdown
    is a follow-up). Block tags become newlines, entities are decoded."""
    text = re.sub(r"<br\s*/?>", "\n", html_text, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|li|h[1-6]|blockquote|pre|tr)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "- ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
