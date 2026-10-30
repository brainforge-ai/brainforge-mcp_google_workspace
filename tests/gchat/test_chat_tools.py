"""
Unit tests for Google Chat MCP tools — attachment support
"""

import base64
import inspect
import json
from urllib.parse import parse_qs, urlparse

import pytest
from googleapiclient.http import HttpMockSequence
from unittest.mock import AsyncMock, Mock, patch
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


def _make_message(text="Hello", attachments=None, msg_name="spaces/S/messages/M"):
    """Build a minimal Chat API message dict for testing."""
    msg = {
        "name": msg_name,
        "text": text,
        "createTime": "2025-01-01T00:00:00Z",
        "sender": {"name": "users/123", "displayName": "Test User"},
    }
    if attachments is not None:
        msg["attachment"] = attachments
    return msg


def _make_attachment(
    name="spaces/S/messages/M/attachments/A",
    content_name="image.png",
    content_type="image/png",
    resource_name="spaces/S/attachments/A",
):
    att = {
        "name": name,
        "contentName": content_name,
        "contentType": content_type,
        "source": "UPLOADED_CONTENT",
    }
    if resource_name:
        att["attachmentDataRef"] = {"resourceName": resource_name}
    return att


def _make_drive_attachment(file_id="FILE1"):
    return {
        "name": "spaces/S/messages/M/attachments/D",
        "contentName": "Budget",
        "contentType": "application/vnd.google-apps.spreadsheet",
        "source": "DRIVE_FILE",
        "driveDataRef": {"driveFileId": file_id},
    }


def _unwrap(tool):
    """Unwrap a FunctionTool + decorator chain to the original async function."""
    fn = getattr(tool, "fn", tool)
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


# ---------------------------------------------------------------------------
# get_messages: attachment metadata appears in output
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("gchat.chat_tools._resolve_sender", new_callable=AsyncMock)
async def test_get_messages_shows_attachment_metadata(mock_resolve):
    """When a message has attachments, get_messages should surface their metadata."""
    mock_resolve.return_value = "Test User"

    att = _make_attachment()
    msg = _make_message(attachments=[att])

    chat_service = Mock()
    chat_service.spaces().get().execute.return_value = {"displayName": "Test Space"}
    chat_service.spaces().messages().list().execute.return_value = {"messages": [msg]}

    people_service = Mock()

    from gchat.chat_tools import get_messages

    result = await _unwrap(get_messages)(
        chat_service=chat_service,
        people_service=people_service,
        user_google_email="test@example.com",
        space_id="spaces/S",
    )

    assert "[attachment 0: image.png (image/png)]" in result
    assert "download_chat_attachment" in result


@pytest.mark.asyncio
@patch("gchat.chat_tools._resolve_sender", new_callable=AsyncMock)
async def test_get_messages_no_attachments_unchanged(mock_resolve):
    """Messages without attachments should not include attachment lines."""
    mock_resolve.return_value = "Test User"

    msg = _make_message(text="Plain text message")

    chat_service = Mock()
    chat_service.spaces().get().execute.return_value = {"displayName": "Test Space"}
    chat_service.spaces().messages().list().execute.return_value = {"messages": [msg]}

    people_service = Mock()

    from gchat.chat_tools import get_messages

    result = await _unwrap(get_messages)(
        chat_service=chat_service,
        people_service=people_service,
        user_google_email="test@example.com",
        space_id="spaces/S",
    )

    assert "Plain text message" in result
    assert "[attachment" not in result


