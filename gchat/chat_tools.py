"""
Google Chat MCP Tools

This module provides MCP tools for interacting with Google Chat API.
"""

import base64
import logging
import asyncio
import re
from typing import List, Optional

import httpx
from googleapiclient.errors import HttpError
from googleapiclient.http import HttpRequest
from googleapiclient.model import JsonModel

# Auth & server utilities
from auth.service_decorator import require_google_service, require_multiple_services
from core.server import server
from core.utils import UserInputError, handle_http_errors
from gchat.chat_helpers import _name_spaces, _resolve_sender

logger = logging.getLogger(__name__)

_SEARCH_SPACE_TYPES = {
    "dm": "DIRECT_MESSAGE",
    "group_chat": "GROUP_CHAT",
    "space": "SPACE",
}
_SEARCH_FILTER_MAX_LENGTH = 1000
_SEARCH_TEXT_PREVIEW_CHARS = 300
_FIND_GROUP_CHATS_MAX_USERS = 49
_CHAT_API_ROOT = "https://chat.googleapis.com/v1/"


def _chat_api_request(
    chat_service, method: str, path: str, query=None, body=None
) -> HttpRequest:
    """Build a request for a Chat method the pinned API client does not know.

    spaces.messages.search and spaces.findGroupChats first appear in
    google-api-python-client 2.201.0. Sending them over the Chat service's
    authorized connection keeps every other Google service on the pinned client.
    Switch to chat_service methods once the pin reaches 2.201.0.
    """
    model = JsonModel()
    headers, _, query_string, payload = model.request({}, {}, query or {}, body)
    return HttpRequest(
        chat_service._http,
        model.response,
        _CHAT_API_ROOT + path + query_string,
        method=method,
        body=payload,
        headers=headers,
    )


def _user_resource(user: str) -> str:
    """Accept an email, a user id, or users/{id}, and return users/{...}."""
    user = user.strip()
    return user if user.startswith("users/") else f"users/{user}"


def _space_resource(space_id: str) -> str:
    space_id = space_id.strip()
    return space_id if space_id.startswith("spaces/") else f"spaces/{space_id}"


def _quoted(param: str, value: str) -> str:
    if '"' in value:
        raise UserInputError(f"{param} cannot contain double quotes.")
    return f'"{value}"'


def _build_search_filter(
    query: Optional[str],
    space_id: Optional[str],
    sender: Optional[str],
    space_type: Optional[str],
    mentions_me: bool,
    has_link: bool,
    has_attachment: bool,
    start_time: Optional[str],
    end_time: Optional[str],
) -> str:
    """Build the filter string for spaces.messages.search."""
    parts = []
    if query and query.strip():
        keywords = query.strip()
        # OR between keywords must be grouped before it is ANDed with field filters.
        if re.search(r"\bOR\b", keywords):
            keywords = f"({keywords})"
        parts.append(keywords)
    if space_id:
        parts.append(f"space.name = {_quoted('space_id', _space_resource(space_id))}")
    if sender:
        parts.append(f"sender.name = {_quoted('sender', _user_resource(sender))}")
    if space_type:
        key = space_type.strip().lower()
        if key not in _SEARCH_SPACE_TYPES:
            raise UserInputError(
                f"space_type must be one of: {', '.join(_SEARCH_SPACE_TYPES)}."
            )
        parts.append(f'space.space_type = "{_SEARCH_SPACE_TYPES[key]}"')
    if mentions_me:
        parts.append("annotations.user_mentions.user.name:users/me")
    if has_link:
        parts.append("has_link()")
    if has_attachment:
        parts.append("attachment:*")
    if start_time:
        parts.append(f"create_time >= {_quoted('start_time', start_time)}")
    if end_time:
        parts.append(f"create_time < {_quoted('end_time', end_time)}")
    if not parts:
        raise UserInputError(
            "Provide a query or at least one filter to search Chat messages."
        )
    search_filter = " AND ".join(parts)
    if len(search_filter) > _SEARCH_FILTER_MAX_LENGTH:
        raise UserInputError(
            f"The search is {len(search_filter)} characters; Chat allows "
            f"{_SEARCH_FILTER_MAX_LENGTH}. Shorten the query."
        )
    return search_filter


