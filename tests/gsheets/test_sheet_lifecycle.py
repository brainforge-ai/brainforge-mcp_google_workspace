"""
Unit tests for the Google Sheets tab-lifecycle and batch-write tools (PLT-2298).

Covers title/sheetId resolution, delete/rename/hide request bodies, and
batch_modify_sheet_values input handling.
"""

import pytest
from unittest.mock import Mock
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from core.utils import UserInputError
from gsheets.sheets_tools import (
    _resolve_sheet_id,
    _delete_sheet_impl,
    _rename_sheet_impl,
    _hide_sheet_impl,
    _batch_modify_sheet_values_impl,
    _replace_table_impl,
    _filter_duplicate_rows,
)


def create_mock_service(sheets=None):
    """Create a mock Sheets service with two tabs: Sheet1 (0), Data (42)."""
    mock_service = Mock()
    metadata = {
        "sheets": sheets
        if sheets is not None
        else [
            {"properties": {"sheetId": 0, "title": "Sheet1"}},
            {"properties": {"sheetId": 42, "title": "Data"}},
        ]
    }
    mock_service.spreadsheets().get().execute = Mock(return_value=metadata)
    mock_service.spreadsheets().batchUpdate().execute = Mock(return_value={})
    mock_service.spreadsheets().values().batchUpdate().execute = Mock(
        return_value={"totalUpdatedCells": 4}
    )
    return mock_service


@pytest.mark.asyncio
async def test_resolve_sheet_id_by_title():
    service = create_mock_service()
    assert await _resolve_sheet_id(service, "ss", "Data") == 42


@pytest.mark.asyncio
async def test_resolve_sheet_id_by_numeric():
    service = create_mock_service()
    assert await _resolve_sheet_id(service, "ss", 7) == 7
    assert await _resolve_sheet_id(service, "ss", "7") == 7


@pytest.mark.asyncio
async def test_resolve_sheet_id_unknown_raises():
    service = create_mock_service()
    with pytest.raises(UserInputError) as exc:
        await _resolve_sheet_id(service, "ss", "Missing")
    assert "not found" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_delete_sheet_builds_delete_request():
    service = create_mock_service()
    result = await _delete_sheet_impl(service, "ss", "Data")
    body = service.spreadsheets().batchUpdate.call_args[1]["body"]
    assert body["requests"][0]["deleteSheet"]["sheetId"] == 42
    assert result["sheet_id"] == 42


@pytest.mark.asyncio
async def test_rename_sheet_builds_update_properties():
    service = create_mock_service()
    await _rename_sheet_impl(service, "ss", "Sheet1", "Renamed")
    body = service.spreadsheets().batchUpdate.call_args[1]["body"]
    req = body["requests"][0]["updateSheetProperties"]
    assert req["properties"] == {"sheetId": 0, "title": "Renamed"}
    assert req["fields"] == "title"


@pytest.mark.asyncio
async def test_rename_sheet_empty_name_raises():
    service = create_mock_service()
    with pytest.raises(UserInputError):
        await _rename_sheet_impl(service, "ss", "Sheet1", "   ")


@pytest.mark.asyncio
async def test_hide_sheet_builds_hidden_property():
    service = create_mock_service()
    await _hide_sheet_impl(service, "ss", "Data", hidden=True)
    body = service.spreadsheets().batchUpdate.call_args[1]["body"]
    req = body["requests"][0]["updateSheetProperties"]
    assert req["properties"] == {"sheetId": 42, "hidden": True}
    assert req["fields"] == "hidden"


@pytest.mark.asyncio
async def test_unhide_sheet():
    service = create_mock_service()
    result = await _hide_sheet_impl(service, "ss", "Data", hidden=False)
    body = service.spreadsheets().batchUpdate.call_args[1]["body"]
    assert body["requests"][0]["updateSheetProperties"]["properties"]["hidden"] is False
    assert result["hidden"] is False


@pytest.mark.asyncio
async def test_batch_modify_builds_value_ranges():
    service = create_mock_service()
    data = [
        {"range_name": "Sheet1!A1:B2", "values": [["a", "b"], ["c", "d"]]},
        {"range_name": "Sheet1!D1", "values": [["e"]]},
    ]
    result = await _batch_modify_sheet_values_impl(service, "ss", data)
    body = service.spreadsheets().values().batchUpdate.call_args[1]["body"]
    assert body["valueInputOption"] == "USER_ENTERED"
    assert [d["range"] for d in body["data"]] == ["Sheet1!A1:B2", "Sheet1!D1"]
    assert result["total_cells_updated"] == 4


