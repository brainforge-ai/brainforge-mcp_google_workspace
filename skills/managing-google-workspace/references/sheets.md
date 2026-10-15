# Google Sheets Tools Reference

MCP tools for reading, writing, formatting, and managing Google Sheets. All tools require `user_google_email` (string, required). The `spreadsheet_id` parameter accepts a spreadsheet ID or a full Google Sheets URL.

## Contents
- Search & Info: list_spreadsheets, get_spreadsheet_info
- Read & Write: read_sheet_values, modify_sheet_values, batch_modify_sheet_values, replace_table
- Tabs: create_sheet, delete_sheet, rename_sheet, hide_sheet
- Tables: list_sheet_tables, append_table_rows
- Create: create_spreadsheet
- Formatting: format_sheet_range, manage_conditional_formatting
- Comments: list_spreadsheet_comments, manage_spreadsheet_comment
- Tips

---

## Search & Info

### list_spreadsheets
List spreadsheets the user has access to (via Drive).

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| max_results | integer | no | 25 | |

### get_spreadsheet_info
Get spreadsheet metadata: title, locale, and each tab's gid, grid size, hidden flag, and conditional-format count.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| spreadsheet_id | string | yes | | |

---

## Read & Write

### read_sheet_values
Read values from a range in a spreadsheet.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| spreadsheet_id | string | yes | | |
| range_name | string | no | A1:Z1000 | A1 notation, e.g. `Sheet1!A1:D10` |
| include_hyperlinks | boolean | no | false | Fetch hyperlink metadata (slower) |
| include_notes | boolean | no | false | Fetch cell notes (slower) |
| include_formulas | boolean | no | false | Fetch raw formula strings for cells containing formulas |
| include_sheet_state | boolean | no | false | Also return the tab inventory (gid, title, hidden) — a structural-change signal |

### modify_sheet_values
Write, update, or clear values in a range.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| spreadsheet_id | string | yes | | |
| range_name | string | yes | | A1 notation |
| values | array or string | conditional | | 2D array of values. Required unless `clear_values=true`. Accepts a JSON string or a list |
| value_input_option | string | no | USER_ENTERED | `RAW` or `USER_ENTERED` |
| clear_values | boolean | no | false | Clear the range instead of writing |

### batch_modify_sheet_values
Write or update several ranges in one API request (atomic, quota-lighter).

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| spreadsheet_id | string | yes | | |
| data | array or string | yes | | List of `{range_name, values}` objects. Accepts a JSON string or a list |
| value_input_option | string | no | USER_ENTERED | Applied to the whole batch: `RAW` or `USER_ENTERED` |

### replace_table
Clear a range, then write the new values — so a shorter replacement cannot leave stale trailing cells (which a plain write would).

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| spreadsheet_id | string | yes | | |
| range_name | string | yes | | A1 notation for the table body |
| values | array or string | yes | | 2D array of replacement values |
| value_input_option | string | no | USER_ENTERED | `RAW` or `USER_ENTERED` |

---

## Create

### create_spreadsheet
Create a new Google Spreadsheet.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| title | string | yes | | Spreadsheet title |
| sheet_names | array of strings | no | | Sheet names to create. Defaults to one sheet with the default name |

### create_sheet
Add a new sheet (tab) to an existing spreadsheet.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| spreadsheet_id | string | yes | | |
| sheet_name | string | yes | | |

### delete_sheet
Delete a whole tab and its content. Accepts the tab title or its numeric sheetId.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| spreadsheet_id | string | yes | | |
| sheet | string or integer | yes | | Tab title or numeric sheetId |

### rename_sheet
Rename a tab. The sheetId stays stable across the rename.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| spreadsheet_id | string | yes | | |
| sheet | string or integer | yes | | Current tab title or numeric sheetId |
| new_name | string | yes | | New tab title |

### hide_sheet
Hide or unhide a tab. Hidden tabs keep their data; `hidden=false` shows them again.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| spreadsheet_id | string | yes | | |
| sheet | string or integer | yes | | Tab title or numeric sheetId |
| hidden | boolean | no | true | True to hide, false to show |

