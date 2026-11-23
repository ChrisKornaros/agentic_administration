"""Phase 8 — read-only probe of ClickUp's public API (v2).

The live check before a ClickUp adapter is written. ClickUp's own docs
disagree with themselves or stay silent on what an adapter needs, so this
reads it: which status `type` values exist, how a standard task's
`custom_item_id` reads (null or 0), whether a sprint List carries its dates
and anything marks a Folder as a Sprint Folder, how deep subtasks nest on
this workspace, whether tasks sit in several Lists, whether custom task ids
are on, how tags are spelled and whether the `tags[]` filter matches
exactly, whether the workspace-wide task read has `last_page` and includes
tasks added to a List, which key a Markdown description reads back under,
what hour a date-only due date is stored at, what a comment looks like, the
rate-limit headers and their unit, and whether urllib's default User-Agent
is refused.

It also surveys the workspace, since how a team models epics and sprints is
a fact about that team: per Space, its Folders and Lists, which Folders
look like sprints, the custom task types defined, and how a sample of tasks
uses types, parents and Lists.

Two outputs, on purpose:

- `clickup-probe-report.json`, next to this file (gitignored): everything
  read, **names included**. Board content. It stays on the machine.
- an `answers` block, printed last and stored in the report: counts, key
  names, ClickUp's own enum values and booleans only. **No name, id, title
  or text from the workspace is in it**, so it is the part that may leave.

Every call is a GET; nothing is written. The token comes from the secrets
boundary (`server/secrets.py`): `CLICKUP_API_TOKEN`, an env var or a
Bitwarden item via `CLICKUP_API_TOKEN_BW_ITEM`. It is never printed. A
personal token (`pk_…`) is sent as the `Authorization` header with no
`Bearer`. Throttled 0.7 s a call (a Free workspace allows 100 a minute).
Stdlib only.

Usage:
  uv run python probes/clickup_phase8_readonly.py --plan     # call list, no network
  CLICKUP_API_TOKEN=... uv run python probes/clickup_phase8_readonly.py            # lists the Spaces, then stops
  CLICKUP_API_TOKEN=... uv run python probes/clickup_phase8_readonly.py --space <id> [--space <id> …]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from server import secrets  # noqa: E402  (the one secret boundary)

API = "https://api.clickup.com/api/v2"
THROTTLE = 0.7
USER_AGENT = "agentic-administration/0.0 (clickup probe; +https://github.com/ChrisKornaros/agentic_administration)"
KEEP_HEADERS = re.compile(r"ratelimit|retry-after", re.I)
SPRINT_NAME = re.compile(r"sprint", re.I)
TEXT_FIELDS = ("short_text", "text")

log: list[dict] = []


class Probe:
    def __init__(self, token: str) -> None:
        self._token = token

    def get(self, label: str, path: str, params: list[tuple[str, object]] | None = None, *,
            user_agent: str | None = USER_AGENT) -> tuple[int, object]:
        """GET API+path; record (status, response shape, rate headers) and return it."""
        query = urllib.parse.urlencode(params or [])
        url = f"{API}{path}{'?' + query if query else ''}"
        headers = {"Authorization": self._token, "Accept": "application/json"}
        if user_agent:
            headers["User-Agent"] = user_agent  # left out once, to see what urllib's own gets
        req = urllib.request.Request(url, method="GET", headers=headers)
        status, raw, hdrs = 0, "", {}
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                status, raw, hdrs = resp.status, resp.read().decode("utf-8"), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read().decode("utf-8", "replace")
            hdrs = dict(exc.headers or {})
        except urllib.error.URLError as exc:
            status, raw = -1, str(exc.reason)
        try:
            body = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = raw[:200]  # an edge wall's page, not the API
        kept = {k: v for k, v in hdrs.items() if KEEP_HEADERS.search(k)}
        log.append({"label": label, "path": path, "params": params, "status": status,
                    "content_type": hdrs.get("Content-Type") or hdrs.get("content-type"),
                    "shape": summarize(body), "headers": kept})
        print(f"{status:>4}  {label:<34} {path}", flush=True)
        time.sleep(THROTTLE)
        return status, body


def summarize(body: object) -> object:
    """Shape of a response: keys and counts, never content."""
    if isinstance(body, dict):
        lists = {k: v for k, v in body.items() if isinstance(v, list)}
        if len(lists) == 1:
            (env, items), = lists.items()
            first = items[0] if items else None
            return {"envelope": sorted(k for k in body if k != env), "list": env, "count": len(items),
                    "item_keys": sorted(first) if isinstance(first, dict) else None}
        return {"keys": sorted(body)}
    if isinstance(body, list):
        return {"list_len": len(body)}
    return body


def rows(body: object, env: str) -> list[dict]:
    found = body.get(env) if isinstance(body, dict) else None
    return [r for r in found if isinstance(r, dict)] if isinstance(found, list) else []


def keys(body: object) -> list[str]:
    return sorted(body) if isinstance(body, dict) else []


def kind(value: object) -> str:
    """A value's kind, for the answers block: never the value itself."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "0" if value == 0 else "1" if value == 1 else "number"
    if isinstance(value, str):
        return "empty string" if not value else "digits" if value.isdigit() else "string"
    return type(value).__name__


