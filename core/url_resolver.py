from __future__ import annotations

import re
from typing import Optional, Literal
from urllib.parse import urlparse, parse_qs

from typing_extensions import TypedDict as ExtTypedDict


GoogleResourceType = Literal[
    "doc",
    "sheet",
    "slide",
    "form",
    "script",
    "drive_file",
    "drive_folder",
    "unknown",
]


class ResolvedGoogleUrl(ExtTypedDict):
    resource_type: GoogleResourceType
    id: Optional[str]
    original_url: str


_DOC_RE = re.compile(r"^https?://docs\.google\.com/(?:[^/]+/)?document/d/([a-zA-Z0-9_-]+)")
_SHEETS_RE = re.compile(r"^https?://docs\.google\.com/(?:[^/]+/)?spreadsheets/d/([a-zA-Z0-9_-]+)")
_SLIDES_RE = re.compile(r"^https?://docs\.google\.com/(?:[^/]+/)?presentation/d/([a-zA-Z0-9_-]+)")
_FORMS_RE = re.compile(r"^https?://docs\.google\.com/(?:[^/]+/)?forms/d/([a-zA-Z0-9_-]+)")
_SCRIPT_RE = re.compile(r"^https?://script\.google\.com/(?:.*?/)?d/([a-zA-Z0-9_-]+)")
_DRIVE_FILE_RE = re.compile(r"^https?://drive\.google\.com/file/d/([a-zA-Z0-9_-]+)")
_DRIVE_FOLDERS_RE = re.compile(r"^https?://drive\.google\.com/drive/(?:u/\d+/)?folders/([a-zA-Z0-9_-]+)")
_DRIVE_OPEN_ID_RE = re.compile(r"^https?://drive\.google\.com/open$")
_DRIVE_UC_RE = re.compile(r"^https?://drive\.google\.com/uc$")


def resolve_google_url(url: str) -> ResolvedGoogleUrl:
    url = (url or "").strip()
    if not url:
        return {"resource_type": "unknown", "id": None, "original_url": url}

    parsed = urlparse(url)
    qs = parse_qs(parsed.query or "")

    # Common Drive formats:
    # - https://drive.google.com/open?id=<FILE_ID>
    # - https://drive.google.com/uc?id=<FILE_ID>&export=download
    if parsed.scheme in ("http", "https") and parsed.netloc == "drive.google.com":
        full = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if _DRIVE_OPEN_ID_RE.match(full) or _DRIVE_UC_RE.match(full):
            file_id = (qs.get("id") or [None])[0]
            if file_id:
                return {
                    "resource_type": "drive_file",
                    "id": file_id,
                    "original_url": url,
                }

    for resource_type, pattern in (
        ("doc", _DOC_RE),
        ("sheet", _SHEETS_RE),
        ("slide", _SLIDES_RE),
        ("form", _FORMS_RE),
        ("script", _SCRIPT_RE),
        ("drive_file", _DRIVE_FILE_RE),
        ("drive_folder", _DRIVE_FOLDERS_RE),
    ):
        match = pattern.match(url)
        if match:
            return {"resource_type": resource_type, "id": match.group(1), "original_url": url}

    return {"resource_type": "unknown", "id": None, "original_url": url}
