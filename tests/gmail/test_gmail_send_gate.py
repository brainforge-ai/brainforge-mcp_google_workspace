"""Tests for the Gmail send gate, draft updates, and date normalization."""

from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import Mock

import pytest

from core.utils import UserInputError
from gmail import gmail_tools


def _unwrap(tool):
    fn = tool.fn if hasattr(tool, "fn") else tool
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


@pytest.mark.asyncio
async def test_send_is_blocked_without_confirm_send():
    service = Mock()

    with pytest.raises(UserInputError, match="Sending is disabled by default"):
        await _unwrap(gmail_tools.send_gmail_message)(
            service=service,
            user_google_email="user@example.com",
            to="recipient@example.com",
            subject="Hello",
            body="Hi",
        )

    service.users.return_value.messages.return_value.send.assert_not_called()


@pytest.mark.asyncio
async def test_send_with_confirm_send_sends_and_reports_quota():
    service = Mock()
    service.users.return_value.messages.return_value.send.return_value.execute.return_value = {
        "id": "msg_1"
    }

    result = await _unwrap(gmail_tools.send_gmail_message)(
        service=service,
        user_google_email="user@example.com",
        to="recipient@example.com",
        subject="Hello",
        body="Hi",
        confirm_send=True,
    )

    assert "Email sent! Message ID: msg_1" in result
    assert "Consumed ~100 quota units" in result


@pytest.mark.asyncio
async def test_update_draft_replaces_message_and_returns_new_id():
    service = Mock()
    service.users.return_value.drafts.return_value.get.return_value.execute.return_value = {
        "message": {
            "threadId": "thread_1",
            "payload": {"headers": []},
        }
    }
    service.users.return_value.drafts.return_value.update.return_value.execute.return_value = {
        "message": {"id": "msg_2"}
    }

    result = await _unwrap(gmail_tools.update_draft)(
        service=service,
        user_google_email="user@example.com",
        draft_id="draft_1",
        subject="Updated",
        body="New body",
        to="recipient@example.com",
        include_signature=False,
    )

    call_kwargs = service.users.return_value.drafts.return_value.update.call_args.kwargs
    assert call_kwargs["id"] == "draft_1"
    assert "raw" in call_kwargs["body"]["message"]
    assert call_kwargs["body"]["message"]["threadId"] == "thread_1"
    assert "Draft draft_1 updated" in result
    assert "msg_2" in result
    assert "Consumed ~10 quota units" in result


@pytest.mark.asyncio
async def test_search_normalizes_date_filters_to_pacific_midnight():
    service = Mock()
    service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
        "messages": []
    }

    result = await _unwrap(gmail_tools.search_gmail_messages)(
        service=service,
        user_google_email="user@example.com",
        query="after:2026/01/01 is:unread",
    )

    expected = int(
        datetime(
            2026, 1, 1, tzinfo=ZoneInfo("America/Los_Angeles")
        ).timestamp()
    )
    request_q = service.users.return_value.messages.return_value.list.call_args.kwargs[
        "q"
    ]
    assert request_q == f"after:{expected} is:unread"
    assert "Pacific midnight" in result


@pytest.mark.asyncio
async def test_update_draft_refuses_attachments_by_default():
    service = Mock()
    service.users.return_value.drafts.return_value.get.return_value.execute.return_value = {
        "message": {
            "payload": {
                "parts": [{"filename": "report.pdf", "body": {"attachmentId": "a1"}}]
            }
        }
    }

    result = await _unwrap(gmail_tools.update_draft)(
        service=service,
        user_google_email="user@example.com",
        draft_id="draft_1",
        subject="Updated",
        body="New body",
        include_signature=False,
    )

    assert "has attachments" in result
    service.users.return_value.drafts.return_value.update.assert_not_called()


@pytest.mark.asyncio
async def test_search_normalizes_dashed_dates_and_skips_quoted_literals():
    service = Mock()
    service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
        "messages": []
    }

    result = await _unwrap(gmail_tools.search_gmail_messages)(
        service=service,
        user_google_email="user@example.com",
        query='after:2026-07-01 subject:"after:2024/1/1"',
    )

    july = int(
        datetime(2026, 7, 1, tzinfo=ZoneInfo("America/Los_Angeles")).timestamp()
    )
    request_q = service.users.return_value.messages.return_value.list.call_args.kwargs[
        "q"
    ]
    assert request_q == f'after:{july} subject:"after:2024/1/1"'
    assert "Pacific midnight" in result


@pytest.mark.asyncio
async def test_search_leaves_invalid_dates_unchanged():
    service = Mock()
    service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
        "messages": []
    }

    result = await _unwrap(gmail_tools.search_gmail_messages)(
        service=service,
        user_google_email="user@example.com",
        query="after:2026/02/30",
    )

    request_q = service.users.return_value.messages.return_value.list.call_args.kwargs[
        "q"
    ]
    assert request_q == "after:2026/02/30"
    assert "Pacific midnight" not in result
