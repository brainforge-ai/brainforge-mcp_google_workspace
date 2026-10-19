"""
Google Slides MCP Tools

This module provides MCP tools for interacting with Google Slides API.
"""

import logging
import asyncio
import uuid
from typing import List, Dict, Any, Optional


from auth.service_decorator import require_google_service
from core.server import server
from core.utils import handle_http_errors
from core.comments import create_comment_tools

logger = logging.getLogger(__name__)


@server.tool()
@handle_http_errors("create_presentation", service_type="slides")
@require_google_service("slides", "slides")
async def create_presentation(
    service, user_google_email: str, title: str = "Untitled Presentation"
) -> str:
    """
    Create a new Google Slides presentation.

    Args:
        user_google_email (str): The user's Google email address. Required.
        title (str): The title for the new presentation. Defaults to "Untitled Presentation".

    Returns:
        str: Details about the created presentation including ID and URL.
    """
    logger.info(
        f"[create_presentation] Invoked. Email: '{user_google_email}', Title: '{title}'"
    )

    body = {"title": title}

    result = await asyncio.to_thread(service.presentations().create(body=body).execute)

    presentation_id = result.get("presentationId")
    presentation_url = f"https://docs.google.com/presentation/d/{presentation_id}/edit"

    confirmation_message = f"""Presentation Created Successfully for {user_google_email}:
- Title: {title}
- Presentation ID: {presentation_id}
- URL: {presentation_url}
- Slides: {len(result.get("slides", []))} slide(s) created"""

    logger.info(f"Presentation created successfully for {user_google_email}")
    return confirmation_message


@server.tool()
@handle_http_errors("get_presentation", is_read_only=True, service_type="slides")
@require_google_service("slides", "slides_read")
async def get_presentation(
    service, user_google_email: str, presentation_id: str
) -> str:
    """
    Get details about a Google Slides presentation.

    Args:
        user_google_email (str): The user's Google email address. Required.
        presentation_id (str): The ID of the presentation to retrieve.

    Returns:
        str: Details about the presentation including title, slides count, and metadata.
    """
    logger.info(
        f"[get_presentation] Invoked. Email: '{user_google_email}', ID: '{presentation_id}'"
    )

    result = await asyncio.to_thread(
        service.presentations().get(presentationId=presentation_id).execute
    )

    title = result.get("title", "Untitled")
    slides = result.get("slides", [])
    page_size = result.get("pageSize", {})

    slides_info = []
    for i, slide in enumerate(slides, 1):
        slide_id = slide.get("objectId", "Unknown")
        page_elements = slide.get("pageElements", [])

        # Collect text from the slide whose JSON structure is very complicated
        # https://googleapis.github.io/google-api-python-client/docs/dyn/slides_v1.presentations.html#get
        slide_text = ""
        try:
            texts_from_elements = []
            for page_element in slide.get("pageElements", []):
                shape = page_element.get("shape", None)
                if shape and shape.get("text", None):
                    text = shape.get("text", None)
                    if text:
                        text_elements_in_shape = []
                        for text_element in text.get("textElements", []):
                            text_run = text_element.get("textRun", None)
                            if text_run:
                                content = text_run.get("content", None)
                                if content:
                                    start_index = text_element.get("startIndex", 0)
                                    text_elements_in_shape.append(
                                        (start_index, content)
                                    )

                        if text_elements_in_shape:
                            # Sort text elements within a single shape
                            text_elements_in_shape.sort(key=lambda item: item[0])
                            full_text_from_shape = "".join(
                                [item[1] for item in text_elements_in_shape]
                            )
                            texts_from_elements.append(full_text_from_shape)

            # cleanup text we collected
            slide_text = "\n".join(texts_from_elements)
            slide_text_rows = slide_text.split("\n")
            slide_text_rows = [row for row in slide_text_rows if len(row.strip()) > 0]
            if slide_text_rows:
                slide_text_rows = ["    > " + row for row in slide_text_rows]
                slide_text = "\n" + "\n".join(slide_text_rows)
            else:
                slide_text = ""
        except Exception as e:
            logger.warning(f"Failed to extract text from the slide {slide_id}: {e}")
            slide_text = f"<failed to extract text: {type(e)}, {e}>"

        slides_info.append(
            f"  Slide {i}: ID {slide_id}, {len(page_elements)} element(s), text: {slide_text if slide_text else 'empty'}"
        )

    confirmation_message = f"""Presentation Details for {user_google_email}:
- Title: {title}
- Presentation ID: {presentation_id}
- Revision ID: {result.get("revisionId", "unknown")}
- URL: https://docs.google.com/presentation/d/{presentation_id}/edit
- Total Slides: {len(slides)}
- Page Size: {page_size.get("width", {}).get("magnitude", "Unknown")} x {page_size.get("height", {}).get("magnitude", "Unknown")} {page_size.get("width", {}).get("unit", "")}

Slides Breakdown:
{chr(10).join(slides_info) if slides_info else "  No slides found"}"""

    logger.info(f"Presentation retrieved successfully for {user_google_email}")
    return confirmation_message


