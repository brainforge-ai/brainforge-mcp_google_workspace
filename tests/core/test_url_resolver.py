from core.url_resolver import resolve_google_url


def test_resolve_doc_url():
    assert resolve_google_url("https://docs.google.com/document/d/abc123DEF_/edit") == {
        "resource_type": "doc",
        "id": "abc123DEF_",
        "original_url": "https://docs.google.com/document/d/abc123DEF_/edit",
    }


def test_resolve_sheet_url():
    out = resolve_google_url("https://docs.google.com/spreadsheets/d/1AbC-23_def/edit#gid=0")
    assert out["resource_type"] == "sheet"
    assert out["id"] == "1AbC-23_def"


def test_resolve_drive_file_url():
    out = resolve_google_url("https://drive.google.com/file/d/FILE_ID/view?usp=sharing")
    assert out["resource_type"] == "drive_file"
    assert out["id"] == "FILE_ID"


def test_resolve_drive_open_id_url():
    out = resolve_google_url("https://drive.google.com/open?id=OPEN_ID")
    assert out["resource_type"] == "drive_file"
    assert out["id"] == "OPEN_ID"


def test_resolve_drive_uc_id_url():
    out = resolve_google_url("https://drive.google.com/uc?id=UC_ID&export=download")
    assert out["resource_type"] == "drive_file"
    assert out["id"] == "UC_ID"


def test_resolve_drive_folder_u0_url():
    out = resolve_google_url("https://drive.google.com/drive/u/0/folders/FOLDER_ID")
    assert out["resource_type"] == "drive_folder"
    assert out["id"] == "FOLDER_ID"


def test_unknown_url():
    assert resolve_google_url("https://example.com") == {
        "resource_type": "unknown",
        "id": None,
        "original_url": "https://example.com",
    }
