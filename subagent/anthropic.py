"""Anthropic SDK integration for the subagent tool.

Provides :func:`create_runner` — a factory that builds a runner function
compatible with :class:`SubagentTool`.  The runner executes a full agent
loop using the Anthropic messages API.

Does **not** require ``anthropic`` as a dependency — works with any client
that has a ``messages.create()`` method returning the expected shape.

Usage::

    from anthropic import Anthropic
    from shared_context import SharedContextStore
    from shared_context.anthropic import tool_definition as sc_tool_def
    from shared_context.tool import handle as sc_handle
    from subagent import SubagentTool, AgentConfig
    from subagent.anthropic import create_runner

    client = Anthropic()
    store = SharedContextStore("sess1")

    runner = create_runner(
        client=client,
        tool_definitions={"shared_context": sc_tool_def(), "search": search_def},
        tool_handlers={"search": search_handler},
        shared_context_store=store,
    )

    tool = SubagentTool(runner=runner, available_tools={"shared_context", "search"})
"""

from __future__ import annotations

import json
from typing import Any, Callable

from subagent.registry import AgentConfig

# Appended to every subagent's system prompt (spec §8.4).
_SUBAGENT_SUFFIX = (
    "\n\nYou are a subagent. Keep your final response concise (under 1000 tokens). "
    "Write detailed findings to shared context rather than including them "
    "in your response. Your response will be returned to the orchestrator "
    "as a summary of your work."
)

# Type for application-provided tool handlers.
ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


def create_runner(
    *,
    client: Any,
    tool_definitions: dict[str, dict[str, Any]],
    tool_handlers: dict[str, ToolHandler] | None = None,
    shared_context_store: Any | None = None,
) -> Callable[[AgentConfig, str, str], tuple[str, int]]:
    """Build a runner function for the Anthropic messages API.

    Parameters
    ----------
    client:
        An Anthropic client (or anything with ``messages.create()``).
    tool_definitions:
        Mapping of tool name → Anthropic tool definition dict.  These are
        passed to the API's ``tools`` parameter.
    tool_handlers:
        Mapping of tool name → callable that takes the tool input dict and
        returns a result dict.  Not needed for ``shared_context`` — that
        is handled automatically when ``shared_context_store`` is provided.
    shared_context_store:
        A :class:`SharedContextStore` instance.  If provided and an agent's
        tools include ``"shared_context"``, the runner wires it up with the
        correct participant identity.

    Returns
    -------
    callable
        A runner function with signature
        ``(config, task_string, participant) -> (result_text, turns_used)``.
    """
    handlers = dict(tool_handlers or {})

    def run(config: AgentConfig, task_string: str, participant: str) -> tuple[str, int]:
        # Build the tool list and handler map for this agent.
        tools: list[dict[str, Any]] = []
        local_handlers: dict[str, ToolHandler] = {}

        for tool_name in config.tools:
            if tool_name == "shared_context" and shared_context_store is not None:
                # Import here to avoid hard dependency on shared_context.
                from shared_context.schema import anthropic_tool as sc_tool_def
                from shared_context.tool import handle as sc_handle

                tools.append(sc_tool_def())
                # Capture participant in closure for this run.
                _participant = participant
                local_handlers["shared_context"] = (
                    lambda req, p=_participant: sc_handle(
                        shared_context_store, req, participant=p
                    )
                )
            elif tool_name in tool_definitions:
                tools.append(tool_definitions[tool_name])
                if tool_name in handlers:
                    local_handlers[tool_name] = handlers[tool_name]

        system = config.system_prompt + _SUBAGENT_SUFFIX
        messages: list[dict[str, Any]] = [{"role": "user", "content": task_string}]
        turns_used = 0

        for _ in range(config.max_turns):
            kwargs: dict[str, Any] = {
                "model": config.model,
                "system": system,
                "max_tokens": 4096,
                "messages": messages,
            }
            if tools:
                kwargs["tools"] = tools

            response = client.messages.create(**kwargs)

            # Extract fields — support SDK objects and raw dicts.
            if isinstance(response, dict):
                stop_reason = response.get("stop_reason", "")
                content = response.get("content", [])
            else:
                stop_reason = response.stop_reason
                content = response.content

            turns_used += 1

            # Build assistant message.
            assistant_content: list[dict[str, Any]] = []
            tool_results: list[dict[str, Any]] = []

            for block in content:
                if isinstance(block, dict):
                    assistant_content.append(block)
                    block_type = block.get("type", "")
                    block_name = block.get("name", "")
                    block_input = block.get("input", {})
                    block_id = block.get("id", "")
                else:
                    block_type = block.type
                    if block_type == "text":
                        assistant_content.append({"type": "text", "text": block.text})
                    elif block_type == "tool_use":
                        assistant_content.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        })
                    block_name = getattr(block, "name", "")
                    block_input = getattr(block, "input", {})
                    block_id = getattr(block, "id", "")

                if block_type == "tool_use" and block_name in local_handlers:
                    result = local_handlers[block_name](block_input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block_id,
                        "content": json.dumps(result),
                    })

            messages.append({"role": "assistant", "content": assistant_content})

            if stop_reason == "end_turn" or not tool_results:
                # Extract final text response.
                final_text = _extract_text(assistant_content)
                return final_text, turns_used

            messages.append({"role": "user", "content": tool_results})

        raise _MaxTurnsError(
            "Max turns exceeded without producing a final response",
            turns_used=turns_used,
        )

    return run


def _extract_text(content: list[dict[str, Any]]) -> str:
    """Extract concatenated text from content blocks."""
    parts = []
    for block in content:
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts)


class _MaxTurnsError(Exception):
    """Raised when a subagent exceeds its turn limit."""

    def __init__(self, message: str, turns_used: int = 0) -> None:
        super().__init__(message)
        self.turns_used = turns_used