@server.tool()
@handle_http_errors("batch_update_presentation", service_type="slides")
@require_google_service("slides", "slides")
async def batch_update_presentation(
    service,
    user_google_email: str,
    presentation_id: str,
    requests: List[Dict[str, Any]],
    required_revision_id: Optional[str] = None,
) -> str:
    """
    Apply batch updates to a Google Slides presentation.

    Args:
        user_google_email (str): The user's Google email address. Required.
        presentation_id (str): The ID of the presentation to update.
        requests (List[Dict[str, Any]]): List of update requests to apply.
        required_revision_id (Optional[str]): Revision guard. The write is
            rejected when the presentation changed after this revision.

    Returns:
        str: Details about the batch update operation results.
    """
    logger.info(
        f"[batch_update_presentation] Invoked. Email: '{user_google_email}', ID: '{presentation_id}', Requests: {len(requests)}"
    )

    try:
        result = await _execute_slides_batch(
            service, presentation_id, requests, required_revision_id
        )
    except SlidesRevisionError as exc:
        return f"Error: {exc}"

    resulting_revision = result.get("writeControl", {}).get(
        "requiredRevisionId"
    )

    replies = result.get("replies", [])

    confirmation_message = f"""Batch Update Completed for {user_google_email}:
- Presentation ID: {presentation_id}
- Resulting revision: {resulting_revision or "unknown"}
- Precondition: {required_revision_id or "none"}
- URL: https://docs.google.com/presentation/d/{presentation_id}/edit
- Requests Applied: {len(requests)}
- Replies Received: {len(replies)}"""

    if replies:
        confirmation_message += "\n\nUpdate Results:"
        for i, reply in enumerate(replies, 1):
            if "createSlide" in reply:
                slide_id = reply["createSlide"].get("objectId", "Unknown")
                confirmation_message += (
                    f"\n  Request {i}: Created slide with ID {slide_id}"
                )
            elif "createShape" in reply:
                shape_id = reply["createShape"].get("objectId", "Unknown")
                confirmation_message += (
                    f"\n  Request {i}: Created shape with ID {shape_id}"
                )
            else:
                confirmation_message += f"\n  Request {i}: Operation completed"

    logger.info(f"Batch update completed successfully for {user_google_email}")
    return confirmation_message


class SlidesRevisionError(Exception):
    """Raised when a Slides write fails its revision precondition."""


def _new_object_id(prefix: str = "bf") -> str:
    """Generate a stable-enough object ID for Slides create requests."""
    return f"{prefix}_{uuid.uuid4().hex}"


def _slides_revision_error(error: Exception) -> Optional[str]:
    text = str(error)
    raw_content = getattr(error, "content", None)
    if raw_content:
        try:
            text += " " + raw_content.decode("utf-8", "replace")
        except (AttributeError, UnicodeDecodeError):
            pass

    lowered = text.lower()
    if ("revision" in lowered or "precondition" in lowered) and any(
        marker in lowered
        for marker in (
            "required revision",
            "requiredrevisionid",
            "changed since",
            "precondition",
            "failed_precondition",
            "mismatch",
            "does not match",
        )
    ):
        return (
            "The presentation changed since the revision you supplied. "
            "Re-read the presentation, then retry with the new revision ID. "
            f"Original error: {text}"
        )
    return None


async def _execute_slides_batch(
    service,
    presentation_id: str,
    requests: List[Dict[str, Any]],
    required_revision_id: Optional[str] = None,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"requests": requests}
    if required_revision_id is not None:
        if not required_revision_id.strip():
            raise SlidesRevisionError("required_revision_id cannot be empty.")
        body["writeControl"] = {"requiredRevisionId": required_revision_id}

    try:
        return await asyncio.to_thread(
            service.presentations()
            .batchUpdate(presentationId=presentation_id, body=body)
            .execute
        )
    except Exception as exc:
        revision_error = (
            _slides_revision_error(exc) if required_revision_id else None
        )
        if revision_error:
            raise SlidesRevisionError(revision_error) from exc
        raise


