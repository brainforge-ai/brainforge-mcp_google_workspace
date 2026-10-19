"""Tests for the shared Google API error envelope."""

import httplib2
import pytest
from googleapiclient.errors import HttpError

from core.utils import handle_http_errors


def _resp(status: int, headers=None):
    response = httplib2.Response({"status": status})
    if headers:
        response.update(headers)
    return response


async def _raise(tool_name, service_type, status, body, headers=None):
    @handle_http_errors(tool_name, service_type=service_type)
    async def fn():
        raise HttpError(_resp(status, headers), body)

    with pytest.raises(Exception) as exc:
        await fn()
    return str(exc.value)


@pytest.mark.asyncio
async def test_429_returns_quota_reason_and_retry_step():
    message = await _raise(
        "send_gmail_message",
        "gmail",
        429,
        b'{"error":{"errors":[{"reason":"rateLimitExceeded"}]}}',
        {"retry-after": "7"},
    )

    assert "API error in send_gmail_message: HTTP 429." in message
    assert "Service: Gmail" in message
    assert "Reason: rateLimitExceeded" in message
    assert "Retry: after ~7s" in message
    assert "Next step: Back off and retry" in message


@pytest.mark.asyncio
async def test_drive_permission_403_names_shared_drive_and_scope():
    message = await _raise(
        "search_drive_files",
        "drive",
        403,
        b'{"error":{"errors":[{"reason":"forbidden"}]}}',
    )

    assert "Service: Drive" in message
    assert "Reason: forbidden" in message
    assert "Next step:" in message
    assert "Confirm shared drive membership" in message
    assert "drive.readonly" in message


@pytest.mark.asyncio
async def test_drive_rate_limit_403_is_not_called_a_permission_problem():
    message = await _raise(
        "search_drive_files",
        "drive",
        403,
        b'{"error":{"errors":[{"reason":"userRateLimitExceeded"}]}}',
    )

    assert "Reason: userRateLimitExceeded" in message
    assert "This is a rate limit, not a permission problem" in message


@pytest.mark.asyncio
async def test_400_revision_returns_reread_step():
    message = await _raise(
        "batch_update_doc",
        "docs",
        400,
        b'{"error":{"message":"The document has changed since the required revision"}}',
    )

    assert "Service: Docs" in message
    assert "Reason: revision mismatch" in message
    assert "Next step: Re-read the document" in message


@pytest.mark.asyncio
async def test_404_returns_id_and_access_step():
    message = await _raise(
        "get_drive_file_content",
        "drive",
        404,
        b'{"error":{"message":"File not found"}}',
    )

    assert "Service: Drive" in message
    assert "Next step: Check the file or document ID" in message


@pytest.mark.asyncio
async def test_401_returns_reauth_step():
    message = await _raise(
        "get_gmail_message_content",
        "gmail",
        401,
        b'{"error":{"message":"Unauthorized"}}',
    )

    assert "Service: Gmail" in message
    assert "re-authenticate the user" in message.lower()
