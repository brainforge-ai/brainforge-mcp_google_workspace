# PLT-2298 — brainforge-google MCP: tab lifecycle, batch range writes, revisionId on reads

**Status:** Ready for implementation
**Date:** 2026-10-15
**Ticket:** PLT-2298 (`brainforge-ai/brainforge-mcp_google_workspace`)
**Repo:** `brainforge-mcp_google_workspace` (server behind `https://gws-cf.brainforge.ai/mcp`)
**Branch:** `uttam/plt-2298-sheets-tools`
**Source:** [Retro over Google Sheets sessions](brainforge-platform) + `knowledge/engineering/google-sheets-agent-reference.md` § "Upstream improvements".

## Problem

Agents drive Sheets through this server and hit avoidable friction:

- **No tab lifecycle.** Merging two tabs leaves an orphan an agent can empty but not remove — there is no `delete_sheet` / `rename_sheet` / `hide_sheet`.
- **No cheap title→gid, no change signal.** A renamed tab fails `read_sheet_values`/`modify_sheet_values` with `Unable to parse range`, and reads do not say the tab set changed, so the agent re-reads blind. `get_spreadsheet_info` is re-called repeatedly per session.
- **N+1 writes.** A multi-range or table rewrite is one call per range; each is quota and latency, and a rewrite shorter than the prior table leaves invisible trailing cells.
- **Blind append.** `append_table_rows` is not idempotent; a retried append can double-write.
- **Opaque quota errors.** A `429` surfaces as a generic error with no retry guidance.

## Conventions (this repo)

Every tool is `@server.tool()` + `@handle_http_errors("<name>", is_read_only=?, service_type="sheets")` + `@require_google_service("sheets", "sheets_read"|"sheets_write")`. New tools are exported from `gsheets/__init__.py`, listed in `core/tool_tiers.yaml`, and tested under `tests/gsheets/`. Errors funnel through `core/utils.py::handle_http_errors`.

## Design

### U1 — `_resolve_sheet_id(service, spreadsheet_id, sheet)` helper (`sheets_helpers.py`)
Accept a tab title **or** numeric `sheetId`; resolve to `sheetId` via a `spreadsheets.get(fields="sheets(properties(title,sheetId))")`. Used by every structure tool, so a caller can name the tab or its stable gid.

### U2 — Tab lifecycle tools (`sheets_tools.py`)
- `delete_sheet(user_google_email, spreadsheet_id, sheet)` → `batchUpdate {deleteSheet:{sheetId}}`. Refuse deleting the last visible sheet (API error surfaced cleanly).
- `rename_sheet(user_google_email, spreadsheet_id, sheet, new_name)` → `updateSheetProperties{properties:{sheetId,title}, fields:"title"}`.
- `hide_sheet(user_google_email, spreadsheet_id, sheet, hidden=True)` → `updateSheetProperties{properties:{sheetId,hidden}, fields:"hidden"}`.

One `sheets_write` service, resolved sheet id, per-tool `@handle_http_errors`. Registered + tiered.

### U3 — `revisionId` + gid + hidden on reads
- `get_spreadsheet_info`: widen `fields` to `properties(title,locale,revisionId)` and `sheets(properties(title,sheetId,hidden,gridProperties(...)),conditionalFormats)`; print `revisionId` and each sheet's `gid` + `hidden`.
- `read_sheet_values`: add opt-in `include_revision: bool=False`; when set, one extra `spreadsheets.get(fields="spreadsheetId,properties(revisionId)")` and print it. Off by default (no extra call).

### U4 — `batch_modify_sheet_values`
`values.batchUpdate` accepts one `valueInputOption` for the whole batch (`data:[{range,values}...]`). Tool: `batch_modify_sheet_values(user_google_email, spreadsheet_id, data, value_input_option="USER_ENTERED")` where `data` is a list of `{range_name, values}` (JSON string or list). One request, atomic.

### U5 — `replace_table` convenience
`replace_table(user_google_email, spreadsheet_id, range_name, values, value_input_option="USER_ENTERED")`: `values.clear(range)` then `values.update` in one logical op, so a shorter rewrite cannot leave trailing cells. (Two API calls, one tool, documented.)

### U6 — Idempotent append
Surface the `tableRange` from `append_table_rows`; add optional `dedupe_column` + `dedupe_value`: before appending, read the table's key column and skip if the value already exists. Off by default (no extra read).

### U7 — Quota-aware errors (`core/utils.py::handle_http_errors`)
On `HttpError` status `429`/`503`: read `Retry-After` (seconds or HTTP-date), back off and retry up to `max_retries` for **read-only** tools, and in the raised message include the status, `Retry-After`, and the quota name when present.

## Files

| File | Change |
|---|---|
| `gsheets/sheets_helpers.py` | `_resolve_sheet_id`, batch payload builders |
| `gsheets/sheets_tools.py` | U2 tools; U3 field/output changes; U4/U5/U6 tools |
| `gsheets/__init__.py` | export new tools |
| `core/tool_tiers.yaml` | tier entries for new tools |
| `core/utils.py` | U7 429/503 handling |
| `tests/gsheets/` | unit tests per new tool (mock service, follow `test_format_sheet_range.py`) |

## Test plan

Mock the Sheets service (as existing `tests/gsheets` do). Assert: correct `batchUpdate` request bodies; title→gid resolution; `revisionId`/`hidden` appear only when requested; batch builds one `batchUpdate`; `replace_table` issues clear-then-update; dedupe skips a duplicate; `handle_http_errors` retries `429` with `Retry-After` on read-only and raises a clean message otherwise. Run `pytest tests/gsheets`.

## Rollout

Code + tests land on a branch and open a PR. Deployment to `gws-cf` is separate (Cloudflare/prod) and out of scope for this plan; `gcloud auth login` is available if a GCP step is needed.

## Risks

- `deleteSheet` on the last visible sheet errors — surface the API message, do not swallow.
- `fields` widening on `get_spreadsheet_info` returns more per call; negligible.
- `values.batchUpdate` shares one `valueInputOption` across ranges — document it.