@server.tool()
@handle_http_errors("add_slide_text", service_type="slides")
@require_google_service("slides", "slides")
async def add_slide_text(
    service,
    user_google_email: str,
    presentation_id: str,
    slide_object_id: str,
    text: str,
    object_id: Optional[str] = None,
    x: float = 50.0,
    y: float = 100.0,
    width: float = 600.0,
    height: float = 300.0,
    unit: str = "PT",
    required_revision_id: Optional[str] = None,
) -> str:
    """
    Add a text box to a slide and fill it in one batch.

    Args:
        slide_object_id: Slide to place the text box on.
        text: Text to insert.
        object_id: Optional text box ID. Generated when omitted. Pass a stable
            value to make retries idempotent.
        x, y, width, height: Position and size in the chosen unit.
        unit: "PT" (default) or "EMU".
        required_revision_id: Optional revision guard.
    """
    if not text:
        return "Error: text is required."

    shape_id = object_id or _new_object_id("bf_text")
    requests = [
        {
            "createShape": {
                "objectId": shape_id,
                "shapeType": "TEXT_BOX",
                "elementProperties": {
                    "pageObjectId": slide_object_id,
                    "size": {
                        "width": {"magnitude": width, "unit": unit},
                        "height": {"magnitude": height, "unit": unit},
                    },
                    "transform": {
                        "scaleX": 1,
                        "scaleY": 1,
                        "translateX": x,
                        "translateY": y,
                        "unit": unit,
                    },
                },
            }
        },
        {
            "insertText": {
                "objectId": shape_id,
                "text": text,
                "insertionIndex": 0,
            }
        },
    ]

    try:
        result = await _execute_slides_batch(
            service, presentation_id, requests, required_revision_id
        )
    except SlidesRevisionError as exc:
        return f"Error: {exc}"
    resulting_revision = result.get("writeControl", {}).get("requiredRevisionId")

    link = f"https://docs.google.com/presentation/d/{presentation_id}/edit"
    return (
        f"Added text box '{shape_id}' to slide '{slide_object_id}' in "
        f"presentation {presentation_id}. Precondition: "
        f"{required_revision_id or 'none'}. Resulting revision: "
        f"{resulting_revision or 'unknown'}. Link: {link}"
    )


@server.tool()
@handle_http_errors("replace_slide_text", service_type="slides")
@require_google_service("slides", "slides")
async def replace_slide_text(
    service,
    user_google_email: str,
    presentation_id: str,
    find_text: str,
    replace_text: str,
    match_case: bool = False,
    slide_object_id: Optional[str] = None,
    required_revision_id: Optional[str] = None,
) -> str:
    """
    Replace every occurrence of text across a presentation.

    Args:
        find_text: Text to find.
        replace_text: Replacement text.
        match_case: Whether the match is case-sensitive.
        slide_object_id: Optional slide/page ID. When set, only that page is
            changed; otherwise the replacement is presentation-wide.
        required_revision_id: Optional revision guard.
    """
    if not find_text:
        return "Error: find_text is required."

    replace_request: Dict[str, Any] = {
        "containsText": {"text": find_text, "matchCase": match_case},
        "replaceText": replace_text,
    }
    if slide_object_id:
        replace_request["pageObjectIds"] = [slide_object_id]

    request = {"replaceAllText": replace_request}
    try:
        result = await _execute_slides_batch(
            service, presentation_id, [request], required_revision_id
        )
    except SlidesRevisionError as exc:
        return f"Error: {exc}"
    resulting_revision = result.get("writeControl", {}).get("requiredRevisionId")

    replacements = 0
    replies = result.get("replies", [])
    if replies and "replaceAllText" in replies[0]:
        replacements = replies[0]["replaceAllText"].get("occurrencesChanged", 0)

    link = f"https://docs.google.com/presentation/d/{presentation_id}/edit"
    return (
        f"Replaced {replacements} occurrence(s) of '{find_text}' in presentation "
        f"{presentation_id}. Precondition: {required_revision_id or 'none'}. "
        f"Resulting revision: {resulting_revision or 'unknown'}. Link: {link}"
    )