def _message_space(msg: dict) -> Optional[str]:
    """Return the space resource name for a message (spaces/X/messages/Y -> spaces/X)."""
    space_name = msg.get("space", {}).get("name")
    if space_name:
        return space_name
    parts = msg.get("name", "").split("/")
    return "/".join(parts[:2]) if len(parts) >= 2 and parts[0] == "spaces" else None


def _extract_rich_links(msg: dict) -> List[str]:
    """Extract URLs from RICH_LINK annotations (smart chips).

    When a user pastes a Google Workspace URL in Chat and it renders as a
    smart chip, the URL is NOT in the text field — it's only available in
    the annotations array as a RICH_LINK with richLinkMetadata.uri.
    """
    text = msg.get("text", "")
    urls = []
    for ann in msg.get("annotations", []):
        if ann.get("type") == "RICH_LINK":
            uri = ann.get("richLinkMetadata", {}).get("uri", "")
            if uri and uri not in text:
                urls.append(uri)
    return urls


@server.tool()
@require_multiple_services(
    [
        {
            "service_type": "chat",
            "scopes": "chat_spaces_readonly",
            "param_name": "chat_service",
        },
        {
            "service_type": "people",
            "scopes": "contacts_read",
            "param_name": "people_service",
        },
    ]
)
@handle_http_errors("list_spaces", service_type="chat")
async def list_spaces(
    chat_service,
    people_service,
    user_google_email: str,
    page_size: int = 100,
    space_type: str = "all",  # "all", "room", "dm"
) -> str:
    """
    Lists Google Chat spaces (rooms and direct messages) accessible to the user.

    Returns:
        str: A formatted list of Google Chat spaces accessible to the user.
    """
    logger.info(f"[list_spaces] Email={user_google_email}, Type={space_type}")

    # Build filter based on space_type
    filter_param = None
    if space_type == "room":
        filter_param = "spaceType = SPACE"
    elif space_type == "dm":
        filter_param = "spaceType = DIRECT_MESSAGE"

    request_params = {"pageSize": page_size}
    if filter_param:
        request_params["filter"] = filter_param

    response = await asyncio.to_thread(
        chat_service.spaces().list(**request_params).execute
    )

    spaces = response.get("spaces", [])
    if not spaces:
        return f"No Chat spaces found for type '{space_type}'."

    space_labels = await _name_spaces(chat_service, people_service, spaces)
    output = [f"Found {len(spaces)} Chat spaces (type: {space_type}):"]
    for space in spaces:
        space_id = space.get("name", "")
        space_name = space_labels[space.get("name")]
        space_type_actual = space.get("spaceType", "UNKNOWN")
        output.append(f"- {space_name} (ID: {space_id}, Type: {space_type_actual})")

    return "\n".join(output)


