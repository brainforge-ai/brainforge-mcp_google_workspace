"""Tests for typed Slides helpers and revision guards."""

from unittest.mock import Mock

import pytest

from gslides import slides_tools


def _unwrap(tool):
    fn = tool.fn if hasattr(tool, "fn") else tool
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def _service():
    service = Mock()
    service.presentations.return_value.batchUpdate.return_value.execute.return_value = {
        "replies": [{}]
    }
    service.presentations.return_value.get.return_value.execute.return_value = {
        "title": "Deck",
        "revisionId": "rev-1",
        "slides": [],
        "pageSize": {},
    }
    return service


def _body(service):
    return service.presentations.return_value.batchUpdate.call_args.kwargs["body"]


@pytest.mark.asyncio
async def test_batch_update_presentation_sends_write_control():
    service = _service()

    await _unwrap(slides_tools.batch_update_presentation)(
        service=service,
        user_google_email="user@example.com",
        presentation_id="p" * 25,
        requests=[{"deleteObject": {"objectId": "x"}}],
        required_revision_id="rev-1",
    )

    assert _body(service)["writeControl"] == {"requiredRevisionId": "rev-1"}


@pytest.mark.asyncio
async def test_add_slide_text_creates_shape_and_inserts_text():
    service = _service()

    result = await _unwrap(slides_tools.add_slide_text)(
        service=service,
        user_google_email="user@example.com",
        presentation_id="p" * 25,
        slide_object_id="slide_1",
        text="Hello",
        object_id="box_1",
    )

    requests = _body(service)["requests"]
    assert requests[0]["createShape"]["objectId"] == "box_1"
    assert requests[0]["createShape"]["elementProperties"]["pageObjectId"] == "slide_1"
    assert requests[1]["insertText"] == {
        "objectId": "box_1",
        "text": "Hello",
        "insertionIndex": 0,
    }
    assert "box_1" in result


@pytest.mark.asyncio
async def test_replace_slide_text_returns_occurrence_count():
    service = _service()
    service.presentations.return_value.batchUpdate.return_value.execute.return_value = {
        "replies": [{"replaceAllText": {"occurrencesChanged": 3}}]
    }

    result = await _unwrap(slides_tools.replace_slide_text)(
        service=service,
        user_google_email="user@example.com",
        presentation_id="p" * 25,
        find_text="{{CLIENT}}",
        replace_text="Acme",
    )

    assert _body(service)["requests"][0]["replaceAllText"]["containsText"] == {
        "text": "{{CLIENT}}",
        "matchCase": False,
    }
    assert "Replaced 3 occurrence(s)" in result


@pytest.mark.asyncio
async def test_duplicate_slide_returns_new_id():
    service = _service()

    result = await _unwrap(slides_tools.duplicate_slide)(
        service=service,
        user_google_email="user@example.com",
        presentation_id="p" * 25,
        slide_object_id="slide_1",
        object_id="slide_copy",
    )

    request = _body(service)["requests"][0]["duplicateObject"]
    assert request["objectId"] == "slide_1"
    assert request["objectIds"] == {"slide_1": "slide_copy"}
    assert "slide_copy" in result


@pytest.mark.asyncio
async def test_update_slide_notes_replaces_existing_text():
    service = _service()
    service.presentations.return_value.get.return_value.execute.return_value = {
        "revisionId": "rev-1",
        "slides": [
            {
                "objectId": "slide_1",
                "slideProperties": {
                    "notesPage": {
                        "pageElements": [
                            {
                                "objectId": "notes_1",
                                "shape": {
                                    "placeholder": {"type": "BODY"},
                                    "text": {
                                        "textElements": [
                                            {"textRun": {"content": "Old notes"}}
                                        ]
                                    },
                                },
                            }
                        ]
                    }
                },
            }
        ]
    }

    result = await _unwrap(slides_tools.update_slide_notes)(
        service=service,
        user_google_email="user@example.com",
        presentation_id="p" * 25,
        slide_object_id="slide_1",
        notes_text="New notes",
    )

    requests = _body(service)["requests"]
    assert requests[0]["deleteText"] == {
        "objectId": "notes_1",
        "textRange": {"type": "ALL"},
    }
    assert requests[1]["insertText"]["text"] == "New notes"
    assert _body(service)["writeControl"] == {"requiredRevisionId": "rev-1"}
    assert "Updated notes" in result


@pytest.mark.asyncio
async def test_update_slide_notes_missing_slide_returns_error():
    service = _service()

    result = await _unwrap(slides_tools.update_slide_notes)(
        service=service,
        user_google_email="user@example.com",
        presentation_id="p" * 25,
        slide_object_id="missing",
        notes_text="New notes",
    )

    assert "was not found" in result
    service.presentations.return_value.batchUpdate.assert_not_called()


@pytest.mark.asyncio
async def test_get_presentation_includes_revision_id():
    service = _service()

    result = await _unwrap(slides_tools.get_presentation)(
        service=service,
        user_google_email="user@example.com",
        presentation_id="p" * 25,
    )

    assert "Revision ID: rev-1" in result


@pytest.mark.asyncio
async def test_update_slide_notes_missing_placeholder_returns_error():
    service = _service()
    service.presentations.return_value.get.return_value.execute.return_value = {
        "slides": [
            {
                "objectId": "slide_1",
                "slideProperties": {"notesPage": {"pageElements": []}},
            }
        ]
    }

    result = await _unwrap(slides_tools.update_slide_notes)(
        service=service,
        user_google_email="user@example.com",
        presentation_id="p" * 25,
        slide_object_id="slide_1",
        notes_text="New notes",
    )

    assert "no notes placeholder" in result
    service.presentations.return_value.batchUpdate.assert_not_called()


@pytest.mark.asyncio
async def test_update_slide_notes_empty_existing_text_inserts_only():
    service = _service()
    service.presentations.return_value.get.return_value.execute.return_value = {
        "slides": [
            {
                "objectId": "slide_1",
                "slideProperties": {
                    "notesPage": {
                        "pageElements": [
                            {
                                "objectId": "notes_1",
                                "shape": {"placeholder": {"type": "BODY"}},
                            }
                        ]
                    }
                },
            }
        ]
    }

    await _unwrap(slides_tools.update_slide_notes)(
        service=service,
        user_google_email="user@example.com",
        presentation_id="p" * 25,
        slide_object_id="slide_1",
        notes_text="New notes",
    )

    requests = _body(service)["requests"]
    assert len(requests) == 1
    assert requests[0]["insertText"]["insertionIndex"] == 0


@pytest.mark.asyncio
async def test_add_slide_text_stale_revision_returns_actionable_error():
    class RevisionError(Exception):
        content = b"The document has changed since the required revision"

    service = _service()
    service.presentations.return_value.batchUpdate.return_value.execute.side_effect = (
        RevisionError("400")
    )

    result = await _unwrap(slides_tools.add_slide_text)(
        service=service,
        user_google_email="user@example.com",
        presentation_id="p" * 25,
        slide_object_id="slide_1",
        text="Hello",
        required_revision_id="rev-1",
    )

    assert "Error: The presentation changed" in result


@pytest.mark.asyncio
async def test_replace_slide_text_scopes_to_one_slide():
    service = _service()

    await _unwrap(slides_tools.replace_slide_text)(
        service=service,
        user_google_email="user@example.com",
        presentation_id="p" * 25,
        find_text="Q3",
        replace_text="Q4",
        slide_object_id="slide_1",
    )

    request = _body(service)["requests"][0]["replaceAllText"]
    assert request["pageObjectIds"] == ["slide_1"]