@server.tool()
@handle_http_errors("duplicate_slide", service_type="slides")
@require_google_service("slides", "slides")
async def duplicate_slide(
    service,
    user_google_email: str,
    presentation_id: str,
    slide_object_id: str,
    object_id: Optional[str] = None,
    required_revision_id: Optional[str] = None,
) -> str:
    """
    Duplicate a slide and return the new slide ID.

    Args:
        slide_object_id: Slide to duplicate.
        object_id: Optional ID for the copy. Generated when omitted. Pass a
            stable value to make retries idempotent.
        required_revision_id: Optional revision guard.
    """
    new_slide_id = object_id or _new_object_id("bf_slide")
    request = {
        "duplicateObject": {
            "objectId": slide_object_id,
            "objectIds": {slide_object_id: new_slide_id},
        }
    }

    try:
        result = await _execute_slides_batch(
            service, presentation_id, [request], required_revision_id
        )
    except SlidesRevisionError as exc:
        return f"Error: {exc}"
    resulting_revision = result.get("writeControl", {}).get("requiredRevisionId")
    created_id = (
        result.get("replies", [{}])[0].get("duplicateObject", {}).get("objectId")
        if result.get("replies")
        else None
    )

    link = f"https://docs.google.com/presentation/d/{presentation_id}/edit"
    return (
        f"Duplicated slide '{slide_object_id}' as '{created_id or new_slide_id}' "
        f"in presentation {presentation_id}. Precondition: "
        f"{required_revision_id or 'none'}. Resulting revision: "
        f"{resulting_revision or 'unknown'}. Link: {link}"
    )


@server.tool()
@handle_http_errors("update_slide_notes", service_type="slides")
@require_google_service("slides", "slides")
async def update_slide_notes(
    service,
    user_google_email: str,
    presentation_id: str,
    slide_object_id: str,
    notes_text: str,
    required_revision_id: Optional[str] = None,
) -> str:
    """
    Replace the speaker notes for a slide.

    Args:
        slide_object_id: Slide whose notes to update.
        notes_text: New notes text.
        required_revision_id: Optional revision guard.
    """
    presentation = await asyncio.to_thread(
        service.presentations().get(presentationId=presentation_id).execute
    )

    slide = next(
        (
            item
            for item in presentation.get("slides", [])
            if item.get("objectId") == slide_object_id
        ),
        None,
    )
    if not slide:
        return f"Error: Slide '{slide_object_id}' was not found."

    notes_page = slide.get("slideProperties", {}).get("notesPage", {})
    notes_object_id = notes_page.get("notesProperties", {}).get(
        "speakerNotesObjectId"
    )
    notes_shape = next(
        (
            element
            for element in notes_page.get("pageElements", [])
            if notes_object_id and element.get("objectId") == notes_object_id
        ),
        None,
    )
    if not notes_shape:
        notes_shape = next(
            (
                element
                for element in notes_page.get("pageElements", [])
                if element.get("shape", {})
                .get("placeholder", {})
                .get("type")
                == "BODY"
            ),
            None,
        )
        if notes_shape:
            notes_object_id = notes_shape.get("objectId")

    if not notes_object_id:
        return f"Error: Slide '{slide_object_id}' has no notes placeholder."

    requests: List[Dict[str, Any]] = []
    if notes_shape and notes_shape.get("shape", {}).get("text", {}).get(
        "textElements"
    ):
        requests.append(
            {
                "deleteText": {
                    "objectId": notes_object_id,
                    "textRange": {"type": "ALL"},
                }
            }
        )
    requests.append(
        {
            "insertText": {
                "objectId": notes_object_id,
                "text": notes_text,
                "insertionIndex": 0,
            }
        }
    )

    revision_id = required_revision_id or presentation.get("revisionId")
    try:
        result = await _execute_slides_batch(
            service, presentation_id, requests, revision_id
        )
    except SlidesRevisionError as exc:
        return f"Error: {exc}"
    resulting_revision = result.get("writeControl", {}).get("requiredRevisionId")

    link = f"https://docs.google.com/presentation/d/{presentation_id}/edit"
    return (
        f"Updated notes for slide '{slide_object_id}' in presentation "
        f"{presentation_id}. Precondition: {revision_id or 'none'}. "
        f"Resulting revision: {resulting_revision or 'unknown'}. "
        f"Link: {link}"
    )


