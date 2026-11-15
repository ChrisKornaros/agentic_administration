"""The Markdown → Plane HTML renderer, and the lossy reverse."""

import pytest

from adapters.plane.markdown import render, to_text


@pytest.mark.parametrize(
    "md, html",
    [
        ("", ""),
        ("plain text", "<p>plain text</p>"),
        ("line one\nline two", "<p>line one<br>line two</p>"),
        ("para one\n\npara two", "<p>para one</p><p>para two</p>"),
        ("a <b> & c", "<p>a &lt;b&gt; &amp; c</p>"),
        ("# Title\n\nbody", "<h1>Title</h1><p>body</p>"),
        ("## Given / When", "<h2>Given / When</h2>"),
        ("**bold** and *em* and `code`", "<p><strong>bold</strong> and <em>em</em> and <code>code</code></p>"),
        ("__bold__ _em_", "<p><strong>bold</strong> <em>em</em></p>"),
        ("see [docs](https://example.invalid/x)", '<p>see <a href="https://example.invalid/x">docs</a></p>'),
        ("[x](javascript:alert(1))", "<p>[x](javascript:alert(1))</p>"),
        ("`<not html>`", "<p><code>&lt;not html&gt;</code></p>"),
        ("- a\n- b", "<ul><li>a</li><li>b</li></ul>"),
        ("1. a\n2. b", "<ol><li>a</li><li>b</li></ol>"),
        ("- a\n  - a1\n  - a2\n- b", "<ul><li>a<ul><li>a1</li><li>a2</li></ul></li><li>b</li></ul>"),
        ("- a\n  continued\n- b", "<ul><li>a continued</li><li>b</li></ul>"),
        ("- a\n\npara", "<ul><li>a</li></ul><p>para</p>"),
        ("> quoted *text*", "<blockquote><p>quoted <em>text</em></p></blockquote>"),
        ("```py\nx = 1 < 2\n```", '<pre><code class="language-py">x = 1 &lt; 2</code></pre>'),
        ("```\nraw\n```\nafter", "<pre><code>raw</code></pre><p>after</p>"),
        ("  ```\n  raw\n  ```\nafter", "<pre><code>  raw</code></pre><p>after</p>"),
        # underscores inside a word stay literal; a bare __x__ is bold, as in CommonMark
        ("PLANE_API_KEY_BW_ITEM, __init__ and _em_", "<p>PLANE_API_KEY_BW_ITEM, <strong>init</strong> and <em>em</em></p>"),
    ],
)
def test_render(md, html):
    assert render(md) == html


def test_acceptance_criteria_shape():
    md = (
        "As a requester I want to file a bug.\n\n"
        "## Acceptance\n"
        "- **Given** a board\n"
        "- **When** I confirm\n"
        "- **Then** the item lands in Backlog with `needs-review`\n"
    )
    assert render(md) == (
        "<p>As a requester I want to file a bug.</p>"
        "<h2>Acceptance</h2>"
        "<ul><li><strong>Given</strong> a board</li><li><strong>When</strong> I confirm</li>"
        "<li><strong>Then</strong> the item lands in Backlog with <code>needs-review</code></li></ul>"
    )


def test_to_text_is_readable():
    assert to_text("<p>one</p><p>two &amp; three</p><ul><li>a</li><li>b</li></ul>") == "one\n\ntwo & three\n\n- a\n- b"
    assert to_text("<p></p>") == ""


def test_to_text_keeps_the_blank_line_between_paragraphs():
    caption = "Hook.\n\nThe recipe:\nhttps://example.com/recipes/ragu\n\n#ragu #pasta"
    assert to_text(render(caption)) == caption
    # Plane's editor stores an empty paragraph for an extra blank line, and
    # wraps a list item's text in a paragraph.
    assert to_text("<p>one</p><p></p><p>two</p>") == "one\n\ntwo"
    assert to_text("<ul><li><p>a</p></li><li><p>b</p></li></ul><p>after</p>") == "- a\n- b\nafter"


# Plane's editor stores a rule typed in its UI as this node (its open-source
# editor, packages/editor/src/extensions/horizontal-rule.ts), and reads a plain <hr> as one.
EDITOR_RULE = '<div class="py-4 border-strong-1" data-type="horizontalRule"><div></div></div>'


@pytest.mark.parametrize("rule", ["<hr>", "<hr/>", "<hr />", '<HR class="x">', EDITOR_RULE])
def test_to_text_keeps_a_horizontal_rule_as_a_line_of_its_own(rule):
    assert to_text(f"<p>caption</p>{rule}<p>notes</p>") == "caption\n\n---\n\nnotes"
    assert to_text(f"<p>a</p><p>b<br>c</p>{rule}<ul><li><p>d</p></li></ul>") == "a\n\nb\nc\n\n---\n\n- d"


def test_to_text_drops_whatever_the_editors_rule_node_holds():
    nested = '<div data-type="horizontalRule"><div><div></div></div></div>'
    assert to_text(f"<p>a</p>{nested}<p>b</p><div>c</div>") == "a\n\n---\n\nb\n\nc"


@pytest.mark.parametrize(
    "html_text, text",
    [  # what to_text returned before rules were kept, for text without one
        ("<p>one</p><p>two &amp; three</p><ul><li>a</li><li>b</li></ul>", "one\n\ntwo & three\n\n- a\n- b"),
        ("<h2>Head</h2><p>a<br/>b</p><blockquote><p>q</p></blockquote>", "Head\n\na\nb\n\nq"),
        ('<div class="x"><p>in a div</p></div><p>after</p>', "in a div\n\nafter"),
        ("<table><tr><td><p>c1</p></td><td>c2</td></tr></table>", "c1c2"),
        ("<pre><code>x &lt; 2</code></pre>", "x < 2"),
        ("<p>&lt;hr&gt; is text</p>", "<hr> is text"),  # an escaped tag is the text's own
        ("", ""),
    ],
)
def test_to_text_is_unchanged_for_text_without_a_rule(html_text, text):
    assert to_text(html_text) == text


def test_render_writes_a_dash_line_as_text_not_a_rule():
    # A notes separator is written as paragraph text; only a person's rule typed in the UI is an <hr>.
    described = "Caption.\n\n#tag\n\n------\n\nNotes."
    assert render(described) == "<p>Caption.</p><p>#tag</p><p>------</p><p>Notes.</p>"
    assert "<hr" not in render("---") and render("---") == "<p>---</p>"
    assert to_text(render(described)) == described
