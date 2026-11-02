"""
Chat tools under `--permissions chat:readonly`.

Permissions mode removes every tool whose required scopes the permission level
does not grant. Brainforge deploys Chat this way, so the read tools must stay
covered by the readonly level and the write tools must not.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from auth import permissions as permissions_module
from auth.permissions import get_allowed_scopes_set, set_permissions
from gchat import chat_tools

READ_TOOLS = [
    "list_spaces",
    "get_messages",
    "search_messages",
    "download_chat_attachment",
    "find_conversations",
]
WRITE_TOOLS = ["send_message", "create_reaction"]


def _required_scopes(tool_name):
    tool = getattr(chat_tools, tool_name)
    fn = getattr(tool, "fn", tool)
    return set(getattr(fn, "_required_google_scopes", []))


@pytest.fixture(autouse=True)
def chat_readonly():
    set_permissions({"chat": "readonly"})
    yield
    permissions_module._PERMISSIONS = None


@pytest.mark.parametrize("tool_name", READ_TOOLS)
def test_readonly_level_grants_read_tool_scopes(tool_name):
    required = _required_scopes(tool_name)
    assert required, f"{tool_name} declares no required scopes"
    assert required <= get_allowed_scopes_set()


@pytest.mark.parametrize("tool_name", WRITE_TOOLS)
def test_readonly_level_withholds_write_tool_scopes(tool_name):
    required = _required_scopes(tool_name)
    assert required, f"{tool_name} declares no required scopes"
    assert not required <= get_allowed_scopes_set()
