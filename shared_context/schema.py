"""Tool schema definitions for shared_context.

Provides the JSON Schema for the tool's parameters (shared across all
API formats) and ready-to-use tool definitions for OpenAI and Anthropic.

Usage::

    from shared_context.schema import openai_tool, anthropic_tool

    # Pass directly to the API
    response = client.chat.completions.create(
        tools=[openai_tool()],
        ...
    )
"""

from __future__ import annotations

import copy
from typing import Any

TOOL_NAME = "shared_context"

TOOL_DESCRIPTION = (
    "Read and write to the shared context store — the session's working memory. "
    "Use list_keys to see available keys (always call this first). "
    "Use read to get a key's value. "
    "Use write to create or update a key. "
    "Use delete to remove a key that is no longer relevant."
)

PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["list_keys", "read", "write", "delete"],
            "description": (
                "The operation to perform. "
                "list_keys: returns all keys with metadata (no values). "
                "read: returns the value for a single key. "
                "write: creates or overwrites a key. "
                "delete: removes a key entirely."
            ),
        },
        "key": {
            "type": "string",
            "description": (
                "The key to operate on. Required for read, write, and delete. "
                "Must be lowercase alphanumeric + underscores, max 64 characters."
            ),
        },
        "value": {
            "type": "string",
            "description": (
                "The value to write. Required for write. "
                "Must be distilled state, not raw data. Max ~1000 tokens."
            ),
        },
    },
    "required": ["action"],
}


def openai_tool(
    *,
    name: str = TOOL_NAME,
    description: str = TOOL_DESCRIPTION,
    strict: bool = False,
) -> dict[str, Any]:
    """Return the tool definition in OpenAI function-calling format.

    Suitable for passing directly to ``tools=[openai_tool()]`` in a
    chat completions request.

    Parameters
    ----------
    name:
        Override the tool name (default ``"shared_context"``).
    description:
        Override the tool description.
    strict:
        Enable OpenAI's strict mode for structured outputs.
    """
    schema = copy.deepcopy(PARAMETERS_SCHEMA)
    tool: dict[str, Any] = {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": schema,
        },
    }
    if strict:
        tool["function"]["strict"] = True
    return tool


def anthropic_tool(
    *,
    name: str = TOOL_NAME,
    description: str = TOOL_DESCRIPTION,
) -> dict[str, Any]:
    """Return the tool definition in Anthropic tool-use format.

    Suitable for passing directly to ``tools=[anthropic_tool()]`` in a
    messages API request.
    """
    return {
        "name": name,
        "description": description,
        "input_schema": copy.deepcopy(PARAMETERS_SCHEMA),
    }
