"""Plug-and-play integration with the Anthropic messages API.

Works with both the ``anthropic`` Python SDK and raw dict responses.
Does **not** require ``anthropic`` as a dependency.

Usage::

    from anthropic import Anthropic
    from shared_context import SharedContextStore
    from shared_context.anthropic import tool_definition, process_response

    client = Anthropic()
    store = SharedContextStore("sess1", storage_path="./data/sess1.json")
    messages = [{"role": "user", "content": "Investigate the issue."}]

    while True:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=messages,
            tools=[tool_definition()],
        )
        new_messages, done = process_response(response, store, participant="agent")
        messages.extend(new_messages)
        if done:
            break
"""

from __future__ import annotations

import json
from typing import Any

from shared_context.schema import TOOL_NAME, anthropic_tool
from shared_context.store import SharedContextStore
from shared_context.tool import handle

# Re-export so users only need one import.
tool_definition = anthropic_tool


def handle_tool_use(
    block: Any,
    store: SharedContextStore,
    *,
    participant: str = "unknown",
    tool_name: str = TOOL_NAME,
) -> dict[str, Any] | None:
    """Handle a single Anthropic tool_use content block.

    Accepts both SDK ``ToolUseBlock`` objects and plain dicts.

    Returns a ``tool_result`` content block dict, or ``None`` if the
    block is not for shared_context.
    """
    if isinstance(block, dict):
        block_type = block.get("type", "")
        name = block.get("name", "")
        input_data = block.get("input", {})
        block_id = block.get("id", "")
    else:
        block_type = getattr(block, "type", "")
        if block_type != "tool_use":
            return None
        name = block.name
        input_data = block.input
        block_id = block.id

    if block_type != "tool_use" or name != tool_name:
        return None

    result = handle(store, input_data, participant=participant)

    return {
        "type": "tool_result",
        "tool_use_id": block_id,
        "content": json.dumps(result),
    }


def process_response(
    response: Any,
    store: SharedContextStore,
    *,
    participant: str = "unknown",
    tool_name: str = TOOL_NAME,
) -> tuple[list[dict[str, Any]], bool]:
    """Process a full Anthropic messages API response.

    Returns a tuple of ``(new_messages, done)``:

    - ``new_messages``: list of message dicts to append to your messages list.
      Includes the assistant message and any tool_result user message.
    - ``done``: ``True`` if the model finished (``end_turn``), ``False`` if it
      made tool calls and you should loop again.

    Example::

        while True:
            response = client.messages.create(...)
            new_messages, done = process_response(response, store, participant="agent")
            messages.extend(new_messages)
            if done:
                break
    """
    # Extract fields — support SDK objects and raw dicts.
    if isinstance(response, dict):
        stop_reason = response.get("stop_reason", "")
        content = response.get("content", [])
    else:
        stop_reason = response.stop_reason
        content = response.content

    # Build the assistant message with all content blocks.
    assistant_content: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []

    for block in content:
        if isinstance(block, dict):
            assistant_content.append(block)
        else:
            # SDK object — convert to dict.
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        # Process tool_use blocks.
        result = handle_tool_use(
            block, store, participant=participant, tool_name=tool_name
        )
        if result is not None:
            tool_results.append(result)

    result_messages: list[dict[str, Any]] = [
        {"role": "assistant", "content": assistant_content}
    ]

    if stop_reason == "end_turn" or not tool_results:
        return result_messages, True

    # Tool results go in a user message (Anthropic's format).
    result_messages.append({"role": "user", "content": tool_results})
    return result_messages, False
