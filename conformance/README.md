# conformance/

The adapter conformance suite. A new backend is supported when its
adapter passes this suite live against a **throwaway** project on that
tracker (design: agentic_optimization_research `roadmap/14` D7). It
lives outside `tests/` because it writes to a real board: the default
`uv run pytest` never runs it. `tests/test_conformance.py` runs it
offline against the fake Plane and Jira transports.

## Run it

```sh
uv run python -m conformance boards/<board>.toml --dry-run   # the cases; no calls
uv run python -m conformance boards/<board>.toml             # live: real writes, no deletes
```

The credentials resolve the same way as `adapters.<backend> describe`
(see the top-level README). Options: `--run-id` (default: today,
`YYYYMMDD`), `--throttle` (seconds between calls; default the backend's
own, Plane 1.5 and Jira 0.5), `--reports` (where run records go).

- **Point it only at a throwaway project.** A run files an epic, a
  story, a bug and two tasks, plus a feature, two iterations, types and
  labels. Nothing is ever deleted, so the board keeps what each run
  leaves.
- **Re-runs resume.** The run record (`reports/<board>-<run id>.json`,
  gitignored because it holds board content) keeps each case's outcome,
  notes and call counts. A re-run with the same run id skips what
  passed. Items are found by `external_id` (`conformance:<run id>:<name>`)
  before they are created, so a 429 or the Cloudflare wall costs a wait,
  not a duplicate.
- **Exit codes:** 0 pass · 1 a case failed · 2 bad config or backend ·
  3 stopped (act on the last note, or wait out the wall, then re-run).
- **Budget:** one Plane run is about 20 POSTs and 5 PATCHes. Cloudflare's
  managed challenge showed up after about 24 creates in a burst. Keep
  the throttle. One Jira run is about 50 GETs, 14 POSTs and 1 PUT, far
  under its burst limit.

## The cases

| Case | Checks |
|---|---|
| `provision` | *Backend-specific.* Plane: turns on the features the config needs, then creates the missing non-epic types and labels, each by name so a re-run is safe. Jira: nothing to create (labels are free-form; types and statuses are admin settings), so it reads the board and stops for the operator if the config does not fit. Either stops for the operator where the API can't help. |
| `describe` | `describe_board` reports no problems, and every materialized level resolves. |
| `epic` | An epic written with an `external_id` is found by `find_items(external_id=…)`: exactly that item, and nothing for an id nobody wrote. `get_item` by key and by id agree, and the Markdown description reads back. |
| `placement` | A feature; a story under the epic, in the feature, with the review label; a bug under the epic; a task under the story. All are confirmed from the board's list read. Where the board collapses Feature, the story names it and must carry it where the collapse rule says. A task under a *known* epic is refused by the model before any call. |
| `hierarchy` | A task straight under the epic, with the epic's level left unstated so only the tracker can object. Either answer passes: accepted, or refused as a mapped `ValidationError`. The note says which. |
| `update` | Clearing the review label leaves the item's level alone. A task moves to done. A comment is added. |
| `iterations` | This month's iteration, ending **today**: whether the tracker still takes items into it shows whether the end day is open. Next month's iteration reads planned. The dates read back exactly as written. Items move into both, confirmed by the list read. |
| `close` | `close_iteration` closes this month's iteration, a fresh read agrees, and the closed iteration refuses new items as a `ValidationError`. |
| `no-delete` | No DELETE was sent at any point in the run. The count comes from the transport's own call log, across resumed runs. |

## Results

| Ran | Backend / board | Verdict |
|---|---|---|
| 2026-09-22 | Plane Cloud, throwaway project `AGADMIN` | **PASS 9/9**. The run sent GET 81, PATCH 5, POST 20 and no DELETE, with no 429 or edge wall. It needed three adapter fixes along the way, plus a fourth found by a read-only check after the run (below). |
| 2026-09-27 | Jira Cloud (Premium trial), company-managed Scrum project `AGADM`, board 2 | **PASS 9/9** on the first run. It sent GET 48, POST 14, PUT 1 and no DELETE, with no 429. No adapter fix was needed; one fake-transport rule was wrong and is corrected (below). |

### What the 2026-09-27 Jira run settled

- **Jira takes a sub-task straight under an epic.** The `hierarchy`
  case's sub-task landed as AGADM-5 with the epic as its parent. The
  REST create does not hold a child to the adjacent level, whatever the
  docs say, so on Jira too the model is the only guard. The fake had
  modelled the documented rule; it now accepts any higher-level parent.
