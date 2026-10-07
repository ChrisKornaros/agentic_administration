# probes/

Throwaway, read-only scripts that check a tracker's live API before a
phase depends on the answer. They are evidence, not product code: each
one is dated, run once against a personal workspace, and kept so the
finding it produced can be re-run when the vendor changes again.

| Probe | Ran | What it settled |
|---|---|---|
| [plane_phase1_readonly.py](plane_phase1_readonly.py) | 2026-09-16 | Plane Cloud after the May-2026 model change: old routes alias the new `work-items` / `work-item-types` names; Work Item Types are live per project (Epic/Story/Task, no Bug); the Hierarchy feature has no API read surface; `external_id` is on every record and search accepts it as a filter; plus `features`, `members-lite`, retrieve-by-identifier and `expand=` shapes. |
| [jira_phase5_readonly.py](jira_phase5_readonly.py) | 2026-09-27 | Jira Cloud, a company-managed Scrum project (29 GETs). A classic token plus the account email works as Basic auth on the site URL. Types are Epic (level 1), Story/Bug/Task (0) and Sub-task (−1); nothing sits above Epic. Five statuses, with global transitions named after their target; a new item starts in Backlog. The create screens carry labels, components, parent, Sprint (`customfield_10020`), description and assignee. The old `/rest/api/3/search` answers 410 (removed); `/search/jql` pages by `nextPageToken` / `isLast` with no total. JQL matches `labels` exactly with `=`; summary and text only take `~`. Labels are free-form, so none exist until used. `/project/{id}/hierarchy` and `/board/{id}/features` answer for team-managed projects only. Rate headers: `RateLimit-Policy: "jira-burst-based";q=100;w=1`. |
| [plane_phase6c_readonly.py](plane_phase6c_readonly.py) | 2026-10-07 | Plane Cloud's dates and work-item properties, on the throwaway project and the Food Content calendar board (43 GETs). Properties belong to a type: the throwaway project's types have none, and Food Content's Story has two, a boolean and a multi-valued option property. An option property's options ride on its record (`options`: `id`, `name`, `is_default`, `is_active`); the `…/options/` route answers 404. A value reads one property at a time, from `…/work-items/{id}/work-item-properties/{prop}/values/`. A single-valued property comes back as one record and a multi-valued one as a list, each with `value` (a boolean, or an option id) and `value_type`. An unset value answers 404 ("Property value not set for this work item"), and no route returns all of an item's values at once (404). Every item read, the list, by id and by key, carries `start_date` and `target_date` as `YYYY-MM-DD`. The by-key read's `cycle_id` is null on all six stories read, while the by-id read carries it (the Phase 6 gate's finding 6). Both projects' time zone is UTC. |
| [jira_phase6c_readonly.py](jira_phase6c_readonly.py) | 2026-10-07 | Jira Cloud's dates and custom fields on the company-managed throwaway project (22 GETs, all 200). The system `duedate` (type `date`) and the site's Start date, `customfield_10015` (a datepicker with one global context for every issue type), are on every issue type's create and edit screens. Advanced Roadmaps' Target start and Target end (`customfield_10022` / `10023`) are separate fields. Apart from Sprint and Team, no custom field is on the project's screens, so a live custom-field write first needs one added to them. No issue had a date set yet. |
| [confluence_phase6b_readonly.py](confluence_phase6b_readonly.py) | 2026-09-28 | Confluence Cloud, a `knowledge_base` space made from Atlassian's template (18 GETs, all 200). The classic Jira token and account email work as Basic auth on `/wiki` (D29). The site ran a Premium trial, which ends on 2026-10-27, the same day as Jira's. So this probe didn't show whether the API works on Free; a re-run after that date will. The template made a homepage plus two child pages. The homepage's ADF holds panels and (inline) `extension` macros; `adapters.jira.adf.to_markdown` reads it without error. v2 returns the ADF `value` as a JSON *string*. Links: `_links.base` is `<site>/wiki`, and a page carries `webui` and `tinyui` paths. Labels read on v2 and v1, page properties on v2 (the editor keeps four of its own). The exact-title lookup works, and a space starts with no properties. CQL: `label = "<absent>"` answers 200 and empty (not an error), and both `text ~` and `siteSearch ~` answer. Hits carry `title`, `url`, `excerpt` and `breadcrumbs`, which is what `search_docs` needs. No rate-limit headers came back at all. |

Rules:

- **GET only.** A probe never writes. Write-side questions become
  conformance cases in `conformance/`, run against a throwaway project.
- **Secrets stay at one boundary.** The Plane probe reuses the seed
  CLI's Bitwarden-backed resolver; the Jira probe uses this repo's
  [server/secrets.py](../server/secrets.py), as does the Confluence probe.
  None of them reads a token itself.
- **Reports are local.** `probe-report.json`, `jira-probe-report.json`,
  `confluence-probe-report.json` and the two `*-6c-probe-report.json` hold
  board or space content and are gitignored. The summarized findings live in the design repo.
