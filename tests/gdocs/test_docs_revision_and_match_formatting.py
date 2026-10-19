"""Tests for Docs revision guards and match-based formatting helpers."""

from unittest.mock import Mock

import pytest

from gdocs import docs_tools
from gdocs.docs_helpers import (
    find_paragraph_range_in_content,
    find_text_range_in_content,
    get_doc_body_content,
)
from gdocs.managers.batch_operation_manager import BatchOperationManager


def _unwrap(tool):
    fn = tool.fn if hasattr(tool, "fn") else tool
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def _doc_body(*paragraphs):
    content = []
    index = 1
    for text in paragraphs:
        end_index = index + len(text)
        content.append(
            {
                "startIndex": index,
                "endIndex": end_index,
                "paragraph": {
                    "elements": [
                        {
                            "startIndex": index,
                            "endIndex": end_index - 1,
                            "textRun": {"content": text},
                        }
                    ]
                },
            }
        )
        index = end_index
    return {"body": {"content": content}}


def _service(doc):
    service = Mock()
    service.documents.return_value.get.return_value.execute.return_value = doc
    service.documents.return_value.batchUpdate.return_value.execute.return_value = {
        "replies": [{}]
    }
    return service


def test_find_text_range_across_runs():
    content = [
        {
            "startIndex": 1,
            "endIndex": 10,
            "paragraph": {
                "elements": [
                    {"startIndex": 1, "textRun": {"content": "Hello "}},
                    {"startIndex": 7, "textRun": {"content": "world"}},
                ]
            },
        }
    ]

    assert find_text_range_in_content(content, "world") == (7, 12)
    assert find_text_range_in_content(content, "Hello world") == (1, 12)
    assert find_text_range_in_content(content, "missing") is None


def test_find_paragraph_range_returns_paragraph_bounds():
    doc = _doc_body("First line\n", "Second line\n")
    content = doc["body"]["content"]

    assert find_paragraph_range_in_content(content, "Second") == (12, 24)


@pytest.mark.asyncio
async def test_batch_update_doc_sends_write_control():
    service = _service(_doc_body("Text\n"))

    await _unwrap(docs_tools.batch_update_doc)(
        service=service,
        user_google_email="user@example.com",
        document_id="d" * 25,
        operations=[{"type": "insert_text", "end_of_segment": True, "text": "x"}],
        required_revision_id="rev-123",
    )

    body = service.documents().batchUpdate.call_args.kwargs["body"]
    assert body["writeControl"] == {"requiredRevisionId": "rev-123"}


def test_stale_revision_error_is_actionable():
    manager = BatchOperationManager(Mock())

    message = manager._rewrite_execution_error(
        "HttpError 400: Precondition failed: requiredRevisionId mismatch",
        [{"type": "insert_text"}],
    )

    assert "document changed" in message.lower()
    assert "required_revision_id" in message


@pytest.mark.asyncio
async def test_format_doc_text_by_match_formats_matched_range():
    service = _service(_doc_body("Quarterly revenue grew.\n"))

    result = await _unwrap(docs_tools.format_doc_text_by_match)(
        service=service,
        user_google_email="user@example.com",
        document_id="e" * 25,
        match_text="Quarterly revenue",
        bold=True,
    )

    request = service.documents().batchUpdate.call_args.kwargs["body"]["requests"][0]
    assert request["updateTextStyle"]["range"] == {"startIndex": 1, "endIndex": 18}
    assert request["updateTextStyle"]["textStyle"] == {"bold": True}
    assert "Formatted occurrence 1" in result


@pytest.mark.asyncio
async def test_format_doc_text_by_match_missing_text_returns_error():
    service = _service(_doc_body("Some text\n"))

    result = await _unwrap(docs_tools.format_doc_text_by_match)(
        service=service,
        user_google_email="user@example.com",
        document_id="f" * 25,
        match_text="not here",
        bold=True,
    )

    assert "was not found" in result
    service.documents().batchUpdate.assert_not_called()


@pytest.mark.asyncio
async def test_format_doc_paragraph_by_match_formats_paragraph():
    service = _service(_doc_body("Summary\n", "Body copy\n"))

    result = await _unwrap(docs_tools.format_doc_paragraph_by_match)(
        service=service,
        user_google_email="user@example.com",
        document_id="g" * 25,
        match_text="Summary",
        heading_level=1,
    )

    request = service.documents().batchUpdate.call_args.kwargs["body"]["requests"][0]
    assert request["updateParagraphStyle"]["range"] == {"startIndex": 1, "endIndex": 9}
    assert request["updateParagraphStyle"]["paragraphStyle"] == {
        "namedStyleType": "HEADING_1"
    }
    assert "Applied paragraph style" in result


def _tabs_doc(*tab_specs):
    """Build a tabs-shaped document: each spec is (tab_id, text, child_tabs)."""
    tabs = []
    for tab_id, text, children in tab_specs:
        tabs.append(
            {
                "tabProperties": {"tabId": tab_id},
                "documentTab": {"body": _doc_body(text)["body"]},
                "childTabs": children,
            }
        )
    return {"tabs": tabs, "revisionId": "rev-9"}


def test_find_text_range_uses_utf16_units():
    content = _doc_body("😄Summary\n")["body"]["content"]

    assert find_text_range_in_content(content, "Summary") == (3, 10)