---

## Tables

### list_sheet_tables
List structured tables with their IDs, names, ranges, and columns. Use to find a table's ID for `append_table_rows`.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| spreadsheet_id | string | yes | | |

### append_table_rows
Append rows to a structured table (extends the table range).

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| spreadsheet_id | string | yes | | |
| table_id | string | yes | | From `list_sheet_tables` |
| values | array or string | yes | | 2D array; each inner list is one row |
| dedupe_column | string | no | | Table column name to deduplicate on — rows whose value already exists are skipped, so the append is safe to retry |

---

## Formatting

### format_sheet_range
Apply visual formatting to a range: colors, number formats, text wrapping, alignment, and text styling.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| spreadsheet_id | string | yes | | |
| range_name | string | yes | | A1 notation (with optional sheet name) |
| background_color | string | no | | Hex `#RRGGBB` |
| text_color | string | no | | Hex `#RRGGBB` |
| number_format_type | string | no | | `NUMBER`, `CURRENCY`, `DATE`, `PERCENT`, etc. |
| number_format_pattern | string | no | | Custom pattern for the number format |
| wrap_strategy | string | no | | `WRAP`, `CLIP`, or `OVERFLOW_CELL` |
| horizontal_alignment | string | no | | `LEFT`, `CENTER`, or `RIGHT` |
| vertical_alignment | string | no | | `TOP`, `MIDDLE`, or `BOTTOM` |
| bold | boolean | no | | |
| italic | boolean | no | | |
| font_size | integer | no | | Size in points |

### manage_conditional_formatting
Add, update, or delete conditional formatting rules.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| spreadsheet_id | string | yes | | |
| action | string | yes | | `add`, `update`, or `delete` |
| range_name | string | for add | | A1 notation. Optional for update (preserves existing ranges if omitted) |
| condition_type | string | for add | | e.g. `NUMBER_GREATER`, `TEXT_CONTAINS`, `DATE_BEFORE`, `CUSTOM_FORMULA` |
| condition_values | array or string | conditional | | Values for the condition. Depends on `condition_type` |
| background_color | string | no | | Hex `#RRGGBB` applied when condition matches |
| text_color | string | no | | Hex `#RRGGBB` applied when condition matches |
| rule_index | integer | for update/delete | | 0-based index of the rule |
| gradient_points | array or string | no | | List of gradient point dicts for color-scale rules. Overrides boolean rule parameters |
| sheet_name | string | no | first sheet | Sheet name for locating the rule (used by update/delete) |

---

## Comments

### list_spreadsheet_comments
List all comments on a spreadsheet.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| spreadsheet_id | string | yes | | |

### manage_spreadsheet_comment
Create, reply to, or resolve a comment.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| spreadsheet_id | string | yes | | |
| action | string | yes | | `create`, `reply`, or `resolve` |
| comment_content | string | for create/reply | | Comment text |
| comment_id | string | for reply/resolve | | Target comment ID |

---

## Tips

**Range notation**: Use A1 notation throughout. Include the sheet name for multi-sheet spreadsheets (e.g. `Sheet2!A1:C10`). If no sheet name is given, the first sheet is used.

**USER_ENTERED vs RAW**: `USER_ENTERED` (default) parses values as if typed into the Sheets UI -- formulas are evaluated, dates parsed, numbers formatted. `RAW` stores exact strings without interpretation.

**Conditional formatting condition types**: Common values include `NUMBER_GREATER`, `NUMBER_LESS`, `NUMBER_BETWEEN`, `TEXT_CONTAINS`, `TEXT_NOT_CONTAINS`, `DATE_BEFORE`, `DATE_AFTER`, `CUSTOM_FORMULA`, `BLANK`, `NOT_BLANK`.

**Gradient rules**: Provide `gradient_points` as a list of dicts, each with `type` (`MIN`, `MAX`, `NUMBER`, `PERCENT`, `PERCENTILE`), `value` (string, optional for `MIN`/`MAX`), and `color` (hex `#RRGGBB`). When gradient points are set, boolean formatting parameters are ignored.
