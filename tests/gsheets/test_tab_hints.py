"""
Unit tests for the stale-tab-title self-healing hints (PLT-2298 follow-up).
"""

import pytest
from unittest.mock import Mock
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from gsheets.sheets_helpers import (
    _is_range_parse_error,
    _tab_name_suggestions,
)


def create_mock_service(titles=("BF Customers (Past/Current)", "Status", "Deal Reg")):
    mock_service = Mock()
    mock_service.spreadsheets().get().execute = Mock(
        return_value={
            "sheets": [{"properties": {"title": t}} for t in titles],
        }
    )
    return mock_service


def test_is_range_parse_error_true_on_sheets_message():
    err = Exception(
        '<HttpError 400 ...> returned "Unable to parse range: BF Customers!A1:Z40"'
    )
    assert _is_range_parse_error(err) is True


def test_is_range_parse_error_false_for_other_errors():
    assert _is_range_parse_error(Exception("quota exceeded")) is False


@pytest.mark.asyncio
async def test_suggestions_name_closest_and_current_tabs():
    service = create_mock_service()
    note = await _tab_name_suggestions(service, "ss", "BF Customers!A1:Z40")
    assert "not found" in note
    assert "BF Customers (Past/Current)" in note  # closest match
    assert "Status" in note  # current tabs listed
    assert "get_spreadsheet_info" in note  # actionable next step


@pytest.mark.asyncio
async def test_suggestions_empty_without_sheet_name():
    service = create_mock_service()
    assert await _tab_name_suggestions(service, "ss", "A1:Z40") == ""


@pytest.mark.asyncio
async def test_suggestions_empty_when_lookup_fails():
    service = Mock()
    service.spreadsheets().get().execute = Mock(side_effect=Exception("boom"))
    assert await _tab_name_suggestions(service, "ss", "Missing!A1") == ""


@pytest.mark.asyncio
async def test_suggestions_handles_quoted_sheet_name():
    service = create_mock_service()
    note = await _tab_name_suggestions(service, "ss", "'BF Customers'!A1:Z40")
    assert "BF Customers (Past/Current)" in note
