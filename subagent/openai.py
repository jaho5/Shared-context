"""OpenAI SDK integration for the subagent tool.

Provides :func:`create_runner` — a factory that builds a runner function
compatible with :class:`SubagentTool`.  The runner executes a full agent
loop using the OpenAI chat completions API.

Does **not** require ``openai`` as a dependency — works with any client
that has a ``chat.completions.create()`` method returning the expected shape.

Usage::

    from openai import OpenAI
    from shared_context import SharedContextStore
    from shared_context.openai import tool_definition as sc_tool_def
    from shared_context.tool import handle as sc_handle
    from subagent import SubagentTool, AgentConfig
    from subagent.openai import create_runner

    client = OpenAI()
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
    """Build a runner function for the OpenAI chat completions API.

    Parameters
    ----------
    client:
        An OpenAI client (or anything with ``chat.completions.create()``).
    tool_definitions:
        Mapping of tool name → OpenAI tool definition dict (function-calling
        format).  These are passed to the API's ``tools`` parameter.
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
                from shared_context.schema import openai_tool as sc_tool_def
                from shared_context.tool import handle as sc_handle

                tools.append(sc_tool_def())
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

        system_msg = {"role": "system", "content": config.system_prompt + _SUBAGENT_SUFFIX}
        messages: list[dict[str, Any]] = [
            system_msg,
            {"role": "user", "content": task_string},
        ]
        turns_used = 0

        for _ in range(config.max_turns):
            kwargs: dict[str, Any] = {
                "model": config.model,
                "messages": messages,
            }
            if tools:
                kwargs["tools"] = tools

            response = client.chat.completions.create(**kwargs)

            # Extract fields — support SDK objects and raw dicts.
            if isinstance(response, dict):
                choice = response["choices"][0]
                finish_reason = choice.get("finish_reason", "")
                message = choice.get("message", {})
                content = message.get("content")
                tool_calls = message.get("tool_calls") or []
            else:
                choice = response.choices[0]
                finish_reason = choice.finish_reason
                message = choice.message
                content = message.content
                tool_calls = message.tool_calls or []

            turns_used += 1

            # Build assistant message.
            assistant_msg: dict[str, Any] = {"role": "assistant"}
            if content:
                assistant_msg["content"] = content

            # Process tool calls.
            tool_results: list[dict[str, Any]] = []

            if tool_calls:
                tc_list = []
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        tc_id = tc.get("id", "")
                        fn = tc.get("function", {})
                        fn_name = fn.get("name", "")
                        fn_args = fn.get("arguments", "{}")
                    else:
                        tc_id = tc.id
                        fn_name = tc.function.name
                        fn_args = tc.function.arguments

                    tc_list.append({
                        "id": tc_id,
                        "type": "function",
                        "function": {"name": fn_name, "arguments": fn_args},
                    })

                    if fn_name in local_handlers:
                        input_data = json.loads(fn_args)
                        result = local_handlers[fn_name](input_data)
                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": json.dumps(result),
                        })

                assistant_msg["tool_calls"] = tc_list

            messages.append(assistant_msg)

            if finish_reason == "stop" or not tool_results:
                return content or "", turns_used

            messages.extend(tool_results)

        raise _MaxTurnsError(
            "Max turns exceeded without producing a final response",
            turns_used=turns_used,
        )

    return run


class _MaxTurnsError(Exception):
    """Raised when a subagent exceeds its turn limit."""

    def __init__(self, message: str, turns_used: int = 0) -> None:
        super().__init__(message)
        self.turns_used = turns_used