def plan_calls() -> list[str]:
    return [
        "GET /user                                   (auth works; the token owner's time zone; rate headers)",
        "GET /user                                   (once more with urllib's default User-Agent)",
        "GET /team                                   (the workspaces this token sees; members)",
        "GET /team/{ws}/plan                         (the plan's name)",
        "GET /team/{ws}/custom_item                  (custom task types)",
        "GET /team/{ws}/space?archived=false         (the Spaces; without --space the probe stops here)",
        "--- per --space ---",
        "GET /space/{id}                             (statuses and their types; features)",
        "GET /space/{id}/tag                         (tags as spelled)",
        "GET /space/{id}/folder?archived=false       (Folders, each with its Lists)",
        "GET /space/{id}/list?archived=false         (Lists outside a Folder)",
        "GET /folder/{id}                            (one per sprint-like Folder: is anything a sprint flag)",
        "GET /folder/{id}/list?archived=true         (same Folders: archived sprint Lists)",
        "--- per sampled List (--max-lists a Space, sprint-like first) ---",
        "GET /list/{id}                              (statuses, start_date, due_date, status)",
        "GET /list/{id}/field?include_applied_objects=true   (custom fields and their types)",
        "GET /list/{id}/task?page=0&subtasks=true&include_closed=true&include_timl=true&include_markdown_description=true",
        "--- once, from what the samples held ---",
        "GET /team/{ws}/task?page=0&list_ids[]={list}&subtasks=true&include_closed=true   (envelope; last_page)",
        "GET /team/{ws}/task?list_ids[]={a List a task was added to}                      (is that task there)",
        "GET /team/{ws}/task?tags[]={a tag}   and   tags[]={its first half}               (exact or not)",
        "GET /list/{id}/task?custom_fields=[…]     ×4                                     (== exact, == other case, = whole, = part)",
        "GET /task/{id}?include_markdown_description=true&include_subtasks=true            (one task, whole)",
        "GET /task/{custom id}?custom_task_ids=true&team_id={ws}                          (when a task has one)",
        "GET /task/{id}/comment                      (a comment's shape)",
    ]


def sprint_like(folder: dict) -> bool:
    lists = [x for x in folder.get("lists") or [] if isinstance(x, dict)]
    dated = [x for x in lists if x.get("start_date") and x.get("due_date")]
    return bool(SPRINT_NAME.search(folder.get("name") or "")) or (len(lists) >= 2 and len(dated) * 2 >= len(lists))


def depth(task_id: str, parent_of: dict[str, str | None]) -> int:
    """How many parents sit above a task, as far as the sample shows."""
    hops, seen = 0, set()
    while (parent := parent_of.get(task_id)) and task_id not in seen:
        seen.add(task_id)
        hops, task_id = hops + 1, parent
    return hops