@pytest.mark.asyncio
@patch("gchat.chat_tools._resolve_sender", new_callable=AsyncMock)
async def test_get_messages_multiple_attachments(mock_resolve):
    """Multiple attachments should each appear with their index."""
    mock_resolve.return_value = "Test User"

    attachments = [
        _make_attachment(content_name="photo.jpg", content_type="image/jpeg"),
        _make_attachment(
            name="spaces/S/messages/M/attachments/B",
            content_name="doc.pdf",
            content_type="application/pdf",
        ),
    ]
    msg = _make_message(attachments=attachments)

    chat_service = Mock()
    chat_service.spaces().get().execute.return_value = {"displayName": "Test Space"}
    chat_service.spaces().messages().list().execute.return_value = {"messages": [msg]}

    people_service = Mock()

    from gchat.chat_tools import get_messages

    result = await _unwrap(get_messages)(
        chat_service=chat_service,
        people_service=people_service,
        user_google_email="test@example.com",
        space_id="spaces/S",
    )

    assert "[attachment 0: photo.jpg (image/jpeg)]" in result
    assert "[attachment 1: doc.pdf (application/pdf)]" in result


@pytest.mark.asyncio
@patch("gchat.chat_tools._resolve_sender", new_callable=AsyncMock)
async def test_get_messages_exposes_message_filter_and_forwards_it(mock_resolve):
    """get_messages should expose message_filter publicly and pass it to the Chat API."""
    mock_resolve.return_value = "Test User"

    msg = _make_message(text="Filtered message")
    chat_service = Mock()
    chat_service.spaces().get().execute.return_value = {"displayName": "Test Space"}
    chat_service.spaces().messages().list().execute.return_value = {"messages": [msg]}
    people_service = Mock()

    from gchat.chat_tools import get_messages

    public_fn = getattr(get_messages, "fn", get_messages)
    params = inspect.signature(public_fn).parameters

    assert "message_filter" in params
    assert "filter" not in params

    result = await _unwrap(get_messages)(
        chat_service=chat_service,
        people_service=people_service,
        user_google_email="test@example.com",
        space_id="spaces/S",
        message_filter="thread.name = spaces/S/threads/T",
    )

    assert "Filtered message" in result
    list_kwargs = chat_service.spaces().messages().list.call_args.kwargs
    assert list_kwargs["filter"] == "thread.name = spaces/S/threads/T"


@pytest.mark.asyncio
@patch("gchat.chat_tools._resolve_sender", new_callable=AsyncMock)
async def test_get_messages_pages_with_token(mock_resolve):
    mock_resolve.return_value = "Test User"
    chat_service = Mock()
    chat_service.spaces().get().execute.return_value = {"displayName": "Test Space"}
    chat_service.spaces().messages().list().execute.return_value = {
        "messages": [_make_message()],
        "nextPageToken": "PAGE3",
    }

    from gchat.chat_tools import get_messages

    result = await _unwrap(get_messages)(
        chat_service=chat_service,
        people_service=Mock(),
        user_google_email="test@example.com",
        space_id="spaces/S",
        page_token="PAGE2",
    )

    list_kwargs = chat_service.spaces().messages().list.call_args.kwargs
    assert list_kwargs["pageToken"] == "PAGE2"
    assert "Call again with page_token='PAGE3'" in result


@pytest.mark.asyncio
@patch("gchat.chat_tools._resolve_sender", new_callable=AsyncMock)
async def test_get_messages_points_drive_attachments_to_drive(mock_resolve):
    mock_resolve.return_value = "Test User"
    msg = _make_message(attachments=[_make_drive_attachment()])
    chat_service = Mock()
    chat_service.spaces().get().execute.return_value = {"displayName": "Test Space"}
    chat_service.spaces().messages().list().execute.return_value = {"messages": [msg]}

    from gchat.chat_tools import get_messages

    result = await _unwrap(get_messages)(
        chat_service=chat_service,
        people_service=Mock(),
        user_google_email="test@example.com",
        space_id="spaces/S",
    )

    assert "[attachment 0: Budget (application/vnd.google-apps.spreadsheet)]" in result
    assert (
        "Google Drive file: read it with get_drive_file_content(file_id='FILE1')"
        in result
    )
    assert "download_chat_attachment" not in result


# ---------------------------------------------------------------------------
# search_messages: Chat API search (spaces.messages.search)
# ---------------------------------------------------------------------------