- **The `xid:<external_id>` label works as the idempotency key.** Colons
  are fine in a label. `find_items(external_id=…)` found the new epic in
  one `/search/jql` call, so this run met no search lag. The adapter's
  memory of what it created stays as the guard for when it does.
- **Sprints:** a sprint created with dates and then set `active` keeps
  its dates, which were written on the account time zone's day edges
  (`202609` = 2026-09-01 00:00 to 09-27 23:59 New York) and read back as
  written. Closing it with incomplete items in it just works through the
  API, and sets `completeDate`. A closed sprint refuses new items with
  HTTP 400 "You must specify a sprint which has not been completed."
  The case moved the story and its sub-task in one call and both carry
  the sprint. A sub-task moved on its own is still unproven.
- **Transitions and comments:** the task reached Done through its
  transition, and a comment posted as ADF came back with its author.
- **Statuses:** on this run To Do and Cancelled still sat in the
  `indeterminate` category. The adapter maps by name, so it made no
  difference here, but Jira's own reports count cancelled work as
  unfinished until Cancelled moves into Done.

Left on `AGADM` by that run: AGADM-1 to AGADM-5, one comment on AGADM-2,
sprints `202609` (closed) and `202610` (future).

### What the 2026-09-22 run settled

The design's open questions:

- **`PATCH …/projects/{pid}/features/` flips `work_item_types` and
  `epics`.** API.md's "the Epics enable is UI-only" no longer holds.
  Turning on `epics` creates the `Epic` type (`is_epic: true`), and
  turning on work-item types adds a default `Task`. A fresh project can
  therefore be provisioned entirely by API.
- **`POST …/labels/` exists.** A `{"name"}` body is enough.
  `POST …/work-item-types/` with `{"name"}` made `Story` and `Bug`.
- **Cycle end day:** Plane still took items into a cycle whose
  `end_date` was today. Once the end moved to yesterday, it refused them
  (HTTP 400, "The Cycle has already been completed…", which the adapter
  maps to `ValidationError`). So a cycle completes once `end_date <
  today`, and `close_iteration`'s pull to yesterday is right. A past
  `start_date` is accepted on create, and a PATCH of `end_date` alone
  closes a current cycle. Plane returns **no cycle `status`** on either
  the list or the single read, so the adapter always works out an
  iteration's state from its dates.
- **Hierarchy (off on this workspace):** Plane accepted a task parented
  straight under an epic (AGADMIN-5). The model is the only guard, and it
  refuses the case when the parent's level is known.

What the run caught in the adapter (all fixed in the same PR, and now
modelled by the fake):

- **Every Plane route ends in `/`.** A slash-less one gets a 301 to the
  slashed path. urllib follows it silently for a GET, at double the
  requests and outside the throttle, but never re-sends a write. That
  broke `PATCH …/features` and `POST …/work-item-types`. The transport
  now reports a 3xx as "redirected to …", not "server error".
- **The `external_id` lookup is the project list, not the workspace
  search.** `GET …/projects/{pid}/work-items/?external_id=…&external_source=…`
  returns the one record, or 404, and needs both params (with
  `external_id` alone the filter is ignored). The workspace
  `work-items/search/` ignores both params and returns nothing for an
  empty term. Phase 1's "search accepts the filter" was a false
  positive. The write side was always right: both fields are stored.
- **A single-item read returns labels as whole objects;** the list read
  returns ids. `min_module_name`, the item's module membership, is on
  both.
- **Cycle dates come back as datetimes at a shifted offset.** Plane
  stores them on the project timezone's day boundaries (start 00:00:01,
  end 23:59; this project is UTC) but returns them at -04:00. So a
  `2026-10-01` start reads back as `2026-09-30T20:00:01-04:00`. The
  adapter took the first ten characters and read every start a day early.
  It now converts to the project's timezone first, and the `iterations`
  case checks that dates read back exactly as written. Found by a
  read-only check after the run; the fixed adapter reads the live cycles
  as 202609 = 09-01 to 09-21 and 202610 = 10-01 to 10-31.

Settled alongside: the adapter stays mechanical and does **not** add the
review label on create. Adding it is the MCP server's job (Phase 3), and
the suite passes it explicitly.

Left on `AGADMIN` by that run: AGADMIN-1 to AGADMIN-5, module
`Conformance 20260922`, cycles `202609` (closed) and `202610`.
