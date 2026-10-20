"""Tests for Calendar event IDs, edit scope, timezone validation, and notifications."""

import httplib2
import pytest
from googleapiclient.errors import HttpError
from unittest.mock import Mock

from gcalendar import calendar_tools


def _unwrap(tool):
    fn = tool.fn if hasattr(tool, "fn") else tool
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def _service(event=None):
    service = Mock()
    service.events.return_value.insert.return_value.execute.return_value = {
        "id": "evt_1",
        "summary": "Test",
        "htmlLink": "https://calendar.google.com/event",
    }
    service.events.return_value.get.return_value.execute.return_value = event or {
        "id": "evt_1",
        "summary": "Test",
    }
    service.events.return_value.patch.return_value.execute.return_value = {
        "id": "evt_1",
        "summary": "Test",
        "htmlLink": "https://calendar.google.com/event",
    }
    return service


@pytest.mark.asyncio
async def test_create_sends_caller_event_id():
    service = _service()

    await _unwrap(calendar_tools.manage_event)(
        service=service,
        user_google_email="user@example.com",
        action="create",
        summary="Standup",
        start_time="2026-10-20T10:00:00-04:00",
        end_time="2026-10-20T10:30:00-04:00",
        event_id="abcde12345",
        timezone="America/New_York",
    )

    body = service.events.return_value.insert.call_args.kwargs["body"]
    assert body["id"] == "abcde12345"


@pytest.mark.asyncio
async def test_create_duplicate_returns_existing_message():
    service = _service()
    service.events.return_value.insert.return_value.execute.side_effect = HttpError(
        httplib2.Response({"status": 409}), b"duplicate"
    )

    result = await _unwrap(calendar_tools.manage_event)(
        service=service,
        user_google_email="user@example.com",
        action="create",
        summary="Standup",
        start_time="2026-10-20T10:00:00-04:00",
        end_time="2026-10-20T10:30:00-04:00",
        event_id="abcde12345",
        timezone="America/New_York",
    )

    assert "already exists" in result


@pytest.mark.asyncio
async def test_timed_create_without_timezone_is_rejected():
    with pytest.raises(ValueError, match="needs an IANA timezone"):
        await _unwrap(calendar_tools.manage_event)(
            service=_service(),
            user_google_email="user@example.com",
            action="create",
            summary="Standup",
            start_time="2026-10-20T10:00:00",
            end_time="2026-10-20T10:30:00",
        )


@pytest.mark.asyncio
async def test_timed_create_with_explicit_offset_is_allowed():
    result = await _unwrap(calendar_tools.manage_event)(
        service=_service(),
        user_google_email="user@example.com",
        action="create",
        summary="Standup",
        start_time="2026-10-20T10:00:00Z",
        end_time="2026-10-20T10:30:00Z",
    )

    assert "Successfully created event" in result


@pytest.mark.asyncio
async def test_update_series_from_instance_targets_parent():
    service = _service({"id": "instance_1", "recurringEventId": "parent_1"})

    result = await _unwrap(calendar_tools.manage_event)(
        service=service,
        user_google_email="user@example.com",
        action="update",
        event_id="instance_1",
        edit_scope="series",
        summary="Updated",
    )

    assert service.events.return_value.patch.call_args.kwargs["eventId"] == "parent_1"
    assert "Scope: series" in result


@pytest.mark.asyncio
async def test_update_instance_targets_instance():
    service = _service({"id": "instance_1", "recurringEventId": "parent_1"})

    await _unwrap(calendar_tools.manage_event)(
        service=service,
        user_google_email="user@example.com",
        action="update",
        event_id="instance_1",
        edit_scope="instance",
        summary="Updated",
    )

    assert service.events.return_value.patch.call_args.kwargs["eventId"] == "instance_1"


@pytest.mark.asyncio
async def test_update_instance_rejects_non_recurring_event():
    service = _service({"id": "standalone_1"})

    with pytest.raises(ValueError, match="not a recurring instance"):
        await _unwrap(calendar_tools.manage_event)(
            service=service,
            user_google_email="user@example.com",
            action="update",
            event_id="standalone_1",
            edit_scope="instance",
            summary="Updated",
        )


@pytest.mark.asyncio
async def test_update_response_reports_notifications():
    service = _service({"id": "instance_1", "recurringEventId": "parent_1"})

    result = await _unwrap(calendar_tools.manage_event)(
        service=service,
        user_google_email="user@example.com",
        action="update",
        event_id="instance_1",
        edit_scope="series",
        summary="Updated",
        send_updates="none",
    )

    assert "Notifications: none" in result


@pytest.mark.asyncio
async def test_update_instance_without_scope_requires_a_choice():
    service = _service({"id": "instance_1", "recurringEventId": "parent_1"})

    with pytest.raises(ValueError, match="is a recurring instance"):
        await _unwrap(calendar_tools.manage_event)(
            service=service,
            user_google_email="user@example.com",
            action="update",
            event_id="instance_1",
            summary="Updated",
        )


@pytest.mark.asyncio
async def test_standalone_update_without_scope_uses_the_event():
    service = _service({"id": "standalone_1"})

    await _unwrap(calendar_tools.manage_event)(
        service=service,
        user_google_email="user@example.com",
        action="update",
        event_id="standalone_1",
        summary="Updated",
    )

    assert service.events.return_value.patch.call_args.kwargs["eventId"] == "standalone_1"


@pytest.mark.asyncio
async def test_invalid_timezone_is_rejected():
    with pytest.raises(ValueError, match="Unknown IANA timezone"):
        await _unwrap(calendar_tools.manage_event)(
            service=_service(),
            user_google_email="user@example.com",
            action="create",
            summary="Standup",
            start_time="2026-10-20T10:00:00",
            end_time="2026-10-20T10:30:00",
            timezone="America/New_Yrok",
        )


@pytest.mark.asyncio
async def test_all_day_create_does_not_require_timezone():
    result = await _unwrap(calendar_tools.manage_event)(
        service=_service(),
        user_google_email="user@example.com",
        action="create",
        summary="Holiday",
        start_time="2026-10-20",
        end_time="2026-10-21",
    )

    assert "Successfully created event" in result


@pytest.mark.asyncio
async def test_explicit_offset_is_allowed_without_timezone():
    result = await _unwrap(calendar_tools.manage_event)(
        service=_service(),
        user_google_email="user@example.com",
        action="create",
        summary="Standup",
        start_time="2026-10-20T10:00:00+05:30",
        end_time="2026-10-20T10:30:00+05:30",
    )

    assert "Successfully created event" in result


@pytest.mark.asyncio
async def test_duplicate_with_different_summary_is_reported_as_conflict():
    service = _service()
    service.events.return_value.insert.return_value.execute.side_effect = HttpError(
        httplib2.Response({"status": 409}),
        b'{"error":{"errors":[{"reason":"duplicate"}]}}',
    )
    service.events.return_value.get.return_value.execute.return_value = {
        "id": "abcde12345",
        "summary": "Old title",
        "htmlLink": "https://calendar.google.com/event",
    }

    result = await _unwrap(calendar_tools.manage_event)(
        service=service,
        user_google_email="user@example.com",
        action="create",
        summary="New title",
        start_time="2026-10-20T10:00:00-04:00",
        end_time="2026-10-20T10:30:00-04:00",
        event_id="abcde12345",
        timezone="America/New_York",
    )

    assert "different details" in result
    assert "not modified" in result
