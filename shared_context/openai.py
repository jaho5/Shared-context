"""Plug-and-play integration with the OpenAI chat completions API.

Works with both the ``openai`` Python SDK and raw dict responses.
Does **not** require ``openai`` as a dependency.

Usage::

    from openai import OpenAI
    from shared_context import SharedContextStore
    from shared_context.openai import tool_definition, process_response

    client = OpenAI()
    store = SharedContextStore("sess1", storage_path="./data/sess1.json")
    messages = [{"role": "user", "content": "Investigate the issue."}]

    while True:
        response = client.chat.completions.create(
            model="gpt-4o",
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

from shared_context.schema import TOOL_NAME, openai_tool
from shared_context.store import SharedContextStore
from shared_context.tool import handle

# Re-export so users only need one import.
tool_definition = openai_tool


def handle_tool_call(
    tool_call: Any,
    store: SharedContextStore,
    *,
    participant: str = "unknown",
    tool_name: str = TOOL_NAME,
) -> dict[str, Any] | None:
    """Handle a single OpenAI tool call, returning a tool message dict.

    Accepts both SDK ``ChoiceDeltaToolCall`` / ``ChatCompletionMessageToolCall``
    objects and plain dicts.

    Returns ``None`` if the tool call is not for shared_context (i.e. it has
    a different function name), so you can mix shared_context with other tools.
    """
    # Extract fields — support both SDK objects and raw dicts.
    if isinstance(tool_call, dict):
        fn = tool_call.get("function", {})
        name = fn.get("name", "")
        arguments = fn.get("arguments", "{}")
        call_id = tool_call.get("id", "")
    else:
        name = tool_call.function.name
        arguments = tool_call.function.arguments
        call_id = tool_call.id

    if name != tool_name:
        return None

    request = json.loads(arguments)
    result = handle(store, request, participant=participant)

    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps(result),
    }


def process_response(
    response: Any,
    store: SharedContextStore,
    *,
    participant: str = "unknown",
    tool_name: str = TOOL_NAME,
) -> tuple[list[dict[str, Any]], bool]:
    """Process a full chat completion response, handling any shared_context tool calls.

    Returns a tuple of ``(new_messages, done)``:

    - ``new_messages``: list of message dicts to append to your messages list.
      Includes the assistant message and any tool result messages.
    - ``done``: ``True`` if the model finished (``stop``), ``False`` if it
      made tool calls and you should loop again.

    Supports both SDK response objects and raw dicts.

    Example::

        while True:
            response = client.chat.completions.create(...)
            new_messages, done = process_response(response, store, participant="agent")
            messages.extend(new_messages)
            if done:
                break
    """
    # Extract the first choice — support SDK objects and raw dicts.
    if isinstance(response, dict):
        choice = response["choices"][0]
        finish_reason = choice.get("finish_reason", "")
        message = choice.get("message", {})
        tool_calls = message.get("tool_calls") or []
        # Build assistant message dict.
        assistant_msg: dict[str, Any] = {"role": "assistant"}
        if message.get("content"):
            assistant_msg["content"] = message["content"]
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
    else:
        choice = response.choices[0]
        finish_reason = choice.finish_reason
        message = choice.message
        tool_calls = message.tool_calls or []
        # Build assistant message dict from SDK object.
        assistant_msg = {"role": "assistant"}
        if message.content:
            assistant_msg["content"] = message.content
        if tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ]

    result_messages: list[dict[str, Any]] = [assistant_msg]

    if finish_reason == "stop" or not tool_calls:
        return result_messages, True

    # Process each tool call.
    for tc in tool_calls:
        tool_msg = handle_tool_call(
            tc, store, participant=participant, tool_name=tool_name
        )
        if tool_msg is not None:
            result_messages.append(tool_msg)

    return result_messages, False