@server.tool()
@require_multiple_services(
    [
        {"service_type": "chat", "scopes": "chat_read", "param_name": "chat_service"},
        {
            "service_type": "people",
            "scopes": "contacts_read",
            "param_name": "people_service",
        },
    ]
)
@handle_http_errors("get_messages", service_type="chat")
async def get_messages(
    chat_service,
    people_service,
    user_google_email: str,
    space_id: str,
    page_size: int = 50,
    order_by: str = "createTime desc",
    message_filter: Optional[str] = None,
) -> str:
    """
    Retrieves messages from a Google Chat space.

    Args:
        message_filter: Optional filter string using the Chat API filter syntax.
                        Supports createTime and thread.name.
                        Examples:
                          'createTime > "2026-03-18T00:00:00-03:00"'
                          'createTime > "2026-03-18T00:00:00-03:00" AND createTime < "2026-03-19T00:00:00-03:00"'
                          'thread.name = spaces/X/threads/Y'

    Returns:
        str: Formatted messages from the specified space.
    """
    logger.info(f"[get_messages] Space ID: '{space_id}' for user '{user_google_email}'")

    # Get space info first
    space_info = await asyncio.to_thread(
        chat_service.spaces().get(name=space_id).execute
    )
    space_labels = await _name_spaces(chat_service, people_service, [space_info])
    space_name = space_labels[space_info.get("name")]

    # Get messages
    list_params = {"parent": space_id, "pageSize": page_size, "orderBy": order_by}
    if message_filter is not None:
        list_params["filter"] = message_filter
    response = await asyncio.to_thread(
        chat_service.spaces().messages().list(**list_params).execute
    )

    messages = response.get("messages", [])
    if not messages:
        return f"No messages found in space '{space_name}' (ID: {space_id})."

    # Pre-resolve unique senders in parallel
    sender_lookup = {}
    for msg in messages:
        s = msg.get("sender", {})
        key = s.get("name", "")
        if key and key not in sender_lookup:
            sender_lookup[key] = s
    resolved_names = await asyncio.gather(
        *[_resolve_sender(people_service, s) for s in sender_lookup.values()]
    )
    sender_map = dict(zip(sender_lookup.keys(), resolved_names))

    output = [f"Messages from '{space_name}' (ID: {space_id}):\n"]
    for msg in messages:
        sender_obj = msg.get("sender", {})
        sender_key = sender_obj.get("name", "")
        sender = sender_map.get(sender_key) or await _resolve_sender(
            people_service, sender_obj
        )
        create_time = msg.get("createTime", "Unknown Time")
        text_content = msg.get("text", "No text content")
        msg_name = msg.get("name", "")

        output.append(f"[{create_time}] {sender}:")
        output.append(f"  {text_content}")
        rich_links = _extract_rich_links(msg)
        for url in rich_links:
            output.append(f"  [linked: {url}]")
        # Show attachments
        attachments = msg.get("attachment", [])
        for idx, att in enumerate(attachments):
            att_name = att.get("contentName", "unnamed")
            att_type = att.get("contentType", "unknown type")
            att_resource = att.get("name", "")
            output.append(f"  [attachment {idx}: {att_name} ({att_type})]")
            if att_resource:
                output.append(
                    f"  Use download_chat_attachment(message_id='{msg_name}', attachment_index={idx}) to download"
                )
        # Show thread info if this is a threaded reply
        thread = msg.get("thread", {})
        if msg.get("threadReply") and thread.get("name"):
            output.append(f"  [thread: {thread['name']}]")
        # Show emoji reactions
        reactions = msg.get("emojiReactionSummaries", [])
        if reactions:
            parts = []
            for r in reactions:
                emoji = r.get("emoji", {})
                symbol = emoji.get("unicode", "")
                if not symbol:
                    ce = emoji.get("customEmoji", {})
                    symbol = f":{ce.get('uid', '?')}:"
                count = r.get("reactionCount", 0)
                parts.append(f"{symbol}x{count}")
            output.append(f"  [reactions: {', '.join(parts)}]")
        output.append(f"  (Message ID: {msg_name})\n")

    return "\n".join(output)


@server.tool()
@require_google_service("chat", "chat_write")
@handle_http_errors("send_message", service_type="chat")
async def send_message(
    service,
    user_google_email: str,
    space_id: str,
    message_text: str,
    thread_key: Optional[str] = None,
    thread_name: Optional[str] = None,
) -> str:
    """
    Sends a message to a Google Chat space.

    Args:
        thread_name: Reply in an existing thread by its resource name (e.g. spaces/X/threads/Y).
        thread_key: Reply in a thread by app-defined key (creates thread if not found).

    Returns:
        str: Confirmation message with sent message details.
    """
    logger.info(f"[send_message] Email: '{user_google_email}', Space: '{space_id}'")

    message_body = {"text": message_text}

    request_params = {"parent": space_id, "body": message_body}

    # Thread reply support
    if thread_name:
        message_body["thread"] = {"name": thread_name}
        request_params["messageReplyOption"] = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"
    elif thread_key:
        message_body["thread"] = {"threadKey": thread_key}
        request_params["messageReplyOption"] = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"

    message = await asyncio.to_thread(
        service.spaces().messages().create(**request_params).execute
    )

    message_name = message.get("name", "")
    create_time = message.get("createTime", "")

    msg = f"Message sent to space '{space_id}' by {user_google_email}. Message ID: {message_name}, Time: {create_time}"
    logger.info(
        f"Successfully sent message to space '{space_id}' by {user_google_email}"
    )
    return msg