def _chat_http(*responses):
    """Fake authorized HTTP that answers each request with the next (status, body)."""
    return HttpMockSequence(
        [({"status": str(status)}, json.dumps(body)) for status, body in responses]
    )


def _sent_requests(chat_service):
    """(method, path, query, body) of each request sent over the Chat connection."""
    sent = []
    for uri, method, body, _ in chat_service._http.request_sequence:
        url = urlparse(uri)
        sent.append(
            (method, url.path, parse_qs(url.query), json.loads(body) if body else None)
        )
    return sent


def _search_service(messages, spaces=None, next_page_token=None):
    """Chat service whose search returns `messages` and whose spaces.get returns `spaces`."""
    chat_service = Mock()
    response = {"results": [{"message": m} for m in messages]}
    if next_page_token:
        response["nextPageToken"] = next_page_token
    chat_service._http = _chat_http((200, response))
    by_name = {s["name"]: s for s in (spaces or [])}
    chat_service.spaces().get.side_effect = lambda name: Mock(
        execute=Mock(return_value=by_name.get(name, {"name": name}))
    )
    return chat_service


async def _search(chat_service, **kwargs):
    from gchat.chat_tools import search_messages

    return await _unwrap(search_messages)(
        chat_service=chat_service,
        people_service=Mock(),
        user_google_email="test@example.com",
        **kwargs,
    )


def _search_body(chat_service):
    [(_, _, _, body)] = _sent_requests(chat_service)
    return body


@pytest.mark.asyncio
@patch("gchat.chat_tools._name_spaces", new_callable=AsyncMock)
@patch("gchat.chat_tools._resolve_sender", new_callable=AsyncMock)
async def test_search_messages_searches_all_spaces_server_side(
    mock_resolve, mock_name_spaces
):
    mock_resolve.return_value = "Test User"
    mock_name_spaces.return_value = {"spaces/S": "General"}
    msg = _make_message(text="Deploy finished")
    chat_service = _search_service(
        [msg], spaces=[{"name": "spaces/S", "displayName": "General"}]
    )

    result = await _search(chat_service, query="deploy")

    assert _sent_requests(chat_service) == [
        (
            "POST",
            "/v1/spaces/-/messages:search",
            {"alt": ["json"]},
            {"filter": "deploy", "pageSize": 25},
        )
    ]
    assert "Found 1 messages matching: deploy" in result
    assert "Test User in 'General': Deploy finished" in result
    assert "(Message ID: spaces/S/messages/M)" in result
    chat_service.spaces().messages().list.assert_not_called()


@pytest.mark.asyncio
@patch("gchat.chat_tools._name_spaces", new_callable=AsyncMock)
@patch("gchat.chat_tools._resolve_sender", new_callable=AsyncMock)
async def test_search_messages_builds_filter_from_every_option(
    mock_resolve, mock_name_spaces
):
    mock_resolve.return_value = "Test User"
    mock_name_spaces.return_value = {}
    chat_service = _search_service([_make_message()])

    await _search(
        chat_service,
        query='"quarterly report" budget',
        space_id="AAAA",
        sender="alice@example.com",
        space_type="dm",
        mentions_me=True,
        has_link=True,
        has_attachment=True,
        start_time="2026-10-01T00:00:00Z",
        end_time="2026-10-29T00:00:00Z",
        page_size=7,
        page_token="NEXT",
    )

    assert _search_body(chat_service) == {
        "filter": (
            '"quarterly report" budget'
            ' AND space.name = "spaces/AAAA"'
            ' AND sender.name = "users/alice@example.com"'
            ' AND space.space_type = "DIRECT_MESSAGE"'
            " AND annotations.user_mentions.user.name:users/me"
            " AND has_link()"
            " AND attachment:*"
            ' AND create_time >= "2026-10-01T00:00:00Z"'
            ' AND create_time < "2026-10-29T00:00:00Z"'
        ),
        "pageSize": 7,
        "pageToken": "NEXT",
    }


