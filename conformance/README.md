# conformance/

The adapter conformance suite. A new backend is supported when its
adapter passes this suite live against a **throwaway** project on that
tracker (design: agentic_optimization_research `roadmap/14` D7). It
lives outside `tests/` because it writes to a real board: the default
`uv run pytest` never runs it. `tests/test_conformance.py` runs it
offline against the fake Plane and Jira transports. The knowledge
publisher has its own live suite, on the same runner:
[below](#the-knowledge-publisher-phase-6b).

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
- **Custom fields are the operator's.** The `fields` case needs the
  config's `[fields]` to exist on the board, and the suite never creates
  one, since the config gives no kind or options. On Plane, `provision`
  stops and names the work-item properties to add. On Jira, the field must
  be on the project's screens (Jira lists it only then), and an option
  field needs its options.
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
| `dates` | *Phase 6c (D41).* A story with a start and a target date: both read back as written, from `get_item` and from the list read alike. `update_item` then moves the target date a day, and the start date stays. |
| `fields` | *Phase 6c (D41).* Each `[fields]` entry the story type carries: written at create, read back by `get_item`, then changed by `update_item` while the others stay. The values come from `describe_board` (a boolean flips, an option field takes its first options then its last, and so on). It skips when the config has no `[fields]`. |
| `iterations` | This month's iteration, ending **today**: whether the tracker still takes items into it shows whether the end day is open. Next month's iteration reads planned. The dates read back exactly as written. Items move into both, confirmed by the list read. |
| `close` | `close_iteration` closes this month's iteration, a fresh read agrees, and the closed iteration refuses new items as a `ValidationError`. |
| `rollover` | *Phase 6.* `create_iteration` with next month's name returns that iteration rather than a duplicate. `find_items(iteration=…)` on the closed iteration returns only items still in it. Everything there that is neither done nor cancelled moves to next month's iteration (board-wide, as a real rollover does), and fresh reads of both iterations agree. The note records what stayed, and what left along with a moved parent. Skips when nothing is unfinished. |
| `no-delete` | No DELETE was sent at any point in the run. The count comes from the transport's own call log, across resumed runs. It runs again on every process, so a case added to a finished run is covered too. |

## Results

| Ran | Backend / board | Verdict |
|---|---|---|
| 2026-09-22 | Plane Cloud, throwaway project `AGADMIN` | **PASS 9/9**. The run sent GET 81, PATCH 5, POST 20 and no DELETE, with no 429 or edge wall. It needed three adapter fixes along the way, plus a fourth found by a read-only check after the run (below). |
| 2026-09-27 | Jira Cloud (Premium trial), company-managed Scrum project `AGADM`, board 2 | **PASS 9/9** on the first run. It sent GET 48, POST 14, PUT 1 and no DELETE, with no 429. No adapter fix was needed; one fake-transport rule was wrong and is corrected (below). |
| 2026-09-27 | Jira `AGADM`: run `20260927` resumed with the new `rollover` case | **PASS 10/10.** `rollover` sent GET 16 and POST 1; the run's total is GET 64, POST 15, PUT 1 and no DELETE. The fake had one more rule wrong, now corrected (below). |
| 2026-09-27 | Plane `AGADMIN`: a new run, `20260927` | **PASS: 9 pass, 1 skip.** `iterations` skipped because `202609` was already closed; `close` and `rollover` ran on the ids it recorded first. GET 36, PATCH 2, POST 10 and no DELETE. |
| 2026-10-07 | Plane `AGADMIN`: a new run, `20261007`, with `[fields]` (a yes/no and a multi-select property on Story) | **PASS: 10 pass, 2 skip.** The new `dates` and `fields` cases pass. `iterations` skipped because `202610` was already closed, and `rollover` because it held nothing unfinished. GET 80, PATCH 3, POST 15 and no DELETE. The first process stopped on a network timeout at the start of `fields`, before any write; the re-run resumed there. |
| 2026-10-07 | Jira `AGADM`: a new run, `20261007`, with `[fields]` (a multi-checkbox custom field) | **PASS: 10 pass, 2 skip** on the first run, skipping as Plane did. GET 78, POST 10, PUT 3 and no DELETE. The read-only check before it found one adapter message to fix (below). |

### What the 2026-10-07 runs settled (Phase 6c, D41)

- **Plane dates** go in the create POST and the PATCH, as `YYYY-MM-DD`,
  and read back the same from `get_item` and the list read.
- **Plane values:** the upsert `POST …/values/` took a boolean and a
  list of option ids. On a multi-select it **replaces the set**: `option
  a, option b`, then `option c`, read back as `option c` alone. A value
  reads back one property at a time, so each `get_item` costs a GET per
  property on the item's type. A multi-select's values may come back in
  another order; the case compares them as a set.
- **Jira dates:** the target date is `duedate`, and the start date is
  `customfield_10015`, the field named "Start date". Both are written in
  the create and the PUT, and the search returns them too.
- **Jira values:** a multi-checkbox field takes `[{"value": <name>}]` in
  the create and the PUT, and the PUT replaces the set.
- **A new Jira field is missing from `GET /rest/api/3/field`** until it
  is on one of the project's screens, although it has a global context
  (the admin `field/search` finds it). Until it has options, its create
  screen lists no `allowedValues`. `describe_board` now says so when a
  configured field isn't found.

Left on the boards by these runs: `AGADMIN-17` to `AGADMIN-23` and module
`Conformance 20261007` on Plane; `AGADM-7` to `AGADM-13` and one comment
on `AGADM-8` on Jira.

### What the 2026-09-27 rollover runs settled (Phase 6)

- **Both trackers let an item leave a closed iteration.** A plain move
  into the next one works: Plane's `POST …/cycles/{next}/cycle-issues/`
  took AGADMIN-2 out of the completed `202609`, and Jira's `POST
  …/sprint/{next}/issue` took AGADM-2 out of the closed `202609`. So
  rollover can close first and move after, which Jira's one-active-sprint
  rule requires. Plane's own `transfer-issues` isn't needed.
- **Jira carries a moved story's sub-tasks, done ones too.** AGADM-4,
  the story's done sub-task, left `202609` with AGADM-2. On Plane a task
  is its own item, and the done one stayed in `202609`. A sub-task moved
  *on its own* is still unproven.
- **Jira's Sprint field keeps the closed sprint.** AGADM-2 now lists
  `202609` (closed) then `202610` (future), and JQL `sprint = <202609>`
  still matches it. So `find_items(iteration=…)` keeps only the issues
  whose *current* sprint it is. On Plane an item is in one cycle, read
  from the cycle's own `cycle-issues/` list.
- **Find-or-create:** `create_iteration("202610")` returned the existing
  iteration on both boards, with no second one made. Starting a Jira
  sprint made ahead of time, once its first day comes, was covered only
  offline until the Phase 6 gate ran it live on 2026-10-01
  ([the gate record](../transcripts/2026-10-02-phase6-gate.md)).

Left on the boards by these runs: `AGADMIN-12` to `AGADMIN-16` and
module `Conformance 20260927` on Plane. `AGADMIN-2` and `AGADM-2`/`-4`
now sit in `202610`.

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
  the sprint. A sub-task moved on its own is still unproven. The rollover
  run found that moving the story alone carries its sub-tasks too
  (above).
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

## The knowledge publisher (Phase 6b)

`knowledge.py` proves the Markdown → Confluence publisher against a
**throwaway** space (roadmap/14 §9 row 6b). It publishes a six-page tree
it writes itself, then edits, moves and removes parts of it.
`tests/test_conformance.py` runs it offline against the fake Confluence.

```sh
uv run python -m conformance.knowledge boards/<kb>.toml --dry-run   # the cases; no calls
uv run python -m conformance.knowledge boards/<kb>.toml             # live: real writes, no deletes
```

- **The config is the publisher's own**
  ([examples/knowledge/confluence.example.toml](../examples/knowledge/confluence.example.toml)),
  with the Jira adapter's credentials. `space.parent` must be a fresh,
  empty page: the `space` case stops if it holds anything.
- **Runs keep apart.** A run labels its pages `<publish.label>-<run id>`
  and ends each title in the run id. Titles are unique across a whole
  space, so a new run id also needs a new parent page.
- **It stops once, on purpose.** At `archived`, it exits 3 and asks you to
  archive the removed file's page by hand, as the design leaves orphans to
  people. Run the same command again to resume.
- **Options, record, exit codes:** the same as the adapter suite's.
  `--run-id` must be lowercase, because it goes into a label.

| Case | Checks |
|---|---|
| `space` | Read before any write: the space, its homepage, and a parent page that isn't the homepage and holds nothing. |
| `publish` | A dry run writes nothing and plans six creates. The real run makes them in the planned number of writes. Read back apart from the publisher, each page has its title and sits under its folder's page. Each page's version equals its `md-source` property's. Every relative link and `[[wikilink]]` lands on its target page's URL, as does each page's closing "Linked from" list, and the external link survives. |
| `search` | How long CQL takes to find the pages by the run's label (polls every 5 s, up to 180 s); a file's own label then finds exactly its page. |
| `paging` | The v2 page listing and v1 CQL, read one row at a time: the form `_links.next` takes, and whether the walk reaches the same rows as one call. |
| `rerun` | The same tree again: no write at all, every page unchanged, none reported as drift. |
| `edit` | One file edited: exactly its page PUT and its property PUT, its version +1, and no other page's version changed. |
| `move` | A v2 PUT naming a new `parentId` moves the page. The publisher then reports it as drift and writes nothing. The file's next edit puts it back. |
| `remove` | A removed file's page is reported as an orphan, with nothing written, and stays current. |
| `refusals` | The real errors for a PUT at a stale version and a create with a taken title. |
| `archived` | *Needs a person.* Once the orphan is archived: whether the default listing still holds it, whether its title still blocks a new page, and that the publisher then leaves it alone. |
| `no-delete` | No DELETE across the run's processes, from the transport's own log. |

### Its results

| Ran | Space | Verdict |
|---|---|---|
| 2026-09-28 | Confluence Cloud (Premium trial), throwaway space `AGKB`, under a fresh page | **PASS 11/11**, over two processes with one stop for the archive. It sent GET 106, POST 20, PUT 16 and no DELETE, with no 429. It found one publisher bug, fixed in the same PR (below). |
| 2026-10-26 | `AGKB`, a new run, `20261026`, under a new empty page, with the tree's wikilinks and backlinks | **PASS 11/11** on the first run, over two processes with the one stop. GET 202, POST 20, PUT 16 and no DELETE. No fix was needed (below). |

### What the 2026-10-26 run settled

- **Wikilinks and backlinks, live.** The tree gained a wikilink to a note
  and one to a folder note on 2026-10-25. `publish` read every page back
  apart from the publisher: each wikilink and each "Linked from" entry
  landed on its target page's URL, as the relative links do.
- **A page's own labels hold a just-written label at once.** Before any
  wait, the v2 labels route showed the shared label on all six pages. That
  was the inference behind the one-label-per-tree guard (PR #27), now
  measured. CQL found the pages 14 s after the publish ended (16 s on
  2026-09-28).
- The rest matched the 2026-09-28 run: `_links.next` in the same forms,
  each walk reaching the same rows as a single call; the same 409 and 400
  bodies; and an archived page that stays in the listing and still blocks
  its title.

Left on `AGKB` by this run: `Conformance 20261026` and its five pages
under `Conformance Test 20261026`, with `Old 20261026` archived.

### The `publish-docs.yml` example, on GitHub's runners (2026-10-26)

[examples/knowledge/publish-docs.yml](../examples/knowledge/publish-docs.yml)
ran once, in a private throwaway docs repo: three pages (a relative link,
a wikilink, front matter) under "Team Docs" with their own label. The
workflow was copied unchanged, except that, while this repo is private,
the `PUBLISHER` URL reads it with a fine-grained, read-only token (a third
secret), pinned to `b0aedc1`.

- **PASS** in 1 min 42 s. `actions/checkout@v7` and
  `astral-sh/setup-uv@v10.2.0` resolved, the publisher installed from the
  pinned commit (29 packages), and the run made 4 pages in 7 writes, as a
  local dry run had planned. The log masked all three secrets.
- Read back apart from the run: a re-run dry run planned 0 writes.
  `search_docs` found all four pages, scoped to the label. `get_doc`
  showed the wikilink and the relative link landing on their pages, each
  page's "Linked from" list, and the front-matter table.

### What the 2026-09-28 run settled

The six points the offline fake had only taken from the docs:

- **`_links.next`:** v2 gives a path under `/wiki`
  (`/wiki/api/v2/spaces/{id}/pages?limit=…&cursor=…`). v1 search gives one
  relative to it (`/rest/api/search?next=true&cursor=…&limit=…&start=…&cql=…`).
  Walked one row at a time, both reached the same rows as a single call.
- **A property or label write leaves the page version alone.** So the
  publisher's own writes never read as drift, and the re-run reported
  none.
- **A v2 PUT with a new `parentId` moves the page.** The publisher found
  the moved page, still inside the tree, and reported drift without
  writing. The file's next edit put the page back.
- **CQL lag:** a poll 16 s after the publish ended found all six pages by
  their shared label. A file's own label then found exactly its page. The
  scan below the parent page covers the gap.
- **The real errors** come back as a v2 `errors[]` list, and both map to
  `ValidationError`, which the publisher reports as a conflict. A stale
  version gets HTTP 409 `CONFLICT` "Version must be incremented when
  updating a page. Current Version: [2]. Provided version: [2]", which the
  fake now matches. A taken title gets HTTP 400 `BAD_REQUEST` "A page with
  this title already exists: A page already exists with the same TITLE in
  this space".
- **Archived pages:** the default v2 page listing still holds one, with
  status `archived`, and its title still blocks a new page (the same 400).
  The publisher already counts every listed title as taken, so a file
  whose title clashes gets its folder added instead of meeting that 400.
  Once a page is archived, the publisher stops reporting it.

What the fake didn't model:

- **Page ids are not in creation order.** `old.md`'s page got a lower id
  than the root page made before it. When two pages claim one file, the
  publisher kept the lowest id as the oldest. It now orders them by the
  listing's `createdAt`. The fake carries `createdAt` too, and a test puts
  a newer copy at a lower id.
- **Links:** each relative link came back as a link mark on
  `<site>/wiki/spaces/AGKB/pages/<id>`. A page's own `webui` is that path
  plus a title slug.

Left on `AGKB` by this run: `Conformance 20260928` and its five pages
under `Conformance Test`, with `Old 20260928` archived. The duplicate-title
attempts made no page.
