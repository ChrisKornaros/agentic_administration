# probes/

Throwaway, read-only scripts that check a tracker's live API before a
phase depends on the answer. They are evidence, not product code: each
one is dated, run once against a personal workspace, and kept so the
finding it produced can be re-run when the vendor changes again.

| Probe | Ran | What it settled |
|---|---|---|
| [plane_phase1_readonly.py](plane_phase1_readonly.py) | 2026-09-16 | Plane Cloud after the May-2026 model change: old routes alias the new `work-items` / `work-item-types` names; Work Item Types are live per project (Epic/Story/Task, no Bug); the Hierarchy feature has no API read surface; `external_id` is on every record and search accepts it as a filter; plus `features`, `members-lite`, retrieve-by-identifier and `expand=` shapes. |

Rules:

- **GET only.** A probe never writes. Write-side questions become
  conformance cases in `conformance/`, run against a throwaway project.
- **Secrets stay at one boundary.** The Plane probe reuses the seed
  CLI's Bitwarden-backed resolver rather than reading a token itself.
- **Reports are local.** `probe-report.json` holds board content and is
  gitignored; the summarized findings live in the design repo.