@pytest.mark.asyncio
@patch("gchat.chat_tools._name_spaces", new_callable=AsyncMock)
@patch("gchat.chat_tools._resolve_sender", new_callable=AsyncMock)
async def test_search_messages_groups_or_keywords_before_field_filters(
    mock_resolve, mock_name_spaces
):
    mock_resolve.return_value = "Test User"
    mock_name_spaces.return_value = {}
    chat_service = _search_service([_make_message()])

    await _search(chat_service, query="budget OR forecast", sender="users/123")

    assert (
        _search_body(chat_service)["filter"]
        == '(budget OR forecast) AND sender.name = "users/123"'
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"query": "   "},
        {"query": "deploy", "space_type": "channel"},
        {"sender": 'alice" OR sender.name = "users/1'},
        {"query": "x" * 1001},
        {"query": "deploy", "start_time": "yesterday"},
        {"query": "deploy", "end_time": "2026-10-01"},
        {"query": "deploy", "start_time": "2026-13-01T00:00:00Z"},
    ],
)
async def test_search_messages_rejects_bad_input_before_calling_chat(kwargs):
    from core.utils import UserInputError

    chat_service = _search_service([])

    with pytest.raises(UserInputError):
        await _search(chat_service, **kwargs)
    assert _sent_requests(chat_service) == []


@pytest.mark.asyncio
async def test_search_messages_reports_no_matches():
    chat_service = _search_service([])

    result = await _search(chat_service, query="nothing", mentions_me=True)

    assert result == (
        "No messages found matching: nothing"
        " AND annotations.user_mentions.user.name:users/me"
    )


@pytest.mark.asyncio
async def test_search_messages_says_when_a_later_page_is_empty():
    chat_service = _search_service([])

    result = await _search(chat_service, query="report", page_token="PAGE2")

    assert result == "No more messages matching: report"


@pytest.mark.asyncio
@patch("gchat.chat_tools._name_spaces", new_callable=AsyncMock)
@patch("gchat.chat_tools._resolve_sender", new_callable=AsyncMock)
async def test_search_messages_shows_attachment_thread_and_next_page(
    mock_resolve, mock_name_spaces
):
    mock_resolve.return_value = "Test User"
    mock_name_spaces.return_value = {"spaces/S": "General"}
    att = _make_attachment(content_name="report.pdf", content_type="application/pdf")
    msg = _make_message(text="Here is the report", attachments=[att])
    msg["threadReply"] = True
    msg["thread"] = {"name": "spaces/S/threads/T"}
    chat_service = _search_service([msg], next_page_token="PAGE2")

    result = await _search(chat_service, query="report")

    assert "[attachment: report.pdf (application/pdf)]" in result
    assert "(Message ID: spaces/S/messages/M, thread: spaces/S/threads/T)" in result
    assert "Call again with page_token='PAGE2'" in result


@pytest.mark.asyncio
async def test_search_messages_raises_chat_errors():
    from googleapiclient.errors import HttpError

    chat_service = Mock()
    chat_service._http = _chat_http(
        (400, {"error": {"code": 400, "message": "Invalid filter"}})
    )

    with pytest.raises(HttpError) as excinfo:
        await _search(chat_service, query="deploy")
    assert excinfo.value.resp.status == 400


@pytest.mark.asyncio
@patch("gchat.chat_tools._name_spaces", new_callable=AsyncMock)
@patch("gchat.chat_tools._resolve_sender", new_callable=AsyncMock)
async def test_search_messages_looks_up_each_space_once(mock_resolve, mock_name_spaces):
    mock_resolve.return_value = "Test User"
    mock_name_spaces.return_value = {}
    messages = [
        _make_message(msg_name="spaces/A/messages/1"),
        _make_message(msg_name="spaces/B/messages/2"),
        _make_message(msg_name="spaces/A/messages/3"),
    ]
    chat_service = _search_service(messages)

    await _search(chat_service, query="hello")

    looked_up = [c.kwargs["name"] for c in chat_service.spaces().get.call_args_list]
    assert looked_up == ["spaces/A", "spaces/B"]


