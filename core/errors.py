from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, Optional, TypedDict


ErrorKind = Literal[
    "auth_required",
    "permission_denied",
    "rate_limited",
    "invalid_input",
    "not_found",
    "upstream_error",
    "server_misconfigured",
    "transient_network",
    "unknown",
]


class ToolErrorPayload(TypedDict, total=False):
    kind: ErrorKind
    message: str
    recommended_action: str
    retry_after_seconds: int
    details: Any


@dataclass(frozen=True)
class ToolExecutionError(Exception):
    payload: ToolErrorPayload

    def __str__(self) -> str:
        # Backward compatible: preserve a readable string while embedding structured data.
        # Many MCP clients surface only the string, so include both.
        message = self.payload.get("message", "Tool failed")
        recommended = self.payload.get("recommended_action")
        retry_after = self.payload.get("retry_after_seconds")

        suffix = []
        if recommended:
            suffix.append(f"recommended_action={recommended}")
        if retry_after is not None:
            suffix.append(f"retry_after_seconds={retry_after}")

        json_blob = json.dumps(self.payload, default=str)
        if suffix:
            return f"{message} ({', '.join(suffix)})\n\nMCP_ERROR_JSON: {json_blob}"
        return f"{message}\n\nMCP_ERROR_JSON: {json_blob}"