@server.tool()
@require_multiple_services(
    [
        {
            "service_type": "chat",
            "scopes": ["chat_read", "chat_spaces_readonly"],
            "param_name": "chat_service",
        },
        {
            "service_type": "people",
            "scopes": "contacts_read",
            "param_name": "people_service",
        },
    ]
)
@handle_http_errors("search_messages", is_read_only=True, service_type="chat")
async def search_messages(
    chat_service,
    people_service,
    user_google_email: str,
    query: Optional[str] = None,
    space_id: Optional[str] = None,
    sender: Optional[str] = None,
    space_type: Optional[str] = None,
    mentions_me: bool = False,
    has_link: bool = False,
    has_attachment: bool = False,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    page_size: int = 25,
    page_token: Optional[str] = None,
) -> str:
    """
    Searches Google Chat messages across every space, group chat, and direct message you belong to.

    Uses Google Chat's own search. Combine keywords with any of the filters; at least
    one is required. Search skips messages posted by Chat apps, spaces you muted, and
    private messages, so use get_messages to read a space in full.

    Args:
        query: Keywords to find in message text. Words must all match; wrap a phrase
               in double quotes, e.g. '"quarterly report" budget'.
        space_id: Limit to one space, e.g. 'spaces/AAAAxxxx'.
        sender: Only messages from this person, by email or 'users/{id}'.
        space_type: Limit to 'dm', 'group_chat', or 'space'.
        mentions_me: Only messages that @mention you.
        has_link: Only messages that contain a link.
        has_attachment: Only messages with an attachment.
        start_time: Only messages created at or after this RFC 3339 time, e.g. '2026-10-01T00:00:00Z'.
        end_time: Only messages created before this RFC 3339 time.
        page_size: Messages per page, up to 100.
        page_token: Token from a previous call, to fetch the next page.

    Returns:
        str: Matching messages with their space, sender, time, and message ID.
    """
    search_filter = _build_search_filter(
        query,
        space_id,
        sender,
        space_type,
        mentions_me,
        has_link,
        has_attachment,
        start_time,
        end_time,
    )
    logger.info(
        f"[search_messages] Email={user_google_email}, Filter='{search_filter}'"
    )

    body = {"filter": search_filter, "pageSize": page_size}
    if page_token:
        body["pageToken"] = page_token
    response = await asyncio.to_thread(
        _chat_api_request(
            chat_service, "POST", "spaces/-/messages:search", body=body
        ).execute
    )
    messages = [r["message"] for r in response.get("results", []) if r.get("message")]
    if not messages:
        return f"No messages found matching: {search_filter}"

    # Results carry only the space resource name, so fetch each space once for its
    # label. One request at a time: googleapiclient/httplib2 service objects are not
    # safe to fan out and can trigger SSL churn.
    spaces = []
    for space_name in dict.fromkeys(filter(None, map(_message_space, messages))):
        try:
            spaces.append(
                await asyncio.to_thread(
                    chat_service.spaces().get(name=space_name).execute
                )
            )
        except HttpError as e:
            logger.debug(f"Could not get space {space_name}: {e}")
            spaces.append({"name": space_name})
    space_labels = await _name_spaces(chat_service, people_service, spaces)

    sender_map = {}
    for msg in messages:
        sender_obj = msg.get("sender", {})
        key = sender_obj.get("name", "")
        if key and key not in sender_map:
            sender_map[key] = await _resolve_sender(people_service, sender_obj)

    output = [f"Found {len(messages)} messages matching: {search_filter}"]
    for msg in messages:
        sender_obj = msg.get("sender", {})
        sender = sender_map.get(sender_obj.get("name", "")) or await _resolve_sender(
            people_service, sender_obj
        )
        create_time = msg.get("createTime", "Unknown Time")
        space_label = space_labels.get(_message_space(msg), "Unknown Space")
        text_content = msg.get("text") or "No text content"
        if len(text_content) > _SEARCH_TEXT_PREVIEW_CHARS:
            text_content = text_content[:_SEARCH_TEXT_PREVIEW_CHARS] + "..."

        links_suffix = "".join(f" [linked: {url}]" for url in _extract_rich_links(msg))
        att_suffix = "".join(
            f" [attachment: {a.get('contentName', 'unnamed')} ({a.get('contentType', 'unknown type')})]"
            for a in msg.get("attachment", [])
        )
        output.append(
            f"- [{create_time}] {sender} in '{space_label}': {text_content}{links_suffix}{att_suffix}"
        )
        details = f"  (Message ID: {msg.get('name', '')}"
        thread = msg.get("thread", {})
        if msg.get("threadReply") and thread.get("name"):
            details += f", thread: {thread['name']}"
        output.append(details + ")")

    next_page_token = response.get("nextPageToken")
    if next_page_token:
        output.append(
            f"\nMore results available. Call again with page_token='{next_page_token}'."
        )
    return "\n".join(output)


