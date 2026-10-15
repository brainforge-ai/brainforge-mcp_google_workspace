"""
Doc/skill parity: every exported Google Sheets tool must be documented.

Guards against the drift the ce-code-review flagged (a registered tool missing
from skills/managing-google-workspace).
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import gsheets

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
SHEETS_REF = os.path.join(REPO, "skills/managing-google-workspace/references/sheets.md")
SKILL = os.path.join(REPO, "skills/managing-google-workspace/SKILL.md")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_every_exported_sheets_tool_is_in_the_reference():
    ref = _read(SHEETS_REF)
    missing = [t for t in gsheets.__all__ if t not in ref]
    assert not missing, f"Undocumented sheets tools in references/sheets.md: {missing}"


def test_every_exported_sheets_tool_is_in_the_skill():
    skill = _read(SKILL)
    missing = [t for t in gsheets.__all__ if t not in skill]
    assert not missing, f"Undocumented sheets tools in SKILL.md: {missing}"
