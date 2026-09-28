"""Markdown ↔ Atlassian Document Format, offline."""

import pytest

from adapters.jira.adf import empty, render, to_markdown


def text(t, *marks):
    node = {"type": "text", "text": t}
    if marks:
        node["marks"] = list(marks)
    return node


def para(*content):
    return {"type": "paragraph", "content": list(content)}


def doc(*content):
    return {"version": 1, "type": "doc", "content": list(content)}


STRONG, EM, CODE = {"type": "strong"}, {"type": "em"}, {"type": "code"}


def test_empty_and_plain():
    assert render("") == doc() == empty()
    assert render("plain text") == doc(para(text("plain text")))
    assert render("line one\nline two") == doc(para(text("line one"), {"type": "hardBreak"}, text("line two")))
    assert render("one\n\ntwo") == doc(para(text("one")), para(text("two")))


def test_inline_marks_nest_and_code_only_keeps_link():
    assert render("**bold** and *em*")["content"][0]["content"] == [text("bold", STRONG), text(" and "), text("em", EM)]
    assert render("**a `b` c**")["content"][0]["content"] == [text("a ", STRONG), text("b", CODE), text(" c", STRONG)]
    link = {"type": "link", "attrs": {"href": "https://example.invalid/x"}}
    assert render("[see `x`](https://example.invalid/x)")["content"][0]["content"] == [text("see ", link), text("x", link, CODE)]
    assert render("[x](javascript:alert(1))")["content"][0]["content"] == [text("[x](javascript:alert(1))")]
    assert render("SNAKE_CASE_NAME")["content"][0]["content"] == [text("SNAKE_CASE_NAME")]


def test_blocks():
    assert render("## Acceptance")["content"] == [{"type": "heading", "attrs": {"level": 2}, "content": [text("Acceptance")]}]
    assert render("```py\nx = 1\n```")["content"] == [{"type": "codeBlock", "attrs": {"language": "py"}, "content": [text("x = 1")]}]
    assert render("```\n```")["content"] == [{"type": "codeBlock", "content": []}]  # no empty text node
    assert render("> quoted")["content"] == [{"type": "blockquote", "content": [para(text("quoted"))]}]


def test_lists_nest_and_every_item_holds_a_paragraph():
    out = render("- a\n  - a1\n- b\n  continued\n1. one")["content"]
    item = lambda *c: {"type": "listItem", "content": list(c)}
    assert out == [
        {"type": "bulletList", "content": [
            item(para(text("a")), {"type": "bulletList", "content": [item(para(text("a1")))]}),
            item(para(text("b continued"))),
        ]},
        {"type": "orderedList", "content": [item(para(text("one")))]},
    ]


@pytest.mark.parametrize("md", [
    "plain text",
    "As a requester I can **file** a *story* with `code`.\n\n## Acceptance\n\n- **Given** a board\n- **When** I confirm",
    "- a\n  - a1\n  - a2\n- b",
    "1. one\n2. two",
    "```py\nx = 1\n```",
    "see [docs](https://example.invalid/x)",
    "> quoted",
])
def test_round_trip(md):
    assert to_markdown(render(md)) == md


def cell(kind, *content):
    return {"type": kind, "content": [para(*content)]}


def row(*cells):
    return {"type": "tableRow", "content": list(cells)}


def test_tables():
    assert render("intro\n| a | b |\n| --- | :-: |\n| **1** | x \\| y |\n\nafter")["content"] == [
        para(text("intro")),
        {"type": "table", "content": [
            row(cell("tableHeader", text("a")), cell("tableHeader", text("b"))),
            row(cell("tableCell", text("1", STRONG)), cell("tableCell", text("x | y"))),
        ]},
        para(text("after")),
    ]
    # a short row is padded with an empty cell (no empty text node), a long one cut; no leading pipe needed
    assert render("a | b\n--|--\n1 |\n1 | 2 | 3")["content"][0]["content"][1:] == [
        row(cell("tableCell", text("1")), cell("tableCell")),
        row(cell("tableCell", text("1")), cell("tableCell", text("2"))),
    ]
    # not tables: a rule row with another width, a setext-style rule with no pipe
    assert render("| a | b |\n| --- |")["content"][0]["type"] == "paragraph"
    assert render("a | b\n---")["content"][0]["type"] == "paragraph"


@pytest.mark.parametrize("md", [
    "| a | b |\n| --- | --- |\n| 1 | **2** |",
    "| pipe |\n| --- |\n| x \\| y |",
])
def test_table_round_trip(md):
    assert to_markdown(render(md)) == md


def test_to_markdown_keeps_text_of_nodes_it_does_not_render():
    adf = doc(
        para(text("hi "), {"type": "mention", "attrs": {"id": "a", "text": "@Chris"}}, text(" "),
             {"type": "inlineCard", "attrs": {"url": "https://example.invalid"}}),
        {"type": "panel", "content": [para(text("note"))]},
        {"type": "rule"},
    )
    assert to_markdown(adf) == "hi @Chris https://example.invalid\n\nnote\n\n---"
    assert to_markdown(None) == "" and to_markdown("plain v2 string") == "plain v2 string"
