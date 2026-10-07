"""The product skills in skills/: the frontmatter every host reads, the tools
they call (only the board server's eleven and the knowledge server's two),
intake's retrieval all in its context step, the intake records they show the
model, which must pass the schema so the examples teach a valid shape,
plan-sprint's order (reads and one yes, then close, create, move) and
groom's (reads and one yes, then a fresh read before each update)."""

import json
import re
from pathlib import Path

import pytest

from schema.intake import SIBLING, Intake
from server import titlecase
from server.config import ItemCase
from server.model import Materialization
from tests.test_docs import DOC_TOOLS
from tests.test_mcp_app import TOOLS

SKILLS = Path(__file__).resolve().parents[1] / "skills"
CREATE = {"create-story": {"story"}, "create-bug": {"bug"}, "create-epic": {"epic", "story"}}
NAMES = ["intake", *CREATE, "plan-sprint", "groom"]
READS = {"describe_board", "find_items", "get_item", "get_iteration"}
ROLLOVER = ["close_iteration", "create_iteration", "move_to_iteration"]  # Jira: one active sprint
CALL = re.compile(r"\b([a-z]+(?:_[a-z]+)+)\(")  # describe_board(), propose_item(intake=…)
FULL_READ = {  # a read that must see everything: an iteration's items, the review queue
    "plan-sprint": re.compile(r'find_items\(iteration="[^"]*"(?:, limit=(\d+))?\)'),
    "groom": re.compile(r'find_items\(label="[^"]*"(?:, limit=(\d+))?\)'),
}
JSON_BLOCK = re.compile(r"```json\n(.*?)```", re.S)
INTAKE_ID = re.compile(r"\d{8}-[a-z0-9-]+")  # the skills' convention: YYYYMMDD-<slug>


def read(name: str) -> tuple[dict[str, str], str]:
    text = (SKILLS / name / "SKILL.md").read_text()
    assert text.startswith("---\n"), f"{name}: no frontmatter"
    head, _, body = text[4:].partition("\n---\n")
    return dict(line.split(": ", 1) for line in head.splitlines()), body


def examples(body: str) -> list[Intake]:
    records = [json.loads(block) for block in JSON_BLOCK.findall(body)]
    return [Intake.from_dict(r).check() for r in records if "parts" in r]


def test_the_skill_set():
    assert sorted(p.name for p in SKILLS.iterdir() if p.is_dir()) == sorted(NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_frontmatter_is_the_portable_subset(name):
    meta, _ = read(name)
    assert set(meta) == {"name", "description"}
    assert meta["name"] == name and re.fullmatch(r"[a-z0-9-]{1,64}", name)
    assert 0 < len(meta["description"]) <= 1024


@pytest.mark.parametrize("name", NAMES)
def test_a_skill_calls_only_the_servers_tools(name):
    _, body = read(name)
    calls = set(CALL.findall(body))
    assert calls and calls <= TOOLS | DOC_TOOLS, f"not server tools: {sorted(calls - TOOLS - DOC_TOOLS)}"


def test_intake_retrieves_only_in_its_context_step():
    _, body = read("intake")
    before, sep, rest = body.partition("## 3. Context provider")
    step, _, after = rest.partition("\n## 4.")
    assert sep and {"find_items", "search_docs", "get_doc"} <= set(CALL.findall(step))
    assert not {"find_items", *DOC_TOOLS} & set(CALL.findall(before + after))  # swap a provider in one place
    assert step.index("search_docs(") < step.index("get_doc(")  # an excerpt is read in full before use


def test_intake_hands_off_to_every_create_skill():
    _, body = read("intake")
    assert all(name in body for name in CREATE)


@pytest.mark.parametrize("name", CREATE)
def test_a_create_skill_proposes_before_it_commits(name):
    _, body = read(name)
    assert body.index("propose_item(") < body.index("commit_item(")


def test_plan_sprint_plans_on_reads_then_writes_in_rollover_order():
    _, body = read("plan-sprint")
    plan, sep, rollover = body.partition("## 5. Roll over")
    assert sep, "plan-sprint has no rollover section"
    assert "yes" in plan and set(CALL.findall(plan)) <= READS  # the PM's yes comes before any write
    assert 'find_items(iteration="<next>"' in plan  # an existing next one is read, never assumed empty
    order = [rollover.index(f"{tool}(") for tool in ROLLOVER]
    assert order == sorted(order)


def test_groom_reviews_on_reads_then_rereads_before_each_update():
    _, body = read("groom")
    review, sep, apply = body.partition("## 5. Apply")
    assert sep, "groom has no apply section"
    assert "yes" in review and set(CALL.findall(review)) <= READS  # the PO's yes comes before any write
    assert apply.index("get_item(") < apply.index("update_item(")  # labels replace the whole set


def test_the_skills_read_a_board_without_a_bug_level_or_review():
    # D39 / D40: describe_board reports capabilities.levels.bug as absent and review_label as null
    absent = f"`{Materialization.ABSENT.value}`"
    assert all(absent in read(name)[1] for name in ("intake", "create-bug", "create-epic"))
    assert "If `review_label` is null" in read("groom")[1]
    assert "`review_label`: null" in read("intake")[1]


@pytest.mark.parametrize("name", FULL_READ)
def test_a_full_read_has_a_generous_limit(name):
    limits = FULL_READ[name].findall(read(name)[1])
    assert limits and all(limit and int(limit) >= 100 for limit in limits)  # the tool's default is 20


@pytest.mark.parametrize("name", CREATE)
def test_every_example_record_is_valid_and_ordered(name):
    records = examples(read(name)[1])
    assert records, f"{name} shows no example record"
    for rec in records:
        assert INTAKE_ID.fullmatch(rec.id)
        assert {p.level.value for p in rec.parts} == CREATE[name]
        # the examples model a title-case board, so they would draw no D14 warning
        assert [p.title for p in rec.parts if titlecase.suggest(p.title, ItemCase.TITLE)] == []
        seen: set[str] = set()
        for p in rec.parts:  # a sibling parent is committed first, so it must come first
            parent = p.placement.parent or ""
            assert not parent.startswith(SIBLING) or parent[1:] in seen
            seen.add(p.part)