@server.tool()
@require_multiple_services(
    [
        {
            "service_type": "chat",
            "scopes": ["chat_spaces_readonly", "chat_memberships_readonly"],
            "param_name": "chat_service",
        },
        {
            "service_type": "people",
            "scopes": "contacts_read",
            "param_name": "people_service",
        },
    ]
)
@handle_http_errors("find_conversations", is_read_only=True, service_type="chat")
async def find_conversations(
    chat_service,
    people_service,
    user_google_email: str,
    participants: List[str],
) -> str:
    """
    Finds your direct message or group chats with specific people.

    Args:
        participants: The other people, by email or 'users/{id}'. With one person,
                      returns your direct message with them. With several, returns
                      group chats whose members are exactly you and those people.

    Returns:
        str: Matching conversations with the space IDs that get_messages and
             search_messages accept.
    """
    people = [_user_resource(p) for p in participants if p and p.strip()]
    if not people:
        raise UserInputError("Provide at least one participant.")
    if len(people) > _FIND_GROUP_CHATS_MAX_USERS:
        raise UserInputError(
            f"Chat can match at most {_FIND_GROUP_CHATS_MAX_USERS} other participants."
        )
    logger.info(f"[find_conversations] Email={user_google_email}, People={people}")

    if len(people) == 1:
        try:
            space = await asyncio.to_thread(
                chat_service.spaces().findDirectMessage(name=people[0]).execute
            )
        except HttpError as e:
            if e.resp.status == 404:
                return f"No direct message found with {people[0]}."
            raise
        spaces = [space]
    else:
        response = await asyncio.to_thread(
            _chat_api_request(
                chat_service,
                "GET",
                "spaces:findGroupChats",
                query={
                    "users": people,
                    "spaceView": "SPACE_VIEW_EXPANDED",
                    "pageSize": 30,
                },
            ).execute
        )
        spaces = response.get("spaces", [])
        if not spaces:
            return f"No group chats found with exactly you and {', '.join(people)}."

    labels = await _name_spaces(chat_service, people_service, spaces)
    output = [f"Found {len(spaces)} conversation(s):"]
    for space in spaces:
        space_name = space.get("name", "")
        output.append(
            f"- {labels.get(space_name, 'Unnamed Space')} "
            f"({space.get('spaceType', 'UNKNOWN')}, ID: {space_name})"
        )
    return "\n".join(output)


@server.tool()
@require_google_service("chat", "chat_write")
@handle_http_errors("create_reaction", service_type="chat")
async def create_reaction(
    service,
    user_google_email: str,
    message_id: str,
    emoji_unicode: str,
) -> str:
    """
    Adds an emoji reaction to a Google Chat message.

    Args:
        message_id: The message resource name (e.g. spaces/X/messages/Y).
        emoji_unicode: The emoji character to react with (e.g. 👍).

    Returns:
        str: Confirmation message.
    """
    logger.info(f"[create_reaction] Message: '{message_id}', Emoji: '{emoji_unicode}'")

    reaction = await asyncio.to_thread(
        service.spaces()
        .messages()
        .reactions()
        .create(
            parent=message_id,
            body={"emoji": {"unicode": emoji_unicode}},
        )
        .execute
    )

    reaction_name = reaction.get("name", "")
    return f"Reacted with {emoji_unicode} on message {message_id}. Reaction ID: {reaction_name}"