# ---------------------------------------------------------------------------
# find_conversations
# ---------------------------------------------------------------------------


async def _find(chat_service, participants):
    from gchat.chat_tools import find_conversations

    return await _unwrap(find_conversations)(
        chat_service=chat_service,
        people_service=Mock(),
        user_google_email="test@example.com",
        participants=participants,
    )


@pytest.mark.asyncio
@patch("gchat.chat_tools._name_spaces", new_callable=AsyncMock)
async def test_find_conversations_returns_direct_message(mock_name_spaces):
    mock_name_spaces.return_value = {"spaces/DM": "Alice Smith"}
    chat_service = Mock()
    chat_service.spaces().findDirectMessage.return_value.execute.return_value = {
        "name": "spaces/DM",
        "spaceType": "DIRECT_MESSAGE",
    }

    result = await _find(chat_service, ["alice@example.com"])

    chat_service.spaces().findDirectMessage.assert_called_with(
        name="users/alice@example.com"
    )
    assert "- Alice Smith (DIRECT_MESSAGE, ID: spaces/DM)" in result


@pytest.mark.asyncio
async def test_find_conversations_reports_missing_direct_message():
    import httplib2
    from googleapiclient.errors import HttpError

    chat_service = Mock()
    chat_service.spaces().findDirectMessage.return_value.execute.side_effect = (
        HttpError(httplib2.Response({"status": 404}), b"{}")
    )

    result = await _find(chat_service, ["nobody@example.com"])

    assert result == "No direct message found with users/nobody@example.com."


@pytest.mark.asyncio
async def test_find_conversations_reports_unknown_person():
    import httplib2
    from googleapiclient.errors import HttpError

    chat_service = Mock()
    chat_service.spaces().findDirectMessage.return_value.execute.side_effect = (
        HttpError(httplib2.Response({"status": 400}), b"{}")
    )

    result = await _find(chat_service, ["nobody@example.com"])

    assert result == (
        "Google Chat does not recognize users/nobody@example.com. "
        "Check the email address."
    )


@pytest.mark.asyncio
async def test_find_conversations_reports_unknown_person_in_group():
    chat_service = Mock()
    chat_service._http = _chat_http(
        (400, {"error": {"code": 400, "message": "Invalid membership state"}})
    )

    result = await _find(chat_service, ["alice@example.com", "nobody@example.com"])

    assert result == (
        "Google Chat does not recognize at least one of users/alice@example.com, "
        "users/nobody@example.com. Check the email addresses."
    )


@pytest.mark.asyncio
@patch("gchat.chat_tools._name_spaces", new_callable=AsyncMock)
async def test_find_conversations_returns_group_chats(mock_name_spaces):
    mock_name_spaces.return_value = {"spaces/GC": "Alice Smith, Bob Jones"}
    chat_service = Mock()
    chat_service._http = _chat_http(
        (200, {"spaces": [{"name": "spaces/GC", "spaceType": "GROUP_CHAT"}]})
    )

    result = await _find(chat_service, ["alice@example.com", "users/300"])

    assert _sent_requests(chat_service) == [
        (
            "GET",
            "/v1/spaces:findGroupChats",
            {
                "users": ["users/alice@example.com", "users/300"],
                "spaceView": ["SPACE_VIEW_EXPANDED"],
                "pageSize": ["30"],
                "alt": ["json"],
            },
            None,
        )
    ]
    assert "- Alice Smith, Bob Jones (GROUP_CHAT, ID: spaces/GC)" in result


@pytest.mark.asyncio
async def test_find_conversations_requires_a_participant():
    from core.utils import UserInputError

    with pytest.raises(UserInputError):
        await _find(Mock(), ["", "  "])