def test_find_text_range_case_insensitive_preserves_offsets():
    content = _doc_body("İx Yaz\n")["body"]["content"]

    assert find_text_range_in_content(content, "yaz") == (4, 7)


def test_find_text_range_uses_occurrence():
    content = _doc_body("foo and foo\n")["body"]["content"]

    assert find_text_range_in_content(content, "foo", occurrence=2) == (9, 12)
    assert find_text_range_in_content(content, "foo", occurrence=3) is None


def test_find_text_range_skips_table_of_contents():
    content = [
        {
            "startIndex": 1,
            "endIndex": 8,
            "tableOfContents": {
                "content": [
                    {
                        "startIndex": 1,
                        "endIndex": 8,
                        "paragraph": {
                            "elements": [
                                {"startIndex": 1, "textRun": {"content": "Summary"}}
                            ]
                        },
                    }
                ]
            },
        },
        {
            "startIndex": 10,
            "endIndex": 17,
            "paragraph": {
                "elements": [
                    {"startIndex": 10, "textRun": {"content": "Summary"}}
                ]
            },
        },
    ]

    assert find_text_range_in_content(content, "Summary") == (10, 17)


def test_find_text_range_in_table_cell():
    content = [
        {
            "startIndex": 1,
            "endIndex": 20,
            "table": {
                "tableRows": [
                    {
                        "tableCells": [
                            {
                                "content": [
                                    {
                                        "startIndex": 5,
                                        "endIndex": 12,
                                        "paragraph": {
                                            "elements": [
                                                {
                                                    "startIndex": 5,
                                                    "textRun": {"content": "Total 10"},
                                                }
                                            ]
                                        },
                                    }
                                ]
                            }
                        ]
                    }
                ]
            },
        }
    ]

    assert find_text_range_in_content(content, "10") == (11, 13)


def test_find_paragraph_range_missing_returns_none():
    content = _doc_body("Only this\n")["body"]["content"]

    assert find_paragraph_range_in_content(content, "missing") is None


def test_get_doc_body_content_uses_first_tab():
    doc = _tabs_doc(("t.0", "First tab\n", []), ("t.1", "Second tab\n", []))
    content = get_doc_body_content(doc)

    assert content[0]["paragraph"]["elements"][0]["textRun"]["content"] == "First tab\n"


def test_get_doc_body_content_reads_nested_child_tab():
    child = {
        "tabProperties": {"tabId": "t.child"},
        "documentTab": {"body": _doc_body("Child text\n")["body"]},
    }
    doc = _tabs_doc(("t.0", "Parent\n", [child]))
    content = get_doc_body_content(doc, "t.child")

    assert content[0]["paragraph"]["elements"][0]["textRun"]["content"] == "Child text\n"


def test_get_doc_body_content_unknown_tab_returns_none():
    doc = _tabs_doc(("t.0", "Text\n", []))

    assert get_doc_body_content(doc, "missing") is None


@pytest.mark.asyncio
async def test_format_doc_text_by_match_sends_default_revision_guard():
    service = _service(_tabs_doc(("t.0", "Summary\n", [])))

    await _unwrap(docs_tools.format_doc_text_by_match)(
        service=service,
        user_google_email="user@example.com",
        document_id="h" * 25,
        match_text="Summary",
        bold=True,
    )

    body = service.documents().batchUpdate.call_args.kwargs["body"]
    assert body["writeControl"] == {"requiredRevisionId": "rev-9"}


@pytest.mark.asyncio
async def test_format_doc_text_by_match_clear_link_only():
    service = _service(_doc_body("Link text\n"))

    await _unwrap(docs_tools.format_doc_text_by_match)(
        service=service,
        user_google_email="user@example.com",
        document_id="i" * 25,
        match_text="Link text",
        clear_link=True,
    )

    request = service.documents().batchUpdate.call_args.kwargs["body"]["requests"][0]
    assert request["updateTextStyle"]["fields"] == "link"


@pytest.mark.asyncio
async def test_format_doc_text_by_match_requires_a_formatting_option():
    service = _service(_doc_body("Text\n"))

    result = await _unwrap(docs_tools.format_doc_text_by_match)(
        service=service,
        user_google_email="user@example.com",
        document_id="j" * 25,
        match_text="Text",
    )

    assert "at least one formatting option" in result
    service.documents.return_value.batchUpdate.assert_not_called()


@pytest.mark.asyncio
async def test_format_doc_text_by_match_unknown_tab_returns_error():
    service = _service(_tabs_doc(("t.0", "Text\n", [])))

    result = await _unwrap(docs_tools.format_doc_text_by_match)(
        service=service,
        user_google_email="user@example.com",
        document_id="k" * 25,
        match_text="Text",
        tab_id="missing",
        bold=True,
    )

    assert "Tab 'missing' was not found" in result
    service.documents.return_value.batchUpdate.assert_not_called()


@pytest.mark.asyncio
async def test_format_doc_text_by_match_stale_revision_is_actionable():
    class RevisionError(Exception):
        content = b"The document has changed since the specified revision"

    service = _service(_doc_body("Text\n"))
    service.documents.return_value.batchUpdate.return_value.execute.side_effect = (
        RevisionError("400")
    )

    result = await _unwrap(docs_tools.format_doc_text_by_match)(
        service=service,
        user_google_email="user@example.com",
        document_id="l" * 25,
        match_text="Text",
        bold=True,
    )

    assert "Re-read the document" in result