def probe(pr: Probe, workspace: str | None, spaces: list[str], max_lists: int) -> dict:
    board: dict = {}   # names included: stays in the report
    a: dict = {}       # the answers: no name, id, title or text
    out = {"answers": a, "board": board}

    st, me = pr.get("user", "/user")
    user = me.get("user") if isinstance(me, dict) and isinstance(me.get("user"), dict) else {}
    a["auth"] = {"status": st, "user_keys": keys(user), "has_timezone": bool(user.get("timezone") or user.get("timezeone"))}
    board["token_owner_timezone"] = user.get("timezone") or user.get("timezeone")
    a["rate_headers"] = {k: (v if k.lower().endswith(("limit", "remaining")) else f"{len(str(v))} characters")
                         for k, v in log[-1]["headers"].items()}
    if st != 200:
        board["user_error"] = me
        return out  # auth failed: nothing else will answer

    st, _ = pr.get("user (urllib's User-Agent)", "/user", user_agent=None)
    a["default_user_agent"] = {"status": st, "content_type": log[-1]["content_type"]}

    st, teams = pr.get("workspaces", "/team")
    found = rows(teams, "teams")
    board["workspaces"] = [{"id": t.get("id"), "name": t.get("name"), "members": len(t.get("members") or [])} for t in found]
    a["workspaces"] = {"count": len(found), "keys": keys(found[0]) if found else [],
                       "member_keys": keys((found[0].get("members") or [{}])[0].get("user")) if found else []}
    ws = workspace or (str(found[0].get("id")) if len(found) == 1 else None)
    if not ws:
        print("\nSeveral workspaces: pass --workspace <id>.", file=sys.stderr)
        for row in board["workspaces"]:
            print(f"  {row['id']}  {row['name']}", file=sys.stderr)
        return out

    st, plan = pr.get("plan", f"/team/{ws}/plan")
    a["plan"] = {"status": st, "plan_name": plan.get("plan_name") if isinstance(plan, dict) else None, "keys": keys(plan)}

    st, items = pr.get("custom task types", f"/team/{ws}/custom_item")
    types = rows(items, "custom_items")
    board["custom_task_types"] = [{k: t.get(k) for k in ("id", "name", "name_plural")} for t in types]
    a["custom_task_types"] = {"status": st, "count": len(types), "keys": keys(types[0]) if types else [],
                              "id_kinds": dict(Counter(type(t.get("id")).__name__ for t in types))}
    type_name = {str(t.get("id")): t.get("name") for t in types}

    st, sp = pr.get("spaces", f"/team/{ws}/space", [("archived", "false")])
    all_spaces = rows(sp, "spaces")
    board["spaces"] = [{"id": s.get("id"), "name": s.get("name")} for s in all_spaces]
    a["spaces"] = {"status": st, "count": len(all_spaces), "keys": keys(all_spaces[0]) if all_spaces else []}
    if not spaces:
        print("\nPass --space <id> for each Space to read:", file=sys.stderr)
        for row in board["spaces"]:
            print(f"  {row['id']}  {row['name']}", file=sys.stderr)
        return out

    status_types: Counter[str] = Counter()
    closed_per_workflow: Counter[int] = Counter()
    field_types: Counter[str] = Counter()
    type_config_keys: dict[str, list[str]] = {}
    tasks: dict[str, dict] = {}          # every sampled task, by id
    home: dict[str, str] = {}            # task id -> the List it was read from
    a["sprint_folders"], a["lists"], board["space_detail"] = [], [], {}
    features: Counter[str] = Counter()
    tags_seen: list[str] = []
    list_envelopes: set[str] = set()
    text_field: tuple[str, str, str] | None = None  # (list id, field id, a value)

    def note_statuses(statuses: object) -> None:
        mine = [s.get("type") for s in statuses or [] if isinstance(s, dict)]
        status_types.update(str(t) for t in mine)
        closed_per_workflow[sum(1 for t in mine if t == "closed")] += 1

    for space_id in spaces:
        detail: dict = {"folders": [], "lists": []}
        board["space_detail"][space_id] = detail
        st, space = pr.get("space", f"/space/{space_id}")
        if st != 200 or not isinstance(space, dict):
            detail["error"] = space
            continue
        detail["name"] = space.get("name")
        detail["statuses"] = [{k: s.get(k) for k in ("status", "type", "orderindex")} for s in space.get("statuses") or []]
        note_statuses(space.get("statuses"))
        for name, cfg in (space.get("features") or {}).items():
            if isinstance(cfg, dict) and cfg.get("enabled"):
                features[name] += 1
        a.setdefault("space_keys", keys(space))

        st, tg = pr.get("space tags", f"/space/{space_id}/tag")
        tags = [t.get("name") for t in rows(tg, "tags") if isinstance(t.get("name"), str)]
        detail["tags"] = tags
        tags_seen += tags
        a.setdefault("tag_keys", keys(rows(tg, "tags")[0]) if rows(tg, "tags") else [])

        st, fo = pr.get("folders", f"/space/{space_id}/folder", [("archived", "false")])
        folders = rows(fo, "folders")
        st, fl = pr.get("folderless lists", f"/space/{space_id}/list", [("archived", "false")])
        loose = rows(fl, "lists")
        candidates: list[tuple[bool, dict]] = [(False, x) for x in loose]
        for folder in folders:
            is_sprint = sprint_like(folder)
            lists = [x for x in folder.get("lists") or [] if isinstance(x, dict)]
            row = {"id": folder.get("id"), "name": folder.get("name"), "sprint_like": is_sprint,
                   "lists": [{k: x.get(k) for k in ("id", "name", "start_date", "due_date", "task_count")} for x in lists]}
            detail["folders"].append(row)
            candidates += [(is_sprint, x) for x in lists]
            if is_sprint:
                st, one = pr.get("sprint-like folder", f"/folder/{folder.get('id')}")
                st2, arch = pr.get("its archived lists", f"/folder/{folder.get('id')}/list", [("archived", "true")])
                a["sprint_folders"].append({
                    "name_says_sprint": bool(SPRINT_NAME.search(folder.get("name") or "")),
                    "folder_keys": keys(one), "lists": len(lists),
                    "lists_with_start_date": sum(1 for x in lists if x.get("start_date")),
                    "lists_with_due_date": sum(1 for x in lists if x.get("due_date")),
                    "archived_lists": len(rows(arch, "lists")),
                    "list_names_say_sprint": sum(1 for x in lists if SPRINT_NAME.search(x.get("name") or "")),
                    "list_names_hold_a_date": sum(1 for x in lists if re.search(r"\d{1,2}/\d{1,2}", x.get("name") or ""))})
        detail["lists"] = [{k: x.get(k) for k in ("id", "name", "task_count")} for x in loose]
        a.setdefault("folders_per_space", []).append({"folders": len(folders), "folderless_lists": len(loose),
                                                      "sprint_like_folders": sum(1 for r in detail["folders"] if r["sprint_like"])})

        candidates.sort(key=lambda c: not c[0])  # sprint-like first
        for is_sprint, lst in candidates[:max_lists]:
            lid = str(lst.get("id"))
            st, one = pr.get("list", f"/list/{lid}")
            one = one if isinstance(one, dict) else {}
            note_statuses(one.get("statuses"))
            st, fd = pr.get("list fields", f"/list/{lid}/field", [("include_applied_objects", "true")])
            fields = rows(fd, "fields")
            for f in fields:
                field_types[str(f.get("type"))] += 1
                type_config_keys.setdefault(str(f.get("type")), keys(f.get("type_config")))
            st, tk = pr.get("list tasks", f"/list/{lid}/task", [
                ("page", 0), ("subtasks", "true"), ("include_closed", "true"), ("include_timl", "true"),
                ("include_markdown_description", "true")])
            sample = rows(tk, "tasks")
            list_envelopes.update(k for k in keys(tk) if k != "tasks")
            for t in sample:
                tid = str(t.get("id"))
                tasks.setdefault(tid, t)
                home.setdefault(tid, lid)
                for cf in t.get("custom_fields") or []:
                    if not text_field and cf.get("type") in TEXT_FIELDS and isinstance(cf.get("value"), str) and len(cf["value"]) >= 4:
                        text_field = (lid, str(cf.get("id")), cf["value"])
            a["lists"].append({
                "in_sprint_like_folder": is_sprint, "list_keys": keys(one),
                "start_date": kind(one.get("start_date")), "due_date": kind(one.get("due_date")),
                "status": kind(one.get("status")), "override_statuses": one.get("override_statuses"),
                "fields": len(fields), "fields_with_applied_objects": sum(1 for f in fields if f.get("applied_objects")),
                "tasks_on_page_0": len(sample), "last_page": tk.get("last_page") if isinstance(tk, dict) else None})

    a["status_types"] = dict(status_types)
    a["closed_statuses_per_workflow"] = {str(k): v for k, v in closed_per_workflow.items()}
    a["features_on"] = dict(features)
    a["field_types"], a["type_config_keys"] = dict(field_types), type_config_keys
    a["list_task_envelope"] = sorted(list_envelopes)
    a["tags"] = {"count": len(tags_seen), "with_capitals": sum(1 for t in tags_seen if t != t.lower()),
                 "with_colon": sum(1 for t in tags_seen if ":" in t), "with_slash": sum(1 for t in tags_seen if "/" in t),
                 "with_space": sum(1 for t in tags_seen if " " in t), "longest": max(map(len, tags_seen), default=0)}

    # -- what the sampled tasks show --------------------------------------------------------
    parent_of = {tid: (str(t["parent"]) if t.get("parent") else None) for tid, t in tasks.items()}
    depths = Counter(depth(tid, parent_of) for tid in tasks)
    by_type = Counter(str(t.get("custom_item_id")) for t in tasks.values())
    board["tasks_by_type"] = {type_name.get(k, k): v for k, v in by_type.items()}
    board["parent_and_child_types"] = dict(Counter(
        f"{type_name.get(str(tasks[p].get('custom_item_id')), tasks[p].get('custom_item_id'))} > "
        f"{type_name.get(str(t.get('custom_item_id')), t.get('custom_item_id'))}"
        for tid, t in tasks.items() if (p := parent_of[tid]) in tasks))
    date_only = [t for t in tasks.values() if t.get("due_date") and not t.get("due_date_time")]
    multi = [tid for tid, t in tasks.items() if t.get("locations")]
    custom_ids = [t for t in tasks.values() if t.get("custom_id")]
    a["tasks"] = {
        "sampled": len(tasks), "task_keys": sorted({k for t in tasks.values() for k in t}),
        "custom_item_id_kinds": dict(Counter(kind(t.get("custom_item_id")) for t in tasks.values())),
        "distinct_types_in_use": len(by_type), "with_parent": sum(1 for p in parent_of.values() if p),
        "parents_above_a_task": {str(k): v for k, v in sorted(depths.items())},
        "parent_child_type_pairs": len(board["parent_and_child_types"]),
        "in_several_lists": len(multi), "with_custom_id": len(custom_ids),
        "with_markdown_description_key": sum(1 for t in tasks.values() if "markdown_description" in t),
        "with_due_date_time_key": sum(1 for t in tasks.values() if "due_date_time" in t),
        "date_only_due_hour_utc": dict(Counter(str(int(t["due_date"]) // 3_600_000 % 24) for t in date_only
                                               if str(t["due_date"]).isdigit())),
        "status_types": dict(Counter(str((t.get("status") or {}).get("type")) for t in tasks.values())),
        "with_tags": sum(1 for t in tasks.values() if t.get("tags")),
        "with_linked_tasks": sum(1 for t in tasks.values() if t.get("linked_tasks")),
    }
    if not tasks:
        return out

    # -- the workspace-wide read ------------------------------------------------------------
    first = next(iter(tasks))
    wide = [("page", 0), ("subtasks", "true"), ("include_closed", "true")]
    st, tw = pr.get("workspace tasks", f"/team/{ws}/task", wide + [("list_ids[]", home[first])])
    a["workspace_task_read"] = {"status": st, "envelope": [k for k in keys(tw) if k != "tasks"], "count": len(rows(tw, "tasks"))}
    if multi:
        added = str((tasks[multi[0]]["locations"][0] or {}).get("id"))
        st, tm = pr.get("workspace tasks, added List", f"/team/{ws}/task", wide + [("list_ids[]", added)])
        a["workspace_task_read"]["includes_a_task_added_to_the_list"] = multi[0] in {str(t.get("id")) for t in rows(tm, "tasks")}
    tagged = next((t for t in tasks.values() if t.get("tags")), None)
    if tagged:
        tag = str(tagged["tags"][0].get("name"))
        st, full = pr.get("tag filter, whole", f"/team/{ws}/task", wide + [("tags[]", tag)])
        st2, part = pr.get("tag filter, first half", f"/team/{ws}/task", wide + [("tags[]", tag[: max(1, len(tag) // 2)])])
        a["tag_filter"] = {"whole": {"status": st, "count": len(rows(full, "tasks"))},
                           "first_half": {"status": st2, "count": len(rows(part, "tasks"))}, "tag_length": len(tag)}
    if text_field:
        lid, fid, value = text_field
        a["text_field_filter"] = {}
        # The flags of the read that found the value: without them a subtask, or a task only
        # added to this List, is out of the filter's reach and every count is 0 whatever it matches.
        reach = [("subtasks", "true"), ("include_closed", "true"), ("include_timl", "true")]
        for label, op, v in (("exact", "==", value), ("other_case", "==", value.swapcase()),
                             ("whole", "=", value), ("part", "=", value[: len(value) // 2])):
            flt = json.dumps([{"field_id": fid, "operator": op, "value": v}])
            st, hit = pr.get(f"text field {label}", f"/list/{lid}/task", reach + [("custom_fields", flt)])
            a["text_field_filter"][label] = {"operator": op, "status": st, "count": len(rows(hit, "tasks"))}

    # -- one task, whole --------------------------------------------------------------------
    pick = next((tid for tid, t in tasks.items() if t.get("markdown_description") or t.get("description")), first)
    st, one = pr.get("one task", f"/task/{pick}", [("include_markdown_description", "true"), ("include_subtasks", "true")])
    one = one if isinstance(one, dict) else {}
    a["one_task"] = {"status": st, "keys": keys(one), "markdown_description": kind(one.get("markdown_description")),
                     "description": kind(one.get("description")), "text_content": kind(one.get("text_content")),
                     "custom_item_id": kind(one.get("custom_item_id")), "parent": kind(one.get("parent")),
                     "top_level_parent": kind(one.get("top_level_parent")), "list_keys": keys(one.get("list")),
                     "locations": len(one.get("locations") or []), "subtasks": len(one.get("subtasks") or [])}
    if custom_ids:
        cid = urllib.parse.quote(str(custom_ids[0]["custom_id"]), safe="")
        st, by_key = pr.get("task by custom id", f"/task/{cid}", [("custom_task_ids", "true"), ("team_id", ws)])
        a["task_by_custom_id"] = {"status": st, "same_task": isinstance(by_key, dict) and by_key.get("id") == custom_ids[0].get("id")}
    st, cm = pr.get("comments", f"/task/{pick}/comment")
    comments = rows(cm, "comments")
    segments = [s for c in comments for s in c.get("comment") or [] if isinstance(s, dict)]
    a["comments"] = {"status": st, "envelope": [k for k in keys(cm) if k != "comments"], "count": len(comments),
                     "keys": keys(comments[0]) if comments else [], "segment_keys": sorted({k for s in segments for k in s}),
                     "attribute_keys": sorted({k for s in segments for k in (s.get("attributes") or {})}),
                     "newest_first": len(comments) < 2 or int(comments[0].get("date") or 0) >= int(comments[-1].get("date") or 0)}
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="clickup_phase8_readonly.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--workspace", help="workspace (team) id; needed only when the token sees several")
    parser.add_argument("--space", action="append", default=[], help="a Space id to read; repeat for more")
    parser.add_argument("--max-lists", type=int, default=12, help="Lists sampled per Space, sprint-like first (default 12)")
    parser.add_argument("--plan", action="store_true", help="print the call list; no network")
    args = parser.parse_args(argv)
    if args.plan:
        print("\n".join(plan_calls()))
        return 0
    try:
        pr = Probe(secrets.get("CLICKUP_API_TOKEN"))
    except secrets.SecretUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    findings = probe(pr, args.workspace, args.space, max(1, args.max_lists))
    findings["call_log"] = log
    out = HERE / "clickup-probe-report.json"
    out.write_text(json.dumps(findings, indent=2, default=str))
    print(f"\n{len(log)} calls, all GET; report (board content, stays here) → {out}")
    if args.space and findings["answers"].get("tasks") is not None:
        print("\nThe answers block: no name, id, title or text from the workspace.\n")
        print(json.dumps(findings["answers"], indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