# ---------------------------------------------------------------------------
# download_chat_attachment: edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_no_attachments():
    """Should return a clear message when the message has no attachments."""
    service = Mock()
    service.spaces().messages().get().execute.return_value = _make_message()

    from gchat.chat_tools import download_chat_attachment

    result = await _unwrap(download_chat_attachment)(
        service=service,
        user_google_email="test@example.com",
        message_id="spaces/S/messages/M",
    )

    assert "No attachments found" in result


@pytest.mark.asyncio
async def test_download_invalid_index():
    """Should return an error for out-of-range attachment_index."""
    msg = _make_message(attachments=[_make_attachment()])
    service = Mock()
    service.spaces().messages().get().execute.return_value = msg

    from gchat.chat_tools import download_chat_attachment

    result = await _unwrap(download_chat_attachment)(
        service=service,
        user_google_email="test@example.com",
        message_id="spaces/S/messages/M",
        attachment_index=5,
    )

    assert "Invalid attachment_index" in result
    assert "1 attachment(s)" in result


@pytest.mark.asyncio
async def test_download_points_drive_files_to_drive():
    msg = _make_message(attachments=[_make_drive_attachment()])
    service = Mock()
    service.spaces().messages().get().execute.return_value = msg

    from gchat.chat_tools import download_chat_attachment

    with patch("gchat.chat_tools.httpx.AsyncClient") as mock_client:
        result = await _unwrap(download_chat_attachment)(
            service=service,
            user_google_email="test@example.com",
            message_id="spaces/S/messages/M",
        )

    mock_client.assert_not_called()
    assert result == (
        "Attachment 'Budget' is a Google Drive file, which Chat cannot download. "
        "Read it with get_drive_file_content(file_id='FILE1')."
    )


@pytest.mark.asyncio
async def test_download_uses_api_media_endpoint():
    """Should always use chat.googleapis.com media endpoint, not downloadUri."""
    fake_bytes = b"fake image content"
    att = _make_attachment()
    # Even with a downloadUri present, we should use the API endpoint
    att["downloadUri"] = "https://chat.google.com/api/get_attachment_url?bad=url"
    msg = _make_message(attachments=[att])

    service = Mock()
    service.spaces().messages().get().execute.return_value = msg
    service._http.credentials.token = "fake-access-token"

    from gchat.chat_tools import download_chat_attachment

    saved = Mock()
    saved.path = "/tmp/image_abc.png"
    saved.file_id = "abc"

    mock_response = Mock()
    mock_response.content = fake_bytes
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("gchat.chat_tools.httpx.AsyncClient", return_value=mock_client),
        patch("auth.oauth_config.is_stateless_mode", return_value=False),
        patch("core.config.get_transport_mode", return_value="stdio"),
        patch("core.attachment_storage.get_attachment_storage") as mock_get_storage,
    ):
        mock_get_storage.return_value.save_attachment.return_value = saved

        result = await _unwrap(download_chat_attachment)(
            service=service,
            user_google_email="test@example.com",
            message_id="spaces/S/messages/M",
            attachment_index=0,
        )

    assert "image.png" in result
    assert "/tmp/image_abc.png" in result
    assert "Saved to:" in result

    # Verify we used the API endpoint with attachmentDataRef.resourceName
    call_args = mock_client.get.call_args
    url_used = call_args.args[0]
    parsed = urlparse(url_used)
    assert parsed.scheme == "https"
    assert parsed.hostname == "chat.googleapis.com"
    assert "alt=media" in url_used
    assert "spaces/S/attachments/A" in parsed.path
    assert "/messages/" not in parsed.path

    # Verify Bearer token
    assert call_args.kwargs["headers"]["Authorization"] == "Bearer fake-access-token"

    # Verify save_attachment was called with correct base64 data
    save_args = mock_get_storage.return_value.save_attachment.call_args
    assert save_args.kwargs["filename"] == "image.png"
    assert save_args.kwargs["mime_type"] == "image/png"
    decoded = base64.urlsafe_b64decode(save_args.kwargs["base64_data"])
    assert decoded == fake_bytes