@pytest.mark.asyncio
async def test_batch_modify_accepts_json_string():
    import json

    service = create_mock_service()
    data = json.dumps([{"range_name": "A1", "values": [["x"]]}])
    await _batch_modify_sheet_values_impl(service, "ss", data)
    body = service.spreadsheets().values().batchUpdate.call_args[1]["body"]
    assert body["data"][0]["range"] == "A1"


@pytest.mark.asyncio
async def test_batch_modify_empty_raises():
    service = create_mock_service()
    with pytest.raises(UserInputError):
        await _batch_modify_sheet_values_impl(service, "ss", [])


@pytest.mark.asyncio
async def test_batch_modify_missing_range_raises():
    service = create_mock_service()
    with pytest.raises(UserInputError):
        await _batch_modify_sheet_values_impl(service, "ss", [{"values": [["x"]]}])


@pytest.mark.asyncio
async def test_batch_modify_bad_value_input_option_raises():
    service = create_mock_service()
    with pytest.raises(UserInputError):
        await _batch_modify_sheet_values_impl(
            service, "ss", [{"range_name": "A1", "values": [["x"]]}], "NOPE"
        )


@pytest.mark.asyncio
async def test_resolve_sheet_id_title_wins_over_numeric():
    service = create_mock_service(
        sheets=[{"properties": {"sheetId": 99, "title": "2024"}}]
    )
    assert await _resolve_sheet_id(service, "ss", "2024") == 99


@pytest.mark.asyncio
async def test_resolve_sheet_id_bool_raises():
    service = create_mock_service()
    with pytest.raises(UserInputError):
        await _resolve_sheet_id(service, "ss", True)


@pytest.mark.asyncio
async def test_batch_modify_non_2d_row_raises():
    service = create_mock_service()
    with pytest.raises(UserInputError):
        await _batch_modify_sheet_values_impl(
            service, "ss", [{"range_name": "A1", "values": ["a", "b"]}]
        )


@pytest.mark.asyncio
async def test_replace_table_clears_then_writes():
    service = Mock()
    service.spreadsheets().values().clear().execute = Mock(
        return_value={"clearedRange": "Sheet1!A1:B10"}
    )
    service.spreadsheets().values().update().execute = Mock(
        return_value={"updatedCells": 4, "updatedRows": 2}
    )
    result = await _replace_table_impl(
        service, "ss", "Sheet1!A1:B2", [["a", "b"], ["c", "d"]]
    )
    assert service.spreadsheets().values().clear.called
    assert service.spreadsheets().values().update.called
    assert result["updated_cells"] == 4
    assert result["cleared_range"] == "Sheet1!A1:B10"


@pytest.mark.asyncio
async def test_replace_table_non_2d_raises():
    service = create_mock_service()
    with pytest.raises(UserInputError):
        await _replace_table_impl(service, "ss", "Sheet1!A1", ["a", "b"])


def _table_service(existing_values, column_name="Email"):
    service = Mock()
    service.spreadsheets().get().execute = Mock(
        return_value={
            "sheets": [
                {
                    "properties": {"sheetId": 0, "title": "Contacts"},
                    "tables": [
                        {
                            "tableId": "t1",
                            "range": {"startColumnIndex": 0},
                            "columnProperties": [
                                {"columnName": "Email"},
                                {"columnName": "Name"},
                            ],
                        }
                    ],
                }
            ]
        }
    )
    service.spreadsheets().values().get().execute = Mock(
        return_value={"values": [[v] for v in existing_values]}
    )
    return service


@pytest.mark.asyncio
async def test_filter_duplicate_rows_skips_existing():
    service = _table_service(["a@x.com"])
    kept, skipped = await _filter_duplicate_rows(
        service,
        "ss",
        "t1",
        "Email",
        [["a@x.com", "A"], ["b@x.com", "B"]],
    )
    assert skipped == 1
    assert kept == [["b@x.com", "B"]]


@pytest.mark.asyncio
async def test_filter_duplicate_rows_unknown_column_raises():
    service = _table_service([])
    with pytest.raises(UserInputError):
        await _filter_duplicate_rows(service, "ss", "t1", "Nope", [["v"]])
