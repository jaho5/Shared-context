"""Tool schema definitions for the subagent tool.

Provides the JSON Schema for the tool's parameters (shared across all
API formats) and ready-to-use tool definitions for OpenAI and Anthropic.

Usage::

    from subagent.schema import openai_tool, anthropic_tool

    response = client.chat.completions.create(
        tools=[openai_tool()],
        ...
    )
"""

from __future__ import annotations

import copy
from typing import Any

TOOL_NAME = "subagent"

TOOL_DESCRIPTION = (
    "Delegate tasks to specialist agents. "
    "Use list_agents to see available specialists. "
    "Use define to create a new specialist at runtime. "
    "Use spawn to start a task (returns immediately). "
    "Use status to check progress. "
    "Use collect to retrieve the result when done."
)

PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["list_agents", "define", "spawn", "status", "collect"],
            "description": (
                "The operation to perform. "
                "list_agents: see available specialists. "
                "define: register a new specialist at runtime. "
                "spawn: start a task on a specialist (async). "
                "status: check task progress. "
                "collect: retrieve completed task result."
            ),
        },
        "name": {
            "type": "string",
            "description": (
                "Agent name for define. "
                "Lowercase alphanumeric + underscores + hyphens, max 64 chars."
            ),
        },
        "description": {
            "type": "string",
            "description": "One-line agent description for define.",
        },
        "system_prompt": {
            "type": "string",
            "description": (
                "System prompt for the new agent (define). "
                "Focused instructions, max ~4000 tokens."
            ),
        },
        "tools": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Tool names available to the agent (define).",
        },
        "model": {
            "type": "string",
            "description": "Model identifier for the agent (define).",
        },
        "max_turns": {
            "type": "integer",
            "description": "Max agent loop iterations (define). Default 10, max 25.",
        },
        "agent": {
            "type": "string",
            "description": "Name of the agent to run (spawn).",
        },
        "task": {
            "type": "string",
            "description": (
                "Task description sent to the subagent (spawn). "
                "Keep concise; reference shared context keys for large context."
            ),
        },
        "task_id": {
            "type": "string",
            "description": "Task identifier (status, collect).",
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
    """Return the tool definition in OpenAI function-calling format."""
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
    """Return the tool definition in Anthropic tool-use format."""
    return {
        "name": name,
        "description": description,
        "input_schema": copy.deepcopy(PARAMETERS_SCHEMA),
    }