@pytest.mark.asyncio
async def test_download_falls_back_to_att_name():
    """When attachmentDataRef is missing, should fall back to attachment name."""
    fake_bytes = b"fetched content"
    att = _make_attachment(name="spaces/S/messages/M/attachments/A", resource_name=None)
    msg = _make_message(attachments=[att])

    service = Mock()
    service.spaces().messages().get().execute.return_value = msg
    service._http.credentials.token = "fake-access-token"

    saved = Mock()
    saved.path = "/tmp/image_fetched.png"
    saved.file_id = "f1"

    mock_response = Mock()
    mock_response.content = fake_bytes
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    from gchat.chat_tools import download_chat_attachment

    with (
        patch("gchat.chat_tools.httpx.AsyncClient", return_value=mock_client),
        patch("auth.oauth_config.is_stateless_mode", return_value=False),
        patch("core.config.get_transport_mode", return_value="stdio"),
        patch("core.attachment_storage.get_attachment_storage") as mock_get_storage,
    ):
        mock_get_storage.return_value.save_attachment.return_value = saved

        result = await _unwrap(download_chat_attachment)(
            service=service,
            user_google_email="test@example.com",
            message_id="spaces/S/messages/M",
            attachment_index=0,
        )

    assert "image.png" in result
    assert "/tmp/image_fetched.png" in result

    # Falls back to attachment name when no attachmentDataRef
    call_args = mock_client.get.call_args
    assert "spaces/S/messages/M/attachments/A" in call_args.args[0]


@pytest.mark.asyncio
async def test_download_http_mode_returns_url():
    """In HTTP mode, should return a download URL instead of file path."""
    fake_bytes = b"image data"
    att = _make_attachment()
    msg = _make_message(attachments=[att])

    service = Mock()
    service.spaces().messages().get().execute.return_value = msg
    service._http.credentials.token = "fake-token"

    mock_response = Mock()
    mock_response.content = fake_bytes
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    saved = Mock()
    saved.path = "/tmp/image_alt.png"
    saved.file_id = "alt1"

    from gchat.chat_tools import download_chat_attachment

    with (
        patch("gchat.chat_tools.httpx.AsyncClient", return_value=mock_client),
        patch("auth.oauth_config.is_stateless_mode", return_value=False),
        patch("core.config.get_transport_mode", return_value="http"),
        patch("core.attachment_storage.get_attachment_storage") as mock_get_storage,
        patch(
            "core.attachment_storage.get_attachment_url",
            return_value="http://localhost:8005/attachments/alt1",
        ),
    ):
        mock_get_storage.return_value.save_attachment.return_value = saved

        result = await _unwrap(download_chat_attachment)(
            service=service,
            user_google_email="test@example.com",
            message_id="spaces/S/messages/M",
            attachment_index=0,
        )

    assert "Download URL:" in result
    assert "expire after 1 hour" in result


@pytest.mark.asyncio
async def test_download_returns_error_on_failure():
    """When download fails, should return a clear error message."""
    att = _make_attachment()
    att["downloadUri"] = "https://storage.googleapis.com/fake?alt=media"
    msg = _make_message(attachments=[att])

    service = Mock()
    service.spaces().messages().get().execute.return_value = msg
    service._http.credentials.token = "fake-token"

    mock_client = AsyncMock()
    mock_client.get.side_effect = Exception("connection refused")
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    from gchat.chat_tools import download_chat_attachment

    with patch("gchat.chat_tools.httpx.AsyncClient", return_value=mock_client):
        result = await _unwrap(download_chat_attachment)(
            service=service,
            user_google_email="test@example.com",
            message_id="spaces/S/messages/M",
            attachment_index=0,
        )

    assert "Failed to download" in result
    assert "connection refused" in result