@server.tool()
@handle_http_errors("download_chat_attachment", is_read_only=True, service_type="chat")
@require_google_service("chat", "chat_read")
async def download_chat_attachment(
    service,
    user_google_email: str,
    message_id: str,
    attachment_index: int = 0,
) -> str:
    """
    Downloads an attachment from a Google Chat message and saves it to local disk.

    In stdio mode, returns the local file path for direct access.
    In HTTP mode, returns a temporary download URL (valid for 1 hour).

    Args:
        message_id: The message resource name (e.g. spaces/X/messages/Y).
        attachment_index: Zero-based index of the attachment to download (default 0).

    Returns:
        str: Attachment metadata with either a local file path or download URL.
    """
    logger.info(
        f"[download_chat_attachment] Message: '{message_id}', Index: {attachment_index}"
    )

    # Fetch the message to get attachment metadata
    msg = await asyncio.to_thread(
        service.spaces().messages().get(name=message_id).execute
    )

    attachments = msg.get("attachment", [])
    if not attachments:
        return f"No attachments found on message {message_id}."

    if attachment_index < 0 or attachment_index >= len(attachments):
        return (
            f"Invalid attachment_index {attachment_index}. "
            f"Message has {len(attachments)} attachment(s) (0-{len(attachments) - 1})."
        )

    att = attachments[attachment_index]
    filename = att.get("contentName", "attachment")
    content_type = att.get("contentType", "application/octet-stream")
    source = att.get("source", "")

    # The media endpoint needs attachmentDataRef.resourceName (e.g.
    # "spaces/S/attachments/A"), NOT the attachment name which includes
    # the /messages/ segment and causes 400 errors.
    media_resource = att.get("attachmentDataRef", {}).get("resourceName", "")
    att_name = att.get("name", "")

    logger.info(
        f"[download_chat_attachment] Downloading '{filename}' ({content_type}), "
        f"source={source}, mediaResource={media_resource}, name={att_name}"
    )

    # Download the attachment binary data via the Chat API media endpoint.
    # We use httpx with the Bearer token directly because MediaIoBaseDownload
    # and AuthorizedHttp fail in OAuth 2.1 (no refresh_token). The attachment's
    # downloadUri points to chat.google.com which requires browser cookies.
    if not media_resource and not att_name:
        return f"No resource name available for attachment '{filename}'."

    # Prefer attachmentDataRef.resourceName for the media endpoint
    resource_name = media_resource or att_name
    download_url = f"https://chat.googleapis.com/v1/media/{resource_name}?alt=media"

    try:
        access_token = service._http.credentials.token
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(
                download_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if resp.status_code != 200:
                body = resp.text[:500]
                return (
                    f"Failed to download attachment '{filename}': "
                    f"HTTP {resp.status_code} from {download_url}\n{body}"
                )
            file_bytes = resp.content
    except Exception as e:
        return f"Failed to download attachment '{filename}': {e}"

    size_bytes = len(file_bytes)
    size_kb = size_bytes / 1024

    # Check if we're in stateless mode (can't save files)
    from auth.oauth_config import is_stateless_mode

    if is_stateless_mode():
        b64_preview = base64.urlsafe_b64encode(file_bytes).decode("utf-8")[:100]
        return "\n".join(
            [
                f"Attachment downloaded: {filename} ({content_type})",
                f"Size: {size_kb:.1f} KB ({size_bytes} bytes)",
                "",
                "Stateless mode: File storage disabled.",
                f"Base64 preview: {b64_preview}...",
            ]
        )

    # Save to local disk
    from core.attachment_storage import get_attachment_storage, get_attachment_url
    from core.config import get_transport_mode

    storage = get_attachment_storage()
    b64_data = base64.urlsafe_b64encode(file_bytes).decode("utf-8")
    result = storage.save_attachment(
        base64_data=b64_data, filename=filename, mime_type=content_type
    )

    result_lines = [
        f"Attachment downloaded: {filename}",
        f"Type: {content_type}",
        f"Size: {size_kb:.1f} KB ({size_bytes} bytes)",
    ]

    if get_transport_mode() == "stdio":
        result_lines.append(f"\nSaved to: {result.path}")
        result_lines.append(
            "\nThe file has been saved to disk and can be accessed directly via the file path."
        )
    else:
        download_url = get_attachment_url(result.file_id)
        result_lines.append(f"\nDownload URL: {download_url}")
        result_lines.append("\nThe file will expire after 1 hour.")

    logger.info(
        f"[download_chat_attachment] Saved {size_kb:.1f} KB attachment to {result.path}"
    )
    return "\n".join(result_lines)
