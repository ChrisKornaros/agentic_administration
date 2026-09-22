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
    assert to_text("<p>one</p><p>two &amp; three</p><ul><li>a</li><li>b</li></ul>") == "one\ntwo & three\n- a\n- b"
    assert to_text("<p></p>") == ""
