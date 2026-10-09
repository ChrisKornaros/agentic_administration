"""The product skills in skills/: the frontmatter every host reads, the tools
they call (only the board server's eleven and the knowledge server's two),
intake's retrieval all in its context step, the intake records they show the
model, which must pass the schema so the examples teach a valid shape, the
arguments they pass, which must be the tools' own, plan-sprint's order (reads
and one yes, then close, create, move), plan-cycle's (reads and checks and
one yes, then the cycle, the epic, its slots and a read-back) and groom's
(reads and one yes, then a fresh read before each update)."""

import json
import re
from datetime import date
from pathlib import Path

import pytest
from mcp import Client

from knowledge.mcp_app import build as build_docs
from schema.intake import NAME, SIBLING, Intake
from server import titlecase
from server.config import DESCRIPTION_SLOTS, WEEKDAYS, DateRule, ItemCase, load
from server.mcp_app import build
from server.model import Materialization
from server.service import Boards
from tests.test_docs import DOC_TOOLS, published
from tests.test_mcp_app import TOOLS
from tests.test_service import service

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
CREATE = {"create-story": {"story"}, "create-bug": {"bug"}, "create-epic": {"epic", "story"}}
NAMES = ["intake", *CREATE, "plan-sprint", "plan-cycle", "groom"]
READS = {"describe_board", "find_items", "get_item", "get_iteration"}
ROLLOVER = ["close_iteration", "create_iteration", "move_to_iteration"]  # Jira: one active sprint
CALL = re.compile(r"\b([a-z]+(?:_[a-z]+)+)\(")  # describe_board(), propose_item(intake=…)
ARGS = re.compile(r"\b([a-z]+(?:_[a-z]+)+)\(([^()]*)\)")  # a call and its arguments
KEYWORD = re.compile(r"(?:^|,)\s*([a-z_]+)=")
ITERATION_READ = re.compile(r'find_items\(iteration="[^"]*"(?:, limit=(\d+))?\)')
FULL_READ = {  # a read that must see everything: an iteration's items, the review queue
    "plan-sprint": ITERATION_READ,
    "plan-cycle": ITERATION_READ,
    "groom": re.compile(r'find_items\(label="[^"]*"(?:, limit=(\d+))?\)'),
}
CYCLE_ITEM = re.compile(r"`(\d{8}-cycle)/(([a-z]+)-(\d{4}-\d{2}-\d{2}))`")  # plan-cycle's example external id
JSON_BLOCK = re.compile(r"```json\n(.*?)```", re.S)
ENTRY = ["intake", "plan-sprint", "plan-cycle", "groom"]  # each starts a request, so each picks its board (D43)
BOARD_STEP = (
    "If it returns `boards`, the server serves several. Use the board the request names, by its name, its project "
    "or its description. If it names none, list the boards with their descriptions and ask which one. Don't choose "
    'one yourself. Then call `describe_board(board="<board>")` and keep that result instead. Pass that `board` on '
    "every call, and name the board in everything you show before a yes."
)
ON_INTAKES_BOARD = ("Work on the board intake chose: pass that `board` on every call, and name the board in "
                    "everything you show before a yes.")
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


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_a_skill_passes_only_arguments_its_tool_takes(tmp_path):
    svc, _, _ = service()
    docs, _ = published(tmp_path)
    params: dict[str, set[str]] = {}
    for server in (build(Boards([svc])), build_docs(docs)):  # the schemas a host sees
        async with Client(server) as client:
            params |= {t.name: set(t.input_schema.get("properties", {})) for t in (await client.list_tools()).tools}
    for name in NAMES:
        for tool, args in ARGS.findall(read(name)[1]):
            unknown = set(KEYWORD.findall(args)) - params[tool]
            assert not unknown, f"{name}: {tool} takes no {sorted(unknown)}"


@pytest.mark.parametrize("name", NAMES)
def test_every_skill_works_on_one_named_board(name):
    body = " ".join(read(name)[1].split())  # the sentences, whatever the line breaks
    if name in ENTRY:  # the same words everywhere: ask unless the request names the board
        assert BOARD_STEP in body
    else:  # a create skill runs after intake, which carries the board to it
        assert name in CREATE and ON_INTAKES_BOARD in body
    if name == "intake":
        assert "Carry the board and the record" in body


def test_intake_retrieves_only_in_its_context_step():
    _, body = read("intake")
    before, sep, rest = body.partition("## 3. Context provider")
    step, _, after = rest.partition("\n## 4.")
    assert sep and {"find_items", "search_docs", "get_doc"} <= set(CALL.findall(step))
    assert not {"find_items", *DOC_TOOLS} & set(CALL.findall(before + after))  # swap a provider in one place
    assert step.index("search_docs(") < step.index("get_doc(")  # an excerpt is read in full before use


def test_intake_hands_off_to_every_skill_that_files():
    _, body = read("intake")
    assert all(name in body for name in [*CREATE, "plan-cycle"])  # a dated piece goes to plan-cycle


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


def test_plan_cycle_checks_on_reads_then_files_the_epic_before_its_slots():
    _, body = read("plan-cycle")
    plan, sep, write = body.partition("## 5. Write")
    assert sep, "plan-cycle has no write section"
    # propose_item writes nothing, so the plan may check drafts against the board before the PM's yes
    assert "yes" in plan and set(CALL.findall(plan)) <= READS | {"propose_item"}
    assert 'find_items(iteration="<cycle>"' in plan  # an existing cycle is read, never assumed empty
    epic, slot = write.index('part="epic"'), write.index('part="<part>"')
    assert write.index("create_iteration(") < epic < write.index("commit_item(") < slot  # the epic is their parent
    assert write.rindex("commit_item(") < write.index("get_item(")  # the read-back comes after the writes


def test_plan_cycle_plans_by_the_cadence_the_config_carries():
    _, body = read("plan-cycle")
    assert all(f"`{rule.value}`" in body for rule in DateRule)
    assert all(f"`{key}`" in body for key in ("level", "days", "dates"))
    assert f"`{WEEKDAYS[0]}` to `{WEEKDAYS[-1]}`" in body
    assert all(f"`{{{slot}}}`" in body for slot in DESCRIPTION_SLOTS)


def test_plan_cycle_examples_fit_the_calendar_example():
    _, body = read("plan-cycle")
    cfg = load(ROOT / "examples" / "boards" / "calendar.example.toml")
    found = CYCLE_ITEM.search(body)
    assert found, "plan-cycle shows no example external id"
    plan_id, part, template, day = found.groups()
    assert INTAKE_ID.fullmatch(plan_id) and NAME.fullmatch(plan_id) and NAME.fullmatch(part)
    first, slot = date.fromisoformat(f"{plan_id[:4]}-{plan_id[4:6]}-{plan_id[6:8]}"), date.fromisoformat(day)
    assert first.day == 1 and (slot.year, slot.month) == (first.year, first.month)  # a YYYYMM cycle's first day
    assert WEEKDAYS[slot.weekday()] in cfg.templates[template].days
    epic = next(t for t in cfg.templates.values() if t.level.value == "epic")
    assert f'("{epic.title_for(first)}")' in body
    placeholder = f"{template.title()} For {slot:%A, %B} {slot.day}"
    assert f'"{placeholder}"' in body and titlecase.suggest(placeholder, ItemCase.TITLE) is None


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