@server.tool()
@handle_http_errors("get_page", is_read_only=True, service_type="slides")
@require_google_service("slides", "slides_read")
async def get_page(
    service, user_google_email: str, presentation_id: str, page_object_id: str
) -> str:
    """
    Get details about a specific page (slide) in a presentation.

    Args:
        user_google_email (str): The user's Google email address. Required.
        presentation_id (str): The ID of the presentation.
        page_object_id (str): The object ID of the page/slide to retrieve.

    Returns:
        str: Details about the specific page including elements and layout.
    """
    logger.info(
        f"[get_page] Invoked. Email: '{user_google_email}', Presentation: '{presentation_id}', Page: '{page_object_id}'"
    )

    result = await asyncio.to_thread(
        service.presentations()
        .pages()
        .get(presentationId=presentation_id, pageObjectId=page_object_id)
        .execute
    )

    page_type = result.get("pageType", "Unknown")
    page_elements = result.get("pageElements", [])

    elements_info = []
    for element in page_elements:
        element_id = element.get("objectId", "Unknown")
        if "shape" in element:
            shape_type = element["shape"].get("shapeType", "Unknown")
            elements_info.append(f"  Shape: ID {element_id}, Type: {shape_type}")
        elif "table" in element:
            table = element["table"]
            rows = table.get("rows", 0)
            cols = table.get("columns", 0)
            elements_info.append(f"  Table: ID {element_id}, Size: {rows}x{cols}")
        elif "line" in element:
            line_type = element["line"].get("lineType", "Unknown")
            elements_info.append(f"  Line: ID {element_id}, Type: {line_type}")
        else:
            elements_info.append(f"  Element: ID {element_id}, Type: Unknown")

    confirmation_message = f"""Page Details for {user_google_email}:
- Presentation ID: {presentation_id}
- Page ID: {page_object_id}
- Page Type: {page_type}
- Total Elements: {len(page_elements)}

Page Elements:
{chr(10).join(elements_info) if elements_info else "  No elements found"}"""

    logger.info(f"Page retrieved successfully for {user_google_email}")
    return confirmation_message


@server.tool()
@handle_http_errors("get_page_thumbnail", is_read_only=True, service_type="slides")
@require_google_service("slides", "slides_read")
async def get_page_thumbnail(
    service,
    user_google_email: str,
    presentation_id: str,
    page_object_id: str,
    thumbnail_size: str = "MEDIUM",
) -> str:
    """
    Generate a thumbnail URL for a specific page (slide) in a presentation.

    Args:
        user_google_email (str): The user's Google email address. Required.
        presentation_id (str): The ID of the presentation.
        page_object_id (str): The object ID of the page/slide.
        thumbnail_size (str): Size of thumbnail ("LARGE", "MEDIUM", "SMALL"). Defaults to "MEDIUM".

    Returns:
        str: URL to the generated thumbnail image.
    """
    logger.info(
        f"[get_page_thumbnail] Invoked. Email: '{user_google_email}', Presentation: '{presentation_id}', Page: '{page_object_id}', Size: '{thumbnail_size}'"
    )

    result = await asyncio.to_thread(
        service.presentations()
        .pages()
        .getThumbnail(
            presentationId=presentation_id,
            pageObjectId=page_object_id,
            thumbnailProperties_thumbnailSize=thumbnail_size,
            thumbnailProperties_mimeType="PNG",
        )
        .execute
    )

    thumbnail_url = result.get("contentUrl", "")

    confirmation_message = f"""Thumbnail Generated for {user_google_email}:
- Presentation ID: {presentation_id}
- Page ID: {page_object_id}
- Thumbnail Size: {thumbnail_size}
- Thumbnail URL: {thumbnail_url}

You can view or download the thumbnail using the provided URL.

Note: thumbnail generation is an expensive read (60 per user per minute). Cache the URL when you can."""

    logger.info(f"Thumbnail generated successfully for {user_google_email}")
    return confirmation_message


# Create comment management tools for slides
_comment_tools = create_comment_tools("presentation", "presentation_id")
list_presentation_comments = _comment_tools["list_comments"]
manage_presentation_comment = _comment_tools["manage_comment"]

# Aliases for backwards compatibility and intuitive naming
list_slide_comments = list_presentation_comments
manage_slide_comment = manage_presentation_comment
